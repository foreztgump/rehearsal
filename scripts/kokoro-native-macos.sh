#!/usr/bin/env bash
#
# kokoro-native-macos.sh — stand up native-host Kokoro-FastAPI TTS on macOS
# (Apple Silicon), so the Docker agent reaches it over host.docker.internal:8880
# instead of the CPU-TTS container. This is the TTS half of the macOS topology; the
# LLM half is the native Ollama Mac app (see INSTALLATION.md "macOS (Apple Silicon)").
#
# WHY native: Docker Desktop on macOS has no GPU passthrough, so the Apple GPU
# (Metal/MPS) is unreachable from a container. Benchmarked on an M5 (docs/adr/0002),
# native Metal Kokoro hits ~256 ms P50 vs ~799 ms for the CPU container.
#
# BACKEND: defaults to Metal/MPS (fastest). Pass --cpu for the CPU fallback if you hit
# MPS trouble (upstream Mac issues remsky/Kokoro-FastAPI#270). Both use the same clone,
# venv, and torch==2.8.0 wheel — MPS is built in; the flag is the only difference.
#
# LAN EXPOSURE: the server binds 0.0.0.0:8880 (required so the Docker VM's
# host.docker.internal can reach it — a 127.0.0.1 bind is refused). That makes TTS
# reachable by other devices on your LAN. Keep the macOS firewall on, stay off
# untrusted networks, and never port-forward 8880 to the WAN — the SAME posture as the
# native-Ollama 0.0.0.0:11434 bind.
#
# Usage:
#   scripts/kokoro-native-macos.sh          # bring up on Metal (default)
#   scripts/kokoro-native-macos.sh --cpu    # bring up on the CPU fallback
#   scripts/kokoro-native-macos.sh stop     # stop the backgrounded server
#
set -euo pipefail

# --- constants ---------------------------------------------------------------
KOKORO_TAG="v0.5.0"                       # pinned: highest real release tag, matches the
                                          # Docker baseline image; voice parity verified.
KOKORO_REPO="https://github.com/remsky/Kokoro-FastAPI.git"
KOKORO_DIR="${KOKORO_NATIVE_DIR:-$HOME/.rehearsal/kokoro-fastapi}"
KOKORO_PORT=8880
UVICORN_MATCH="uvicorn api.src.main:app"  # pkill pattern for the server process
HEALTH_URL="http://localhost:${KOKORO_PORT}/health"
PYTHON_VERSION="3.10"
HEALTH_MAX_TRIES=40                       # health-poll bound: tries × interval = total wait
HEALTH_POLL_INTERVAL_S=3                  # first MPS boot loads weights, so allow ~2 min
MODEL_WEIGHTS_DIR="api/src/models/v1_0"   # where upstream expects the v1.0 weights
MODEL_WEIGHTS="$MODEL_WEIGHTS_DIR/kokoro-v1_0.pth"  # the file whose absence crashes startup

log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# --- stop subcommand ---------------------------------------------------------
if [ "${1:-}" = "stop" ]; then
  if pkill -f "$UVICORN_MATCH" 2>/dev/null; then
    log "Stopped native Kokoro server."
  else
    log "No native Kokoro server was running."
  fi
  exit 0
fi

# --- backend selection -------------------------------------------------------
USE_GPU=true
BACKEND="Metal/MPS"
if [ "${1:-}" = "--cpu" ]; then
  USE_GPU=false
  BACKEND="CPU"
elif [ -n "${1:-}" ]; then
  die "unknown argument '$1' (expected: --cpu, stop, or no argument for Metal)"
fi

# --- preflight: required tooling --------------------------------------------
command -v brew >/dev/null 2>&1 || die "Homebrew not found — install it from https://brew.sh"
missing=""
command -v uv >/dev/null 2>&1 || missing="uv"
command -v espeak-ng >/dev/null 2>&1 || missing="${missing:+$missing }espeak-ng"
if [ -n "$missing" ]; then
  die "missing prerequisites ($missing) — run:  brew install uv espeak-ng"
fi

# --- clone (pinned, idempotent) ---------------------------------------------
if [ -d "$KOKORO_DIR/.git" ]; then
  log "Reusing existing Kokoro checkout at $KOKORO_DIR"
else
  log "Cloning Kokoro-FastAPI $KOKORO_TAG into $KOKORO_DIR ..."
  mkdir -p "$(dirname "$KOKORO_DIR")"
  git clone --branch "$KOKORO_TAG" --depth 1 "$KOKORO_REPO" "$KOKORO_DIR"
fi
cd "$KOKORO_DIR"

# --- espeak data path (upstream hardcodes a Linux x86_64 path — fix for macOS) --
ESPEAK_DATA_PATH="$(brew --prefix espeak-ng)/share/espeak-ng-data"
export ESPEAK_DATA_PATH
[ -d "$ESPEAK_DATA_PATH" ] || die "espeak-ng data dir not found at $ESPEAK_DATA_PATH"

# --- venv + deps (work around upstream install-before-venv ordering bug) ------
# Upstream start-*.sh run `uv pip install` before any venv exists, which fails with
# "No virtual environment found". Create the venv and install into it explicitly.
if [ ! -x .venv/bin/uvicorn ]; then
  log "Creating venv + installing Kokoro CPU deps (torch 2.8.0; MPS built in) ..."
  uv venv --python "$PYTHON_VERSION" .venv
  uv pip install --python .venv/bin/python -e ".[cpu]"
fi

# --- model weights (upstream start-*.sh download these; we launch uvicorn
# directly, so we must fetch them ourselves or startup dies with
# "File not found: v1_0/kokoro-v1_0.pth"). Idempotent: skip if already present. --
if [ ! -f "$MODEL_WEIGHTS" ]; then
  log "Downloading Kokoro v1.0 model weights (~327 MB) ..."
  .venv/bin/python docker/scripts/download_model.py --output "$MODEL_WEIGHTS_DIR"
  [ -f "$MODEL_WEIGHTS" ] || die "model download did not produce $MODEL_WEIGHTS"
fi

# --- launch ------------------------------------------------------------------
export USE_GPU USE_ONNX=false
export PYTHONPATH="$PWD:$PWD/api"
export MODEL_DIR=src/models VOICES_DIR=src/voices/v1_0
if [ "$USE_GPU" = "true" ]; then
  export DEVICE_TYPE=mps PYTORCH_ENABLE_MPS_FALLBACK=1
fi

log "Starting native Kokoro ($BACKEND) on 0.0.0.0:${KOKORO_PORT} ..."
nohup .venv/bin/uvicorn api.src.main:app --host 0.0.0.0 --port "$KOKORO_PORT" \
  > "$KOKORO_DIR/kokoro-native.log" 2>&1 &

# --- health gate -------------------------------------------------------------
for _ in $(seq 1 "$HEALTH_MAX_TRIES"); do
  if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    log "Native Kokoro ($BACKEND) is healthy at $HEALTH_URL"
    log "Logs: $KOKORO_DIR/kokoro-native.log   Stop: scripts/kokoro-native-macos.sh stop"
    exit 0
  fi
  sleep "$HEALTH_POLL_INTERVAL_S"
done
die "Kokoro did not become healthy within ~$((HEALTH_MAX_TRIES * HEALTH_POLL_INTERVAL_S))s — check $KOKORO_DIR/kokoro-native.log"
