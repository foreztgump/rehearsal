"""Adept LiveKit agent worker — AgentSession wiring + walking-skeleton gate.

Phase 1 scope (Plan 01-03): construct an AgentSession against the three LOCAL
model endpoints (faster-whisper STT, Ollama LLM, Kokoro TTS) with the LOCAL
MultilingualModel turn detector, run a startup warmup that emits exactly ONE
real LLM-TTFT metric line through the scaffold, and register as a worker against
the self-hosted livekit-server. NO live voice turn happens yet — no participant
audio flows in Phase 1.

Local-first invariant (PERF-03 / DEPLOY-02): every model base_url is an in-stack
service on the `adept` Docker network; the turn detector is the local
MultilingualModel, never the cloud-default turn detector plugin. Nothing reaches
a non-LAN endpoint at startup.
"""
from __future__ import annotations

import json
import os
import time

import httpx
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import metrics

# In-stack model endpoints (Docker `adept` network — all LAN-local, no egress).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://ollama:11434/api/generate")
WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://whisper:8000/v1")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://kokoro:8880/v1")

WHISPER_MODEL = "Systran/faster-whisper-large-v3-turbo"
KOKORO_MODEL = "kokoro"
KOKORO_VOICE = "af_bella"

# faster-whisper decode settings tuned for latency (forwarded to the server).
# Greedy single-beam decode, no cross-segment conditioning, VAD pre-filter, en.
WHISPER_PARAMS = {
    "beam_size": 1,
    "condition_on_previous_text": False,
    "vad_filter": True,
    "language": "en",
}

WARMUP_PROMPT = "Reply with the single word: ready."
WARMUP_TIMEOUT_SECONDS = 120.0
WARMUP_NUM_PREDICT = 16
THINKING_ENABLED = False  # protect TTFT (see ollama/Modelfile)
_MS_PER_SECOND = 1000.0

PERSONA_INSTRUCTIONS = (
    "You are a domain expert trainer. Hold a natural spoken conversation that "
    "pulls the user into articulating the subject out loud."
)


def resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (no hardcoded gemma tag)."""
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise SystemExit("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag


def _warmup_llm_ttft_ms(tag: str) -> float:
    """Stream one tiny completion from Ollama; return measured TTFT in ms.

    Mirrors ollama/warmup.py's LLM path: forces the model resident and measures
    first-token latency — the real number routed through the metrics scaffold as
    the walking-skeleton "one real metric" gate.
    """
    payload = {
        "model": tag,
        "prompt": WARMUP_PROMPT,
        "stream": True,
        "think": THINKING_ENABLED,
        "options": {"num_predict": WARMUP_NUM_PREDICT},
    }
    started = time.perf_counter()
    ttft_seconds: float | None = None
    with httpx.Client(timeout=WARMUP_TIMEOUT_SECONDS) as client:
        with client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("response") and ttft_seconds is None:
                    ttft_seconds = time.perf_counter() - started
                if chunk.get("done"):
                    break
    if ttft_seconds is None:
        raise RuntimeError("LLM produced no tokens — warmup failed")
    return round(ttft_seconds * _MS_PER_SECOND, 1)


def build_session(vad: silero.vad.VAD) -> AgentSession:
    """Construct the AgentSession against the three local endpoints + local turn
    detector. Used by the entrypoint; metrics are attached per-plugin after.
    """
    return AgentSession(
        vad=vad,
        stt=openai.STT(
            base_url=WHISPER_BASE_URL,
            model=WHISPER_MODEL,
            api_key="none",
            language=WHISPER_PARAMS["language"],
            extra_kwargs={
                "beam_size": WHISPER_PARAMS["beam_size"],
                "condition_on_previous_text": WHISPER_PARAMS["condition_on_previous_text"],
                "vad_filter": WHISPER_PARAMS["vad_filter"],
            },
        ),
        llm=openai.LLM.with_ollama(
            model=resolved_llm_tag(),
            base_url=OLLAMA_BASE_URL,
        ),
        tts=openai.TTS(
            base_url=KOKORO_BASE_URL,
            model=KOKORO_MODEL,
            voice=KOKORO_VOICE,
            api_key="none",
        ),
        turn_detection=MultilingualModel(),
    )


def prewarm(proc: JobProcess) -> None:
    """Worker-startup hook: load VAD and emit the one real warmup metric line.

    Runs once when the worker process boots — before any job/voice turn — so the
    walking-skeleton gate (exactly one real llm_ttft_ms line) is satisfied at
    startup without a participant. The VAD is cached for reuse in the entrypoint.
    """
    proc.userdata["vad"] = silero.VAD.load()
    ttft_ms = _warmup_llm_ttft_ms(resolved_llm_tag())
    metrics.emit_warmup_metric(ttft_ms)


async def entrypoint(ctx: JobContext) -> None:
    """Per-job entrypoint: connect, build the session, attach per-plugin metrics.

    Phase 1 does NOT start a live voice turn — no generate_reply / no agent
    speech. The session is constructed and metrics are wired so Phase 2 can
    enable the loop without re-plumbing.
    """
    await ctx.connect()
    session = build_session(ctx.proc.userdata["vad"])
    metrics.attach(session)
    await session.start(
        agent=Agent(instructions=PERSONA_INSTRUCTIONS),
        room=ctx.room,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
