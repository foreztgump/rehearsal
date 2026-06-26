---
phase: 11
phase_name: consumer-gpu-deployment-part-e
mode: mvp
depends_on: [10]
requirements: [DEPLOY-04, DEPLOY-05]
plans:
  - 11-01-gpu-doctor-up-wrapper
  - 11-02-readme-consumer-gpu-compose-verify
---

# Phase 11 — Consumer-GPU Deployment (Part E): CONTEXT

## Goal (verbatim)

Drop the Proxmox-VM assumption so `docker compose up` brings the full stack up directly on
the user's consumer machine, with consumer-GPU detection/passthrough via the NVIDIA Container
Toolkit and a preflight GPU "doctor" that gives a clear, actionable message on
driver/CUDA/VRAM/non-NVIDIA failure (falling back to CPU-ONNX STT + Fast model where the GPU
is sub-spec).

## Requirements owned

- **DEPLOY-04** — `docker compose up` runs the full stack directly on the user's consumer
  machine; the Proxmox-VM assumption is dropped.
- **DEPLOY-05** — Consumer-GPU detection/passthrough via the NVIDIA Container Toolkit
  (`--gpus` / `deploy.resources.reservations.devices`), with a preflight GPU "doctor" giving a
  clear, actionable message on driver/CUDA/VRAM/non-NVIDIA failure (falling back to CPU-ONNX
  STT + Fast model where the GPU is sub-spec).

## Discuss decisions (all 4 grey areas — "Accept all (Recommended)")

### Area 1 — Preflight GPU doctor
- **Form:** standalone `scripts/gpu-doctor.sh` (pure host bash, no container) + a thin
  `./up.sh` wrapper that runs the doctor then `docker compose up`.
- **Checks (ordered chain, each failure prints the exact remedy):**
  1. `nvidia-smi` present + driver responds
  2. NVIDIA Container Toolkit wired (`docker run --gpus all … nvidia-smi`)
  3. CUDA/driver version floor
  4. VRAM ≥ spec floor (16 GB)
- **Posture:** non-blocking ADVISE — on any failure print the actionable fix AND the
  `STT_FORCE_CPU=1` + Fast-model degraded command; never silently hang or hard-block.
- **Env handling:** doctor EMITS a copyable env snippet (GPU-ok → `--profile stt-gpu`;
  sub-spec/non-NVIDIA → CPU-ONNX default); it NEVER mutates `.env`.

### Area 2 — Compose topology & GPU passthrough
- ollama/kokoro keep GPU as the spec baseline (CPU-only for them is **out of scope**).
- Consumer GPU is exposed via the existing `deploy.resources.reservations.devices` blocks +
  NVIDIA Container Toolkit; drop all Proxmox/vfio layers. NO switch to `runtime: nvidia` /
  top-level `gpus:`.
- Default `docker compose up` = CPU-ONNX STT (no profile, matches P10 `STT_FORCE_CPU=1`);
  GPU STT is opt-in via `--profile stt-gpu` + the doctor's blessing.
- No `node_ip`/networking change (keep the P8 `127.0.0.1` localhost default).

### Area 3 — Degraded/sub-spec fallback
- Degraded = CPU-ONNX STT (`STT_FORCE_CPU=1`) + Fast model default + GPU STT not started —
  the stack still comes up usable.
- Triggered operator-driven via the doctor's recommended env snippet — NO silent runtime
  auto-switch (honors P10 resolve-once/no-magic).
- ollama/kokoro needing a GPU is a documented limitation (no CPU LLM/TTS in v1.1); the doctor
  flags it.
- No-hung-`up` surfaced via the existing `start_period` + `docker compose ps` health (the
  doctor warns the GPU image build is multi-GB).

### Area 4 — Docs & verification
- README: replace the entire Proxmox two-layer section with one "Consumer GPU setup"
  (nvidia-ctk install + `docker run --gpus all` verify + `gpu-doctor.sh`); keep LiveKit/TLS
  sections. Keep a one-line "Running under a VM/Proxmox? the same toolkit step applies" note
  (no vfio walkthrough).
- Sandbox-verifiable: `bash -n` the doctor + `up.sh`; `docker compose config` (default +
  `--profile stt-gpu`); a stubbed-PATH doctor dry-run (PATH shim for `nvidia-smi`/`docker`)
  asserting each remedy message fires.
- Operator gate `11-DEPLOY-VERIFY.md` (unsigned): real `docker compose up` on the consumer
  RTX 5090 (full stack healthy), the `--gpus all` toolkit proof, the degraded
  non-NVIDIA/sub-spec boot, and the doctor messages on real failures.

## Existing surfaces (grounding)

- `docker-compose.yml` — GPU reservations on `ollama` (L101-107), `nemo-stt` (L142-148,
  behind `profiles: ["stt-gpu"]` L128), `kokoro` (L213-219). `nemo-stt-cpu` (L161-200) is the
  always-on no-GPU default. `web`/`agent`/`livekit-server` no GPU. All ports bind
  `${LAN_BIND_IP:-127.0.0.1}`.
- `scripts/vram-validate.sh` — the existing host-bash script; the STYLE MODEL for
  `gpu-doctor.sh` (`set -euo pipefail`, `readonly` config, `fail()` helper, `nvidia-smi
  --query-gpu`, `command -v` guards).
- `.env.example` — `STT_FORCE_CPU=1` (L98, safe default), `STT_HEADROOM_MEASURED=0` (L103),
  `OLLAMA_MODEL=…unbound-e2b` (L51, the Fast default), `LAN_BIND_IP=127.0.0.1` (L8).
- `README.md` (126 lines) — `## GPU passthrough` (L33) → `### Layer 1 — Proxmox` (L46) →
  `### Layer 2 — NVIDIA Container Toolkit` (L60) → `### Diagnosing…` (L82). Replace L33-91.
  Keep `## Quick start` (L7), `## LiveKit self-host networking` (L93), `## Serving other LAN
  devices` (L110).
- `agent/main.py:211` — `stt_url = NEMO_STT_URL if placement == "gpu" else NEMO_STT_CPU_URL`
  (placement already resolves CPU under the safe default; the doctor only RECOMMENDS env, it
  does not touch this path).

## VRAM/version floors (single-source these in the doctor)
- VRAM floor: **16384 MB** (= `VRAM_LIMIT_MB` in `vram-validate.sh`; the "16GB-VRAM GPU"
  in README L4). Sub-spec ⇒ recommend degraded.
- CUDA floor: kokoro image is `…-cu128` (CUDA 12.8, Blackwell/sm_120, docker-compose L203-206)
  → driver must support CUDA **12.8**. nvidia-smi reports the max CUDA the driver supports.

## Out of scope (do NOT do)
- No CPU fallback for ollama/kokoro.
- No silent/auto runtime switching; no `.env` mutation by the doctor.
- No networking/`node_ip`/TLS changes.
- No new compose GPU-exposure mechanism (keep `reservations.devices`).
- No re-proving the P10 STT placement logic here.

## Verification split
- **Sandbox (executor proves):** `bash -n` both scripts; stubbed-PATH dry-run of the doctor
  across {nvidia-smi-missing, toolkit-missing, CUDA-too-old, VRAM-sub-spec, all-OK} asserting
  the correct remedy + env snippet each time; `docker compose config` default + `--profile
  stt-gpu`.
- **Operator (`11-DEPLOY-VERIFY.md`, unsigned):** real `up` on RTX 5090, `--gpus all` proof,
  degraded boot, real-failure doctor messages.
