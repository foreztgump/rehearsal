# Adept LiveKit agent worker image (Plan 01-03).
#
# Extends the 01-01 uv-based placeholder: installs the pinned deps with uv (NOT
# pip — AGENTS.md mandates the Python agent runs via uv) and bakes the Silero VAD
# + MultilingualModel turn-detector weights into the image at build time with
# `download-files`, so the container starts fully offline-capable (no weight
# download at runtime, no network egress — PERF-03 / DEPLOY-02).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install pinned deps into a uv-managed virtualenv at /app/.venv and put it on
# PATH so `python` resolves to the env interpreter for the bake + runtime.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY requirements.txt ./
RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python -r requirements.txt

# Pre-fetch VAD + turn-detector weights into the image (offline-capable).
RUN python -m livekit.agents download-files

# Worker entrypoint + metrics scaffold (main.py reuses the warmup logic inline).
# persona.py provides the persona model + render_persona used by the runtime
# persona.update RPC handler. history.py + interview.py are flat local modules
# imported by main.py (sliding-window history + Interview mode) — without them the
# container ImportErrors at startup.
COPY metrics.py persona.py history.py interview.py models.py main.py ./
# Wave-2 STT placement + websocket client, and the Phase-12 captioned TTS plugin
# (Kokoro /dev/captioned_speech -> audio + word timestamps for avatar lip-sync).
# main.py imports all three at module load; without them the worker ImportErrors.
COPY nemo_stt.py placement.py captioned_tts.py ./
# Phase-14 pure agent modules: mode-aware endpointing selector (endpointing.py),
# the captioned-TTS avatar gate (captioned_gate.py), and the garbled-finalize
# predicate (transcript_gate.py). main.py + captioned_tts.py import them at module
# load — without them the worker ImportErrors at startup.
COPY endpointing.py captioned_gate.py transcript_gate.py transcript_debug.py ./
# The KB parser package (Plan 04-01) — pure, livekit-free; copied as a directory.
COPY kb/ ./kb/

# Run the LiveKit worker. `start` connects to livekit-server, runs the startup
# warmup, emits the one real metric, and registers — no live voice turn yet.
CMD ["python", "main.py", "start"]
