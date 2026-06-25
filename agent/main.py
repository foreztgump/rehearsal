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

# Default persona (PERS-01). Written as a STATIC top block with NO volatile /
# runtime data so the Phase 3 frozen prefix ([persona] + [KB] + [history] +
# [turn]) can slot a KB beneath it without a rewrite. Voice-friendly: concise and
# conversational because TTS speaks it aloud.
PERSONA_INSTRUCTIONS = (
    "You are a Cybersecurity Trainer: a seasoned security practitioner who coaches "
    "learners by voice. You cover the security domain broadly — threats and attacker "
    "tradecraft, defenses and controls, network and application security, identity, "
    "cryptography, incident response, and risk. "
    "Hold a natural spoken conversation. Pull the learner into articulating the subject "
    "out loud: ask focused questions, have them explain concepts back to you, and build on "
    "their answers rather than lecturing. "
    "When they use sloppy or imprecise terminology, gently correct it toward precise "
    "practitioner phrasing — name the right term, say it plainly, and move on without "
    "scolding. "
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document."
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
        # Thinking-OFF on the hot path (a <think> preamble destroys TTFT and
        # breaks first-sentence TTS). with_ollama connects over Ollama's
        # OpenAI-compat /v1 endpoint, which IGNORES the native `think` field but
        # DOES honor `reasoning_effort` — Ollama maps "none" to its internal
        # Think=false (see Ollama OpenAI-compatibility docs). with_ollama exposes
        # `reasoning_effort` directly (livekit-plugins-openai reference), so this
        # forwards think-off over /v1 WITHOUT a Modelfile change or repointing the
        # model (the tag still resolves from OLLAMA_MODEL via resolved_llm_tag()).
        llm=openai.LLM.with_ollama(
            model=resolved_llm_tag(),
            base_url=OLLAMA_BASE_URL,
            reasoning_effort="none",
        ),
        tts=openai.TTS(
            base_url=KOKORO_BASE_URL,
            model=KOKORO_MODEL,
            voice=KOKORO_VOICE,
            api_key="none",
        ),
        # Endpointing surface (Plan 02-03 BLOCKER — resolved by reading the real
        # AgentSession source across the whole ~=1.5 pin, NOT by guessing).
        # Verified against livekit-agents@1.5.0, @1.5.17 and @1.6.4
        # (voice/agent_session.py + voice/turn.py): the TWO surfaces are NOT
        # mutually exclusive and the direct kwargs do NOT throw TypeError —
        #   * direct kwargs (min_endpointing_delay=..., min_interruption_duration=...)
        #     are present but DEPRECATED; __init__ migrates them via
        #     _migrate_turn_handling() into the dict below.
        #   * turn_handling=TurnHandlingOptions(...) (a TypedDict, passable as a
        #     plain dict) is the NON-deprecated consolidated surface and is the
        #     ONLY one that exposes `mode: "dynamic"` endpointing.
        # We use the dict surface (future-proof under ~=1.5 resolving to 1.6.x;
        # dynamic mode preferred per Pattern D1). The MultilingualModel turn
        # detector is the semantic decider and MUST live INSIDE the dict —
        # when turn_handling is given, the deprecated top-level turn_detection
        # kwarg is dropped (else-branch in __init__), so nesting it is required.
        # min_delay 0.3s ∈ [0.25, 0.35] (default 0.5s is half the P50 budget).
        # VM-introspection-pending: confirm the installed signature with
        #   python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.__init__))"
        # (sandbox cannot import livekit — grounded on tagged source instead).
        # Barge-in / interruption gate (Plan 02-03-2). Barge-in is built in:
        # AgentSession cancels TTS + rolls back the turn on user speech and
        # `interruption.enabled` defaults True (verified in voice/turn.py
        # _INTERRUPTION_DEFAULTS) — we DO NOT disable it (allow_interruptions
        # stays on). On the dict surface the deprecated direct kwargs map as:
        #   min_interruption_duration   -> interruption["min_duration"]
        #   false_interruption_timeout  -> interruption["false_interruption_timeout"]
        #   resume_false_interruption   -> interruption["resume_false_interruption"]
        # All three keys are verified present on InterruptionOptions across
        # livekit-agents@1.5.0..@1.6.4 (voice/turn.py). min_duration 0.3s
        # requires ~300ms of real speech before cancel — defends against the
        # agent's own echo tail and "mm-hmm" backchannels. resume_false_int +
        # a 2.0s timeout make a no-transcript noise-blip barge-in resume the
        # agent instead of dropping the turn (open-mic win).
        # VM-introspection-pending: confirm the installed InterruptionOptions
        # accepts these keys (sandbox cannot import livekit — grounded on tagged
        # source). If a future version renames a key, the dict degrades by
        # ignoring unknown keys at _resolve_interruption (TypedDict, total=False).
        turn_handling={
            "turn_detection": MultilingualModel(),
            "endpointing": {"mode": "dynamic", "min_delay": 0.3, "max_delay": 3.0},
            "interruption": {
                "min_duration": 0.3,
                "resume_false_interruption": True,
                "false_interruption_timeout": 2.0,
            },
        },
    )


def prewarm(proc: JobProcess) -> None:
    """Worker-startup hook: load VAD and emit the one real warmup metric line.

    Runs once when the worker process boots — before any job/voice turn — so the
    walking-skeleton gate (exactly one real llm_ttft_ms line) is satisfied at
    startup without a participant. The VAD is cached for reuse in the entrypoint.
    """
    # Raise Silero VAD activation_threshold 0.5 -> 0.65 (Plan 02-03-2, Pitfall 4):
    # a higher bar to register speech reduces open-mic false triggers from the
    # agent's own playout + room noise. `activation_threshold` is verified
    # present on silero.VAD.load (livekit-plugins-silero vad.py: default 0.5,
    # alongside min_speech_duration/min_silence_duration/deactivation_threshold).
    # VM-introspection-pending: confirm the installed silero.VAD.load signature
    #   python -c "import inspect; from livekit.plugins import silero; print(inspect.signature(silero.VAD.load))"
    # (sandbox cannot import livekit — grounded on tagged source).
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=0.65)
    ttft_ms = _warmup_llm_ttft_ms(resolved_llm_tag())
    metrics.emit_warmup_metric(ttft_ms)


GREETING_INSTRUCTIONS = (
    "Greet the user as the Cybersecurity Trainer and invite them to begin."
)


async def entrypoint(ctx: JobContext) -> None:
    """Per-job entrypoint: connect, build the session, drive the agent's first turn.

    After session.start(...) the agent speaks first (the greeting call below) so
    the learner immediately has a partner (PERS-01 "talking within seconds"). The
    greeting instruction drives the full LLM->TTS path — no second hardcoded
    greeting string. Per-turn replies after this need no manual glue: with VAD +
    turn detector + STT + LLM + TTS all wired, AgentSession runs a turn
    automatically when the user finishes speaking.
    """
    await ctx.connect()
    session = build_session(ctx.proc.userdata["vad"])
    metrics.attach(session)
    await session.start(
        agent=Agent(instructions=PERSONA_INSTRUCTIONS),
        room=ctx.room,
    )
    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
