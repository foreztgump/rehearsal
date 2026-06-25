# Phase 1 Patterns: Foundation & Infrastructure

**Status:** GREENFIELD — no in-repo analogs exist. The only directory with content is
`.planning/`; there is NO existing source code (no `docker-compose.yml`, no agent worker,
no web frontend, no LiveKit config). Every planned file below is net-new. Pattern analogs
from this codebase are therefore *empty/nonexistent by design* — this is expected for the
foundation phase and is not a gap to fix.

Because there are no in-repo analogs, this document captures the **canonical reference
templates** verified in `01-RESEARCH.md` (Docker GPU Compose syntax, LiveKit self-host
config block, Ollama env config, local turn-detector + metrics scaffold patterns) as the
templates the planner should follow. These are reference patterns, **not fabricated
codebase analogs**.

**Source of file list:** `01-RESEARCH.md` (no CONTEXT.md exists for this phase).

---

## Planned files (extracted from RESEARCH.md)

| # | File (proposed path) | Role | Data flow | In-repo analog | Plan |
|---|----------------------|------|-----------|----------------|------|
| 1 | `docker-compose.yml` | Orchestration / infra manifest | Defines all 6 services + GPU reservations + ports + env | **none (greenfield)** | 01-01 |
| 2 | `.env` (compose env, gitignored) | Config / secrets | Feeds Ollama/LiveKit env into compose | **none (greenfield)** | 01-01/02 |
| 3 | TLS reverse proxy config (e.g. `proxy/Caddyfile` or `nginx.conf`) | Edge / secure-context | Terminates mkcert TLS in front of web + LiveKit WS | **none (greenfield)** | 01-01 |
| 4 | mkcert cert material + CA-trust doc (`certs/`, README step) | Infra / security | Local CA → LAN cert → secure context for getUserMedia | **none (greenfield)** | 01-01 |
| 5 | `agent/Dockerfile` | Build / image | Bakes turn-detector + VAD weights at build (`download-files`) | **none (greenfield)** | 01-03 |
| 6 | `agent/requirements.txt` (or `pyproject.toml`) | Build / deps | Pins `livekit-agents~=1.5`, turn-detector, plugins | **none (greenfield)** | 01-03 |
| 7 | `agent/main.py` (worker entrypoint) | Orchestration / compute | Constructs `AgentSession`, warmup inferences, wires metrics | **none (greenfield)** | 01-02/03 |
| 8 | `agent/metrics.py` (per-stage metrics scaffold) | Observability | Subscribes per-plugin `metrics_collected`; emits 1 line/turn | **none (greenfield)** | 01-03 |
| 9 | Ollama model config (Modelfile or pull script) | Model / config | Pins tag, `num_ctx`, sampling, thinking off | **none (greenfield)** | 01-02 |
| 10 | `livekit.yaml` (server config) | Infra / signaling | rtc ICE/node_ip/udp + keys for self-host | **none (greenfield)** | 01-03 |
| 11 | `web/` Next.js shell (static SPA) | Frontend / UI | Serves shell over TLS; proves `navigator.mediaDevices` defined | **none (greenfield)** | 01-01 |
| 12 | `web/api/token` (token-mint endpoint) | API / auth | Mints LiveKit JWT from dev key (skeleton) | **none (greenfield)** | 01-03 |

> All analogs are "none (greenfield)". The templates below replace the missing analogs.

---

## Reference templates (from RESEARCH.md — follow these)

### T1 — Docker GPU passthrough (file #1 `docker-compose.yml`)
Modern Compose `deploy.resources.reservations.devices` block. `capabilities: [gpu]` is
**required**. Pin every image tag (never `:latest` on Kokoro/Whisper).

```yaml
services:
  ollama:
    image: ollama/ollama:0.6.x          # pin, not :latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all                 # or device_ids: ['0']
              capabilities: [gpu]
    environment:
      - OLLAMA_FLASH_ATTENTION=1
      - OLLAMA_KV_CACHE_TYPE=q8_0
      - OLLAMA_KEEP_ALIVE=-1
```
Service inventory (pin tags): `livekit/livekit-server:v1.10.x`, custom agent
(`livekit-agents~=1.5`), `ollama/ollama:0.6.x`, `fedirz/faster-whisper-server:latest-cuda`
(pin), `ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.x`, static Next.js web behind TLS.
Host prereq (outside compose): NVIDIA Container Toolkit + `nvidia-ctk runtime configure
--runtime=docker`; `nvidia-smi` must already work inside the Proxmox VM.

### T2 — Ollama env + model config (files #2, #9)
```bash
OLLAMA_FLASH_ATTENTION=1     # required for KV quant
OLLAMA_KV_CACHE_TYPE=q8_0    # ~halves KV; requires flash attn (verify allowlist for gemma4)
OLLAMA_KEEP_ALIVE=-1         # pin resident; no cold reload
```
Tag ladder (validate empirically, log in STATE.md): try `gemma4:e4b-it-q4_K_M` → fall back
`gemma4:e4b` + q8_0 KV → fall back `gemma3:4b-it-qat` (~3.3GB safe floor). Set `num_ctx`
**tightly** (Ollama pre-allocates full KV upfront). Sampling: `temperature=1.0, top_p=0.95,
top_k=64`. Thinking OFF via `think: false` / strip `<|think|>`; verify no `<think>`
preamble.

### T3 — LiveKit self-host config (file #10 `livekit.yaml`)
```yaml
port: 7880
rtc:
  port_range_start: 50000     # OR use udp mux instead
  port_range_end: 60000
  tcp_port: 7881
  use_external_ip: true       # or set node_ip: 192.168.x.x (then use_external_ip:false)
  # udp_port: 7882            # OPTIONAL udp mux (simpler firewall; then omit port_range_*)
keys:
  devkey: <secret>
```
Homelab guidance: advertise the LAN-reachable IP (else media never flows); prefer udp mux
`7882` for firewall simplicity; open chosen UDP + TCP 7881 inbound; bind LAN-only, no WAN
forward; leave `use_ice_lite` off initially.

### T4 — Local turn detector + weights bake (files #5, #7)
```python
from livekit.plugins.turn_detector.multilingual import MultilingualModel
# turn_detection=MultilingualModel()   # local CPU, INT8 ONNX, <500MB
```
Dockerfile: `RUN python -m livekit.agents download-files` (pre-fetch VAD + turn-detector
weights → offline-capable). **Avoid `inference.TurnDetector`** (defaults to LiveKit Cloud).
Verify import path for the pinned `~=1.5` line.

### T5 — AgentSession wiring (file #7 `agent/main.py`)
```python
from livekit.agents import AgentSession
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://whisper:8000/v1",
                   model="Systran/faster-whisper-large-v3-turbo", api_key="none"),
    llm=openai.LLM.with_ollama(model="gemma4:e4b",            # pinned tag from 01-02
                               base_url="http://ollama:11434/v1"),
    tts=openai.TTS(base_url="http://kokoro:8880/v1",
                   model="kokoro", voice="af_bella", api_key="none"),
    turn_detection=MultilingualModel(),
)
```
faster-whisper settings to set now: `beam_size=1`,
`condition_on_previous_text=False`, `vad_filter=True`, `language="en"`.

### T6 — Per-stage metrics scaffold (file #8 `agent/metrics.py`)
- Subscribe **per-plugin** `metrics_collected` on each instance
  (`llm.on("metrics_collected", ...)`, `stt`, `tts`, `vad`) — session-level event is
  **DEPRECATED**. Per-turn detail lives in `ChatMessage.metrics` (`MetricsReport`).
- Emit **one structured line per turn** with EOU/VAD, STT, LLM TTFT, TTS TTFB (null/zero ok
  now). Stub P50/P95 rolling aggregation.
- **Walking-skeleton gate:** route the startup warmup LLM TTFT through the scaffold = the
  "one real metric emitted" proof (no voice turn needed).
- Budget constants to encode: EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms, TTS TTFB ≤150ms,
  playout ≤100ms. **Local logs only** — no external telemetry export (PERF-03).

### T7 — HTTPS-on-LAN secure context (files #3, #4, #11)
`getUserMedia` / `navigator.mediaDevices` is `undefined` outside a secure context. Use
mkcert to mint a LAN-trusted cert; install CA on client device(s); serve web (and LiveKit
WS) over TLS. Phase 1 verifies `navigator.mediaDevices` is defined on the **real LAN
device** — enabler for Phase 2 (no audio flows yet).

---

## Notes for the planner
- Do not invent codebase analogs — there are none. Follow T1–T7 verbatim as the templates.
- Open validation tasks carried from RESEARCH.md: exact Ollama tag (T2 ladder), q8_0
  flash-attn allowlist engagement for gemma4, udp-mux vs port-range, Whisper image choice,
  token-mint endpoint, `MultilingualModel` import path on `~=1.5`.
- Phase-1 done = all 5 success criteria TRUE; one real metric line emitted; nothing has
  spoken yet.

---
*Phase 1 patterns — greenfield. Mapped 2026-06-24.*
