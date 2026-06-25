# Phase 1 Research: Foundation & Infrastructure

**Phase goal:** Stand up the entire self-hosted stack (LiveKit server, agent worker, Ollama, Whisper, Kokoro, frontend shell) from one Docker Compose with GPU passthrough, corrected model pins, a defended VRAM budget, and a per-stage latency-metrics scaffold — before any voice flows.

**Mode:** mvp / walking skeleton. First deliverable = thinnest end-to-end slice: stack boots, GPU visible, models load, one real metric emitted. **No voice flows in this phase.**

**Requirements covered:** PERF-02, PERF-03, DEPLOY-01, DEPLOY-02
**Plans:** 01-01 (Compose+GPU+HTTPS), 01-02 (Ollama pin+VRAM), 01-03 (LiveKit self-host+turn-detector+metrics scaffold)

**Researched:** 2026-06-24 — grounded in existing `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md` plus live verification of LiveKit config, Docker GPU syntax, Ollama thinking-disable, and the LiveKit metrics API.

---

## TL;DR — What you must know to plan this phase well

1. **The model tag in the success criteria is wrong/unverified.** `gemma4:e4b-it-q4_K_M` as literally written may not be a real Ollama tag. Verified-real Gemma 4 tags are `gemma4:e4b` (9.6GB, full) and quant-suffixed tags like `gemma4:26b-a4b-it-q4_K_M`. **Action: `ollama pull` the exact tag empirically before pinning it; if `e4b-it-q4_K_M` doesn't resolve, fall back to `gemma4:e4b` with KV quant, or `gemma3:4b-it-qat` (~3.3GB) for guaranteed 16GB headroom.** Treat the exact tag as an open validation task in Plan 01-02.
2. **`gemma4:e4b` is 9.6GB, NOT the "~5GB" the original PROJECT.md assumed** (that was Gemma 3n). This makes the 16GB floor real and tight. The whole point of `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` is to claw back KV-cache VRAM so the three models co-reside.
3. **Disabling Gemma 4 thinking is done via the `<|think|>` system-prompt token mechanism / Ollama `think: false`** — but there's a known Ollama bug (#15260) where `think=false` silently breaks `format` (structured JSON output) for gemma4. That bug doesn't bite Phase 1 (no structured output yet) but matters for the KB-distillation phase later. For Phase 1, just verify thinking is off (no `<think>` preamble in output).
4. **LiveKit self-hosting on a Proxmox VM + LAN has two hard blockers:** (a) `getUserMedia` requires a **secure context** (HTTPS or localhost) or `navigator.mediaDevices` is `undefined` → no mic ever; (b) WebRTC ICE advertises the wrong (container/internal) IP unless you set `rtc.use_external_ip` / `rtc.node_ip` and open the UDP port range. Both must be solved in Phase 1 even though no audio flows yet, because Phase 2 is dead without them.
5. **Use the LOCAL `MultilingualModel` turn detector from `livekit-plugins-turn-detector`** — NOT `inference.TurnDetector` (defaults to LiveKit Cloud → violates PERF-03/DEPLOY-02). Pre-download its weights at image-build time (`python -m livekit.agents download-files`) so the container is offline-capable.
6. **The session-level `metrics_collected` event is now deprecated** in newer LiveKit Agents. Per-plugin `metrics_collected` (subscribe on the STT/LLM/TTS/VAD instance) is **not** deprecated; per-turn latency lives in `ChatMessage.metrics` (`MetricsReport`). Build the scaffold on the non-deprecated surfaces. The scaffold must emit VAD/STT/LLM/TTS timings as one structured line per turn — but since there's no voice loop yet, Phase 1 only needs the **plumbing + one synthetic/warmup metric proving it emits**.

---

## Requirement decoding

| ID | Means for this phase | Verification |
|----|----------------------|--------------|
| **PERF-02** | Stack fits the 16GB VRAM floor; STT+LLM+TTS co-resident; no embedder/vector store; LLM is the pinned Gemma 4 quant with thinking OFF | `nvidia-smi` under simultaneous load shows all three resident < 16GB; Ollama serves the pinned tag; output has no `<think>` preamble |
| **PERF-03** | All inference local; nothing leaves the LAN; no cloud turn detector | grep config for any cloud endpoint; turn detector is local `MultilingualModel`; firewall/bind to LAN only |
| **DEPLOY-01** | One `docker compose up` brings up all 6 services with GPU passthrough | Single command boots livekit-server, agent, ollama, whisper, kokoro, web; GPU services see the GPU |
| **DEPLOY-02** | LiveKit fully self-hosted incl. local turn-detection model | No LiveKit Cloud dependency anywhere; turn-detector weights baked into image |

---

## Plan 01-01: Docker Compose + GPU passthrough + HTTPS-on-LAN

### Docker GPU passthrough (verified syntax)

Two equivalent approaches; modern Compose uses the `deploy.resources.reservations.devices` block:

```yaml
services:
  ollama:
    image: ollama/ollama:0.6.x          # pin, not :latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all                 # or device_ids: ['0'] for a specific GPU
              capabilities: [gpu]
    environment:
      - OLLAMA_FLASH_ATTENTION=1
      - OLLAMA_KV_CACHE_TYPE=q8_0
      - OLLAMA_KEEP_ALIVE=-1
```

Gotchas verified from the field:
- `capabilities: [gpu]` is **required** — Compose errors `capabilities is required` without it. Quote as `["gpu"]` if YAML coerces oddly.
- Error `could not select device driver "nvidia"` = NVIDIA Container Toolkit not installed/configured on the host (inside the Proxmox VM). Install `nvidia-container-toolkit` and `nvidia-ctk runtime configure --runtime=docker` before anything works.
- `--gpus all` (CLI) ≡ the deploy block (Compose). Both fine.
- For shared-GPU AI workloads consider `shm_size` / `ipc: host` if a service complains about shared memory (more relevant to multi-GPU training; likely unneeded here but worth knowing).

### Proxmox VM prerequisite (host-level, outside Compose)

GPU must already be passed through to the **VM** (PCIe passthrough / vfio) before Docker can see it. `nvidia-smi` must work inside the VM first. Then NVIDIA Container Toolkit bridges VM→container. This is a two-layer passthrough: Proxmox→VM (vfio), VM→container (nvidia-toolkit). Plan should explicitly verify `nvidia-smi` at each layer.

### HTTPS-on-LAN (mkcert) — the secure-context blocker

- `getUserMedia` / `navigator.mediaDevices` is **only defined in a secure context**: HTTPS, `localhost`, or `file://`. Serving the web UI over plain `http://192.168.x.x` yields `navigator.mediaDevices === undefined` and mic access throws `TypeError`. This silently passes on `localhost` dev and breaks on the real LAN URL.
- **mkcert** generates a locally-trusted CA + cert for the LAN hostname/IP. Install the CA on the client device(s). Serve the web frontend (and ideally the LiveKit WS endpoint) over TLS.
- Even though Phase 1 has no voice, **stand up HTTPS now** and verify `navigator.mediaDevices` is defined on the real device — it's a Phase 1 success-enabler for Phase 2.
- Security note: per-deployment cert; restrict to LAN; document the CA-trust step. Don't reuse/leak the cert (LAN MITM risk).

### Service inventory (6 services)

| Service | Image (pin tags) | GPU? | Ports | VRAM |
|---------|------------------|------|-------|------|
| livekit-server | `livekit/livekit-server:v1.10.x` | no | 7880 (WS/API), 7881 (ICE/TCP), 50000-60000/udp (or udp mux 7882) | none |
| agent | custom Python (`livekit-agents~=1.5`) | no (orchestration) | — | small/none |
| ollama | `ollama/ollama:0.6.x` | yes | 11434 | ~9.6GB (e4b) |
| whisper | `fedirz/faster-whisper-server:latest-cuda` (pin) | yes | 8000 | ~2GB |
| kokoro | `ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.x` (pin) | yes | 8880 | ~2-3GB |
| web | static Next.js build behind TLS | no | 443 | none |

**Pin every image tag** — `:latest` on Kokoro/Whisper causes silent breaking changes.

---

## Plan 01-02: Ollama model pin + flash-attn/KV-quant + VRAM validation

### The model-tag reality check (DO THIS FIRST)

The success criterion says `gemma4:e4b-it-q4_K_M`. Verification status:
- **Confirmed real:** `gemma4:e4b` (9.6GB), `gemma4:e2b` (7.2GB), `gemma4:26b` (18GB MoE A4B), `gemma4:31b` (20GB), and quant-suffixed `gemma4:26b-a4b-it-q4_K_M` (appears in Ollama issue trackers → real).
- **Unconfirmed:** the exact string `gemma4:e4b-it-q4_K_M`. The `-it-q4_K_M` quant suffix pattern is real for the 26b line; whether an E4B q4_K_M tag is published must be checked by `ollama pull gemma4:e4b-it-q4_K_M` / browsing the Ollama library page.
- **Decision rule for the plan:**
  1. Try the literal tag. If it pulls, pin it.
  2. If not, pin `gemma4:e4b` + `q8_0` KV cache (quality, tight on 16GB).
  3. If VRAM won't hold, fall back to `gemma3:4b-it-qat` (~3.3GB) — large headroom, documented as the safe-floor choice.
- **Log the decision** in STATE.md — this resolves the open blocker already noted there.

### Required Ollama env (all three needed for the budget)

```bash
OLLAMA_FLASH_ATTENTION=1     # memory-efficient attention; REQUIRED for KV quant
OLLAMA_KV_CACHE_TYPE=q8_0    # ~halves KV memory; requires flash attention
OLLAMA_KEEP_ALIVE=-1         # pin model resident forever (no cold reload, no KV dump)
```

Plus per-request / Modelfile:
- `num_ctx` sized **tightly** to real worst case (persona + KB brief + history + headroom), NOT a round 32768. Ollama **pre-allocates the full `num_ctx` KV cache upfront** — every extra 1k is pre-reserved VRAM. (Phase 1 can use a modest `num_ctx` since no KB yet; document that it grows in Phase 4.)
- Sampling (Gemma 4 guidance): `temperature=1.0, top_p=0.95, top_k=64` (tune temp down later for a steadier trainer voice).

### Critical caveat — flash-attn allowlist (the STATE.md blocker)

`OLLAMA_KV_CACHE_TYPE=q8_0` only works if `OLLAMA_FLASH_ATTENTION=1` AND the model arch is on Ollama's flash-attn allowlist. **If Gemma 4 is not on the allowlist, q8_0 silently falls back to F16 KV cache → VRAM budget breaks.** This is the open concern in STATE.md line 67. **Validate empirically:** check Ollama logs at model load for a flash-attention/KV-quant warning; measure actual VRAM with q8_0 set vs unset. If it falls back, the 16GB math must be redone (smaller model or smaller num_ctx).

### Disabling thinking (the latency killer)

- Gemma 4 thinking is triggered by a `<|think|>` token in the system prompt template. Mechanisms to disable:
  - Ollama API `think: false` (supported Ollama 0.24+).
  - Omit/strip the `<|think|>` token (template-level).
  - `enable_thinking: false` in some configs.
- **Known bug (Ollama #15260):** `think=false` + `format` (structured JSON) → format constraint silently dropped for gemma4. Not a Phase 1 problem (no structured output here) but flag it for the KB-distillation phase, which may want JSON output.
- **Phase 1 verification:** send a trivial prompt, confirm output has no `<think>...</think>` reasoning preamble and TTFT is low. Do not carry prior-turn thoughts in history (later phases).

### VRAM validation under load (PERF-02 proof)

```
gemma4:e4b           ~9.6 GB
faster-whisper turbo int8   ~2.0 GB
Kokoro-82M               ~2.5 GB
+ per-process CUDA overhead (~0.5-1GB each), fragmentation, KV pre-alloc
-----------------------------------
~14-15 GB peak → fits 16GB but with thin headroom
```

- Plan ~12-13GB *usable* on a 16GB card, not 16. Per-process CUDA context eats ~0.5-1GB × 3.
- **Validation procedure:** warm all three models (tiny dummy inference each), then run them concurrently and capture `nvidia-smi` peak used-VRAM. Assert < 16GB with headroom. This is the literal PERF-02 / success-criterion-3 test.
- Turn-detector + Silero VAD run on **CPU** (<500MB RAM, negligible VRAM) — not part of the GPU budget.
- No embedder, no vector store (PERF-02 explicit) — don't add one.

---

## Plan 01-03: Self-hosted LiveKit + ICE config + local turn-detector + metrics scaffold

### livekit-server config (verified from config-sample.yaml)

```yaml
port: 7880                    # WS/API (behind TLS)
rtc:
  port_range_start: 50000     # UDP host candidates — MUST be open inbound
  port_range_end: 60000
  tcp_port: 7881              # ICE/TCP fallback (VPN/firewall)
  use_external_ip: true       # discover public/reachable IP via STUN
  # node_ip: 192.168.x.x      # OR set explicitly if use_external_ip can't find the LAN IP
                              # (use_external_ip takes precedence; for node_ip set use_external_ip:false)
# udp_port: 7882              # OPTIONAL: UDP mux — all UDP on one port (simpler firewall);
                              # if set, port_range_start/end must NOT be set
keys:
  devkey: <secret>            # API key/secret pair for token minting
```

LAN/Proxmox-specific guidance:
- The default config often advertises the **internal/container IP** as the ICE host candidate → signaling "connects" but **media never flows**. Fix: `use_external_ip: true` (STUN-discovered) or explicit `node_ip` set to the LAN-reachable VM IP.
- **For single-user LAN, no TURN/STUN server is strictly needed** — host candidates work if the correct LAN IP is advertised and the UDP port range is open VM→client. TURN is only for restrictive NATs (not the homelab LAN case).
- **UDP mux (`udp_port: 7882`)** dramatically simplifies firewalling on Proxmox — one UDP port instead of a 10k range. Strongly consider it for a homelab single-node deploy.
- Open the chosen UDP port(s) + TCP 7881 inbound on the VM firewall. Bind LiveKit to the LAN interface; **do not** port-forward to WAN (privacy/security).
- `use_ice_lite: true` speeds ICE but "might cause connect issues behind NAT" — leave off initially on the VM.

### Local turn detector (DEPLOY-02 / PERF-03)

```python
from livekit.plugins.turn_detector.multilingual import MultilingualModel
# ... turn_detection=MultilingualModel()  # local CPU, <500MB, 14 langs
```

- Use `MultilingualModel` (fine-tuned Qwen2.5-0.5B, INT8 ONNX, CPU in-process). **Avoid `inference.TurnDetector`** — it defaults to LiveKit Cloud inference → violates local-first.
- **Bake weights into the image at build time:** `RUN python -m livekit.agents download-files` (pre-fetches VAD + turn-detector weights) so the container starts fully offline-capable. Without this, first start tries to download → fails air-gapped / leaks to network.
- Phase 1 only needs the detector *loaded and proven local* (no live turns yet). Verify no outbound network call at startup.

### Per-stage metrics scaffold (success criterion 5)

**API reality (verified, important — the API changed):**
- Session-level `metrics_collected` event: **DEPRECATED**. Migrate to:
  - **Per-plugin `metrics_collected`** (NOT deprecated): subscribe on each plugin instance, e.g. `llm.on("metrics_collected", ...)`, `stt.on(...)`, `tts.on(...)`, `vad.on(...)`. This gives per-component STT/LLM/TTS/VAD latency+usage.
  - **`ChatMessage.metrics`** (`MetricsReport`): per-turn latency breakdown attached to each message.
  - `session_usage_updated` / `session.usage`: cumulative per-model token/duration.
  - `SessionReport` via `ctx.make_session_report()`: end-of-session snapshot.
- Metrics exposed for tuning: **EOU/end-of-utterance delay, STT duration, LLM TTFT, TTS TTFB**, end-to-end.

**What the Phase 1 scaffold must do (walking-skeleton scope):**
- Wire a structured logger that emits **one structured line per turn** with fields for VAD/EOU, STT, LLM TTFT, TTS TTFB (even if zero/null now). Compute P50/P95 over a rolling window — stub the aggregation.
- Subscribe to the per-plugin `metrics_collected` events on whatever plugin instances exist (they exist as soon as the `AgentSession` is constructed, even without a live call).
- **Prove emission with a real metric:** the model warmup inference (dummy prompt to Ollama at startup) produces a real LLM TTFT — emit that through the scaffold. That's the "one real metric emitted" walking-skeleton gate, satisfying success criterion 5 without needing a voice turn.
- Per-stage budget constants to encode now (used as alerts later): EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms, TTS TTFB ≤150ms, playout ≤100ms.
- Keep metrics **in-memory / local logs only** (PERF-03) — no external telemetry export (the Opik/Prometheus/Grafana integrations in the wild all assume export; don't use them in v1).

### AgentSession wiring (reference, even if not driven this phase)

```python
from livekit.agents import AgentSession
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://whisper:8000/v1",
                   model="Systran/faster-whisper-large-v3-turbo", api_key="none"),
    llm=openai.LLM.with_ollama(model="gemma4:e4b",       # pinned tag from 01-02
                               base_url="http://ollama:11434/v1"),
    tts=openai.TTS(base_url="http://kokoro:8880/v1",
                   model="kokoro", voice="af_bella", api_key="none"),
    turn_detection=MultilingualModel(),                   # local CPU
)
```

faster-whisper streaming settings to set now (avoid Pitfall 13 later): `beam_size=1`, `condition_on_previous_text=False`, `vad_filter=True`, explicit `language="en"`.

---

## Phase-1-relevant pitfalls (from PITFALLS.md, filtered)

| # | Pitfall | Phase 1 action |
|---|---------|----------------|
| 1 | Latency compounds silently across un-instrumented stages | Build the per-stage metric scaffold NOW (criterion 5); cheap to add, painful to retrofit |
| 3 | Cold start / keep-alive eviction | `OLLAMA_KEEP_ALIVE=-1`; warm all 3 models at startup with dummy inferences (also feeds the metric scaffold) |
| 9 | 3 models + KV growth → OOM on 16GB | Flash-attn + q8_0 KV + tight `num_ctx`; budget ~12-13GB usable; `nvidia-smi` watchdog logging |
| 12 | LiveKit HTTPS/WebRTC/LAN breaks mic | mkcert HTTPS + `use_external_ip`/`node_ip` + open UDP ports — solve in Phase 1, test on real LAN device |
| — | flash-attn allowlist silent F16 fallback | Empirically verify q8_0 actually engages for Gemma 4 (STATE.md blocker) |

Security/privacy for Phase 1: bind Ollama/LiveKit/all ports to LAN interface only; no WAN port-forward; per-deployment mkcert cert; no transcripts/audio to disk or logs (nothing to log yet, but set the discipline).

---

## Open questions / validation tasks to resolve during planning or execution

1. **Exact Ollama tag** for the LLM — pull-test `gemma4:e4b-it-q4_K_M`; pick the fallback ladder if it doesn't resolve. (Updates STATE.md decision.)
2. **Does q8_0 KV cache actually engage for Gemma 4** (flash-attn allowlist)? Empirical VRAM measurement. (Resolves STATE.md blocker line 67.)
3. **UDP mux vs port range** for LiveKit on the Proxmox VM — pick based on firewall simplicity (recommend mux `udp_port: 7882`).
4. **Whisper image choice** — `fedirz/faster-whisper-server` vs Speaches (bundles STT+TTS). Pin a release tag either way.
5. **Where the agent gets the LiveKit token** — token-mint endpoint (web/api.ts) needed even for the skeleton; trivial dev key for now.
6. **Confirm `MultilingualModel` import path** for the installed `livekit-plugins-turn-detector` version (`.multilingual` vs string `"multilingual"`); the plugin is marked deprecated on PyPI but is the correct local choice — verify it still imports in the pinned `~=1.5` line.

---

## Build order within Phase 1 (walking skeleton)

1. **01-01 first:** host GPU visible in VM (`nvidia-smi`) → toolkit → Compose with GPU reservation → all 6 containers start → mkcert HTTPS serving the web shell → `navigator.mediaDevices` defined on real LAN device.
2. **01-02 next:** pin/validate the LLM tag, set flash-attn+KV-quant+keep-alive env, warm all 3 models, capture `nvidia-smi` under concurrent load < 16GB, confirm thinking off.
3. **01-03 last:** livekit-server config (ICE/node_ip/UDP), bake turn-detector weights, construct `AgentSession`, wire the per-plugin metrics scaffold, emit the warmup LLM TTFT as the first real metric.

**Phase-1 done = all 5 success criteria TRUE; one real metric line emitted; nothing has spoken yet.** Phase 2 builds the actual voice loop on top.

---

## Sources

- Existing project research: `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md` (HIGH confidence, June 2026 stack verification)
- LiveKit `config-sample.yaml` (rtc.port_range, use_external_ip, node_ip, udp_port mux, tcp_port) — github.com/livekit/livekit
- LiveKit Docs — Ports and firewall (7880 API, 50000-60000 ICE/UDP, 7881 ICE/TCP, 7882 UDP mux)
- LiveKit Docs — Data hooks / observability (`metrics_collected` session-level DEPRECATED; per-plugin not deprecated; `ChatMessage.metrics` / `MetricsReport`; EOU/STT/LLM-TTFT/TTS-TTFB fields)
- Ollama blog "Thinking" + Google AI forum (`think: false`, `<|think|>` token, `enable_thinking: false`); Ollama issue #15260 (`think=false` breaks `format` for gemma4)
- Docker NVIDIA GPU Compose syntax (`deploy.resources.reservations.devices`, `capabilities: [gpu]`, toolkit `could not select device driver`) — multiple field reports, Jan 2026
- MDN getUserMedia secure-context requirement (HTTPS/localhost; `mediaDevices` undefined otherwise)
- Ollama FAQ — `OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE=q8_0` (requires flash attn), `OLLAMA_KEEP_ALIVE=-1`

---
*Phase 1 research — Foundation & Infrastructure. Researched 2026-06-24.*
</content>
</invoke>
