# Walking Skeleton — Adept (Near-Real-Time Voice Persona Trainer)

**Phase:** 1
**Generated:** 2026-06-24

## Capability Proven End-to-End

> One sentence: the smallest verifiable capability that exercises the full stack.

`docker compose up` brings the entire self-hosted stack online — LiveKit server, agent
worker, Ollama, Whisper, Kokoro, and the web shell behind LAN-trusted HTTPS — with the GPU
passed through so `nvidia-smi` shows STT+LLM+TTS co-resident under 16GB, the agent registered
to the self-hosted LiveKit (never the cloud), and the per-stage metrics scaffold emitting one
real model-warmup **LLM TTFT** line. Nothing has spoken yet; the skeleton proves the stack
boots, the GPU is real, the models load, and one real timing flows through the metrics path.

(Infra-phase mapping of the standard skeleton: "one real UI interaction / DB read-write" →
"stack boots via `docker compose up`, `nvidia-smi` shows co-resident models < 16GB, and the
metrics scaffold emits one real warmup timing"; "one real UI interaction" → "the web shell,
served over mkcert HTTPS on the real LAN device, reports `navigator.mediaDevices` defined".)

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Orchestration | Single `docker-compose.yml`, 6 services + caddy proxy | DEPLOY-01: one command boots everything with GPU passthrough |
| GPU passthrough | Proxmox→VM (vfio) + VM→container (NVIDIA Container Toolkit) | Two-layer chain; `nvidia-smi` must pass at each layer before Docker sees the GPU |
| LLM serving | Ollama, pinned Gemma 4 quant via fallback ladder, thinking OFF, `keep_alive=-1` | PERF-02: tight 16GB floor; thinking off protects TTFT; tag is UNVERIFIED so a pull-test ladder resolves it |
| VRAM budget | flash-attn (`OLLAMA_FLASH_ATTENTION=1`) + q8_0 KV (`OLLAMA_KV_CACHE_TYPE=q8_0`), tight `num_ctx` | Claws back KV VRAM so STT+LLM+TTS co-reside < 16GB; q8_0 engagement verified empirically (allowlist risk) |
| STT | faster-whisper-server (CUDA), large-v3-turbo, beam_size=1 | ~2GB; streaming-friendly settings set now to avoid later pitfalls |
| TTS | Kokoro-FastAPI (GPU), OpenAI-compatible | ~2.5GB; OpenAI-compatible interface keeps voice swappable later |
| Signaling | Self-hosted LiveKit server, udp mux 7882 + tcp 7881, LAN-correct ICE | DEPLOY-02/PERF-03: no cloud; mux simplifies homelab firewall; ICE must advertise the LAN IP or media never flows |
| Turn detection | Local `MultilingualModel` (turn-detector plugin), weights baked at build | DEPLOY-02/PERF-03: `inference.TurnDetector` defaults to cloud — avoided; image is offline-capable |
| Secure context | mkcert LAN cert terminated by Caddy on 443 | `getUserMedia`/`navigator.mediaDevices` is undefined outside a secure context — required for Phase 2 mic |
| Metrics | In-process per-plugin `metrics_collected` scaffold, local logs only | Success criterion 5; session-level event is deprecated; no external telemetry export (PERF-03) |
| Frontend | Next.js App Router, standalone build, static shell | Minimal shell now; grows into the SPA in Phase 2 |
| Directory layout | `agent/`, `web/`, `ollama/`, `proxy/`, `certs/`, `scripts/`, root compose | Service-per-folder; net-new (greenfield) |

## Stack Touched in Phase 1

- [x] Project scaffold — compose manifest, Next.js shell, agent image, build/lint paths
- [x] Routing — web shell route + `/api/token` mint endpoint
- [x] "Read/write" (infra mapping) — models load resident; `nvidia-smi` reads co-resident VRAM; metrics scaffold writes one real warmup-TTFT line
- [x] UI — web shell over HTTPS reports `navigator.mediaDevices` defined on the real LAN device
- [x] Deployment — `docker compose up` runs the full stack on the Proxmox VM dev environment

## Out of Scope (Deferred to Later Slices)

> Explicit minimalism guard — these are NOT in the Phase 1 skeleton.

- Any live voice turn (mic → STT → LLM → TTS loop) — Phase 2
- Barge-in, semantic endpointing tuning, agent-state indicator, two-sided transcript — Phase 2
- `getUserMedia` actually being called / mic prompt — Phase 2 (Phase 1 only proves the API exists)
- Persona editing, knobs, voice selection, frozen-prefix prompt layout — Phase 3
- KB upload / distillation / prefix-cache — Phase 4
- History management / summarization — Phase 5
- Interview mode state machine — Phase 6
- Session controls, transcript export, graceful-failure handling, final latency tuning — Phase 7
- Any embedder or vector store — explicitly excluded by PERF-02, never added
- External telemetry export (Prometheus/Grafana/Opik) — local logs only by PERF-03

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its
architectural decisions (single compose, self-hosted LiveKit, local models, frozen-prefix-ready
prompt path, local metrics):

- Phase 2: Bare voice loop — full streamed mic→STT→LLM→first-sentence-TTS with barge-in, semantic turn-detect, agent-state pill, two-sided transcript, per-turn latency (the MVP gate)
- Phase 3: Live-editable persona over the frozen-prefix prompt layout
- Phase 4: Ephemeral KB upload → distill → inline-and-cache, preserving flat TTFT
- Phase 5: History sliding-window/summarization behind the frozen prefix
- Phase 6: Interview mode (ask → listen → critique → model answer)
- Phase 7: Session lifecycle + graceful failure + P50<1.0s latency tightening
