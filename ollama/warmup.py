#!/usr/bin/env python3
"""Warm all three Adept model services and emit a real LLM TTFT.

Issues one tiny dummy inference to each in-stack service to force the weights
resident, printing one structured JSON line per model:

  {"model": "llm",     "load_ms": ..., "ttft_ms": ...}
  {"model": "whisper", "load_ms": ...}
  {"model": "kokoro",  "load_ms": ...}

The LLM ttft_ms is the "one real metric" the 01-03 metrics scaffold consumes as
its walking-skeleton gate. The LLM tag is read from OLLAMA_MODEL (no hardcoded
gemma tag). Run from the host against the running stack:  python ollama/warmup.py
(the agent image is not built until 01-03, so warmup is NOT routed through
`docker compose run --rm agent`).

Endpoints default to the LAN-published ports; override via env for in-network
calls (e.g. OLLAMA_BASE_URL=http://ollama:11434).
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import time
import wave
from io import BytesIO

import httpx

# Thinking is disabled at request time to protect TTFT (see ollama/Modelfile).
THINKING_ENABLED = False
WARMUP_PROMPT = "Reply with the single word: ready."
TTS_TEXT = "warmup voice check"
HTTP_TIMEOUT_SECONDS = 120.0
SILENT_WAV_SECONDS = 1.0
SILENT_WAV_RATE = 16000
SINE_FREQ_HZ = 440.0
SINE_AMPLITUDE = 0.2
SAMPLE_MAX = 32767

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://127.0.0.1:8000")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://127.0.0.1:8880")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "Systran/faster-whisper-large-v3")
KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "kokoro")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_bella")


def resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (no hardcoded gemma tag)."""
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise SystemExit("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _sine_wav_bytes() -> bytes:
    """A short mono sine WAV — a non-silent clip whisper can transcribe."""
    frame_count = int(SILENT_WAV_RATE * SILENT_WAV_SECONDS)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SILENT_WAV_RATE)
        for index in range(frame_count):
            angle = 2.0 * math.pi * SINE_FREQ_HZ * (index / SILENT_WAV_RATE)
            sample = int(SINE_AMPLITUDE * math.sin(angle) * SAMPLE_MAX)
            wav.writeframes(struct.pack("<h", sample))
    return buffer.getvalue()


def warm_llm(client: httpx.Client, tag: str) -> dict:
    """Stream one tiny completion; measure TTFT (first token) and total load."""
    payload = {
        "model": tag,
        "prompt": WARMUP_PROMPT,
        "stream": True,
        "think": THINKING_ENABLED,
        "options": {"num_predict": 16},
    }
    started = _now_ms()
    ttft_ms: float | None = None
    text_parts: list[str] = []
    with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token and ttft_ms is None:
                ttft_ms = _now_ms() - started
            text_parts.append(token)
            if chunk.get("done"):
                break
    if ttft_ms is None:
        raise RuntimeError("LLM produced no tokens — warmup failed")

    output = "".join(text_parts)
    if "<think>" in output or "</think>" in output:
        raise RuntimeError("thinking is ON — <think> preamble present; expected think=false")

    return {
        "model": "llm",
        "tag": tag,
        "load_ms": round(_now_ms() - started, 1),
        "ttft_ms": round(ttft_ms, 1),
    }


def warm_whisper(client: httpx.Client) -> dict:
    """Transcribe a short sine clip to force the STT weights resident."""
    started = _now_ms()
    files = {"file": ("warmup.wav", _sine_wav_bytes(), "audio/wav")}
    data = {"model": WHISPER_MODEL, "language": "en", "response_format": "json"}
    response = client.post(
        f"{WHISPER_BASE_URL}/v1/audio/transcriptions", files=files, data=data
    )
    response.raise_for_status()
    return {"model": "whisper", "load_ms": round(_now_ms() - started, 1)}


def warm_kokoro(client: httpx.Client) -> dict:
    """Synthesize a 3-word string to force the TTS weights resident."""
    started = _now_ms()
    payload = {"model": KOKORO_MODEL, "voice": KOKORO_VOICE, "input": TTS_TEXT}
    response = client.post(f"{KOKORO_BASE_URL}/v1/audio/speech", json=payload)
    response.raise_for_status()
    _ = response.read()
    return {"model": "kokoro", "load_ms": round(_now_ms() - started, 1)}


def main() -> int:
    tag = resolved_llm_tag()
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for warm in (lambda: warm_llm(client, tag), lambda: warm_whisper(client),
                     lambda: warm_kokoro(client)):
            print(json.dumps(warm()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
