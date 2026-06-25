# Minimal uv-based placeholder for the LiveKit agent worker.
# 01-03 extends this with `uv pip install`/`uv sync` of livekit-agents and a
# `python -m livekit.agents download-files` weights bake. For now it only proves
# the build context resolves and the service boots cleanly at this boundary.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Idle cleanly so `docker compose up` keeps the placeholder service running
# until 01-03 gives it a real worker entrypoint.
CMD ["python", "-c", "print('agent placeholder — fleshed out in 01-03', flush=True); import time; time.sleep(2**31)"]
