---
title: R6 AMD ROCm Support Design
date: 2026-06-29
status: draft for user review
scope: v1.2 R6
---

# R6 - AMD ROCm Support Design

## Summary

R6 adds an AMD hardware profile for Adept without changing the voice pipeline shape.

Chosen path: **Option B - AMD voice stack**.

- LLM runs on AMD GPU through `ollama/ollama:0.30.10-rocm`.
- TTS runs on AMD GPU through `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0`.
- STT stays CPU-backed through the existing R3 `buffered`/CPU path.
- If Kokoro ROCm fails the AMD gate, the fallback is **Option A**: Ollama ROCm on GPU, Kokoro CPU, STT CPU.

R6 does not attempt AMD GPU STT. ONNX Runtime ROCm EP is removed from 1.23 onward, MIGraphX is the forward path, and NeMo GPU STT on ROCm is separate hardware work.

## Goals

- Make the stack boot on supported AMD Linux hosts.
- Keep all inference local.
- Reuse upstream ROCm containers instead of building new serving code.
- Preserve the agent's existing `KOKORO_BASE_URL` and `/dev/captioned_speech` path.
- Document AMD as functional and best-effort until real AMD latency gates pass.
- Provide a clear fallback when Kokoro ROCm is too slow or unstable.

## Non-Goals

- No AMD GPU STT in R6.
- No MIGraphX integration.
- No NeMo-on-ROCm work.
- No new TTS abstraction or `TTSEngine` class.
- No in-app live vendor switching.
- No P50 latency promise for AMD before real hardware measurement.

## Alternatives Considered

### A. Minimal AMD

Ollama ROCm on GPU, STT on CPU, Kokoro on CPU.

This is the safest fallback. It reduces GPU risk but gives up the TTS speedup that makes the AMD profile feel like a real voice stack.

### B. AMD Voice Stack

Ollama ROCm on GPU, Kokoro ROCm on GPU, STT on CPU.

This is the selected design. It is feasible because both required GPU services have upstream ROCm images, and the local agent already talks to Kokoro through a URL and a stable API.

### C. Full AMD GPU Path

Ollama, Kokoro, and STT all on AMD GPU.

Rejected for R6. AMD GPU STT needs real MIGraphX or NeMo ROCm work and real AMD hardware debugging. That is not a profile change.

## Architecture

R6 adds a vendor-specific Compose path and verification runbook. The existing default NVIDIA stack remains unchanged.

The AMD profile swaps only the GPU-backed model containers:

| Service | NVIDIA path today | AMD R6 path |
| --- | --- | --- |
| `ollama` | `ollama/ollama:0.30.10` with NVIDIA device reservation | `ollama/ollama:0.30.10-rocm` with `/dev/kfd` and `/dev/dri` |
| `kokoro` | `ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128` | `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0` |
| `nemo-stt-cpu` | CPU service | unchanged |
| `nemo-stt` | NVIDIA GPU profile | not used by AMD profile |
| `agent` | local LiveKit agent | unchanged except env profile values |
| `web` | Next.js client | unchanged |

The simplest implementation shape is a separate Compose override such as `docker-compose.amd.yml`. It keeps AMD-only device mappings out of the default file and lets the installer or docs run:

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml up
```

No agent code should branch on AMD. The agent already uses:

- `OLLAMA_BASE_URL=http://ollama:11434/v1`
- `OLLAMA_GENERATE_URL=http://ollama:11434/api/generate`
- `KOKORO_BASE_URL=http://kokoro:8880/v1`

Those URLs stay stable.

## Components

### Compose Override

The AMD override owns:

- `ollama.image=ollama/ollama:0.30.10-rocm`
- `ollama.devices=/dev/kfd,/dev/dri`
- `kokoro.image=ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0`
- `kokoro.devices=/dev/kfd,/dev/dri`
- Kokoro MIOpen cache volumes:
  - `/home/appuser/.config/miopen`
  - `/home/appuser/.cache/miopen`
- Kokoro ROCm env:
  - `USE_GPU=true`
  - `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`
  - `MIOPEN_FIND_MODE=2`
- STT env profile:
  - `STT_ENGINE=buffered`
  - `STT_BUFFERED_DEVICE=cpu`
  - `STT_FORCE_CPU=1`

The override should not add new services.

### GPU Doctor

`scripts/gpu-doctor.sh` remains advise-only and always exits 0.

R6 extends it to detect AMD and print an AMD profile snippet. It should not write `.env`.

Detection order:

1. NVIDIA path remains first and unchanged.
2. If NVIDIA is absent, check AMD:
   - `/dev/kfd`
   - `/dev/dri`
   - `rocminfo` or `amd-smi` when available
3. If AMD is present, print:
   - the AMD Compose command
   - required host driver note
   - AMD `.env` snippet
   - Kokoro warmup warning

### Kokoro ROCm Warmup

Kokoro ROCm is the risk-bearing part of B.

Upstream documents MIOpen cache persistence and ships a warmup script. R6 should expose a runbook command to pre-populate the cache before judging latency. The gate records both cold and warmed behavior.

R6 should not run a two-hour warmup automatically during normal `up`.

### Documentation

README changes should state:

- AMD support is Linux-only for v1.2.
- Supported cards are constrained by ROCm/Ollama support.
- AMD uses CPU STT by design.
- AMD latency is best-effort until measured on the user's AMD host.
- Kokoro CPU fallback is supported when ROCm TTS fails or is too slow.

## Data Flow

The live voice turn stays the same:

1. Browser sends microphone audio through LiveKit.
2. Agent STT uses the CPU STT service for final transcript.
3. Agent sends the prompt to Ollama at `http://ollama:11434/v1`.
4. Ollama serves the selected model on AMD ROCm.
5. Agent sends TTS text to Kokoro at `http://kokoro:8880/dev/captioned_speech`.
6. Kokoro serves audio on AMD ROCm.
7. Agent emits audio through LiveKit.
8. If avatar is on, existing word timestamps are published over `lk.avatar.lipsync`.

There is no new API between agent and TTS.

## Error Handling

- If AMD devices are missing, `gpu-doctor.sh` prints the missing `/dev/kfd` or `/dev/dri` condition and recommends CPU/NVIDIA paths where applicable.
- If Ollama ROCm fails to serve a model, the AMD gate fails. Do not silently fall back to CPU LLM because that would hide a broken AMD profile and likely destroy latency.
- If Kokoro ROCm fails health or `/dev/captioned_speech`, switch the profile to Kokoro CPU and keep Ollama ROCm.
- If Kokoro ROCm is functional but cold latency is bad, run the MIOpen warmup gate and compare warmed numbers before falling back.
- If CPU STT cannot keep up, R6 documents the host as unsupported for AMD voice usage. It does not try GPU STT.

## Verification

Sandbox checks:

- Compose config renders for the AMD override.
- `gpu-doctor.sh` shell tests cover AMD detection and advice output.
- README mentions AMD best-effort latency and Kokoro CPU fallback.
- No agent TTS abstraction is added.

AMD hardware gates:

1. `docker compose -f docker-compose.yml -f docker-compose.amd.yml config` is valid.
2. Ollama ROCm starts and serves the selected model.
3. Kokoro ROCm starts and `/v1/audio/speech` works.
4. Kokoro ROCm `/dev/captioned_speech` works with timestamps.
5. Full voice-to-voice smoke passes with `STT_ENGINE=buffered` and `STT_BUFFERED_DEVICE=cpu`.
6. Kokoro cold latency and warmed latency are recorded.
7. If warmed Kokoro is too slow or unstable, profile falls back to Kokoro CPU and the fallback smoke passes.

Exit criteria:

- AMD profile is documented as functional on at least one supported AMD host.
- Fallback profile is documented and tested.
- AMD is not described as P50-guaranteed unless the AMD gate records P50 data that supports it.

## Research Basis

- Ollama Docker docs: `ollama/ollama:rocm` with `/dev/kfd` and `/dev/dri`.
- Ollama GPU docs: ROCm v7 requirement, supported Radeon/Instinct families, `HSA_OVERRIDE_GFX_VERSION`, `ROCR_VISIBLE_DEVICES`.
- Docker Hub: pin-able `ollama/ollama:0.30.10-rocm`.
- ROCm Docker docs: manual device passthrough and AMD Container Runtime Toolkit paths.
- ONNX Runtime docs: ROCm EP removed starting 1.23; MIGraphX is the migration path.
- Kokoro-FastAPI README/changelog: `kokoro-fastapi-rocm` image, AMD support, MIOpen cache behavior.
- Kokoro-FastAPI PRs: AMD GPU support and persisted MIOpen cache/warmup.

Reference URLs:

- https://docs.ollama.com/docker
- https://docs.ollama.com/gpu
- https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html
- https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html
- https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html
- https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html
- https://github.com/remsky/Kokoro-FastAPI

## Implementation Notes

Keep the implementation boring:

- Prefer one Compose override over runtime YAML generation.
- Prefer `gpu-doctor.sh` advice over automatic `.env` mutation.
- Prefer upstream images over local ROCm Dockerfiles.
- Prefer documented fallback to clever self-healing.

The only acceptable R6 fallback is narrower scope, not more code.
