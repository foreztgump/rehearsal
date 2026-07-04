# Tasks — macOS native-host Kokoro TTS

## T1 — `scripts/kokoro-native-macos.sh` (new bring-up + stop helper)

New executable bash script. Acceptance:

- [x] `#!/usr/bin/env bash` + `set -euo pipefail`; passes `bash -n`.
- [x] Default (no `--cpu`) runs Metal: exports `USE_GPU=true DEVICE_TYPE=mps
      PYTORCH_ENABLE_MPS_FALLBACK=1`. `--cpu` runs `USE_GPU=false`.
- [x] `stop` subcommand kills the backgrounded uvicorn (`pkill -f "uvicorn api.src.main:app"`
      or a recorded PID file) and reports whether one was running.
- [x] Preflight: require `brew`, `uv`, `espeak-ng`; if `uv`/`espeak-ng` missing, print the
      exact `brew install uv espeak-ng` line and exit non-zero (don't silently continue).
- [x] Clone pinned: `git clone --branch v0.5.0 --depth 1 https://github.com/remsky/Kokoro-FastAPI.git <dir>`
      (skip clone if the dir already exists — idempotent re-run).
- [x] `export ESPEAK_DATA_PATH="$(brew --prefix espeak-ng)/share/espeak-ng-data"`.
- [x] Create venv + install explicitly (upstream ordering-bug workaround):
      `uv venv --python 3.10 .venv` then `uv pip install --python .venv/bin/python -e ".[cpu]"`.
- [x] Launch `.venv/bin/uvicorn api.src.main:app --host 0.0.0.0 --port 8880` backgrounded,
      then poll `curl -sf http://localhost:8880/health` until 200 (bounded retries) and print
      a clear ready/failed line.
- [x] A leading comment block documents the LAN-exposure caveat (binds `0.0.0.0:8880`, keep
      the mac firewall on) — same posture as the Ollama `0.0.0.0:11434` bind.

## T2 — `docker-compose.macos.yml` (stub kokoro + agent env)

Acceptance:

- [x] `kokoro` service stub added: `image: alpine:3.21`, `command: ["sleep","infinity"]`,
      `ports: !reset []`, `deploy.resources.reservations.devices: !reset []` — mirroring the
      existing `ollama` stub block, with a comment explaining the base `depends_on: kokoro`.
- [x] `agent.environment` gains `KOKORO_BASE_URL=http://host.docker.internal:8880/v1` beside
      the existing `OLLAMA_BASE_URL` lines.
- [x] Header comment updated: the macOS up command is now the 2-file form
      (`-f docker-compose.yml -f docker-compose.macos.yml`), no `cpu-tts`.
- [x] `docker compose -f docker-compose.yml -f docker-compose.macos.yml config` resolves with
      the kokoro stub + `KOKORO_BASE_URL` present (verified in review, run on the Linux host).

## T3 — `install.sh` macOS guidance

Acceptance:

- [x] `show_macos_guidance_and_exit()` gains a native-Kokoro step: run
      `scripts/kokoro-native-macos.sh`, then verify `curl -sf http://localhost:8880/health`.
- [x] The printed step-5 up command drops `-f docker-compose.cpu-tts.yml` (2-file form).
- [x] `bash -n install.sh` passes; the detect+guide+stop shape is unchanged.

## T4 — Docs: INSTALLATION.md + CHANGELOG.md + .gitignore carve-in

Acceptance:

- [x] INSTALLATION.md macOS latency note flipped to the measured result (Metal ~256 ms P50
      default; CPU ~433 ms fallback); native-Kokoro bring-up subsection + health-check
      validation-checklist line added; up command → 2-file form. **Metal is stated as the
      default everywhere** (no lingering "CPU default / Metal opt-in" wording).
- [x] CHANGELOG `[Unreleased]`: Added (helper + macOS override) and Changed (macOS default
      TTS now native Metal) entries, referencing areas `compose`, `install`, `docs`.
- [x] `.gitignore` carves in `!docs/adr/` and `!docs/macos-tts-benchmark-results.md` so the
      decision record is versioned; `git check-ignore` confirms they are no longer ignored.
