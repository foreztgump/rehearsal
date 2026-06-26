---
phase: 11-consumer-gpu-deployment-part-e
verifier: goal-backward analysis
requirement_ids: [DEPLOY-04, DEPLOY-05]
verdict: CODE-COMPLETE — operator gate pending (analogous to Phases 8/9/10)
sandbox_constraint: NO GPU-START Docker daemon, CANNOT pull/build multi-GB GPU images, CANNOT exercise a genuinely broken/sub-spec host
date: 2026-06-26
---

# Phase 11 — Consumer-GPU Deployment (Part E): GOAL-BACKWARD VERIFICATION

## Phase goal (restated)

> Make `docker compose up` on the user's own machine the sole supported deployment —
> no VM/passthrough layer — with consumer-GPU detection via the NVIDIA Container
> Toolkit and a non-blocking preflight "doctor" that gives a clear, actionable message
> on driver/toolkit/CUDA/VRAM/non-NVIDIA failure, falling back to the VRAM-safe
> CPU-ONNX STT + Fast model where the GPU is absent or sub-spec.

**Verdict: CODE-COMPLETE with operator gate pending.** The shipped artifacts deliver
the whole mechanism the phase promised: the preflight doctor runs the ordered
driver→toolkit→CUDA→VRAM chain, is strictly advise-only (always exit 0, never mutates
`.env`, never switches runtime), and emits the exact GPU-ready vs degraded env snippet;
`./up.sh` wraps it then `docker compose up`. The default boot is the VRAM-safe CPU-ONNX
STT and GPU STT is correctly opt-in behind `--profile stt-gpu`. All Proxmox/VM/vfio/PCIe
content is deleted from docs. The only items deferred are those that genuinely require a
real consumer GPU host (live `--gpus all` proof, real `up` to healthy, GPU/CPU STT
routing, doctor behaviour on a truly broken/sub-spec host) — enumerated unsigned in
`11-DEPLOY-VERIFY.md`, exactly as Phases 8/9/10 shipped.

---

## Goal-backward decomposition

The phase is achieved iff ALL of these hold. Each is **CODE-MET** (delivered +
sandbox-verifiable) or **OPERATOR-GATED** (mechanism in code, real-host proof deferred
to 11-DEPLOY-VERIFY.md).

| # | Goal sub-claim | Status | Evidence |
|---|----------------|--------|----------|
| G1 | `docker compose up` on the user's machine is the sole deployment; no VM/passthrough layer anywhere | CODE-MET | README rewritten to a single "GPU setup (NVIDIA Container Toolkit)" section; `grep -iE 'proxmox\|vfio\|pcie\|layer 1\|layer 2\|two-layer\|inside the vm'` returns nothing repo-wide |
| G2 | Consumer-GPU detection via the NVIDIA Container Toolkit | CODE-MET | doctor probes `nvidia-smi` then a live `docker run --gpus all` toolkit check; README documents the one host step (`nvidia-ctk runtime configure`) + the `docker run --gpus all` proof |
| G3 | Preflight doctor: ordered, actionable failure messages on driver/toolkit/CUDA/VRAM/non-NVIDIA | CODE-MET | `scripts/gpu-doctor.sh` ordered chain; each failure prints a specific remedy; harness asserts the right remedy per scenario |
| G4 | Doctor is non-blocking / advise-only | CODE-MET | always `exit 0`; never writes `.env`; never switches runtime; `./up.sh` runs it then `exec docker compose up` (`SKIP_DOCTOR=1` bypass) |
| G5 | Degraded fallback to CPU-ONNX STT + Fast model where GPU absent/sub-spec | CODE-MET | doctor emits the `STT_FORCE_CPU=1` + Fast `OLLAMA_MODEL` snippet on the sub-spec/non-NVIDIA branches; default boot already CPU-ONNX |
| G6 | Default boot is VRAM-safe; GPU STT is opt-in | CODE-MET | `docker compose config` default has `nemo-stt-cpu` (no GPU reservation) and NO `nemo-stt`; `--profile stt-gpu` adds GPU-reserved `nemo-stt`; topology test 9/9 |
| G7 | ollama/kokoro GPU requirement honestly documented as a limitation | CODE-MET | README states a non-NVIDIA host runs STT on CPU but not LLM/TTS (v1.1 limitation); both stay GPU-reserved in both renders |
| G8 | Real-host proof (live toolkit, up→healthy, GPU/CPU routing, broken-host doctor) | CORRECTLY DEFERRED | `11-DEPLOY-VERIFY.md` 7 gates, status `pending-operator`, all unsigned |

---

## Per-requirement assessment

### DEPLOY-04 — `docker compose up` on the user's machine as the sole deployment

**Status: SATISFIED-IN-CODE.**

- README Quick start now leads with `./up.sh` (preflight → `docker compose up`), with
  plain `docker compose up` noted as equivalent.
- The Proxmox two-layer-passthrough section is fully replaced by a single
  Toolkit-only GPU section; no VM/vfio/PCIe language remains anywhere (verified by grep
  across README and the verify doc; only DEPLOY-05's own "detection/passthrough via the
  NVIDIA Container Toolkit" phrasing remains, which is the *supported* mechanism).
- `up.sh` is a thin, correct wrapper: `cd "$(dirname "$0")"`, run doctor unless
  `SKIP_DOCTOR=1`, then `exec docker compose up "$@"` (flags like `-d` pass through).

Operator-gated (11-DEPLOY-VERIFY G1/G2): the real `up` to a healthy stack and the live
`docker run --gpus all` toolkit proof on the consumer host.

### DEPLOY-05 — consumer-GPU detection/passthrough + preflight doctor

**Status: SATISFIED-IN-CODE for the mechanism; real-host behaviour operator-gated.**

What the code delivers (sandbox-verified):
- `scripts/gpu-doctor.sh` — ordered `nvidia-smi` (driver) → `docker run --gpus all`
  (toolkit) → CUDA-floor (`12.8`, kokoro `-cu128` Blackwell) → VRAM-floor (`16384 MB`)
  chain, single-sourced floors, `set -euo pipefail` with `|| true` on every nvidia-smi
  query pipeline (drivers that reject `--query-gpu=cuda_version` exit non-zero) and
  `case` sanitization before any numeric `[ -ge ]` test. Always exits 0. Prints
  `OK: GPU ready` + the `--profile stt-gpu` snippet, or a specific remedy + the
  degraded `STT_FORCE_CPU=1` + Fast-model snippet. Never touches `.env`.
- `scripts/test_gpu_doctor.sh` — PATH-shim harness, 5 scenarios (nvidia-smi-missing,
  toolkit-no-driver, cuda-too-old, vram-sub-spec, all-ok), each asserting the right
  remedy + GPU-vs-degraded snippet + exit 0. **5/5 PASS.** Isolated temp-shim PATH so
  the host's real `nvidia-smi`/`docker` never leak.
- `scripts/test_compose_topology.sh` — 9 assertions over `docker compose config`
  default vs `--profile stt-gpu` (CPU STT present + no GPU reservation, GPU STT
  profile-gated + GPU-reserved, ollama/kokoro GPU-reserved in both); Docker-optional
  skip guard. **9/9 PASS** on this host.
- Real-host smoke during development: the doctor exited 0 against this host's RTX 5090
  (CUDA 13.2 / 24463 MB) with the live `docker run --gpus all` probe succeeding.

Operator-gated (11-DEPLOY-VERIFY G4/G5/G6/G7): the doctor's output on a genuinely
toolkit-missing host and a sub-spec/non-NVIDIA host, the CPU-degraded `up`, and the
no-hung-up first-build health visibility — none provable without those real hosts.

---

## Invariants checked (all HOLD)

- **Doctor never mutates state:** no `.env` write, no runtime switch in `gpu-doctor.sh`;
  pure stdout advice + `exit 0`.
- **Single-sourced floors:** `VRAM_FLOOR_MB`/`CUDA_FLOOR`/`TOOLKIT_PROBE_IMAGE`/
  `FAST_LLM_TAG` declared `readonly` once; no hardcoded duplicates.
- **docker-compose.yml unchanged:** Phase 11 only *verifies* the P10 topology; the
  manifest was not edited (topology test reads the committed file).
- **No forbidden deployment language:** repo-wide grep for
  `proxmox|vfio|pcie|two-layer|inside the vm` is empty.
- **Default-safe:** shipped `.env.example` keeps `STT_FORCE_CPU=1` +
  `STT_HEADROOM_MEASURED=0`; GPU STT cannot engage without an explicit operator opt-in
  gated on 10-PLACEMENT-VERIFY.

---

## Deferred to operator (11-DEPLOY-VERIFY.md, 7 unsigned gates)

G1 toolkit `--gpus all` proof · G2 default CPU-STT boot to healthy · G3 `--profile
stt-gpu` GPU-STT boot + routing · G4 doctor on all-OK host · G5 doctor on
toolkit-missing host + CPU-degraded up · G6 doctor on sub-spec/non-NVIDIA host · G7
no-hung-`up` first-build health visibility. Status `pending-operator`; nothing falsely
passed.

**Bottom line:** Phase 11 is CODE-COMPLETE. The consumer-GPU `docker compose` mechanism
and the advise-only preflight doctor are fully delivered and sandbox-verified; the
remaining proofs legitimately require a real consumer GPU host and are correctly
deferred, consistent with Phases 8/9/10.
