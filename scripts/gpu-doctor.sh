#!/usr/bin/env bash
#
# gpu-doctor.sh — preflight GPU "doctor" for the consumer `docker compose` deploy.
#
# Runs an ORDERED chain of host checks BEFORE `docker compose up` and, on any
# problem, prints the EXACT remedy plus a copy-paste env snippet — instead of
# letting `up` hang on a cryptic `could not select device driver` or silently
# OOM on a sub-spec card. `docker compose` on the user's own machine is the ONLY
# supported deployment (there is no VM/passthrough path).
#
# Posture: NON-BLOCKING ADVISE. This script ALWAYS exits 0 so `./up.sh` proceeds;
# its only job is to make GPU/driver/toolkit/VRAM problems legible and to print
# the env snippet for the VRAM-safe degraded path. It NEVER writes .env and NEVER
# switches anything at runtime — the actual CPU/GPU STT choice stays with
# STT_FORCE_CPU + the Phase-10 placement resolver.
#
# Ordered chain (each step: detect -> on fail, print remedy + keep going):
#   1. nvidia-smi present + driver responds        (non-NVIDIA / no driver)
#   2. NVIDIA Container Toolkit wired              (docker run --gpus all ...)
#   3. CUDA/driver floor >= 12.8                   (Blackwell / kokoro cu128)
#   4. VRAM floor >= 16384 MB                       (the 16GB co-residency budget)
#
# Run directly:        ./scripts/gpu-doctor.sh
# Run via the wrapper: ./up.sh           (runs this first, then docker compose up)
#
# Env overrides (single-sourced floors — do not scatter literals elsewhere):
#   VRAM_FLOOR_MB        (default 16384 — matches scripts/vram-validate.sh VRAM_LIMIT_MB)
#   CUDA_FLOOR           (default 12.8  — kokoro …-cu128 Blackwell/sm_120 image)
#   TOOLKIT_PROBE_IMAGE  (default nvidia/cuda:12.4.0-base-ubuntu22.04 — same image the
#                         README --gpus all verification step uses)
set -euo pipefail

readonly VRAM_FLOOR_MB="${VRAM_FLOOR_MB:-16384}"
readonly CUDA_FLOOR="${CUDA_FLOOR:-12.8}"
readonly TOOLKIT_PROBE_IMAGE="${TOOLKIT_PROBE_IMAGE:-nvidia/cuda:12.4.0-base-ubuntu22.04}"
readonly AMD_DEVICE_ROOT="${AMD_DEVICE_ROOT:-/dev}"
readonly AMD_COMPOSE_FILE="docker-compose.yml:docker-compose.amd.yml"
readonly OLLAMA_ROCM_IMAGE="ollama/ollama:0.30.11-rocm"
readonly KOKORO_ROCM_IMAGE="ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0"

# R3 final (advise-only): use buffered Parakeet everywhere; use GPU only on 16GB+
# NVIDIA hosts, otherwise keep STT buffered on CPU.
readonly VRAM_HYBRID_MB="${VRAM_HYBRID_MB:-12288}"

# The documented degraded defaults (consistent with .env.example): CPU STT +
# the Fast LLM tag. Referenced in the degraded snippet — not new literals.
readonly FAST_LLM_TAG="evalengine/unbound-e2b:latest"

# DEGRADED accumulates across checks; any failed check sets it. The final advice
# block branches on it. We never exit non-zero (ADVISE posture).
DEGRADED=0
NVIDIA_OK=0   # set when step 1 passes (gates steps 3 & 4, which query the GPU)
DETECTED_VRAM_MB=""   # set by check_vram_floor; drives the R3 STT engine recommendation
GPU_VENDOR="none"

ok()     { printf 'OK: %s\n' "$*"; }
advise() { printf 'ADVISE: %s\n' "$*"; DEGRADED=1; }
hr()     { printf -- '----------------------------------------------------------------------\n'; }

detect_gpu_vendor() {
  # macOS first: a Mac has no nvidia-smi and no /dev/kfd, so without this it would
  # fall through to "none" and print a misleading CPU-degraded block — when native
  # host Ollama on Metal is actually the correct, GPU-accelerated Mac path.
  if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
    GPU_VENDOR="macos"
  elif command -v nvidia-smi >/dev/null 2>&1; then
    GPU_VENDOR="nvidia"
  elif [ -e "${AMD_DEVICE_ROOT}/kfd" ] && [ -d "${AMD_DEVICE_ROOT}/dri" ]; then
    GPU_VENDOR="amd"
  else
    GPU_VENDOR="none"
  fi
}

# --- Step 1: nvidia-smi present + driver responds --------------------------------
check_nvidia_smi() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    advise "No \`nvidia-smi\` on PATH — no NVIDIA driver detected."
    printf '  Fix: install the NVIDIA driver for your GPU so nvidia-smi prints a\n'
    printf '       GPU table, then re-run. (Or run CPU-degraded — see below.)\n'
    return
  fi
  if ! nvidia-smi >/dev/null 2>&1; then
    advise "\`nvidia-smi\` is installed but the driver did not respond."
    printf '  Fix: the driver/library versions likely mismatch (common after a driver\n'
    printf '       update without a reboot). Reboot, or reinstall the NVIDIA driver.\n'
    return
  fi
  NVIDIA_OK=1
  ok "nvidia-smi present and the driver responds."
}

# --- Step 2: NVIDIA Container Toolkit wired --------------------------------------
check_toolkit() {
  if ! command -v docker >/dev/null 2>&1; then
    advise "\`docker\` not found — cannot run the stack."
    printf '  Fix: install Docker Engine + the Compose plugin, then re-run.\n'
    return
  fi
  if [ "${NVIDIA_OK}" -ne 1 ]; then
    # No GPU/driver in step 1 — the --gpus probe is guaranteed to fail and would
    # make a non-NVIDIA user pull a CUDA image for nothing. Skip the pull, advise.
    advise "Skipping the container-GPU probe (no working driver from step 1)."
    printf '  Once the driver works, this step verifies the NVIDIA Container Toolkit.\n'
    return
  fi
  local probe_err
  if probe_err="$(docker run --rm --gpus all "${TOOLKIT_PROBE_IMAGE}" nvidia-smi 2>&1)"; then
    ok "NVIDIA Container Toolkit wired — a container can see the GPU."
    return
  fi
  # Distinguish the classic toolkit-missing string from any other failure.
  if printf '%s' "${probe_err}" | grep -qi 'could not select device driver'; then
    advise "GPU not reachable from a container — NVIDIA Container Toolkit missing or the Docker runtime is not configured."
  else
    advise "GPU not reachable from a container (\`docker run --gpus all\` failed)."
    printf '  (probe said: %s)\n' "$(printf '%s' "${probe_err}" | head -1)"
  fi
  printf '  Fix: install + wire the NVIDIA Container Toolkit, then restart Docker:\n'
  printf '       sudo apt-get install -y nvidia-container-toolkit\n'
  printf '       sudo nvidia-ctk runtime configure --runtime=docker\n'
  printf '       sudo systemctl restart docker\n'
}

# Numeric major.minor compare: returns 0 (true) if $1 >= $2. NOT lexical
# ("12.8" < "12.10" must be handled), so split on the dot and compare ints.
version_ge() {
  local a="$1" b="$2"
  local a_major="${a%%.*}" a_minor="${a#*.}" b_major="${b%%.*}" b_minor="${b#*.}"
  [ "${a_minor}" = "${a}" ] && a_minor=0
  [ "${b_minor}" = "${b}" ] && b_minor=0
  # Guard against any non-numeric component reaching the arithmetic [ -gt/-ge ]
  # tests (which abort the script under set -e). Treat unpar? as "older".
  case "${a_major}${a_minor}${b_major}${b_minor}" in *[!0-9]*) return 1 ;; esac
  if [ "${a_major}" -gt "${b_major}" ]; then return 0; fi
  if [ "${a_major}" -lt "${b_major}" ]; then return 1; fi
  [ "${a_minor}" -ge "${b_minor}" ]
}

# --- Step 3: CUDA/driver floor ---------------------------------------------------
check_cuda_floor() {
  [ "${NVIDIA_OK}" -eq 1 ] || return 0   # can't query a GPU that isn't there
  # nvidia-smi's header reports the MAX CUDA the installed driver supports.
  # `|| true`: a driver that rejects the query field exits non-zero, which would
  # trip pipefail+set -e before we get to sanitize the value below.
  local cuda
  cuda="$(nvidia-smi --query-gpu=cuda_version --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ' || true)"
  # Some drivers reject the cuda_version query field and print an error string
  # ("Field ... is not a valid field to query") instead of an empty result — and
  # older drivers lack the field entirely. Accept the value ONLY if it looks like a
  # version number; otherwise fall back to parsing nvidia-smi's textual header.
  case "${cuda}" in
    ''|*[!0-9.]*)
      cuda="$(nvidia-smi 2>/dev/null \
        | sed -n 's/.*CUDA Version: \([0-9][0-9.]*\).*/\1/p; s/.*CUDA UMD Version: \([0-9][0-9.]*\).*/\1/p' \
        | head -1 || true)" ;;
  esac
  if [ -z "${cuda}" ]; then
    advise "Could not read the driver's CUDA version (need >= ${CUDA_FLOOR})."
    printf '  Fix: update your NVIDIA driver; kokoro needs CUDA >= %s (Blackwell).\n' "${CUDA_FLOOR}"
    return
  fi
  if version_ge "${cuda}" "${CUDA_FLOOR}"; then
    ok "Driver supports CUDA ${cuda} (>= ${CUDA_FLOOR})."
  else
    advise "Driver supports CUDA ${cuda}, but kokoro needs CUDA >= ${CUDA_FLOOR} (Blackwell/sm_120)."
    printf '  Fix: update your NVIDIA driver to one that advertises CUDA >= %s.\n' "${CUDA_FLOOR}"
  fi
}

# --- Step 4: VRAM floor ----------------------------------------------------------
check_vram_floor() {
  [ "${NVIDIA_OK}" -eq 1 ] || return 0
  local vram
  vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
            | tr -d ' ' | sort -nr | head -1 || true)"
  # Only accept an all-digit value; a driver that rejects the query field prints an
  # error string, which would crash the numeric [ -ge ] test under set -e.
  case "${vram}" in ''|*[!0-9]*) vram="" ;; esac
  DETECTED_VRAM_MB="${vram}"   # global for print_advice's STT recommendation (may be "")
  if [ -z "${vram}" ]; then
    advise "Could not read total VRAM (need >= ${VRAM_FLOOR_MB} MB)."
    return
  fi
  if [ "${vram}" -ge "${VRAM_FLOOR_MB}" ]; then
    ok "GPU has ${vram} MB VRAM (>= ${VRAM_FLOOR_MB} MB floor)."
  else
    advise "GPU has ${vram} MB VRAM; the full 16 GB STT+LLM+TTS stack will not co-reside (floor ${VRAM_FLOOR_MB} MB)."
    printf '  Fix: run CPU-degraded STT + the Fast model (snippet below); the stack\n'
    printf '       still comes up usable.\n'
  fi
}

# recommend_stt_profile <vram_mb> — echo the advised STT_ENGINE/device/total env lines
# for the detected VRAM. Pure: a number in, lines out; empty/non-numeric → conservative
# buffered/CPU. Advise-only — the operator copies these into .env; we never write it.
recommend_stt_profile() {
  local vram="$1"
  case "${vram}" in
    ''|*[!0-9]*)
      printf '  STT_ENGINE=buffered          # no/unknown VRAM -> accuracy-mode, CPU Parakeet\n'
      printf '  STT_BUFFERED_DEVICE=cpu\n'
      return ;;
  esac
  if [ "${vram}" -ge "${VRAM_FLOOR_MB}" ]; then
    printf '  STT_ENGINE=buffered          # >=16GB -> Parakeet final on GPU\n'
    printf '  STT_BUFFERED_DEVICE=gpu\n'
  elif [ "${vram}" -ge "${VRAM_HYBRID_MB}" ]; then
    printf '  STT_ENGINE=buffered          # 12-16GB -> Parakeet final on CPU (frees VRAM)\n'
    printf '  STT_BUFFERED_DEVICE=cpu\n'
  else
    printf '  STT_ENGINE=buffered          # <12GB -> accuracy-mode, CPU Parakeet\n'
    printf '  STT_BUFFERED_DEVICE=cpu\n'
  fi
  printf '  VRAM_TOTAL_MB=%s\n' "${vram}"
}

# --- Final advice block (always printed) -----------------------------------------
print_advice() {
  hr
  if [ "${DEGRADED}" -eq 0 ]; then
    ok "GPU ready."
    printf 'You can opt into GPU STT (otherwise the default boots VRAM-safe CPU STT):\n\n'
    printf '  # GPU ready — opt into GPU STT ONLY after 10-PLACEMENT-VERIFY.md passes:\n'
    printf '  #   set in .env:  STT_FORCE_CPU=0   STT_HEADROOM_MEASURED=1\n'
    printf '  docker compose --profile stt-gpu up\n\n'
    printf 'Default (safe): docker compose up   # CPU STT, VRAM-safe\n'
  else
    advise_summary
  fi
  printf '\nRecommended STT engine for this host (advise-only — copy into .env if you want):\n'
  recommend_stt_profile "${DETECTED_VRAM_MB}"
  hr
  printf 'Note: the first `up` builds/pulls multi-GB GPU images and bakes the STT\n'
  printf '      model — watch `docker compose ps` for health: starting -> healthy.\n'
  printf '      It is NOT hung.\n'
}

print_amd_advice() {
  hr
  ok "AMD ROCm device nodes present: ${AMD_DEVICE_ROOT}/kfd and ${AMD_DEVICE_ROOT}/dri"
  printf 'R6 AMD ROCm profile (best-effort): Ollama ROCm + Kokoro ROCm + CPU STT.\n\n'
  printf '  COMPOSE_FILE=%s docker compose up -d\n\n' "${AMD_COMPOSE_FILE}"
  printf 'Expected ROCm images:\n'
  printf '  %s\n' "${OLLAMA_ROCM_IMAGE}"
  printf '  %s\n\n' "${KOKORO_ROCM_IMAGE}"
  printf 'Recommended .env settings:\n'
  printf '  STT_ENGINE=buffered\n'
  printf '  STT_BUFFERED_DEVICE=cpu\n'
  printf '  STT_FORCE_CPU=1\n\n'
  printf 'Caution: first ROCm boot may spend time in MIOpen warmup/compilation.\n'
  printf 'See INSTALLATION.md for AMD platform notes.\n'
  hr
}

print_macos_advice() {
  hr
  ok "macOS detected — native host Ollama on Metal is the intended, GPU-accelerated path."
  printf 'Docker Desktop on Mac cannot pass the Apple GPU into a container, so the LLM\n'
  printf 'runs in NATIVE host Ollama (Metal/MLX) and the CPU services run in Docker.\n\n'
  printf 'One-time: native Ollama binds 127.0.0.1, so widen it for host.docker.internal\n'
  printf '(then restart the Ollama app):\n'
  printf '  launchctl setenv OLLAMA_HOST "0.0.0.0:11434"\n\n'
  printf 'Start the stack with the macOS override (TTS is native Kokoro now,\n'
  printf 'no cpu-tts override):\n\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.macos.yml up -d\n\n'
  printf 'Recommended .env settings:\n'
  printf '  STT_ENGINE=buffered\n'
  printf '  STT_BUFFERED_DEVICE=cpu\n'
  printf '  STT_FORCE_CPU=1\n\n'
  printf 'See INSTALLATION.md ("macOS (Apple Silicon)") for the model tiers (abliterated\n'
  printf 'GGUF default vs MLX opt-in) and the validation checklist.\n'
  hr
}

advise_summary() {
  printf 'One or more checks need attention. The stack still runs VRAM-safe on CPU\n'
  printf 'STT + the Fast model. Copy these into .env (this script does NOT edit .env):\n\n'
  printf '  # Sub-spec / non-NVIDIA host — CPU STT + Fast model (the safe defaults):\n'
  printf '  STT_FORCE_CPU=1\n'
  printf '  OLLAMA_MODEL=%s   # the Fast tag\n' "${FAST_LLM_TAG}"
  printf '  # then: docker compose up   (do NOT add --profile stt-gpu)\n\n'
  printf 'Limitation: ollama + kokoro require a supported GPU profile. Without NVIDIA\n'
  printf 'or AMD ROCm device nodes, use the CPU STT profile only.\n'
}

main() {
  printf 'gpu-doctor: preflight checks for `docker compose up` (advise-only, never blocks)\n'
  hr
  detect_gpu_vendor
  case "${GPU_VENDOR}" in
    nvidia)
      check_nvidia_smi
      check_toolkit
      check_cuda_floor
      check_vram_floor
      print_advice ;;
    macos)
      print_macos_advice ;;
    amd)
      print_amd_advice ;;
    *)
      advise "No \`nvidia-smi\` on PATH or working NVIDIA driver, and no AMD ROCm device nodes were found."
      print_advice ;;
  esac
  exit 0
}

main "$@"
