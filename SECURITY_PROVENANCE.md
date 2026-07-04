# Security Provenance

This project is distributed as source. Users build and run it locally.

This document tracks non-source artifacts and dependency inputs that deserve extra
provenance scrutiny before public access.

## Current Trust Claim

- Source is scanned locally with `./scripts/security-check.sh`.
- Optional malicious-package heuristics run locally with `./scripts/guarddog-check.sh`.
- npm dependencies are installed from `web/package-lock.json` with registry integrity metadata.
- Python dependencies are currently resolved from requirement ranges and scanned at runtime.
- Docker images are tag-pinned but not digest-pinned.
- Model artifacts are fetched from named upstreams; some revisions still default to `main`.

## Known Pinning Gaps

| Area | Current state | Smallest next step |
| --- | --- | --- |
| Python packages | Requirement ranges in `agent/`, `stt/`, and `requirements-dev.txt`. | Generate per-runtime hash lockfiles with `uv pip compile --generate-hashes` if exact Python artifact traceability becomes required. |
| Docker images | Tags are pinned; digests are not pinned. | Replace tags with `tag@sha256:<digest>` after the public baseline is green. |
| Hugging Face STT revision | `STT_MODEL_REVISION` defaults to `main` unless overridden. | Pin a commit SHA in `.env.example` after final model choice is frozen. |
| Ollama community models | Ladder rung-1s use `:latest`/remote GGUF refs, BUT `pull-and-pin.sh` now records each resolved tier's manifest digest (`OLLAMA_MODEL_*_DIGEST`, sha256 from `/api/tags`) at install and runs `ollama/verify-build.sh` on the community rungs (FAIL → stock rung) — F20. | Replace the community `:latest` refs with immutable `@sha256` references once Ollama exposes a stable one for the source; diff the recorded digest across installs to detect upstream repoints. |
| Vendored browser assets | Assets are committed under `web/public/vendor/`; upstream/version is known from project research. | Add per-file checksums if those files change again. |
| Native macOS Kokoro (source) | `scripts/kokoro-native-macos.sh` clones `remsky/Kokoro-FastAPI` at the `v0.5.0` tag (same source as the pinned CPU/GPU images) and `uv pip install -e ".[cpu]"` builds its Python deps from PyPI ranges on the host — macOS-only, never in a shipped image. | Pin the clone to the tag's commit SHA (`git clone` then `git checkout <sha>`) and add `--generate-hashes` lock for its deps if host-side traceability becomes required. |

## Docker Images

| Image | Where used | Upstream | Pin status | Notes |
| --- | --- | --- | --- | --- |
| `livekit/livekit-server:v1.10.1` | `docker-compose.yml` | https://hub.docker.com/r/livekit/livekit-server | tag-pinned | Self-hosted LiveKit server. |
| `ollama/ollama:0.30.11` | `docker-compose.yml` | https://hub.docker.com/r/ollama/ollama | tag-pinned | Gemma 4 support; local model server. |
| `ollama/ollama:0.30.11-rocm` | `docker-compose.amd.yml` | https://hub.docker.com/r/ollama/ollama | tag-pinned | AMD ROCm local model server override. |
| `ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128` | `docker-compose.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | NVIDIA CUDA 12.8 TTS image. |
| `ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0` | `docker-compose.cpu-tts.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | CPU TTS override. |
| `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0` | `docker-compose.amd.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | AMD ROCm TTS override. |
| `ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587…` | `agent/Dockerfile` | https://github.com/astral-sh/uv | digest-pinned | Agent base image (F34: pinned by @sha256 — the bare tag floats uv + the python patch). |
| `nvcr.io/nvidia/nemo:25.11` | `stt/Dockerfile`, `stt/Dockerfile.cpu` export stage | https://catalog.ngc.nvidia.com/orgs/nvidia/containers/nemo | tag-pinned | NeMo/STT build and GPU runtime base. |
| `python:3.11-slim` | `stt/Dockerfile.cpu` runtime stage | https://hub.docker.com/_/python | tag-pinned | CPU STT runtime base. |
| `node:24-bookworm-slim` | `web/Dockerfile` | https://hub.docker.com/_/node | tag-pinned | Next.js build/runtime base. |
| `alpine:3.21` | `docker-compose.windows-amd.yml`, `docker-compose.macos.yml` | https://hub.docker.com/_/alpine | tag-pinned | Windows AMD / macOS no-op stub (Ollama, plus Kokoro on macOS). |
| `caddy:2.11.4` | `docker-compose.proxy.yml` | https://hub.docker.com/_/caddy | tag-pinned | Optional LAN TLS reverse proxy (terminates the mkcert cert on 443/7443). |

## Downloaded Model And Tarball Artifacts

| Artifact | Where used | Upstream | Pin/check status | Notes |
| --- | --- | --- | --- | --- |
| `nvidia/parakeet-tdt-0.6b-v2` | `STT_MODEL`, GPU buffered STT | https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 | revision env exists; default is `main` | Baked into STT image with `huggingface_hub.snapshot_download`. |
| `nvidia/nemotron-speech-streaming-en-0.6b` | legacy streaming ONNX export source | https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b | revision env exists; default is `main` | Legacy/manual comparison path. |
| `sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2` | `stt/fetch_parakeet_onnx.sh` | https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2 | sha256 checked in script | Expected sha256: `157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad`. |

## Ollama Model Ladders

| Choice | Source tags | Pin/check status | Notes |
| --- | --- | --- | --- |
| Fast | `evalengine/unbound-e2b:latest`, fallback `gemma4:e2b` | tag + manifest digest recorded during install; community rung gated by `ollama/verify-build.sh` (FAIL → stock rung) — F20 | Community first rung, official fallback. |
| Better | `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest`, fallback `gemma4:e4b` | tag + manifest digest recorded during install; community rung gated by `ollama/verify-build.sh` (FAIL → stock rung) — F20 | Community first rung, official fallback. |
| Floor | `hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M`, `hf.co/bartowski/mlabonne_Qwen3-1.7B-abliterated-GGUF:Q4_K_M`, fallback `qwen3.5:2b-q4_K_M` | tag resolved during install | First rung is rebuilt as `rehearsal-floor` with the local Modelfile template fix. |

## Vendored Browser Assets

| Path | Upstream | Version/status | Notes |
| --- | --- | --- | --- |
| `web/public/vendor/three/` | https://github.com/mrdoob/three.js | Three.js r0.180.0 per stack research | Vendored to avoid CDN runtime dependency. |
| `web/public/vendor/three/addons/libs/draco/` | https://github.com/mrdoob/three.js/tree/dev/examples/jsm/libs/draco | version bundled with Three.js r0.180.0 | Includes `draco_decoder.wasm`; treat as vendored binary. |
| `web/public/vendor/talkinghead/` | https://github.com/met4citizen/TalkingHead | TalkingHead 1.7.0 / HeadAudio path per stack research | Vendored to avoid CDN runtime dependency. |

## Local Check Command

Run before public access:

```bash
./scripts/security-check.sh
```

Run the optional deep supply-chain scan when adding or changing dependencies:

```bash
./scripts/guarddog-check.sh
```

Reports are written to `security/reports/` and are intentionally ignored by git.
