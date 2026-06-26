---
plan: 11-01
title: Preflight GPU doctor (scripts/gpu-doctor.sh — ordered nvidia-smi → toolkit → CUDA-floor → VRAM-floor chain, non-blocking ADVISE, copyable env snippet) + thin ./up.sh wrapper that runs the doctor then docker compose up
phase: 11
wave: 1
depends_on: []
autonomous: false
requirements: [DEPLOY-05]
files_modified:
  - scripts/gpu-doctor.sh
  - up.sh
  - scripts/test_gpu_doctor.sh
---

# Plan 11-01: The preflight GPU doctor + `./up.sh` wrapper

## User Story

**As** a user dropping the stack onto my own machine and running it purely via `docker compose`,
**I want** one command that checks my GPU/driver/toolkit/VRAM before `docker compose up` and,
on any problem, prints the EXACT remedy plus a copy-paste degraded-mode command instead of
letting `up` hang or crash cryptically, **so that** I either boot the full GPU stack with
confidence or fall back cleanly to CPU-ONNX STT + the Fast model — without editing files or
guessing.

## Context

This is the **operator-facing mechanism half** of Phase 11. It adds `scripts/gpu-doctor.sh`
(pure host bash, modeled on the existing `scripts/vram-validate.sh`) that runs an **ordered**
preflight chain and a thin `./up.sh` wrapper that runs the doctor then hands off to
`docker compose up "$@"`. Plan 11-02 then rewrites the README around these and ships the
operator verify file. The doctor RECOMMENDS env (a copyable snippet) and NEVER mutates `.env`
or auto-switches anything at runtime — the actual CPU/GPU STT choice stays with P10's
`STT_FORCE_CPU` + the placement resolver. The doctor is **non-blocking ADVISE**: it always
exits 0 so `./up.sh` proceeds; its job is to make failures legible, not to gate the stack.

### Single-sourced floors (do NOT scatter literals)
- `VRAM_FLOOR_MB=16384` (matches `vram-validate.sh` `VRAM_LIMIT_MB` and the README "16GB-VRAM
  GPU"). Override via env `VRAM_FLOOR_MB`.
- `CUDA_FLOOR="12.8"` (kokoro `…-cu128` Blackwell image — `docker-compose.yml` L203-206).
  nvidia-smi's "CUDA Version:" header reports the **max** CUDA the installed driver supports.
- `TOOLKIT_PROBE_IMAGE="nvidia/cuda:12.4.0-base-ubuntu22.04"` (the image the README Layer-2
  step already uses for the `--gpus all` proof — keep it identical).

## The ordered chain (each step: detect → on fail, print remedy + continue)

`gpu-doctor.sh` runs these IN ORDER, accumulating a `DEGRADED` flag. It never `exit 1`s on a
failed check (ADVISE posture); it prints a per-check `OK:`/`ADVISE:` line and, at the end, the
single recommended env snippet.

1. **`nvidia-smi` present + driver responds.**
   - Detect: `command -v nvidia-smi` AND `nvidia-smi` exits 0.
   - Fail → non-NVIDIA / no driver. Remedy: "No NVIDIA GPU/driver detected. Install the
     NVIDIA driver (`nvidia-smi` must print a GPU table), or run CPU-degraded (below)."
     Set `DEGRADED=1`. **Short-circuit checks 3 & 4** (can't query a GPU that isn't there),
     but STILL run check 2 (toolkit) so the user sees the full picture.
2. **NVIDIA Container Toolkit wired.**
   - Detect: `command -v docker` AND
     `docker run --rm --gpus all "$TOOLKIT_PROBE_IMAGE" nvidia-smi` exits 0.
   - Distinguish the two known failure strings (mirror README's current table):
     `could not select device driver "nvidia"` → toolkit missing/Docker runtime not
     configured. Remedy: the three `apt-get install … nvidia-container-toolkit` /
     `nvidia-ctk runtime configure --runtime=docker` / `systemctl restart docker` lines.
   - Any other non-zero → generic "GPU not reachable from a container" remedy pointing at the
     same toolkit step. Set `DEGRADED=1`.
   - If `nvidia-smi` already failed in step 1, note the probe is expected to fail and skip the
     docker pull (don't make a non-NVIDIA user download a CUDA image).
3. **CUDA/driver floor.** (only if step 1 OK)
   - Detect: parse `nvidia-smi`'s `CUDA Version: X.Y` header; compare ≥ `CUDA_FLOOR` with a
     numeric major.minor compare (NOT lexical). Remedy on fail: "Driver supports CUDA <found>
     but kokoro needs CUDA ≥ 12.8 (Blackwell). Update your NVIDIA driver." Set `DEGRADED=1`.
4. **VRAM floor.** (only if step 1 OK)
   - Detect: `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` (max across
     GPUs); compare ≥ `VRAM_FLOOR_MB`. Remedy on fail: "GPU has <found> MB VRAM; the full
     16 GB stack won't co-reside. Run CPU-degraded STT + the Fast model (below)." Set
     `DEGRADED=1`.

### Final advice block (always printed)
- If `DEGRADED=0`: print `OK: GPU ready.` and the **GPU env snippet**:
  ```
  # GPU ready — opt into GPU STT:
  #   STT_FORCE_CPU=0  STT_HEADROOM_MEASURED=1   (only after 10-PLACEMENT-VERIFY passes)
  #   docker compose --profile stt-gpu up
  ```
  NOTE the honesty: the doctor recommends the GPU profile is AVAILABLE, but reminds the
  operator the GPU-STT flip is still gated on `STT_HEADROOM_MEASURED` (P10). Default `up`
  remains CPU-ONNX-safe.
- If `DEGRADED=1`: print the **degraded snippet** the user copies into `.env` (doctor does NOT
  write it):
  ```
  # Sub-spec / non-NVIDIA host — CPU-ONNX STT + Fast model (already the safe defaults):
  STT_FORCE_CPU=1
  OLLAMA_MODEL=evalengine/unbound-e2b:latest   # the Fast tag
  # then: docker compose up   (do NOT add --profile stt-gpu)
  ```
  Plus the one-line limitation note: "ollama + kokoro still require a working NVIDIA GPU; a
  fully non-NVIDIA host can run STT on CPU but not the LLM/TTS (v1.1 limitation)."
- Multi-GB build note (no-hung-`up`): "First `up` builds/pulls multi-GB GPU images and the STT
  model bakes in — watch `docker compose ps` for `health: starting`→`healthy`; it is not hung."

### Source-of-truth for the degraded env values
- `OLLAMA_MODEL` Fast tag and `STT_FORCE_CPU` MUST be read from / consistent with
  `.env.example` (`evalengine/unbound-e2b:latest`, `STT_FORCE_CPU=1`). Reference them as the
  documented defaults; do not invent new literals.

## `./up.sh` wrapper
- `#!/usr/bin/env bash`, `set -euo pipefail`, `cd` to repo root (`$(dirname "$0")`).
- Run `scripts/gpu-doctor.sh` (inherits stdout). Because the doctor always exits 0, the
  wrapper proceeds unconditionally — but the user has SEEN the advice.
- `exec docker compose up "$@"` (pass through `-d`, `--profile stt-gpu`, etc.).
- Honor a `SKIP_DOCTOR=1` escape hatch (CI / repeat boots): skip the doctor, go straight to
  compose.

## Tasks

1. **`scripts/gpu-doctor.sh`** — header comment (mirror `vram-validate.sh` style: purpose,
   ADVISE posture, the floors, "does NOT mutate .env / does NOT auto-switch"); `set -euo
   pipefail`; `readonly` floors with env overrides; `advise()`/`ok()` helpers; the 4 ordered
   checks with short-circuit logic; the final GPU-vs-degraded snippet block; the multi-GB
   build note; `main "$@"`; **always `exit 0`**.
2. **`up.sh`** — the thin wrapper (doctor → `exec docker compose up "$@"`, `SKIP_DOCTOR=1`
   bypass). `chmod +x` both (note in plan: executor sets the mode bit).
3. **`scripts/test_gpu_doctor.sh`** — the sandbox harness: builds a temp `PATH` shim dir with
   fake `nvidia-smi` + `docker` whose behavior is driven by env (`FAKE_SMI=missing|ok`,
   `FAKE_SMI_CUDA`, `FAKE_SMI_VRAM`, `FAKE_DOCKER=ok|no-driver|missing`), then runs the doctor
   across 5 scenarios — {nvidia-smi-missing, toolkit-no-driver, CUDA-too-old, VRAM-sub-spec,
   all-OK} — asserting (a) the right remedy substring appears, (b) the right env snippet
   (GPU vs degraded) appears, (c) the doctor exits 0 every time. This is the executor's green
   proof; it imports NO GPU and NO real Docker.

## Acceptance (sandbox)
- `bash -n scripts/gpu-doctor.sh up.sh scripts/test_gpu_doctor.sh` clean.
- `scripts/test_gpu_doctor.sh` passes all 5 scenarios.
- `shellcheck` (if available) has no errors (warnings OK).

## Deferred to operator (11-DEPLOY-VERIFY.md)
- Real `nvidia-smi` / `--gpus all` toolkit probe on the RTX 5090.
- The doctor's messages on a REAL toolkit-missing / sub-spec host.
- `./up.sh` end-to-end bringing the full stack healthy.

## Frozen / do-not-touch
- `docker-compose.yml` (11-02 only touches docs/verification; the GPU exposure mechanism is
  unchanged from P10).
- `agent/*`, `stt/*`, `.env*` — the doctor only READS `.env.example` defaults conceptually;
  it does not modify env files or runtime code.
- No networking/TLS/`node_ip` changes.
