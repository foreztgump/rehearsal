#!/usr/bin/env bash
#
# test_gpu_doctor.sh — sandbox harness for scripts/gpu-doctor.sh.
#
# Builds a temp PATH shim dir with FAKE `nvidia-smi` + `docker` whose behavior is
# driven by env (FAKE_SMI / FAKE_SMI_CUDA / FAKE_SMI_VRAM / FAKE_DOCKER), then runs
# the doctor across 5 scenarios and asserts (a) the right remedy substring appears,
# (b) the right env snippet (GPU vs degraded) appears, (c) the doctor exits 0 every
# time. Imports NO real GPU and NO real Docker — this is the executor's green proof.
#
#   ./scripts/test_gpu_doctor.sh
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DOCTOR="${SCRIPT_DIR}/gpu-doctor.sh"
readonly BASH="$(command -v bash)"
readonly SHIM_DIR="$(mktemp -d)"
readonly AMD_DEVICE_ROOT="$(mktemp -d)"
trap 'rm -rf "${SHIM_DIR}" "${AMD_DEVICE_ROOT}"' EXIT

# --- fake nvidia-smi -------------------------------------------------------------
# FAKE_SMI=missing  -> not created (command -v fails)
# FAKE_SMI=broken   -> created but exits non-zero (driver/library mismatch)
# FAKE_SMI=ok       -> responds; serves cuda_version / memory.total queries
cat > "${SHIM_DIR}/nvidia-smi" <<'SMI'
#!/usr/bin/env bash
[ "${FAKE_SMI:-ok}" = "broken" ] && exit 1
case "$*" in
  *cuda_version*)  [ "${FAKE_SMI_QUERY_FAIL:-0}" = "1" ] && { echo "Field 'cuda_version' is not a valid field to query"; exit 1; }; echo "${FAKE_SMI_CUDA:-12.8}" ;;
  *memory.total*)  echo "${FAKE_SMI_VRAM:-32607}" ;;
  *)               echo "fake nvidia-smi: GPU 0: NVIDIA (${FAKE_SMI_HEADER_LABEL:-CUDA Version}: ${FAKE_SMI_CUDA:-12.8})" ;;
esac
exit 0
SMI
chmod +x "${SHIM_DIR}/nvidia-smi"

# --- fake docker -----------------------------------------------------------------
# FAKE_DOCKER=ok        -> `docker run --gpus all ... nvidia-smi` succeeds
# FAKE_DOCKER=no-driver -> prints the classic toolkit-missing string, exit 1
# FAKE_DOCKER=missing   -> handled by NOT putting docker on PATH
cat > "${SHIM_DIR}/docker" <<'DOCK'
#!/usr/bin/env bash
case "${FAKE_DOCKER:-ok}" in
  no-driver)
    echo 'docker: Error response from daemon: could not select device driver "nvidia" with capabilities: [[gpu]].' >&2
    exit 1 ;;
  *)
    echo "fake docker: GPU visible in container"
    exit 0 ;;
esac
DOCK
chmod +x "${SHIM_DIR}/docker"

PASS=0
FAIL=0

reset_fake_amd_devices() {
  rm -f "${AMD_DEVICE_ROOT}/kfd"
  rm -rf "${AMD_DEVICE_ROOT}/dri"
}

enable_fake_amd_devices() {
  mkdir -p "${AMD_DEVICE_ROOT}/dri"
  : > "${AMD_DEVICE_ROOT}/kfd"
}

# Coreutils the doctor invokes by bare name. We symlink ONLY these into an isolated
# PATH so the host's REAL nvidia-smi/docker can never leak in when we drop a shim.
# Includes env + bash because the fake shims use a `#!/usr/bin/env bash` shebang,
# which must resolve against this isolated PATH (the host's /usr/bin is excluded so
# the real nvidia-smi/docker can never leak in).
readonly -a NEEDED_TOOLS=(grep sed sort head tr cat env bash)

# run_doctor <drop> -- captures combined output + exit code. PATH = the temp shim
# dir ONLY (plus symlinked coreutils), so dropping a shim genuinely makes it missing.
run_doctor() {
  local drop="$1"; shift
  local tmpdir="$(mktemp -d)"
  cp "${SHIM_DIR}/nvidia-smi" "${SHIM_DIR}/docker" "${tmpdir}/"
  [ "${drop}" = "no-nvidia-smi" ] && rm -f "${tmpdir}/nvidia-smi"
  [ "${drop}" = "no-docker" ] && rm -f "${tmpdir}/docker"
  local tool path
  for tool in "${NEEDED_TOOLS[@]}"; do
    path="$(command -v "${tool}")" && ln -sf "${path}" "${tmpdir}/${tool}"
  done
  DOCTOR_OUT="$(env -i PATH="${tmpdir}" \
    FAKE_SMI="${FAKE_SMI:-}" FAKE_SMI_CUDA="${FAKE_SMI_CUDA:-}" FAKE_SMI_VRAM="${FAKE_SMI_VRAM:-}" \
    FAKE_SMI_QUERY_FAIL="${FAKE_SMI_QUERY_FAIL:-}" FAKE_SMI_HEADER_LABEL="${FAKE_SMI_HEADER_LABEL:-}" \
    FAKE_DOCKER="${FAKE_DOCKER:-}" AMD_DEVICE_ROOT="${AMD_DEVICE_ROOT}" \
    "${BASH}" "${DOCTOR}" 2>&1)"
  DOCTOR_RC=$?
  rm -rf "${tmpdir}"
}

# assert_scenario <name> <expect-substr> <expect-snippet:gpu|degraded>
assert_scenario() {
  local name="$1" expect="$2" snippet="$3"
  local snippet_marker
  if [ "${snippet}" = "gpu" ]; then
    snippet_marker="--profile stt-gpu up"
  else
    snippet_marker="STT_FORCE_CPU=1"
  fi
  local errs=""
  [ "${DOCTOR_RC}" -eq 0 ] || errs="${errs} [exit ${DOCTOR_RC}!=0]"
  printf '%s' "${DOCTOR_OUT}" | grep -qiF -- "${expect}" || errs="${errs} [missing remedy: ${expect}]"
  printf '%s' "${DOCTOR_OUT}" | grep -qF -- "${snippet_marker}" || errs="${errs} [missing ${snippet} snippet]"
  # The degraded scenarios must NOT print the GPU-ready snippet, and vice-versa.
  if [ "${snippet}" = "degraded" ]; then
    printf '%s' "${DOCTOR_OUT}" | grep -qF -- "OK: GPU ready." && errs="${errs} [unexpected GPU-ready in degraded]"
  else
    printf '%s' "${DOCTOR_OUT}" | grep -qF -- "Sub-spec / non-NVIDIA host" && errs="${errs} [unexpected degraded snippet in OK]"
  fi
  if [ -z "${errs}" ]; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "${name}"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s -%s\n' "${name}" "${errs}"
    printf -- '------ doctor output ------\n%s\n---------------------------\n' "${DOCTOR_OUT}"
  fi
}

assert_contains() {
  local name="$1" substr="$2"
  if printf '%s' "${DOCTOR_OUT}" | grep -qF -- "${substr}"; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "${name}"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s [missing: %s]\n' "${name}" "${substr}"
    printf -- '------ doctor output ------\n%s\n---------------------------\n' "${DOCTOR_OUT}"
  fi
}

assert_not_contains() {
  local name="$1" substr="$2"
  if printf '%s' "${DOCTOR_OUT}" | grep -qF -- "${substr}"; then
    FAIL=$((FAIL+1)); printf 'FAIL  %s [unexpected: %s]\n' "${name}" "${substr}"
    printf -- '------ doctor output ------\n%s\n---------------------------\n' "${DOCTOR_OUT}"
  else
    PASS=$((PASS+1)); printf 'PASS  %s\n' "${name}"
  fi
}

# 1. nvidia-smi missing -> non-NVIDIA, degraded snippet.
reset_fake_amd_devices
FAKE_SMI_CUDA="" FAKE_SMI_VRAM="" FAKE_DOCKER="" run_doctor "no-nvidia-smi"
assert_scenario "nvidia-smi-missing" "No \`nvidia-smi\` on PATH" "degraded"

# 1a. nvidia-smi present but broken -> NVIDIA-specific driver advice.
reset_fake_amd_devices
FAKE_SMI="broken" FAKE_SMI_CUDA="" FAKE_SMI_VRAM="" FAKE_DOCKER="" run_doctor ""
assert_scenario "nvidia-smi-broken" "driver did not respond" "degraded"
FAKE_SMI=""

# 1b. nvidia-smi missing + AMD device nodes -> AMD ROCm advice, no NVIDIA degraded copy.
enable_fake_amd_devices
FAKE_SMI_CUDA="" FAKE_SMI_VRAM="" FAKE_DOCKER="" run_doctor "no-nvidia-smi"
assert_contains "amd-compose-file" "COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml"
assert_contains "amd-ollama-image" "ollama/ollama:0.30.11-rocm"
assert_contains "amd-kokoro-image" "kokoro-fastapi-rocm:v0.5.0"
assert_not_contains "amd-no-nvidia-degraded" "Sub-spec / non-NVIDIA host"
reset_fake_amd_devices

# 2. toolkit missing (docker run --gpus prints the classic string) -> degraded.
reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="no-driver" run_doctor ""
assert_scenario "toolkit-no-driver" "NVIDIA Container Toolkit missing" "degraded"

# 3. CUDA too old -> degraded.
reset_fake_amd_devices
FAKE_SMI_CUDA="12.4" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "cuda-too-old" "needs CUDA >= 12.8" "degraded"

# 4. VRAM sub-spec -> degraded.
reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="8188" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "vram-sub-spec" "will not co-reside" "degraded"

# 5. all OK -> GPU-ready snippet.
reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "all-ok" "OK: GPU ready." "gpu"

# 5a. Newer Windows drivers can reject the cuda_version query field and print
# "CUDA UMD Version" in the header. The fallback parser must accept that label.
reset_fake_amd_devices
FAKE_SMI_CUDA="13.3" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" \
  FAKE_SMI_QUERY_FAIL="1" FAKE_SMI_HEADER_LABEL="CUDA UMD Version" run_doctor ""
assert_scenario "cuda-umd-header-fallback" "Driver supports CUDA 13.3" "gpu"
FAKE_SMI_QUERY_FAIL="" FAKE_SMI_HEADER_LABEL=""

# --- R3: STT engine recommendation per detected VRAM (advise-only) ---------------
reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-16gb-buffered"  "STT_ENGINE=buffered"
assert_contains "engine-16gb-gpu-dev"   "STT_BUFFERED_DEVICE=gpu"

reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="12288" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-12gb-buffered"  "STT_ENGINE=buffered"
assert_contains "engine-12gb-cpu-dev"   "STT_BUFFERED_DEVICE=cpu"

reset_fake_amd_devices
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="8188" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-8gb-buffered"   "STT_ENGINE=buffered"

reset_fake_amd_devices
run_doctor "no-nvidia-smi"
assert_contains "engine-nogpu-buffered" "STT_ENGINE=buffered"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
