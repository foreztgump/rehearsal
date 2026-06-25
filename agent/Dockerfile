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
# persona.update RPC handler.
COPY metrics.py persona.py main.py ./
# The KB parser package (Plan 04-01) — pure, livekit-free; copied as a directory.
COPY kb/ ./kb/

# Run the LiveKit worker. `start` connects to livekit-server, runs the startup
# warmup, emits the one real metric, and registers — no live voice turn yet.
CMD ["python", "main.py", "start"]
