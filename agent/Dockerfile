# Rehearsal LiveKit agent worker image (Plan 01-03).
#
# Extends the 01-01 uv-based placeholder: installs the pinned deps with uv (NOT
# pip — AGENTS.md mandates the Python agent runs via uv) and bakes the Silero VAD
# + MultilingualModel turn-detector weights into the image at build time with
# `download-files`, so the container starts fully offline-capable (no weight
# download at runtime, no network egress — PERF-03 / DEPLOY-02).
# F34: digest-pin the base (was the moving ghcr.io/astral-sh/uv:python3.12-bookworm-slim
# tag, which floats uv + the python patch). The tag is kept in the comment for
# readability; the @sha256 is the reproducible reference. Re-resolve with
# `docker buildx imagetools inspect ghcr.io/astral-sh/uv:python3.12-bookworm-slim`.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

WORKDIR /app

# Install pinned deps into a uv-managed virtualenv at /app/.venv and put it on
# PATH so `python` resolves to the env interpreter for the bake + runtime.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

# F34 follow-up: pin the HuggingFace cache under /app so the baked turn-detector
# weights (languages.json etc.) are readable by the non-root runtime user. The
# default cache is ~/.cache/huggingface; with --no-create-home the app user has
# no writable HOME, and a root-owned /root/.cache is unreadable at runtime ->
# "Could not find file languages.json" -> every agent job crashed. /app/.hf-cache
# is chowned to app by the existing `chown -R app:app /app` below.
ENV HF_HOME=/app/.hf-cache

COPY requirements.txt ./
# O10: --no-cache drops uv's wheel/download cache. In a single-shot image build the
# cache is never reused, so keeping it only bloats the layer — smaller image, faster
# pulls, zero functional change.
RUN uv venv /app/.venv \
    && uv pip install --no-cache --python /app/.venv/bin/python -r requirements.txt

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
# The coalescing KB batch distiller (O3) — flat livekit-free module imported by main.py.
COPY kb_ingest.py ./
# The KB parser package (Plan 04-01) — pure, livekit-free; copied as a directory.
COPY kb/ ./kb/

# F34: run as a non-root user. The agent parses UNTRUSTED uploads with native-code
# parsers (PyMuPDF, python-docx — both have CVE history); doing that as container
# root widens the blast radius of a parser exploit. Create an unprivileged user and
# own /app (the baked venv + weights) so it can read them. --system: no login/home.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && chown -R app:app /app
USER app

# F34: liveness probe. The worker has no HTTP port (it dials livekit-server
# outbound), so probe that the interpreter + the heavy import graph still resolve
# — a crash-looping import (a bad dep bump) then surfaces as unhealthy instead of a
# silently dead worker. Python urllib/import only (no curl in the slim base).
HEALTHCHECK --start-period=60s --interval=30s --timeout=10s --retries=3 \
    CMD ["python", "-c", "import livekit.agents, main"]

# Run the LiveKit worker. `start` connects to livekit-server, runs the startup
# warmup, emits the one real metric, and registers — no live voice turn yet.
CMD ["python", "main.py", "start"]
