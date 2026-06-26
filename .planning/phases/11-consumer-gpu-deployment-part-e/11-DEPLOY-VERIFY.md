---
status: pending-operator
phase: 11-consumer-gpu-deployment-part-e
plan: 11-02
requirement_ids: [DEPLOY-04, DEPLOY-05]
verifies:
  - DEPLOY-04
  - DEPLOY-05
  - "docker run --gpus all toolkit proof on the consumer host"
  - "default docker compose up brings the full stack healthy (CPU-ONNX STT, no nemo-stt)"
  - "--profile stt-gpu opt-in brings nemo-stt healthy on the GPU and the agent routes to it"
  - "gpu-doctor on a real GPU host: OK: GPU ready + GPU snippet, exit 0"
  - "gpu-doctor on a toolkit-missing host: real remedy + degraded snippet, stack still comes up CPU-degraded"
  - "gpu-doctor on a sub-spec/non-NVIDIA host: STT_FORCE_CPU=1 + Fast model, usable boot"
  - "no-hung-up: multi-GB build/pull + STT bake surfaces via docker compose ps health, not a silent hang"
harness_note: >
  Every gate below needs a real consumer host running `docker compose` against an
  NVIDIA GPU (Docker daemon + driver + NVIDIA Container Toolkit + the RTX 5090 + a
  browser + LAN mic). `docker compose` on the user's own machine is the SOLE supported
  deployment — it runs directly on the GPU host with no separate VM layer. The execution sandbox has no
  Docker daemon able to START containers and cannot pull/build the multi-GB GPU images,
  so the real `up`, the live `--gpus all` toolkit proof, the GPU/CPU STT routing, and
  the doctor's behaviour on a genuinely broken/sub-spec host are ALL deferred operator
  gates. NONE are marked passed by the executor — the operator fills each result table
  with observations on the real host.

  What ships sandbox-verified (already green, not re-proven here): `bash -n` of
  scripts/gpu-doctor.sh + up.sh + scripts/test_gpu_doctor.sh + scripts/test_compose_topology.sh;
  scripts/test_gpu_doctor.sh (5 PATH-shim scenarios — nvidia-smi-missing, toolkit-no-driver,
  cuda-too-old, vram-sub-spec, all-ok — each asserting the right remedy + GPU-vs-degraded
  snippet + exit 0); scripts/test_compose_topology.sh (9 assertions over `docker compose
  config` default vs --profile stt-gpu — CPU STT present/no-GPU-reservation, GPU STT
  profile-gated + GPU-reserved, ollama/kokoro GPU-reserved in both); and the doctor's
  clean exit-0 run against this host's real RTX 5090 (CUDA 13.2 / 24463 MB, live
  `docker run --gpus all` probe succeeded during development).
---

# Phase 11 — Consumer-GPU Deployment (Part E): OPERATOR VERIFICATION

**Status:** PENDING OPERATOR — run on the consumer host that will run `docker compose`
(Docker daemon + NVIDIA driver + NVIDIA Container Toolkit + RTX 5090 + browser + LAN
mic). The sandbox cannot start containers or pull/build the multi-GB GPU images, so
every gate below is a deferred operator gate. **None are marked passed by the executor.**

**Owns:**
- **DEPLOY-04** — `docker compose up` runs the full stack directly on the user's own
  machine as the sole supported deployment (runs directly on the GPU host, no VM layer).
- **DEPLOY-05** — consumer-GPU detection/passthrough via the NVIDIA Container Toolkit,
  with a preflight GPU "doctor" that gives a clear, actionable message on
  driver/CUDA/VRAM/non-NVIDIA failure (falling back to CPU-ONNX STT + Fast model where
  the GPU is sub-spec).

---

## Frozen-contract notes (read before running any gate)

- **`docker compose` on the user's machine is the only deployment.** It runs directly
  on the host that has the GPU — there is no separate VM layer.
- **The default boot is CPU-ONNX STT.** `docker compose up` (no profile) starts
  `nemo-stt-cpu` (off-GPU) and NOT `nemo-stt`; `STT_FORCE_CPU=1` is the shipped safe
  default. GPU STT is opt-in (`--profile stt-gpu` + `STT_FORCE_CPU=0` +
  `STT_HEADROOM_MEASURED=1`), gated on `10-PLACEMENT-VERIFY.md`.
- **The doctor is advise-only.** `scripts/gpu-doctor.sh` always exits 0; it never edits
  `.env` and never switches anything at runtime. `./up.sh` runs it then `docker compose
  up "$@"` (`SKIP_DOCTOR=1` bypasses).
- **ollama + kokoro always need the GPU** (no CPU fallback — documented v1.1 limitation).

---

## Gate 1 — Toolkit proof (`docker run --gpus all`)

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

| Check | Expected | Observed |
|-------|----------|----------|
| Command prints the GPU table from inside a container | RTX 5090 row visible, exit 0 | |
| `nvidia-ctk runtime configure` already applied | toolkit wired | |

---

## Gate 2 — Default boot (CPU-ONNX STT, full stack healthy)

```bash
./up.sh -d            # or: docker compose up -d
docker compose ps
```

| Check | Expected | Observed |
|-------|----------|----------|
| Services healthy | livekit-server, agent, ollama, nemo-stt-cpu, kokoro, web all `healthy`/`running` | |
| `nemo-stt` NOT started | absent from `docker compose ps` (profile-gated) | |
| Agent routes STT to CPU | logs show NEMO_STT_CPU_URL / placement=cpu | |
| End-to-end | a browser session transcribes speech and the persona replies in voice | |

---

## Gate 3 — GPU STT opt-in (`--profile stt-gpu`)

Set `STT_FORCE_CPU=0` + `STT_HEADROOM_MEASURED=1` in `.env` (only after
`10-PLACEMENT-VERIFY.md` G7 co-residency passes), then:

```bash
docker compose --profile stt-gpu up -d
docker compose ps
```

| Check | Expected | Observed |
|-------|----------|----------|
| `nemo-stt` healthy on the GPU | health `healthy`, ~2.4 GB resident (nvidia-smi) | |
| Agent routes STT to GPU | logs show NEMO_STT_URL / placement=gpu | |
| Co-residency | cross-ref 10-PLACEMENT-VERIFY G7: peak < total − 1 GB | |

---

## Gate 4 — Doctor on an all-OK GPU host

```bash
./scripts/gpu-doctor.sh; echo "exit=$?"
```

| Check | Expected | Observed |
|-------|----------|----------|
| All 4 checks OK | nvidia-smi, toolkit, CUDA ≥ 12.8, VRAM ≥ 16384 MB | |
| Final line | `OK: GPU ready.` + the GPU `--profile stt-gpu` snippet | |
| Exit code | 0 | |

---

## Gate 5 — Doctor on a toolkit-missing host

With the NVIDIA Container Toolkit uninstalled or the Docker runtime not configured:

```bash
./scripts/gpu-doctor.sh; echo "exit=$?"
docker compose up -d        # must still come up CPU-degraded
```

| Check | Expected | Observed |
|-------|----------|----------|
| Doctor remedy | the real `could not select device driver` case → `nvidia-ctk runtime configure` remedy | |
| Doctor snippet | the degraded `STT_FORCE_CPU=1` + Fast-model snippet, exit 0 | |
| Stack still boots | CPU STT path comes up usable despite the toolkit gap | |

---

## Gate 6 — Doctor on a sub-spec / non-NVIDIA host

On a <16 GB GPU or a non-NVIDIA machine:

| Check | Expected | Observed |
|-------|----------|----------|
| Doctor recommends degraded | `STT_FORCE_CPU=1` + Fast `OLLAMA_MODEL`, exit 0 | |
| STT usable on CPU | `docker compose up` (no profile) transcribes on CPU-ONNX | |
| Limitation surfaced | doctor states ollama/kokoro still need an NVIDIA GPU | |

---

## Gate 7 — No-hung-`up` (multi-GB build/pull + STT bake)

On a cold first boot (no cached images):

| Check | Expected | Observed |
|-------|----------|----------|
| Health visibility | `docker compose ps` shows `health: starting` → `healthy`, not a silent hang | |
| `start_period` honored | GPU STT 180 s / CPU STT 30 s before unhealthy | |
| Doctor pre-warned | the multi-GB build note printed by `./up.sh` before the build | |

---

**Operator:** _______________  **Date:** _______________  **Host/GPU:** RTX 5090 (consumer `docker compose`)

**Result:** ☐ all gates passed  ☐ gaps recorded above
