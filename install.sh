#!/usr/bin/env bash
#
# install.sh — one-command bootstrap for the Rehearsal local-first voice stack.
# curl|bash-compatible. Detects OS + Docker/Compose + GPU vendor, scaffolds .env with a
# generated LIVEKIT_API_SECRET, prompts for which models to install + their aliases,
# prints a setup plan and confirms, builds images + pulls/pins the selected models,
# then prints exact start/stop commands. Missing prerequisites are OFFERED for
# auto-install (apt/dnf/pacman) behind a confirmation gate; declining falls back to
# guidance.
#
#   ./install.sh            # interactive, from a cloned checkout
#   ./install.sh -y         # accept the plan non-interactively (CI / repeat)
#   ./install.sh --expressive   # also build + enable expressive voice (Chatterbox)
#   ASSUME_YES=1 ./install.sh
#   INSTALL_EXPRESSIVE=1 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

ASSUME_YES="${ASSUME_YES:-0}"
# Opt-in expressive voice (Chatterbox-Turbo): OFF by default. Enable via the
# --expressive flag or INSTALL_EXPRESSIVE=1. It is a large extra build (~19GB image)
# and ~4.3GB resident VRAM, GPU-only, and deliberately exceeds the P50<1.0s budget —
# so it is never installed unless explicitly requested.
INSTALL_EXPRESSIVE="${INSTALL_EXPRESSIVE:-0}"
for arg in "$@"; do
  case "$arg" in
    -y) ASSUME_YES=1 ;;
    --expressive) INSTALL_EXPRESSIVE=1 ;;
  esac
done
# Model-default + readiness tunables (single-sourced; no magic numbers inline).
# VRAM_SMALL_MB: NVIDIA cards at/below this can't comfortably co-fit the Better tier,
# so the installer defaults them to the smaller Floor model (field report rec #5).
# READY_*: bound the post-`up` wait for the agent to register (advise-only on timeout).
VRAM_SMALL_MB="${VRAM_SMALL_MB:-8192}"
VRAM_FLOOR_MB="${VRAM_FLOOR_MB:-16384}"   # the 16GB co-residency floor (matches gpu-doctor)
READY_TIMEOUT_S="${READY_TIMEOUT_S:-180}"
READY_POLL_S="${READY_POLL_S:-5}"
DEFAULT_INSTALL_DIR="${HOME:-$PWD}/rehearsal"
REHEARSAL_REPO_URL="${REHEARSAL_REPO_URL:-https://github.com/foreztgump/rehearsal.git}"
REHEARSAL_INSTALL_DIR="${REHEARSAL_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

log() { printf '%s\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; }

# --- 0. curl|bash bootstrap ------------------------------------------------
in_checkout() {
  [ -f install.sh ] && [ -f docker-compose.yml ] && [ -f .env.example ] \
    && [ -f ollama/pull-and-pin.sh ]
}

# True iff <dir> already looks like a complete Rehearsal checkout (F19: mirrors
# install.ps1's Test-InCheckout so the two installers agree on "is this a checkout?").
dir_is_checkout() {
  [ -f "$1/install.sh" ] && [ -f "$1/docker-compose.yml" ] \
    && [ -f "$1/.env.example" ] && [ -f "$1/ollama/pull-and-pin.sh" ]
}

bootstrap_checkout() {
  in_checkout && return 0
  if [ "${REHEARSAL_BOOTSTRAPPED:-0}" = "1" ]; then
    err "Installer checkout is incomplete: $PWD"
    exit 1
  fi
  # F19 idempotency: if the install dir is ALREADY a valid checkout (a repeat of the
  # documented curl|bash one-liner after a successful install), just re-run it there
  # instead of hard-erroring. install.ps1's Test-InCheckout already does this; the two
  # installers used to diverge (bash errored with a factually wrong "not a complete
  # checkout" message on a dir that WAS one).
  if dir_is_checkout "$REHEARSAL_INSTALL_DIR"; then
    log "Existing Rehearsal checkout found at ${REHEARSAL_INSTALL_DIR} — re-running it there…"
    cd "$REHEARSAL_INSTALL_DIR"
    REHEARSAL_BOOTSTRAPPED=1 exec ./install.sh "$@"
  fi
  if ! command -v git >/dev/null 2>&1; then
    err "git is required for curl-style install."
    log "Install git, or run: git clone ${REHEARSAL_REPO_URL} ${REHEARSAL_INSTALL_DIR}"
    exit 1
  fi
  # A non-empty dir that is NOT a checkout is a real conflict — do not clobber it.
  if [ -e "$REHEARSAL_INSTALL_DIR" ]; then
    err "Install directory already exists but is not a complete Rehearsal checkout:"
    log "  ${REHEARSAL_INSTALL_DIR}"
    exit 1
  fi
  log "Cloning Rehearsal into ${REHEARSAL_INSTALL_DIR}..."
  mkdir -p "$(dirname "$REHEARSAL_INSTALL_DIR")"
  git clone "$REHEARSAL_REPO_URL" "$REHEARSAL_INSTALL_DIR"
  cd "$REHEARSAL_INSTALL_DIR"
  REHEARSAL_BOOTSTRAPPED=1 exec ./install.sh "$@"
}

bootstrap_checkout "$@"

# --- 0b. Windows: hand off to the native PowerShell installer ----------------
# When this runs in Git Bash / MSYS / Cygwin (e.g. a curl-to-bash install of
# install.sh on Windows), the Linux prerequisite path (apt/dnf/pacman) is
# meaningless. Delegate
# to install.ps1, which uses the winget-based Docker Desktop path. The checkout is
# guaranteed to exist here (bootstrap_checkout ran), so install.ps1 is on disk.
delegate_windows() {
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) : ;;
    *) return 0 ;;
  esac
  ps=""
  for cand in pwsh powershell; do
    if command -v "$cand" >/dev/null 2>&1; then ps="$cand"; break; fi
  done
  if [ -z "$ps" ]; then
    err "Windows detected but no PowerShell found (pwsh/powershell)."
    log "Run the native installer manually:  ./install.ps1"
    exit 1
  fi
  log "Windows detected — handing off to the native PowerShell installer (install.ps1)…"
  set -- -ExecutionPolicy Bypass -File ./install.ps1
  [ "$ASSUME_YES" = "1" ] && set -- "$@" -Yes
  exec "$ps" "$@"
}
delegate_windows

# --- 0c. macOS: detect + guide + stop ---------------------------------------
# macOS is a DIFFERENT topology this installer can't drive: Docker Desktop on Mac
# runs Linux containers in a VM with NO GPU passthrough, so the Apple GPU
# (Metal/MPS) is unreachable from any container. The ONLY GPU-accelerated LLM path
# is NATIVE host Ollama (the Ollama Mac app, Metal/MLX), with the Docker services
# reaching it via host.docker.internal — exactly the Windows-AMD split. The
# GUI-app install + `launchctl` bind widen + `ollama pull` are inherently manual,
# and pull-and-pin.sh drives `docker compose exec ollama` (a no-op stub here), so
# we DETECT + GUIDE (print the exact manual steps) and STOP — never silently run
# the wrong all-in-container CPU topology (mirrors install.ps1 Windows-AMD).
show_macos_guidance_and_exit() {
  log ""
  log "================ macOS (Apple Silicon) detected — manual path ================"
  log "The one-line installer does NOT drive the macOS topology. Docker Desktop on Mac"
  log "cannot pass the Apple GPU into a container, so BOTH GPU services run natively on"
  log "the host — the LLM in NATIVE Ollama and TTS in NATIVE Kokoro (both Metal) — and"
  log "only the CPU services run in Docker (the in-stack ollama + kokoro are no-op"
  log "stubs). Follow these steps:"
  log ""
  log "  1. Install the native Ollama Mac app (https://ollama.com/download), then"
  log "     confirm it is on PATH in a fresh terminal:  ollama --version"
  log "  2. Widen Ollama's bind so containers can reach it via host.docker.internal"
  log "     (native Ollama binds 127.0.0.1 by default), then restart the Ollama app."
  log "     Either enable Settings > 'Expose Ollama to the network' in the Ollama app"
  log "     (v0.10+; if already on, this step is done), or set the env var:"
  log "       launchctl setenv OLLAMA_HOST \"0.0.0.0:11434\""
  log "     NOTE: either way this exposes Ollama's UNAUTHENTICATED API to your LAN. Keep"
  log "     the macOS firewall on and never port-forward 11434 to the WAN."
  log "  3. Pull the recommended model into NATIVE Ollama (not the container), then"
  log "     verify it is loaded:"
  log "       ollama pull evalengine/unbound-e2b:latest   # abliterated GGUF, GPU on Metal"
  log "       ollama ps"
  log "     Recommended tier: fast (8 GB Macs: choose floor). MLX opt-in (max speed,"
  log "     but STOCK/content-filtered — the persona is no longer the sole guardrail):"
  log "       ollama pull gemma4:e2b-nvfp4      # or gemma4:e4b-mlx-bf16"
  log "  4. Scaffold .env (copy .env.example to .env; set a random LIVEKIT_API_SECRET"
  log "     and the single-model config — see INSTALLATION.md 'macOS (Apple Silicon)')."
  log "     Keep STT_FORCE_CPU=1 (the .env.example default) — Docker on Mac has no"
  log "     container GPU, so GPU STT can't run; setting it to 0 hangs the agent."
  log "  5. Start native Kokoro TTS on Metal (binds 0.0.0.0:8880 so the container can"
  log "     reach it via host.docker.internal — same LAN caveat as the Ollama bind):"
  log "       brew install uv espeak-ng"
  log "       scripts/kokoro-native-macos.sh          # add --cpu for the CPU fallback"
  log "       curl -sf http://localhost:8880/health   # expect {\"status\":\"healthy\"}"
  log "  6. From the checkout, build + start with the macOS override (TTS is native"
  log "     Kokoro now — no cpu-tts override):"
  log "       cd \"$PWD\""
  log "       docker compose -f docker-compose.yml -f docker-compose.macos.yml up -d --build"
  log ""
  log "Full walkthrough + validation checklist: INSTALLATION.md ('macOS (Apple Silicon)')."
  log "==========================================================================="
  exit 0
}
case "$(uname -s 2>/dev/null)" in
  Darwin) show_macos_guidance_and_exit ;;
esac

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

# Total VRAM in MB for the primary NVIDIA GPU, or "" if unknown (non-NVIDIA, or a
# driver that rejects the query). Only digits are accepted — a rejected query field
# prints an error string that must not reach the numeric model-default test.
detect_nvidia_vram_mb() {
  command -v nvidia-smi >/dev/null 2>&1 || return 0
  local vram
  vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
            | tr -d ' ' | sort -nr | head -1 || true)"
  case "${vram}" in ''|*[!0-9]*) return 0 ;; esac
  printf '%s\n' "${vram}"
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
  gpu="$1"; vram_mb="${2:-}"
  case "$gpu" in
    # On NVIDIA, pick by VRAM: cards at/below VRAM_SMALL_MB can't comfortably co-fit
    # the Better tier, so default them to the smaller Floor model (field report rec #5).
    # Unknown VRAM keeps the historical Fast default.
    nvidia)
      if [ -n "${vram_mb}" ] && [ "${vram_mb}" -le "${VRAM_SMALL_MB}" ]; then
        default_model="floor"
        log ""
        log "Detected ${vram_mb} MB VRAM (<= ${VRAM_SMALL_MB} MB) — defaulting to the smaller Floor model."
      else
        default_model="fast"
        [ -n "${vram_mb}" ] && log "" && log "Detected ${vram_mb} MB VRAM — defaulting to the Fast model."
      fi ;;
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
  # REHEARSAL_MODEL_CHOICES — the installed set (comma list).
  if grep -q '^REHEARSAL_MODEL_CHOICES=' .env 2>/dev/null; then
    sed -i "s|^REHEARSAL_MODEL_CHOICES=.*|REHEARSAL_MODEL_CHOICES=${INSTALL_MODELS}|" .env
  else
    printf 'REHEARSAL_MODEL_CHOICES=%s\n' "${INSTALL_MODELS}" >> .env
  fi
  # Labels (baked into the web build via NEXT_PUBLIC_REHEARSAL_MODEL_LABELS).
  if grep -q '^NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=' .env 2>/dev/null; then
    sed -i "s|^NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=.*|NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=${MODEL_LABELS}|" .env
  else
    printf 'NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=%s\n' "${MODEL_LABELS}" >> .env
  fi
  # REHEARSAL_DEFAULT_MODEL — first of the installed set (safe: its tag is pinned).
  default_choice="${INSTALL_MODELS%%,*}"
  if grep -q '^REHEARSAL_DEFAULT_MODEL=' .env 2>/dev/null; then
    sed -i "s|^REHEARSAL_DEFAULT_MODEL=.*|REHEARSAL_DEFAULT_MODEL=${default_choice}|" .env
  else
    printf 'REHEARSAL_DEFAULT_MODEL=%s\n' "${default_choice}" >> .env
  fi
}

# --- 1d-bis. Expressive-voice opt-in (Chatterbox) ---------------------------
# GPU-only, large build, exceeds the latency budget — so it is opt-in and prompted
# (unless --expressive/INSTALL_EXPRESSIVE=1 already set it, or the plan is accepted
# non-interactively). On a non-NVIDIA host it is force-disabled (no CPU fallback).
prompt_expressive() {
  gpu="$1"
  if [ "$gpu" != "nvidia" ]; then
    [ "$INSTALL_EXPRESSIVE" = "1" ] && \
      log "Expressive voice needs an NVIDIA GPU (none detected) — disabling it."
    INSTALL_EXPRESSIVE=0
    return 0
  fi
  # Already opted in (flag/env) or accepting the plan non-interactively: keep as-is.
  [ "$INSTALL_EXPRESSIVE" = "1" ] && return 0
  [ "$ASSUME_YES" = "1" ] && return 0
  printf 'Install expressive voice (Chatterbox)? ~19GB extra build, +4.3GB VRAM, exceeds the P50<1.0s budget [y/N] '
  read -r reply
  case "$reply" in
    y|Y|yes|Yes) INSTALL_EXPRESSIVE=1 ;;
    *) INSTALL_EXPRESSIVE=0 ;;
  esac
}

# --- 1d-ter. Write the expressive-voice env (baked into web + read by up.sh) -
# Two keys: NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE bakes the picker into the web
# bundle; COMPOSE_PROFILES=expressive makes up.sh (which reads COMPOSE_PROFILES) bring
# the chatterbox service up. Both are set only when opted in; otherwise cleared to the
# default so re-running WITHOUT --expressive turns the feature back off.
write_expressive_env() {
  want="$INSTALL_EXPRESSIVE"   # "1" or "0"
  if grep -q '^NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=' .env 2>/dev/null; then
    sed -i "s|^NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=.*|NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=${want}|" .env
  else
    printf 'NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=%s\n' "${want}" >> .env
  fi
  if [ "$want" = "1" ]; then
    if grep -q '^COMPOSE_PROFILES=' .env 2>/dev/null; then
      grep -q '^COMPOSE_PROFILES=.*expressive' .env || \
        sed -i "s|^COMPOSE_PROFILES=\(.*\)|COMPOSE_PROFILES=\1,expressive|" .env
    else
      printf 'COMPOSE_PROFILES=expressive\n' >> .env
    fi
  else
    # Remove the profile so a later default re-run stops starting chatterbox. Drops the
    # whole line only when it is exactly the expressive profile (leaves multi-profile
    # setups, e.g. stt-gpu, untouched — the operator manages those).
    sed -i '/^COMPOSE_PROFILES=expressive$/d' .env
  fi
}

# --- 1e. CPU override layering for AMD / no-GPU Linux hosts (F19) ------------
# The base compose reserves an nvidia device for ollama (and kokoro), so on a host
# with no NVIDIA GPU `docker compose up` dead-ends at ollama with "could not select
# device driver 'nvidia'". Persist a COMPOSE_FILE in .env that layers the cpu-llm +
# cpu-tts overrides (which !reset those reservations) so EVERY later `docker compose`
# / up.sh / down.sh honors it — not just this install run. Idempotent: only written
# when absent, and only on GPU=amd|none (an NVIDIA host keeps the plain base compose).
layer_cpu_overrides() {
  gpu="$1"
  [ "$gpu" = "amd" ] || [ "$gpu" = "none" ] || return 0
  # ':'-separated per Compose's COMPOSE_FILE contract; base first, overrides after.
  cpu_stack="docker-compose.yml:docker-compose.cpu-llm.yml:docker-compose.cpu-tts.yml"
  if grep -q '^COMPOSE_FILE=' .env 2>/dev/null; then
    log "COMPOSE_FILE already set in .env — leaving it untouched."
  else
    printf 'COMPOSE_FILE=%s\n' "${cpu_stack}" >> .env
    log "No NVIDIA GPU — layered CPU overrides via COMPOSE_FILE in .env (ollama + kokoro on CPU)."
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
  log "================ Rehearsal setup plan ================"
  log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  log "GPU vendor detected: ${gpu}"
  log "Models to install: ${models}"
  if [ "$INSTALL_EXPRESSIVE" = "1" ]; then
    log "Expressive voice: ENABLED (Chatterbox) — large extra build + ~4.3GB VRAM;"
    log "  voice-to-voice P50 EXCEEDS the 1.0s budget by design when expressive is used."
  else
    log "Expressive voice: off (Kokoro only). Re-run with --expressive to add it later."
  fi
  log "Install guide: INSTALLATION.md (prereqs, platform notes, download sizes)"
  if [ "$gpu" = "nvidia" ]; then
    log "STT placement: CPU-ONNX by default (STT_FORCE_CPU=1, VRAM-safe). GPU STT is"
    log "  opt-in after the co-residency matrix passes (docker compose --profile stt-gpu)."
    log "VRAM budget: 16 GB target — ollama + kokoro resident (scripts/vram-validate.sh)."
  else
    log "No NVIDIA GPU detected (${gpu}). The installer will layer the CPU overrides"
    log "  (docker-compose.cpu-llm.yml + cpu-tts.yml) so ollama + kokoro run on CPU and"
    log "  the stack BOOTS — but CPU inference will NOT hit the P50<1.0s latency target."
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
  # Expressive-voice env is written BEFORE the build so the web image bakes the
  # correct NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE flag (availability is known
  # up front from the flag/prompt — unlike model choices, it has no pull dependency).
  write_expressive_env
  if [ "$INSTALL_EXPRESSIVE" = "1" ]; then
    log "Building images incl. expressive voice (Chatterbox — large first build)…"
    # --profile expressive so the profiled chatterbox service is built too; the web
    # image bakes AVAILABLE=1 from the .env line just written.
    docker compose --profile expressive build
  else
    log "Building images (first run pulls several GB + bakes the STT model)…"
    docker compose build
  fi
  log "Starting ollama to pull + pin the selected models…"
  docker compose up -d ollama
  INSTALL_MODELS="${INSTALL_MODELS}" REHEARSAL_DEFAULT_MODEL="${INSTALL_MODELS%%,*}" \
    ./ollama/pull-and-pin.sh
  # Write the model-choices env ONLY after pull-and-pin succeeds — so .env never
  # claims a model is installed before its tag is confirmed resident (the
  # floor-path landmine: REHEARSAL_DEFAULT_MODEL=floor with no OLLAMA_MODEL_FLOOR).
  write_model_env
  log "Starting the full stack…"
  docker compose up -d
}

# --- 5. Health-gate the finish line -----------------------------------------
# `docker compose up -d` returns as soon as containers are CREATED, not when the
# agent has warmed models and registered as a LiveKit worker — so a naive installer
# prints "ready" while the first turn would still fail. Poll until the agent logs
# "registered worker" (bounded by READY_TIMEOUT_S); on timeout, advise rather than
# fail (a slow cold warmup on a sub-16GB card is expected, not an error).
wait_for_ready() {
  gpu="$1"; vram_mb="${2:-}"
  log ""
  log "Waiting for the agent to warm models + register (up to ${READY_TIMEOUT_S}s)…"
  waited=0
  while [ "${waited}" -lt "${READY_TIMEOUT_S}" ]; do
    if docker compose logs --tail=200 agent 2>/dev/null | grep -qi 'registered worker'; then
      log "Agent registered — ready to talk. Open the web UI (see NEXT_PUBLIC_LIVEKIT_URL in .env)."
      return 0
    fi
    sleep "${READY_POLL_S}"
    waited=$((waited + READY_POLL_S))
  done
  log "Agent not registered after ${READY_TIMEOUT_S}s — the model may still be warming."
  if [ "$gpu" != "nvidia" ] || { [ -n "${vram_mb}" ] && [ "${vram_mb}" -lt "${VRAM_FLOOR_MB}" ]; }; then
    log "  On CPU / sub-16GB GPUs the first turn is slow while STT/LLM/TTS warm — this is expected."
  fi
  log "  Watch progress: docker compose logs -f agent   (look for 'registered worker')."
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
layer_cpu_overrides "$GPU"
VRAM_MB="$(detect_nvidia_vram_mb)"
prompt_models "$GPU" "$VRAM_MB"
prompt_expressive "$GPU"
print_plan "$GPU" "$INSTALL_MODELS"
confirm
build_and_pull
wait_for_ready "$GPU" "$VRAM_MB"
log ""
log "Done. The stack is up."
log "  Start:  ./up.sh -d        (preflight + docker compose up -d)"
log "  Stop:   ./down.sh         (docker compose down)"
log "  Logs:   docker compose logs -f agent"
log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
log "Install guide: INSTALLATION.md"
