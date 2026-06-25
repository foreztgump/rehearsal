---
status: passed
phase: 01-foundation-infrastructure
verified: 2026-06-25
requirement_ids: [PERF-02, PERF-03, DEPLOY-01, DEPLOY-02]
---

# Phase 01 — Foundation Infrastructure: VERIFICATION

**Verified:** 2026-06-25
**Phase goal:** Stand up the entire self-hosted stack (LiveKit server, agent worker, Ollama, Whisper, Kokoro, frontend shell) from one Docker Compose with GPU passthrough, corrected model pins, a defended VRAM budget, and a per-stage latency-metrics scaffold — before any voice flows.
**Phase requirement IDs:** PERF-02, PERF-03, DEPLOY-01, DEPLOY-02
**Verdict:** PASS (committed artifacts correctly implement all criteria; hardware/daemon gates are operator-gated per MVP-mode policy)

---

## Mode Note

This is an **MVP-mode** phase. Success criteria 1 and 3 require a live Docker daemon + GPU (Proxmox VM) that is **not available in the execution sandbox** (no `docker.sock` access; not in the `docker` group). Per the phase instructions, those are treated as **operator-gated human-verification items**, not failures, because the committed artifacts correctly implement them. The sandbox host does expose an RTX 5090 (`nvidia-smi -L`), and the rung-1 model tag was empirically pull-tested against the host Ollama.

---

## Requirement ID Cross-Reference (PLAN frontmatter ↔ REQUIREMENTS.md)

Every requirement ID claimed in the three plans is accounted for and present in REQUIREMENTS.md.

| Req ID | In plan frontmatter | REQUIREMENTS.md status | Accounted |
|--------|---------------------|------------------------|-----------|
| PERF-02 | 01-01, 01-02, 01-03 | Complete (rung 1 tag confirmed verbatim) | ✅ |
| PERF-03 | 01-01, 01-02, 01-03 | Complete | ✅ |
| DEPLOY-01 | 01-01 | Complete | ✅ |
| DEPLOY-02 | 01-03 | Complete | ✅ |

No dangling or unmapped IDs. REQUIREMENTS.md lines 67–70 mark all four `[x]` Complete; traceability table (lines 154–157) maps all four to Phase 1.

---

## Success Criteria

### 1. `docker compose up` brings up all services with GPU passthrough — ✅ PASS (artifact) / ⏳ operator gate (boot)

- `docker-compose.yml` declares **6 core services** (livekit-server, agent, ollama, whisper, kokoro, web) **+ caddy proxy** = 7 services.
- GPU reservation block (`driver: nvidia`, `count: all`, `capabilities: [gpu]`) on exactly the **3 model services** — `grep -c "capabilities:" docker-compose.yml` = **3** (ollama, whisper, kokoro). ✅
- All image tags pinned: livekit v1.10.0, ollama 0.6.8, kokoro v0.2.4, caddy 2.8; faster-whisper pinned by **sha256 digest** (no bare `:latest`). ✅
- Every published port binds to `${LAN_BIND_IP:-127.0.0.1}` — no `0.0.0.0`/WAN bind. ✅
- `agent` builds from `./agent` and `depends_on` livekit-server/ollama/whisper/kokoro. ✅
- **Operator gate (no daemon in sandbox):** `docker compose up` actually bringing all containers to running + `docker run --rm --gpus all nvidia/cuda:... nvidia-smi` — documented in README and each SUMMARY's Operator Gates section.

### 2. Ollama serves `gemma4:e4b-it-q4_K_M`, thinking off, keep_alive=-1, FLASH_ATTENTION=1, KV_CACHE_TYPE=q8_0 — ✅ PASS

- `.env`: `OLLAMA_MODEL=gemma4:e4b-it-q4_K_M` (rung-1 tag, empirically pull-verified as a real published tag on the RTX 5090 host). ✅
- `docker-compose.yml` ollama service: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_KEEP_ALIVE=-1` all present. ✅
- `ollama/Modelfile`: `num_ctx 8192`, `temperature 1.0`, `top_p 0.95`, `top_k 64`; thinking disabled via request-time `think: false` with the Ollama #15260 caveat documented. ✅
- No hardcoded gemma tag anywhere else — `grep -rn "gemma4:e4b-it-q4_K_M" docker-compose.yml agent/ web/` returns **empty**; everything consumes `OLLAMA_MODEL`. ✅
- `ollama/warmup.py` asserts no `<think>` preamble and emits a real `ttft_ms`. ✅
- **Operator gate:** live `ollama ps` showing the model resident with keep_alive forever and the q8_0 KV cache actually engaged (verified by `scripts/vram-validate.sh`).

### 3. STT + LLM + TTS co-resident within 16GB VRAM floor, no embedder/vector store — ✅ PASS (artifact) / ⏳ operator gate (nvidia-smi under load)

- `scripts/vram-validate.sh`: warms 3 models, drives concurrent load, samples `nvidia-smi --query-gpu=memory.used`, asserts **peak < 16384 MB** with headroom, **fails loudly** on silent q8_0→F16 fallback, and asserts **exactly 3 GPU processes** (no embedder/vector store). ✅
- No embedder or vector-store service exists in `docker-compose.yml` (confirmed — only the 3 model services + livekit/agent/web/proxy). ✅
- **Operator gate:** running the script on the Proxmox VM to record the empirical peak VRAM + q8_0-engagement result (resolves STATE.md blocker line 67).

### 4. LiveKit fully self-hosted incl. local MultilingualModel turn detector — no LiveKit Cloud / external egress — ✅ PASS

- `livekit.yaml`: self-host config with `port 7880`, `rtc.tcp_port 7881`, `rtc.udp_port 7882` (UDP mux, no port range), `use_external_ip: false` + `node_ip` (no STUN/WAN egress). ✅
- `agent/main.py` uses `MultilingualModel()` (local) — `grep -rn "inference.TurnDetector" agent/` returns **empty**. ✅
- `agent/Dockerfile` bakes weights offline via `python -m livekit.agents download-files`. ✅
- All model `base_url`s are in-stack (`http://ollama:11434`, `http://whisper:8000`, `http://kokoro:8880`). ✅
- Keys injected via `LIVEKIT_KEYS` env from gitignored `.env`; no secret committed in `livekit.yaml`. ✅
- Web token mint (`web/app/api/token/route.ts`) signs JWT server-side from dev key. ✅
- **Operator gate:** worker registration logs + `--network none` offline-weights smoke run + startup egress check on the VM.

### 5. Per-stage metrics scaffold emits VAD/STT/LLM/TTS timings — ✅ PASS

- `agent/metrics.py`: subscribes the **non-deprecated per-plugin** `metrics_collected` on llm/stt/tts/vad (`attach()`); handlers for all four stages (`_on_llm/stt/tts/vad_metrics`). ✅
- Budget constants present: EOU 300 / STT 150 / LLM_TTFT 300 / TTS_TTFB 150 / playout 100. ✅
- Emits one structured JSON line per turn (eou_ms, stt_ms, llm_ttft_ms, tts_ttfb_ms, e2e_ms) with rolling P50/P95 stub. ✅
- `emit_warmup_metric()` routes the real warmup LLM TTFT as the "one real metric" gate; wired in `prewarm()`. ✅
- **Local-only, no external telemetry** — `grep -Ein "prometheus|opik|otel|grafana" agent/metrics.py` returns **empty**. ✅

---

## must_haves Audit (per plan)

| Plan | must_have | Status |
|------|-----------|--------|
| 01-01 | DEPLOY-01: one `docker compose up` builds/boots all six services + GPU passthrough | ✅ artifact; ⏳ boot gate |
| 01-01 | PERF-03 (partial): LAN-only binds, no WAN forward, per-deploy LAN cert | ✅ |
| 01-01 | PERF-02 (enabler): GPU reservable by 3 model containers | ✅ |
| 01-01 | Secure context: `navigator.mediaDevices` probe (no getUserMedia) | ✅ (`grep getUserMedia web/app` empty) |
| 01-02 | PERF-02: pinned quant, thinking off, keep_alive=-1, flash-attn+q8_0, co-resident <16GB, no embedder | ✅ artifact; ⏳ nvidia-smi gate |
| 01-02 | PERF-03: model/inference local, in-stack endpoints only | ✅ |
| 01-02 | Open-risk closure: unverified tag resolved (rung 1 verbatim) + q8_0 allowlist instrument | ✅ |
| 01-02 | Requirements reconciliation: PERF-02 tag reconciled in STATE.md + REQUIREMENTS.md | ✅ |
| 01-03 | DEPLOY-02: self-hosted LiveKit + local MultilingualModel, weights baked, no Cloud | ✅ |
| 01-03 | PERF-03: agent + turn detector + inference local, no non-LAN egress, metrics local | ✅ |
| 01-03 | PERF-02 closure: AgentSession vs 3 local endpoints, no embedder added | ✅ |
| 01-03 | Criterion 5: metrics scaffold emits one real timing (warmup LLM TTFT) | ✅ |

---

## Static Verification Run (sandbox)

| Check | Result |
|-------|--------|
| `python3 -m py_compile agent/main.py agent/metrics.py ollama/warmup.py` | COMPILE OK |
| `bash -n scripts/vram-validate.sh` / `ollama/pull-and-pin.sh` | OK |
| `grep -c "capabilities:" docker-compose.yml` | 3 |
| Hardcoded gemma tag in compose/agent/web | none |
| `inference.TurnDetector` in agent/ | none |
| external telemetry in metrics.py | none |
| `getUserMedia` in web/app | none |
| session-level metrics_collected | none (per-plugin only) |
| `pip install` outside `uv pip` in Dockerfile | none |
| `git check-ignore .env` | `.env` (ignored) |
| Task commits | 12 feat/docs commits across 01-01/02/03 present |

---

## Claimed-vs-Actual (SUMMARY cross-check)

All files listed in the three SUMMARY `key-files.created/modified` blocks exist on disk with content matching the claims (docker-compose.yml, .env, .env.example, .gitignore, livekit.yaml, README.md, proxy/Caddyfile, certs/README.md, web/* shell + token route, agent/{Dockerfile,requirements.txt,main.py,metrics.py}, ollama/{Modelfile,pull-and-pin.sh,warmup.py}, scripts/vram-validate.sh). One documented deviation in 01-03 (warmup logic inlined in main.py instead of cross-context COPY of ollama/warmup.py) — verified present and behaviorally equivalent. No discrepancies found.

---

## Operator Gates (must run on the Proxmox VM before declaring hardware-proven)

1. `docker compose up` → all 6 services running; `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` prints the GPU table.
2. `./ollama/pull-and-pin.sh` → container-side pull of `gemma4:e4b-it-q4_K_M`; `ollama ps` shows resident, keep_alive forever.
3. `./scripts/vram-validate.sh` → exits 0, peak VRAM < 16384 MB, reports "q8_0 KV engaged", 3 GPU procs. Record peak + q8_0 result in STATE.md (closes blocker line 67).
4. Agent `--network none` smoke run shows no weight download (offline-capable); worker registers with livekit-server (no Cloud host in logs); exactly one warmup `llm_ttft_ms` line.
5. mkcert CA trusted on a LAN device → `https://<lan-ip>/` shows "secure context: mediaDevices defined".
6. Set `LIVEKIT_NODE_IP` to the VM LAN IP; open UDP 7882 + TCP 7881 (LAN-only).

---

## Conclusion

All five success criteria are satisfied at the committed-artifact level, and all four requirement IDs (PERF-02, PERF-03, DEPLOY-01, DEPLOY-02) are accounted for and consistent between PLAN frontmatter and REQUIREMENTS.md. The remaining checks are hardware/daemon operator gates, appropriately deferred per MVP-mode policy. **Phase 01 goal achieved.**
