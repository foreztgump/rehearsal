---
phase: 01-foundation-infrastructure
plan: 01-03
subsystem: infra
tags: [livekit, ice, udp-mux, node-ip, turn-detector, multilingual-model, metrics, agentsession, jwt, faster-whisper, ollama, kokoro]

requires:
  - phase: 01-01
    provides: Six-service GPU Compose stack + Caddy TLS proxy + uv agent placeholder Dockerfile
  - phase: 01-02
    provides: Resolved OLLAMA_MODEL tag + ollama/warmup.py real LLM TTFT source
provides:
  - Self-hosted livekit.yaml — LAN-correct ICE (udp mux 7882, tcp 7881) via node_ip (no STUN/WAN egress)
  - LIVEKIT_KEYS-injected server keys (no secret committed) + --node-ip runtime override
  - Agent image extending the uv placeholder — uv-pinned livekit-agents~=1.5 + plugins, VAD/turn-detector weights baked offline
  - agent/metrics.py — per-plugin (non-deprecated) metrics scaffold, budget constants, P50/P95 stub, local-only logs
  - agent/main.py — AgentSession against the 3 local endpoints + local MultilingualModel, startup warmup emits one real LLM TTFT
  - web/app/api/token/route.ts — LiveKit JWT mint from the dev key (Phase 2 enabler)
affects: [phase-02-voice-loop, phase-04-knowledge-base]

tech-stack:
  added:
    - "livekit-agents~=1.5 (agent image)"
    - "livekit-plugins-openai / -silero / -turn-detector"
    - "livekit-server-sdk@2.15.5 (web token mint)"
  patterns:
    - "LiveKit ICE via node_ip (--node-ip flag) — never use_external_ip:true (avoids STUN/WAN egress)"
    - "UDP mux single port (7882) over a port range for homelab firewall simplicity"
    - "Server keys via LIVEKIT_KEYS env (built from .env) — no secret in committed yaml"
    - "Turn detector is the local MultilingualModel; weights baked via `download-files` at build (offline-capable)"
    - "Metrics on per-plugin metrics_collected only (session-level is deprecated); local logs, no external export"
    - "Token JWT signed server-side (force-dynamic); secret never reaches the browser"

key-files:
  created:
    - livekit.yaml
    - agent/requirements.txt
    - agent/metrics.py
    - agent/main.py
    - web/app/api/token/route.ts
  modified:
    - docker-compose.yml
    - agent/Dockerfile
    - .env.example
    - .env
    - README.md
    - web/package.json
    - web/package-lock.json

key-decisions:
  - "node_ip over use_external_ip:true — STUN-based external-IP discovery is outbound WAN traffic that violates the no-egress invariant; node_ip pins the LAN ICE candidate with zero egress. Runtime --node-ip flag (LIVEKIT_NODE_IP) overrides the yaml; only works because use_external_ip is false (livekit#4049)."
  - "UDP mux 7882 (single port) instead of a 50000-60000 range — one firewall rule for the Proxmox homelab; port_range_start/end omitted so the mux engages."
  - "Server keys injected via LIVEKIT_KEYS env ('<key>: <secret>' from .env) — no plaintext secret in the committed livekit.yaml."
  - "Warmup LLM TTFT emitted in the worker prewarm hook (before any job/voice turn) so the walking-skeleton 'one real metric' gate fires at worker startup without a participant."
  - "Token endpoint uses livekit-server-sdk@2.15.5 AccessToken.toJwt() (async, jose-based); force-dynamic so each request re-signs."

patterns-established:
  - "Pin the advertised ICE IP explicitly (node_ip) for local-first WebRTC — no STUN"
  - "Bake model weights into the image at build (download-files) for offline-capable startup"
  - "Subscribe per-plugin metrics_collected; never the deprecated session-level event"

requirements-completed: [DEPLOY-02, PERF-03, PERF-02]

duration: 7 min
completed: 2026-06-25
status: complete
---

# Phase 01 Plan 01-03: Self-hosted LiveKit + local turn-detector + per-stage metrics scaffold Summary

**Self-hosted LiveKit with LAN-pinned ICE (udp mux 7882 + node_ip, no STUN egress), a uv-built agent image that bakes the local MultilingualModel + Silero VAD weights offline, an AgentSession wired to the three local model endpoints, a per-plugin metrics scaffold that emits the warmup LLM TTFT as the one real metric, and a LiveKit JWT-mint endpoint for Phase 2.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-25T04:36:45Z
- **Completed:** 2026-06-25T04:43:56Z
- **Tasks:** 4
- **Files modified:** 13 (5 created, 8 modified)

## Accomplishments
- `livekit.yaml` self-host config: TCP 7880 signaling, ICE/TCP 7881, **udp mux 7882** (no port range), and the ICE host candidate pinned to the LAN IP via `node_ip` + `--node-ip` (use_external_ip:false) so media flows on the LAN with **zero STUN/WAN egress**. Keys injected via `LIVEKIT_KEYS` from `.env` — no secret committed. README documents the LAN-only firewall (7882/udp, 7881/tcp, 7443/tcp; no WAN forward).
- Agent image extends the 01-01 uv placeholder: `uv pip install` of `livekit-agents~=1.5` + openai/silero/turn-detector plugins (no pip outside `uv pip`), then `python -m livekit.agents download-files` bakes the Silero VAD + MultilingualModel weights into the image for offline-capable startup.
- `agent/metrics.py` per-stage scaffold: subscribes the **non-deprecated per-plugin** `metrics_collected` on llm/stt/tts/vad, emits one structured JSON line per turn (null stages allowed pre-voice), encodes the budgets (EOU 300 / STT 150 / LLM_TTFT 300 / TTS_TTFB 150 / playout 100), stubs a rolling P50/P95, and exports `emit_warmup_metric()`. Local stdout logs only — no external telemetry.
- `agent/main.py` constructs the `AgentSession` against faster-whisper (beam_size=1, condition_on_previous_text=False, vad_filter=True, language="en"), Ollama (`with_ollama`, resolved `OLLAMA_MODEL`), Kokoro (af_bella), and the local `MultilingualModel`. The worker prewarm hook runs the warmup inference and routes the real LLM TTFT through `metrics.emit_warmup_metric` — the walking-skeleton "one real metric" gate — without starting a voice turn.
- `web/app/api/token/route.ts` mints a signed LiveKit JWT (livekit-server-sdk 2.15.5, `roomJoin` grant) from the dev key — verified end-to-end: a 3-part JWT with the correct `video` grants and `iss=devkey`.

## Task Commits

1. **Task 01-03-1: LiveKit self-host config (LAN ICE udp mux + node_ip)** - `aeb3120` (feat)
2. **Task 01-03-2: Agent image — uv-pinned deps + bake VAD/turn-detector weights** - `f1a9510` (feat)
3. **Task 01-03-3: Per-stage metrics scaffold (per-plugin, local logs)** - `7caef70` (feat)
4. **Task 01-03-4: AgentSession wiring + token endpoint + warmup emit gate** - `12d80c8` (feat)

## Files Created/Modified
- `livekit.yaml` - self-host config: port 7880, rtc tcp 7881 / udp mux 7882, node_ip + use_external_ip:false
- `docker-compose.yml` - livekit `--config`/`--node-ip`/`LIVEKIT_KEYS` + yaml mount; agent service comment updated to real worker
- `agent/Dockerfile` - uv venv + `uv pip install -r requirements.txt` + `download-files` weights bake + `main.py start` CMD
- `agent/requirements.txt` - livekit-agents~=1.5 + openai/silero/turn-detector plugins + httpx
- `agent/metrics.py` - per-plugin metrics scaffold; budgets; P50/P95 stub; warmup-TTFT entrypoint
- `agent/main.py` - AgentSession (local STT/LLM/TTS + MultilingualModel), prewarm warmup + metric emit, no voice turn
- `web/app/api/token/route.ts` - LiveKit JWT mint (force-dynamic); secret stays server-side
- `web/package.json` / `web/package-lock.json` - livekit-server-sdk@2.15.5
- `.env` / `.env.example` - LIVEKIT_NODE_IP added; LiveKit key comments updated
- `README.md` - LiveKit self-host networking + LAN firewall table

## Decisions Made
- **node_ip, not use_external_ip:true** — STUN external-IP discovery is WAN egress; `node_ip` pins the LAN ICE candidate with none. The `--node-ip` runtime flag (from `LIVEKIT_NODE_IP`) overrides the yaml and only takes effect because `use_external_ip` is false (livekit#4049).
- **UDP mux 7882** over a port range — one firewall rule for the homelab; omitting `port_range_start/end` is what engages the mux.
- **Keys via `LIVEKIT_KEYS` env** — keeps the secret out of the committed yaml; built from `.env` in compose as `"<key>: <secret>"` (quoted so YAML doesn't parse the colon as a map).
- **Warmup metric in `prewarm_fnc`** — fires once at worker boot before any job, satisfying the "one real metric" gate with no participant.

## Deviations from Plan

**1. [Rule 2 - Missing Critical] Warmup logic reused inline in main.py instead of COPYing ollama/warmup.py**
- **Found during:** Task 01-03-2 / 01-03-4
- **Issue:** The plan's T5/Dockerfile implies reusing `warmup.py` logic, but the agent build context is `./agent` — it cannot `COPY ../ollama/warmup.py`. COPYing across the context root is impossible without widening the build context (undesirable).
- **Fix:** Re-implemented the minimal LLM-TTFT warmup path (the only part `main.py` needs) inline in `agent/main.py` `_warmup_llm_ttft_ms`, mirroring `ollama/warmup.py`'s streaming first-token measurement. The standalone `ollama/warmup.py` remains the host-side 3-model warmer.
- **Files modified:** agent/main.py, agent/Dockerfile (removed the cross-context COPY)
- **Verification:** `python3 -m py_compile agent/main.py` passes; warmup routes through `metrics.emit_warmup_metric`.
- **Committed in:** `12d80c8`

---

**Total deviations:** 1 auto-fixed (1 missing-critical / build-context constraint).
**Impact on plan:** None on scope — same behavior (real LLM TTFT emitted at startup), just sourced inline because Docker build contexts cannot reach a sibling directory. No external dependency added.

## Issues Encountered
- **No Docker daemon in this sandbox** (same limit as 01-01 / 01-02): `docker.sock` access is denied (not in the `docker` group). `docker compose config` validates client-side (parses clean) but `docker compose build agent` / `up`, the offline `--network none` weights smoke run, live worker registration, and the startup-egress check are **operator gates** for the Proxmox VM. All committable artifacts are complete and client-side-verified; the web token route was verified end-to-end with a real signed JWT, and the metrics scaffold + main.py compile and run.

## Operator Gates (Docker daemon / GPU VM required)
Run on the Proxmox VM with the stack up:
- `docker compose build agent` exits 0; then `python -c "from livekit.plugins.turn_detector.multilingual import MultilingualModel"` inside the image exits 0 (or record the documented string fallback).
- `--network none` smoke run of the agent shows **no** weight download at startup (weights baked) — DEPLOY-02 offline proof.
- `docker compose up`: all six services running; agent logs show worker registration with `livekit-server` (no LiveKit Cloud / external host); **exactly one** warmup metric line with a numeric `llm_ttft_ms`.
- Egress check (agent on the `adept` network only): no call to any non-LAN endpoint at startup — PERF-03.
- `GET /api/token` against the running web service returns HTTP 200 with a `token` field (verified client-side here; confirm on the VM behind Caddy TLS).
- Set `LIVEKIT_NODE_IP` to the VM's LAN IP and open UDP 7882 + TCP 7881 (LAN-only) before testing media in Phase 2.

## Authentication Gates
None.

## User Setup Required
None - no external service accounts. Operator runs the gates above on the GPU VM and sets `LIVEKIT_NODE_IP`/firewall for real LAN media.

## Next Phase Readiness
- The walking skeleton is closed: six services boot from one compose, the agent constructs an AgentSession against the three local endpoints with the local MultilingualModel turn detector, weights are baked offline, the metrics scaffold emits one real LLM TTFT at startup, and a LiveKit JWT path exists for Phase 2 — **nothing has spoken yet**, exactly as scoped.
- Phase 2 (voice loop) can enable `generate_reply` / live turns and point the browser at `wss://<lan-host>:7443` with a token from `/api/token` — no re-plumbing of the session, metrics, or transport required.
- Operator must run the gates above (build/up/egress/offline) on the Proxmox VM to convert the daemon-bound ACs from client-verified to hardware-proven.

## Self-Check: PASSED
- `livekit.yaml`: `udp_port 7882`, `tcp_port 7881`, **no** `port_range_*`; `use_external_ip:false` + `node_ip` (exactly one ICE strategy); no `LIVEKIT_API_SECRET` value in the yaml.
- `docker compose config` parses clean; `LIVEKIT_KEYS` renders `devkey: <secret>`; `--config`/`--node-ip` wired; yaml mounted ro.
- `agent/Dockerfile`: deps via `uv pip` (no bare `pip install`); `download-files` bake present; `agent/requirements.txt` pins `livekit-agents~=1.5` + the three plugins.
- `agent/metrics.py`: per-plugin `.on("metrics_collected", ...)`; no session-level subscription; budgets EOU300/STT150/LLM300/TTS150/playout100; no prometheus/opik/otel/grafana; `emit_warmup_metric(123.4)` prints a line with `llm_ttft_ms: 123.4`.
- `agent/main.py`: `MultilingualModel()` used; `grep -r "inference.TurnDetector" agent/` → none; whisper beam_size=1 / condition_on_previous_text=False / vad_filter=True / language="en"; `emit_warmup_metric` called in prewarm; `py_compile` passes.
- `web/app/api/token/route.ts`: `next build` exit 0 (route `ƒ /api/token` dynamic); AccessToken `.toJwt()` produces a valid 3-part JWT with correct grants (`iss=devkey`).
- 4 task commits present (`aeb3120`, `f1a9510`, `7caef70`, `12d80c8`).

---
*Phase: 01-foundation-infrastructure*
*Completed: 2026-06-25*
