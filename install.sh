#!/usr/bin/env bash
#
# install.sh — one-command bootstrap for the Adept local-first voice stack.
# curl|sh-compatible. Detects OS + Docker/Compose + GPU vendor, scaffolds .env with a
# generated LIVEKIT_API_SECRET, prompts for which models to install + their aliases,
# prints a setup plan and confirms, builds images + pulls/pins the selected models,
# then prints exact start/stop commands. Missing prerequisites are OFFERED for
# auto-install (apt/dnf/pacman) behind a confirmation gate; declining falls back to
# guidance.
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
    DOCKER_WAS_MISSING=1
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 plugin not found (need the 'docker compose' subcommand)."
    log "  https://docs.docker.com/compose/install/linux/"
    DOCKER_WAS_MISSING=1
    return 1
  fi
}

detect_gpu() {  # prints: nvidia | amd | none
  if command -v nvidia-smi >/dev/null 2>&1; then printf 'nvidia\n'
  elif command -v rocm-smi >/dev/null 2>&1; then printf 'amd\n'
  else printf 'none\n'; fi
}

# --- 1b. Offer to install safe prerequisites (behind confirmation) -----------
detect_pkgmgr() {  # prints: apt|dnf|pacman|none
  for pm in apt dnf pacman; do
    if command -v "$pm" >/dev/null 2>&1; then printf '%s\n' "$pm"; return; fi
  done
  printf 'none\n'
}

offer_install_prereqs() {
  pm="$1"
  [ "$pm" = "none" ] && return 0
  log "Detected package manager: ${pm}."
  if [ "$ASSUME_YES" = "1" ]; then reply=y
  else
    printf 'Attempt to install missing Docker/Compose via %s? [y/N] ' "$pm"
    read -r reply
  fi
  case "$reply" in
    y|Y|yes|Yes)
      # A sudo/package failure falls back to guidance (not a silent set -e abort).
      case "$pm" in
        apt)  sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2                 || { err "apt install failed."; log "Install Docker/Compose manually, then re-run."; } ;;
        dnf)  sudo dnf install -y docker docker-compose-plugin                 || { err "dnf install failed."; log "Install Docker/Compose manually, then re-run."; } ;;
        pacman) sudo pacman -S --noconfirm docker docker-compose                 || { err "pacman install failed."; log "Install Docker/Compose manually, then re-run."; } ;;
      esac
      ;;
    *) log "Skipping auto-install. Install Docker/Compose manually, then re-run." ;;
  esac
}

# --- 1c. Model selection ----------------------------------------------------
prompt_models() {  # sets INSTALL_MODELS + MODEL_LABELS (globals)
  gpu="$1"
  case "$gpu" in
    nvidia) default_model="fast" ;;
    amd)    default_model="fast" ;;
    none)   default_model="floor" ;;
  esac
  log ""
  log "Recommended LLM: ${default_model} (best default for this machine)."
  log "Available: fast (snappier), better (more thoughtful), floor (weakest hardware)."
  if [ "$ASSUME_YES" = "1" ]; then
    INSTALL_MODELS="${default_model}"
    MODEL_LABELS="${default_model}"
  else
    printf 'Which models to install (comma list, e.g. fast,better)? [%s] ' "$default_model"
    read -r reply
    INSTALL_MODELS="${reply:-${default_model}}"
    printf 'Aliases (comma list, same order; blank for defaults)? '
    read -r labels
    MODEL_LABELS="${labels:-${INSTALL_MODELS}}"
  fi
  log "Will install: ${INSTALL_MODELS}"
}

# --- 1d. Write model-choices env to .env ------------------------------------
write_model_env() {
  # ADEPT_MODEL_CHOICES — the installed set (comma list).
  if grep -q '^ADEPT_MODEL_CHOICES=' .env 2>/dev/null; then
    sed -i "s|^ADEPT_MODEL_CHOICES=.*|ADEPT_MODEL_CHOICES=${INSTALL_MODELS}|" .env
  else
    printf 'ADEPT_MODEL_CHOICES=%s\n' "${INSTALL_MODELS}" >> .env
  fi
  # Labels (baked into the web build via NEXT_PUBLIC_ADEPT_MODEL_LABELS).
  if grep -q '^NEXT_PUBLIC_ADEPT_MODEL_LABELS=' .env 2>/dev/null; then
    sed -i "s|^NEXT_PUBLIC_ADEPT_MODEL_LABELS=.*|NEXT_PUBLIC_ADEPT_MODEL_LABELS=${MODEL_LABELS}|" .env
  else
    printf 'NEXT_PUBLIC_ADEPT_MODEL_LABELS=%s\n' "${MODEL_LABELS}" >> .env
  fi
  # ADEPT_DEFAULT_MODEL — first of the installed set (safe: its tag is pinned).
  default_choice="${INSTALL_MODELS%%,*}"
  if grep -q '^ADEPT_DEFAULT_MODEL=' .env 2>/dev/null; then
    sed -i "s|^ADEPT_DEFAULT_MODEL=.*|ADEPT_DEFAULT_MODEL=${default_choice}|" .env
  else
    printf 'ADEPT_DEFAULT_MODEL=%s\n' "${default_choice}" >> .env
  fi
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
  gpu="$1"; models="$2"
  log ""
  log "================ Adept setup plan ================"
  log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  log "GPU vendor detected: ${gpu}"
  log "Models to install: ${models}"
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
  log "Starting ollama to pull + pin the selected models…"
  docker compose up -d ollama
  INSTALL_MODELS="${INSTALL_MODELS}" ADEPT_DEFAULT_MODEL="${INSTALL_MODELS%%,*}" \
    ./ollama/pull-and-pin.sh
  # Write the model-choices env ONLY after pull-and-pin succeeds — so .env never
  # claims a model is installed before its tag is confirmed resident (the
  # floor-path landmine: ADEPT_DEFAULT_MODEL=floor with no OLLAMA_MODEL_FLOOR).
  write_model_env
  log "Starting the full stack…"
  docker compose up -d
}

# --- main -------------------------------------------------------------------
GPU="$(detect_gpu)"
DOCKER_WAS_MISSING=0
require_docker || true
if [ "${DOCKER_WAS_MISSING}" = "1" ]; then
  PM="$(detect_pkgmgr)"
  offer_install_prereqs "$PM"
  require_docker   # re-check after offer-to-install (exits if still missing)
fi
if [ "$GPU" = "nvidia" ] && [ "${SKIP_DOCTOR:-0}" != "1" ]; then
  ./scripts/gpu-doctor.sh || true   # advise-only; never blocks
fi
scaffold_env
prompt_models "$GPU"
print_plan "$GPU" "$INSTALL_MODELS"
confirm
build_and_pull
log ""
log "Done. The stack is up."
log "  Start:  ./up.sh -d        (preflight + docker compose up -d)"
log "  Stop:   ./down.sh         (docker compose down)"
log "  Logs:   docker compose logs -f agent"
log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
