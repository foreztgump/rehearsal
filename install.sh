#!/usr/bin/env bash
#
# install.sh — one-command bootstrap for the Adept local-first voice stack.
# curl|sh-compatible. Detects OS + Docker/Compose + GPU vendor, scaffolds .env with a
# generated LIVEKIT_API_SECRET, prints a setup plan and confirms, builds images +
# pulls/pins models, then prints exact start/stop commands. Missing prerequisites are
# GUIDED with the right per-OS commands — never auto-installed.
#
#   ./install.sh            # interactive
#   ./install.sh -y         # accept the plan non-interactively (CI / repeat)
#   ASSUME_YES=1 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

ASSUME_YES="${ASSUME_YES:-0}"
[ "${1:-}" = "-y" ] && ASSUME_YES=1

log() { printf '%s\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; }

# --- 1. Prerequisites: guide, do not auto-install ---------------------------
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    log "Install Docker Engine + the Compose v2 plugin, then re-run ./install.sh:"
    log "  https://docs.docker.com/engine/install/"
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 plugin not found (need the 'docker compose' subcommand)."
    log "  https://docs.docker.com/compose/install/linux/"
    exit 1
  fi
}

detect_gpu() {  # prints: nvidia | amd | none
  if command -v nvidia-smi >/dev/null 2>&1; then printf 'nvidia\n'
  elif command -v rocm-smi >/dev/null 2>&1; then printf 'amd\n'
  else printf 'none\n'; fi
}

# --- 2. .env scaffold with a generated secret -------------------------------
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 48 /dev/urandom | base64 | tr -d '\n/+= '
  fi
}

scaffold_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    log "Created .env from .env.example."
  fi
  if grep -q 'replace-with-a-long-random-secret' .env; then
    secret="$(gen_secret)"
    # Portable in-place edit (BSD vs GNU sed -i differ) via temp file.
    sed "s|^LIVEKIT_API_SECRET=.*|LIVEKIT_API_SECRET=${secret}|" .env > .env.tmp
    mv .env.tmp .env
    log "Generated a random LIVEKIT_API_SECRET in .env."
  else
    log ".env already has a LIVEKIT_API_SECRET — leaving it untouched."
  fi
}

# --- 3. Plan + confirmation -------------------------------------------------
print_plan() {
  gpu="$1"
  log ""
  log "================ Adept setup plan ================"
  log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  log "GPU vendor detected: ${gpu}"
  if [ "$gpu" = "nvidia" ]; then
    log "STT placement: CPU-ONNX by default (STT_FORCE_CPU=1, VRAM-safe). GPU STT is"
    log "  opt-in after the co-residency matrix passes (docker compose --profile stt-gpu)."
    log "VRAM budget: 16 GB target — ollama + kokoro resident (scripts/vram-validate.sh)."
  else
    log "No NVIDIA GPU detected. STT runs on CPU-ONNX. The LLM + TTS still expect a GPU"
    log "  for real-time latency; without one the stack runs but will not hit P50<1.0s."
  fi
  log "================================================="
}

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  printf 'Proceed with build + model pull? [y/N] '
  read -r reply
  case "$reply" in
    y|Y|yes|Yes) return 0 ;;
    *) log "Aborted — nothing built. Re-run ./install.sh when ready."; exit 1 ;;
  esac
}

# --- 4. Build + first-run model pull + boot ---------------------------------
build_and_pull() {
  log "Building images (first run pulls several GB + bakes the STT model)…"
  docker compose build
  log "Starting ollama to pull + pin the two LLMs…"
  docker compose up -d ollama
  ./ollama/pull-and-pin.sh
  log "Starting the full stack…"
  docker compose up -d
}

# --- main -------------------------------------------------------------------
GPU="$(detect_gpu)"
require_docker
if [ "$GPU" = "nvidia" ] && [ "${SKIP_DOCTOR:-0}" != "1" ]; then
  ./scripts/gpu-doctor.sh || true   # advise-only; never blocks
fi
scaffold_env
print_plan "$GPU"
confirm
build_and_pull
log ""
log "Done. The stack is up."
log "  Start:  ./up.sh -d        (preflight + docker compose up -d)"
log "  Stop:   ./down.sh         (docker compose down)"
log "  Logs:   docker compose logs -f agent"
log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
