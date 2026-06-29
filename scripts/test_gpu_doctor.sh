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
trap 'rm -rf "${SHIM_DIR}"' EXIT

# --- fake nvidia-smi -------------------------------------------------------------
# FAKE_SMI=missing  -> not created (command -v fails)
# FAKE_SMI=ok       -> responds; serves cuda_version / memory.total queries
cat > "${SHIM_DIR}/nvidia-smi" <<'SMI'
#!/usr/bin/env bash
case "$*" in
  *cuda_version*)  echo "${FAKE_SMI_CUDA:-12.8}" ;;
  *memory.total*)  echo "${FAKE_SMI_VRAM:-32607}" ;;
  *)               echo "fake nvidia-smi: GPU 0: NVIDIA (CUDA Version: ${FAKE_SMI_CUDA:-12.8})" ;;
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
    FAKE_SMI_CUDA="${FAKE_SMI_CUDA:-}" FAKE_SMI_VRAM="${FAKE_SMI_VRAM:-}" \
    FAKE_DOCKER="${FAKE_DOCKER:-}" \
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

# 1. nvidia-smi missing -> non-NVIDIA, degraded snippet.
FAKE_SMI_CUDA="" FAKE_SMI_VRAM="" FAKE_DOCKER="" run_doctor "no-nvidia-smi"
assert_scenario "nvidia-smi-missing" "No \`nvidia-smi\` on PATH" "degraded"

# 2. toolkit missing (docker run --gpus prints the classic string) -> degraded.
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="no-driver" run_doctor ""
assert_scenario "toolkit-no-driver" "NVIDIA Container Toolkit missing" "degraded"

# 3. CUDA too old -> degraded.
FAKE_SMI_CUDA="12.4" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "cuda-too-old" "needs CUDA >= 12.8" "degraded"

# 4. VRAM sub-spec -> degraded.
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="8188" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "vram-sub-spec" "will not co-reside" "degraded"

# 5. all OK -> GPU-ready snippet.
FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_scenario "all-ok" "OK: GPU ready." "gpu"

# --- R3: STT engine recommendation per detected VRAM (advise-only) ---------------
assert_contains() {
  local name="$1" substr="$2"
  if printf '%s' "${DOCTOR_OUT}" | grep -qF -- "${substr}"; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "${name}"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s [missing: %s]\n' "${name}" "${substr}"
    printf -- '------ doctor output ------\n%s\n---------------------------\n' "${DOCTOR_OUT}"
  fi
}

FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="32607" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-16gb-hybrid"    "STT_ENGINE=hybrid"
assert_contains "engine-16gb-gpu-dev"   "STT_BUFFERED_DEVICE=gpu"

FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="12288" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-12gb-hybrid"    "STT_ENGINE=hybrid"
assert_contains "engine-12gb-cpu-dev"   "STT_BUFFERED_DEVICE=cpu"

FAKE_SMI_CUDA="12.8" FAKE_SMI_VRAM="8188" FAKE_DOCKER="ok" run_doctor ""
assert_contains "engine-8gb-buffered"   "STT_ENGINE=buffered"

run_doctor "no-nvidia-smi"
assert_contains "engine-nogpu-buffered" "STT_ENGINE=buffered"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
