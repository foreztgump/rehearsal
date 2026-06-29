# R6 AMD ROCm Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a best-effort AMD ROCm profile that runs Ollama and Kokoro on AMD GPU, keeps STT on CPU, and documents the Kokoro CPU fallback.

**Architecture:** Add one Compose override for AMD hardware and keep the default NVIDIA stack untouched. Extend the existing advise-only GPU doctor to recognize AMD and print the exact profile command. Keep the agent unchanged because `KOKORO_BASE_URL` and `/dev/captioned_speech` already isolate the TTS service behind a URL.

**Tech Stack:** Docker Compose, Bash, Ollama ROCm, Kokoro-FastAPI ROCm, existing CPU STT service, Markdown docs.

---

## File Structure

- Create `docker-compose.amd.yml`
  - Owns AMD-only service overrides for `ollama` and `kokoro`.
  - Removes inherited NVIDIA reservations with Compose `!reset`.
  - Adds `/dev/kfd`, `/dev/dri`, Kokoro ROCm env, and MIOpen cache volumes.

- Modify `scripts/gpu-doctor.sh`
  - Detects `nvidia`, `amd`, or `none`.
  - Keeps NVIDIA checks unchanged when NVIDIA is present.
  - Prints AMD-specific advice when ROCm device nodes exist.
  - Never writes `.env` and always exits 0.

- Modify `scripts/test_gpu_doctor.sh`
  - Adds fake AMD device roots.
  - Verifies AMD advice does not emit degraded NVIDIA messaging.
  - Keeps existing NVIDIA scenarios passing.

- Modify `.env.example`
  - Adds commented AMD ROCm profile settings and group-id guidance.

- Modify `README.md`
  - Adds the AMD ROCm support section, commands, warmup warning, and fallback.

- Create `docs/r6-amd-rocm-verify.md`
  - AMD hardware gate runbook.
  - Records Kokoro cold/warmed latency and fallback outcome.

No agent code changes are planned.

## Task 1: Add AMD Compose Override

**Files:**
- Create: `docker-compose.amd.yml`
- Verify: Docker Compose merged config

- [ ] **Step 1: Write the AMD Compose override**

Create `docker-compose.amd.yml`:

```yaml
# Adept AMD ROCm override.
# Use with:
#   COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d
#
# Keeps the default docker-compose.yml NVIDIA-first and opt-in only.

services:
  ollama:
    image: ollama/ollama:0.30.10-rocm
    devices:
      - /dev/kfd
      - /dev/dri
    deploy:
      resources:
        reservations:
          devices: !reset []

  kokoro:
    image: ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0
    devices:
      - /dev/kfd
      - /dev/dri
    group_add:
      - "${AMD_VIDEO_GID:-44}"
      - "${AMD_RENDER_GID:-109}"
      - "${AMD_INPUT_GID:-110}"
    environment:
      - USE_GPU=true
      - TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
      - MIOPEN_FIND_MODE=2
    volumes:
      - kokoro-miopen-config:/home/appuser/.config/miopen
      - kokoro-miopen-cache:/home/appuser/.cache/miopen
    deploy:
      resources:
        reservations:
          devices: !reset []

volumes:
  kokoro-miopen-config:
  kokoro-miopen-cache:
```

- [ ] **Step 2: Verify the merged Compose model renders**

Run:

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml config >/tmp/adept-amd-compose.yml
```

Expected: exit 0.

Then run:

```bash
rg -n "driver: nvidia|0.30.10-rocm|kokoro-fastapi-rocm|/dev/kfd|kokoro-miopen" /tmp/adept-amd-compose.yml
```

Expected:

- `0.30.10-rocm` appears.
- `kokoro-fastapi-rocm:v0.5.0` appears.
- `/dev/kfd` appears for both `ollama` and `kokoro`.
- `kokoro-miopen-config` and `kokoro-miopen-cache` appear.
- `driver: nvidia` does not appear under `ollama` or `kokoro`.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.amd.yml
git commit -m "feat(r6): add AMD ROCm compose override"
```

## Task 2: Refactor GPU Doctor for Vendor Profiles

**Files:**
- Modify: `scripts/gpu-doctor.sh`
- Test: `scripts/test_gpu_doctor.sh`

- [ ] **Step 1: Add failing AMD doctor tests**

In `scripts/test_gpu_doctor.sh`, after `readonly SHIM_DIR="$(mktemp -d)"`, add:

```bash
readonly FAKE_DEV_ROOT="$(mktemp -d)"
trap 'rm -rf "${SHIM_DIR}" "${FAKE_DEV_ROOT}"' EXIT
```

Remove the existing `trap 'rm -rf "${SHIM_DIR}"' EXIT` line.

After the fake `docker` shim, add:

```bash
# --- fake ROCm device root -------------------------------------------------------
reset_fake_amd_devices() {
  rm -rf "${FAKE_DEV_ROOT:?}/"*
}

enable_fake_amd_devices() {
  mkdir -p "${FAKE_DEV_ROOT}/dri"
  : > "${FAKE_DEV_ROOT}/kfd"
}
```

In `run_doctor()`, add `AMD_DEVICE_ROOT="${FAKE_DEV_ROOT}"` to the `env -i` invocation:

```bash
  DOCTOR_OUT="$(env -i PATH="${tmpdir}" \
    AMD_DEVICE_ROOT="${FAKE_DEV_ROOT}" \
    FAKE_SMI_CUDA="${FAKE_SMI_CUDA:-}" FAKE_SMI_VRAM="${FAKE_SMI_VRAM:-}" \
    FAKE_DOCKER="${FAKE_DOCKER:-}" \
    "${BASH}" "${DOCTOR}" 2>&1)"
```

Before each existing scenario, call `reset_fake_amd_devices`.

Add this scenario after the existing `nvidia-smi-missing` scenario:

```bash
# 1b. AMD device nodes present -> AMD ROCm snippet, no degraded NVIDIA warning.
reset_fake_amd_devices
enable_fake_amd_devices
FAKE_SMI_CUDA="" FAKE_SMI_VRAM="" FAKE_DOCKER="" run_doctor "no-nvidia-smi"
assert_contains "amd-devices-compose-file" "COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml"
assert_contains "amd-devices-ollama-rocm" "ollama/ollama:0.30.10-rocm"
assert_contains "amd-devices-kokoro-rocm" "kokoro-fastapi-rocm:v0.5.0"
if printf '%s' "${DOCTOR_OUT}" | grep -qF -- "Sub-spec / non-NVIDIA host"; then
  FAIL=$((FAIL+1)); printf 'FAIL  amd-devices-not-degraded [unexpected degraded NVIDIA advice]\n'
else
  PASS=$((PASS+1)); printf 'PASS  amd-devices-not-degraded\n'
fi
reset_fake_amd_devices
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test_gpu_doctor.sh
```

Expected: FAIL on the AMD checks because `gpu-doctor.sh` does not print AMD advice yet.

- [ ] **Step 3: Add AMD vendor detection to `gpu-doctor.sh`**

In `scripts/gpu-doctor.sh`, add constants after `TOOLKIT_PROBE_IMAGE`:

```bash
readonly AMD_DEVICE_ROOT="${AMD_DEVICE_ROOT:-/dev}"
readonly AMD_COMPOSE_FILE="docker-compose.yml:docker-compose.amd.yml"
readonly OLLAMA_ROCM_IMAGE="ollama/ollama:0.30.10-rocm"
readonly KOKORO_ROCM_IMAGE="ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0"
```

Add globals after `DETECTED_VRAM_MB=""`:

```bash
GPU_VENDOR="none"
```

Add this function before `check_nvidia_smi()`:

```bash
detect_gpu_vendor() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    GPU_VENDOR="nvidia"
    return
  fi
  if [ -e "${AMD_DEVICE_ROOT}/kfd" ] && [ -d "${AMD_DEVICE_ROOT}/dri" ]; then
    GPU_VENDOR="amd"
    return
  fi
  GPU_VENDOR="none"
}
```

Add this function before `print_advice()`:

```bash
print_amd_advice() {
  hr
  ok "AMD ROCm device nodes present."
  printf 'AMD ROCm profile (best-effort latency, CPU STT):\n\n'
  printf '  COMPOSE_FILE=%s docker compose up -d\n\n' "${AMD_COMPOSE_FILE}"
  printf 'Images:\n'
  printf '  %s\n' "${OLLAMA_ROCM_IMAGE}"
  printf '  %s\n\n' "${KOKORO_ROCM_IMAGE}"
  printf 'Recommended .env settings:\n'
  printf '  STT_ENGINE=buffered\n'
  printf '  STT_BUFFERED_DEVICE=cpu\n'
  printf '  STT_FORCE_CPU=1\n\n'
  printf 'Kokoro ROCm uses MIOpen kernel caches. First requests can be slow until warmed;\n'
  printf 'record cold and warmed latency with docs/r6-amd-rocm-verify.md before claiming speed.\n'
  hr
}
```

Replace `main()` with:

```bash
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
      print_advice
      ;;
    amd)
      print_amd_advice
      ;;
    *)
      advise "No supported GPU detected (no NVIDIA driver and no AMD ROCm device nodes)."
      advise_summary
      printf '\nRecommended STT engine for this host (advise-only — copy into .env if you want):\n'
      recommend_stt_profile ""
      hr
      ;;
  esac
  exit 0
}
```

- [ ] **Step 4: Run doctor tests**

Run:

```bash
./scripts/test_gpu_doctor.sh
```

Expected: all scenarios PASS, including the new AMD checks.

- [ ] **Step 5: Shell syntax check**

Run:

```bash
bash -n scripts/gpu-doctor.sh scripts/test_gpu_doctor.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/gpu-doctor.sh scripts/test_gpu_doctor.sh
git commit -m "feat(r6): teach gpu doctor AMD ROCm advice"
```

## Task 3: Document AMD Environment and User Commands

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add AMD settings to `.env.example`**

Append this block after the `STT_HEADROOM_MEASURED=0` section:

```dotenv
# AMD ROCm profile (R6, opt-in). Leave these unset for the default NVIDIA stack.
# Run AMD with:
#   COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d
#
# R6 AMD profile:
#   - Ollama runs on AMD ROCm GPU.
#   - Kokoro runs on AMD ROCm GPU when its hardware gate passes.
#   - STT stays CPU-backed by design.
#   - If Kokoro ROCm is too slow or unstable, keep Ollama ROCm and switch Kokoro
#     to the CPU image in docker-compose.amd.yml.
#
# Kokoro ROCm runs as a non-root appuser. If it cannot access /dev/kfd or /dev/dri,
# set these to the numeric host group ids:
#   getent group video render input
# AMD_VIDEO_GID=44
# AMD_RENDER_GID=109
# AMD_INPUT_GID=110
```

- [ ] **Step 2: Add README AMD section**

In `README.md`, after the “Pick your STT by hardware” section, add:

```markdown
### AMD ROCm profile (R6)

AMD support is opt-in and Linux-only in v1.2. It is functional/best-effort, not
P50-guaranteed until measured on the target AMD host.

The AMD profile keeps STT on CPU and runs the voice models on ROCm:

| Stage | AMD profile |
|---|---|
| LLM | `ollama/ollama:0.30.10-rocm` |
| TTS | `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0` |
| STT | CPU `buffered` / Parakeet |

Start it with:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d
```

Recommended `.env` settings:

```dotenv
STT_ENGINE=buffered
STT_BUFFERED_DEVICE=cpu
STT_FORCE_CPU=1
```

ROCm containers need `/dev/kfd` and `/dev/dri`. If Kokoro cannot access those devices,
set `AMD_VIDEO_GID`, `AMD_RENDER_GID`, and `AMD_INPUT_GID` from:

```bash
getent group video render input
```

Kokoro ROCm uses MIOpen kernel caches. First requests can be slow until warmed. Use
[`docs/r6-amd-rocm-verify.md`](docs/r6-amd-rocm-verify.md) to record cold and warmed
latency. If Kokoro ROCm fails or remains too slow, keep Ollama ROCm and fall back to
Kokoro CPU. AMD GPU STT is not part of R6.
```

- [ ] **Step 3: Verify docs mention the required contract**

Run:

```bash
rg -n "AMD ROCm profile|best-effort|0.30.10-rocm|kokoro-fastapi-rocm|AMD GPU STT is not part of R6|AMD_VIDEO_GID" README.md .env.example
```

Expected: all phrases are found.

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example
git commit -m "docs(r6): document AMD ROCm profile"
```

## Task 4: Add AMD Hardware Verification Runbook

**Files:**
- Create: `docs/r6-amd-rocm-verify.md`

- [ ] **Step 1: Write the runbook**

Create `docs/r6-amd-rocm-verify.md`:

```markdown
# R6 AMD ROCm Verification

Status: pending AMD hardware

R6 AMD contract: Ollama and Kokoro run on AMD ROCm GPU; STT remains CPU-backed.
Latency is best-effort until this runbook records real numbers.

## Host

| Field | Value |
|---|---|
| GPU model |  |
| VRAM |  |
| OS |  |
| ROCm version |  |
| Docker version |  |

## Gate A - Compose Model

Run:

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml config >/tmp/adept-amd-compose.yml
rg -n "0.30.10-rocm|kokoro-fastapi-rocm|/dev/kfd|kokoro-miopen" /tmp/adept-amd-compose.yml
```

Result: pending

## Gate B - Ollama ROCm

Run:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d ollama
docker compose exec ollama ollama ps
```

Then serve the selected model through the existing app path.

Result: pending

## Gate C - Kokoro ROCm Speech

Run:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d kokoro
curl -fsS http://localhost:8880/v1/audio/voices >/tmp/kokoro-voices.json
curl -fsS http://localhost:8880/dev/captioned_speech \
  -H 'content-type: application/json' \
  -d '{"model":"kokoro","input":"AMD ROCm smoke test.","voice":"af_heart","response_format":"wav","speed":1.0,"stream":false,"return_timestamps":true}' \
  >/tmp/kokoro-captioned.json
```

Result: pending

## Gate D - Kokoro Cold and Warmed Latency

Record one cold `/dev/captioned_speech` call and one warmed call after MIOpen cache is populated.

| Condition | TTFB or total time | Notes |
|---|---:|---|
| Cold |  |  |
| Warmed |  |  |

Result: pending

## Gate E - Full Voice Smoke

Run:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d
```

Use the browser voice loop with:

```dotenv
STT_ENGINE=buffered
STT_BUFFERED_DEVICE=cpu
STT_FORCE_CPU=1
```

Result: pending

## Fallback Gate - Kokoro CPU

Run only if Kokoro ROCm fails or warmed latency is unacceptable.

Record the change made to `docker-compose.amd.yml` or the local override used to switch Kokoro to CPU.

Result: pending

## Sign-off

| Gate | Status |
|---|---|
| A Compose model | pending |
| B Ollama ROCm | pending |
| C Kokoro ROCm speech | pending |
| D Kokoro latency | pending |
| E Full voice smoke | pending |
| Fallback Kokoro CPU | pending |

Final verdict: pending
```

- [ ] **Step 2: Verify runbook has no vague placeholders**

Run:

```bash
rg -n "[T]BD|[T]ODO|[F]IXME|add [l]ater|implement [l]ater" docs/r6-amd-rocm-verify.md
```

Expected: no matches, exit 1.

- [ ] **Step 3: Commit**

```bash
git add docs/r6-amd-rocm-verify.md
git commit -m "docs(r6): add AMD ROCm verification runbook"
```

## Task 5: Final Verification

**Files:**
- Verify all touched files

- [ ] **Step 1: Run shell checks**

Run:

```bash
bash -n scripts/gpu-doctor.sh scripts/test_gpu_doctor.sh
./scripts/test_gpu_doctor.sh
```

Expected: syntax checks exit 0, doctor test prints all PASS and `0 failed`.

- [ ] **Step 2: Run Compose config checks**

Run:

```bash
docker compose config >/tmp/adept-default-compose.yml
docker compose -f docker-compose.yml -f docker-compose.amd.yml config >/tmp/adept-amd-compose.yml
```

Expected: both commands exit 0.

- [ ] **Step 3: Confirm default NVIDIA Compose still has NVIDIA reservations**

Run:

```bash
rg -n "driver: nvidia" /tmp/adept-default-compose.yml
```

Expected: matches under default GPU services.

- [ ] **Step 4: Confirm AMD Compose removes NVIDIA reservations from Ollama and Kokoro**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

text = Path("/tmp/adept-amd-compose.yml").read_text()
for service in ("ollama:", "kokoro:"):
    start = text.index(f"  {service}")
    rest = text[start + 2:]
    candidates = [i for i in (rest.find("\n  agent:"), rest.find("\n  livekit-server:"), rest.find("\n  nemo-stt:"), rest.find("\n  nemo-stt-cpu:"), rest.find("\n  web:")) if i != -1]
    end = start + 2 + min(candidates) if candidates else len(text)
    block = text[start:end]
    assert "/dev/kfd" in block, f"{service} missing /dev/kfd"
    assert "driver: nvidia" not in block, f"{service} still has NVIDIA reservation"
print("amd compose GPU service blocks OK")
PY
```

Expected: prints `amd compose GPU service blocks OK`.

- [ ] **Step 5: Verify docs and runbook references**

Run:

```bash
rg -n "AMD ROCm|best-effort|Kokoro CPU|AMD GPU STT" README.md docs/r6-amd-rocm-verify.md docs/superpowers/specs/2026-06-29-r6-amd-rocm-design.md
```

Expected: matches in all three files.

- [ ] **Step 6: Commit final verification note if docs changed during fixes**

If Task 5 required edits, commit them:

```bash
git add docker-compose.amd.yml scripts/gpu-doctor.sh scripts/test_gpu_doctor.sh .env.example README.md docs/r6-amd-rocm-verify.md
git commit -m "chore(r6): verify AMD ROCm profile"
```

If Task 5 required no edits, do not create an empty commit.

## Out of Scope During Execution

- Do not edit `agent/main.py`, `agent/captioned_tts.py`, or `agent/captioned_gate.py`.
- Do not add `TTS_ENGINE`.
- Do not change the default `docker compose up` behavior.
- Do not make AMD a P50-guaranteed profile.
- Do not add AMD GPU STT.
