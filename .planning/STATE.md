---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Local-First Pipeline Swap + Avatar
current_phase: 11
current_phase_name: consumer-gpu-deployment-part-e
status: planned-ready-to-execute
stopped_at: Phase 11 discussed + planned (11-01 gpu-doctor+up.sh, 11-02 README rewrite + compose verify + DEPLOY-VERIFY); not yet executed
last_updated: "2026-06-26T22:15:00.000Z"
last_activity: 2026-06-26
last_activity_desc: "Phase 11 (Consumer-GPU Deployment / Part E) DISCUSSED (4 grey areas all Accept-Recommended) + PLANNED. 11-CONTEXT.md + 2 plans written: 11-01 = scripts/gpu-doctor.sh (ordered nvidia-smi→toolkit→CUDA12.8-floor→16GB-VRAM-floor chain, non-blocking ADVISE, copyable env snippet, never mutates .env) + thin ./up.sh wrapper (doctor→docker compose up, SKIP_DOCTOR=1) + scripts/test_gpu_doctor.sh PATH-shim harness; 11-02 = README Proxmox two-layer rewrite→one Consumer-GPU section (keep one-line VM note) + scripts/test_compose_topology.sh (docker compose config default vs --profile stt-gpu) + 11-DEPLOY-VERIFY.md (7 unsigned operator gates). Default up stays CPU-ONNX-safe; ollama/kokoro GPU-required (documented limitation). Next: execute 11-01 then 11-02."
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 6
  completed_plans: 6
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-25)

**Core value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.
**Current focus:** Phase 11 — consumer-gpu-deployment-part-e (PLANNED, ready to execute)

## Current Position

Phase: 11 (consumer-gpu-deployment-part-e) — DISCUSSED + PLANNED, not yet executed
Plan: 0 of 2 executed (11-01 gpu-doctor.sh + ./up.sh wrapper + test harness, 11-02 README Consumer-GPU rewrite + compose-topology verify + 11-DEPLOY-VERIFY.md). All 4 discuss grey areas = Accept-Recommended. Next: execute 11-01 → 11-02.

### (prior) Phase 10 — vram-aware-stt-placement-part-c — CODE-COMPLETE, operator GPU gate pending
Plan: 2 of 2 (10-01 ONNX CPU backend + runtime switch + nemo-stt-cpu service, 10-02 placement resolver + agent wiring) — both executed, reviewed, fixed, verified
Status: CODE-COMPLETE. `STT_RUNTIME=gpu|cpu` dispatch behind shared callables (stt/backend_common.py tag-free + backend_nemo.py GPU + backend_onnx.py CPU ORT 3-graph cache loop w/ numpy-only 128-band Slaney mel incl. NeMo per_feature normalization). New `nemo-stt-cpu` Compose service is the DEFAULT (host 8001, no GPU reservation); GPU `nemo-stt` gated behind the `stt-gpu` profile so the unused image doesn't occupy VRAM. `agent/placement.py` pure `resolve_stt_placement(llm_choice, env)` — STT_FORCE_CPU short-circuits FIRST, then STT_HEADROOM_MEASURED gate, worst-case-LLM headroom table (E2B 7408MB / E4B 8912MB vs 16GB−1GB) returns the SAME decision for fast/better (no mid-session thrash), defaults CPU when unmeasured, never raises. Called ONCE in build_session; model.update RPC + VAD/turn_handling + metrics.py untouched. Quant honesty: int8-dynamic ~0.88GB reproducible default; int4-kquant ~0.67GB (literal STT-05) operator-gated stretch. Review: 1 Critical (CPU backend SystemExit-at-import via STT_MODEL coupling) + 1 High (mel per_feature normalization) FIXED, +3 Medium (incl. M5 compose profiles) +3 Low; M2/M3 mel sub-items (STFT center, Hann periodicity) flagged for operator Gate 2. 10-VERIFICATION.md verdict: code-complete with operator gate pending. STT-05/06/07 satisfied-in-code. 8 GPU gates UNSIGNED in 10-PLACEMENT-VERIFY.md.
Last activity: 2026-06-26 — Phase 10 executed (Waves 1+2 + review fixes). Next: discuss+plan+execute Phase 11 (Part E — Consumer-GPU Deployment).

### (prior) Phase 09 — nemotron-streaming-asr-part-b — CODE-COMPLETE, operator GPU gate pending
Plan: 2 of 2 (09-01 server/compose, 09-02 plugin/agent wiring) — both executed
Status: CODE-COMPLETE. faster-whisper fully removed (compose service, agent code, warmup.py, vram-validate.sh, README). New `nemo-stt` FastAPI websocket NeMo streaming server (stt/server.py, Dockerfile, requirements) keep-resident, /health-gated; `NemoSTT`/`NemoSpeechStream` true streaming plugin (agent/nemo_stt.py) wired into build_session replacing openai.STT. The load-bearing STTMetrics emit in `_emit_final` keeps stt_ms non-null. att_context_size knob (STT_ATT_CONTEXT_SIZE default [56,3]) + cyber-vocab fine-tune hook. Code review: 1 Critical (decoder state not reset per turn) + 2 High (WS frame robustness) FIXED, +4 Medium +2 Low; 2 Low skipped out-of-scope. 09-VERIFICATION.md verdict: code-complete with operator gate pending (STT-01..04 satisfied-in-code, PERF-04 operator-gated). Single-source no-hardcoded-tag, metrics.py-untouched, endpoint-authority-unchanged invariants all HOLD. 6 GPU gates UNSIGNED in 09-STT-VERIFY.md (status pending-operator).
Last activity: 2026-06-26 — Phase 9 executed (commits 7efb550..3a6d849). Next: discuss+plan+execute Phase 10 (Part C — VRAM-aware STT placement).

## Performance Metrics

**Velocity:**

- Total plans completed: 11
- Average duration: —
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 2 | 3 | - | - |
| 03-persona-layer | 2 | - | - |
| 05 | 1 | - | - |
| 06 | 2 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01-01 | 22 min | 4 tasks | 17 files |
| Phase 01 P01-02 | 18 min | 4 tasks | 6 files |
| Phase 01 P01-03 | 7 min | 4 tasks | 13 files |
| Phase 02 P01 | 12 min | 5 tasks | 8 files |
| Phase 02 P02-02 | 9 min | 3 tasks | 1 files |
| Phase 02 P02-03 | 18 | 4 tasks | 3 files |
| Phase 03 P03-01 | 12 min | 2 tasks | 2 files |
| Phase 03 P02 | 12 min | 4 tasks | 3 files |
| Phase 04 P04-01 | 12 min | 5 tasks | 7 files |
| Phase 04 P04-02 | 10 min | 4 tasks | 4 files |
| Phase 04 P04-03 | 8 min | 3 tasks | 3 files |
| Phase 05 P05-01 | 5 min | 3 tasks | 3 files |
| Phase 06 P01 | 12 min | 3 tasks | 4 files |
| Phase 06 P02 | 9 min | 3 tasks | 3 files |
| Phase 08 P01 | 18 min | 4 tasks | 4 files |
| Phase 08 P02 | 12 min | 3 tasks | 3 files |
| Phase 09 P01 | — | 5 tasks | 5 files |
| Phase 09 P02 | — | 4 tasks | 7 files |
| Phase 10 P01 | — | 7 tasks | 9 files |
| Phase 10 P02 | — | 6 tasks | 6 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 1]: Pin `gemma4:e4b-it-q4_K_M` (smaller quant for the tight 16GB floor) with thinking/reasoning mode OFF
- [Phase 1 / 01-02]: Model-pin RESOLVED — fallback ladder rung 1 wins. `gemma4:e4b-it-q4_K_M` is a real published Ollama tag: `ollama pull` advanced past `pulling manifest` into the 9.6GB blob on the RTX 5090 host (a non-existent tag errors instantly at the manifest step). PERF-02's literal tag is CONFIRMED VERBATIM — not superseded. Pinned to `.env` OLLAMA_MODEL; `ollama/pull-and-pin.sh` encodes the ladder for the operator's container-side full pull.
- [Phase 1]: Self-host LiveKit from day one including the local `MultilingualModel` turn detector (deprecated cloud path avoided)
- [Phase 3]: Establish frozen-prefix prompt layout `[persona] + [KB] + [history] + [turn]` before KB depends on it
- [Phase 3]: Persona knobs render fixed-string fragments (not interpolated numbers) → byte-stable frozen prefix for the Phase-4 KB cache; live hot-swap via `persona.update` RPC verified end-to-end via CDP
- [Phase 3]: Stack runs from baked Docker images (no source mount) — a phase touching agent/web MUST `docker compose build web agent && up -d` before live verification (stale-deploy bug + missing `persona.py` in agent/Dockerfile COPY both surfaced during UAT, fixed in dd17ffa)
- [Phase 4]: Inline-and-cache KB (distill once, inject once) — not per-turn RAG — to protect the flat-TTFT invariant
- [Phase 01]: 01-03: LiveKit ICE pinned via node_ip + --node-ip flag (use_external_ip:false) — STUN discovery is WAN egress; udp mux 7882 single firewall rule. Keys via LIVEKIT_KEYS env, not committed. Turn detector = local MultilingualModel, weights baked offline. Metrics scaffold subscribes per-plugin metrics_collected (session-level deprecated); warmup LLM TTFT emitted in worker prewarm as the one real metric. — Local-first WebRTC requires pinning the advertised IP (node_ip) instead of STUN discovery; bake model weights at build for offline startup.
- [Phase 02]: Phase 2 / 02-02: thinking-OFF on live LLM turns plumbed via with_ollama(reasoning_effort="none") — Ollama /v1 ignores native think but maps reasoning_effort=none to internal Think=false. Path (a) chosen over a Modelfile <think> strip: no Modelfile change, tag still resolves from OLLAMA_MODEL. preemptive_generation NOT passed (livekit not importable in sandbox — introspection deferred to VM). Greeting via session.generate_reply after session.start. — Keeps the no-second-hardcoded-LLM-tag prohibition; avoids unverified-kwarg risk per sandbox conservative-path guidance.
- [Phase ?]: Phase 2 / 02-03: endpointing pinned on the non-deprecated turn_handling dict (dynamic, min_delay 0.3s) with MultilingualModel nested; the plan's claimed two-incompatible-surfaces TypeError BLOCKER is disproven by reading livekit-agents@1.5.0/1.5.17/1.6.4 source (direct kwargs are deprecated-but-migrated, no TypeError). Barge-in tuned (interruption min_duration 0.3s + resume_false_interruption); Silero VAD activation_threshold 0.5->0.65. Per-turn metrics consolidated via a speech_id-keyed buffer computing real e2e_ms (no LiveKit v2v field exists) + rolling P50/P95. Client-side AEC is the sole echo defense (headphones hint added); no server noise-cancellation plugin.
- [Phase 04]: num_ctx kept at 8192: documented worst case (persona+brief+history+headroom ~8190) fits; Ollama pre-allocates num_ctx as VRAM so no inflation. Bump gated on operator Proof-C measurement. — KB-05/PERF-02 keystone proof coupled the num_ctx pin to BRIEF_TOKEN_BUDGET; flat-TTFT + cache-hit + KB-load VRAM are deferred VM operator gates in 04-KB-VERIFY.md.
- [Phase 05]: 05-01: History windowing is item-list-only (HistoryWindowAgent.on_user_turn_completed → truncate(max_items=HISTORY_MAX_ITEMS=20) + update_chat_ctx); NEVER update_instructions, so the frozen persona+KB prefix is untouched by construction. Window-only is the MVP floor (no summarization). Exact N + flat-TTFT proof are deferred VM gates in 05-HISTORY-VERIFY.md. — SESS-05 keystone: bounded history → flat per-turn TTFT (Pitfall 10) without busting the KB prefix cache (Pitfall 7).
- [Phase 08]: 08-02: Two-model pull/pin generalizes `pull-and-pin.sh` to named `FAST_LADDER`/`BETTER_LADDER` + a parameterized `write_resolved_tag <key> <tag>`, pinning `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` (+ `OLLAMA_MODEL` Fast back-compat alias). `ollama/verify-build.sh` is the standalone pull-time LLM-05 gate: Check A asserts STRUCTURAL chat-template sanity (role-turn markers + diff vs stock Gemma — catches a malformed-but-nonempty template) and Check B scans a think=false `/api/generate` stream for the artifact superset (`<think>`/`<|channel|>`/`<|analysis|>`/…) — an accepted equivalent mirror of the live `/v1 reasoning_effort=none` path. The persona stays the SOLE guardrail (UNCHANGED); 08-LLM-VERIFY.md Gate B red-teams it and ESCALATES a FAIL rather than editing it. All GPU/live gates are deferred operator gates in 08-LLM-VERIFY.md. — Per-build verification + per-model fallback ladders keep a misbehaving abliterated build from leaking reasoning markers into TTS.
- [Phase 06]: 06-02: Rubric-structured critique (4 qualitative dims, no numeric score) + slow-speech interview endpointing (min_delay 0.7/max_delay 5.0, mechanism-3 single session profile, [VM-INTROSPECT] for the switch setter). The E4B critique-depth blocker (line 101) is now GATED by Gate A (scripted strong-vs-weak discrimination) in 06-INTERVIEW-VERIFY.md but NOT yet discharged — deferred operator gate; FAIL triggers the documented 24GB OLLAMA_MODEL fallback (no 24GB code in v1). — Prompt structure compensates for the 4B model depth; the strong-vs-weak gate is the operator-verifiable bar the STATE.md blocker demands; over_budget:[eou] on interview turns is expected.

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 / 01-02]: Flash-attn allowlist + VRAM-under-load are now INSTRUMENTED, not assumed — `scripts/vram-validate.sh` warms all 3 models, drives concurrent load, asserts peak used-VRAM < 16384 MB (with 1GB headroom), greps ollama logs and FAILS LOUDLY if q8_0 silently falls back to F16, and asserts exactly 3 GPU processes (no embedder/vector store). The empirical run is an OPERATOR GATE: this sandbox has no Docker daemon (same limit as 01-01), so the full-stack co-residency measurement must be captured on the Proxmox VM. Rung-1 tag itself was verified against the real RTX 5090 host Ollama (manifest resolved). Record peak VRAM + q8_0-engaged result here when the operator runs the script on the VM.
- [Phase 6]: E4B critique depth unproven — gate on a strong-vs-weak answer check; keep 24GB larger-model swap behind LiveKit's interface
- [Phase 8 / 08-02]: Operator [VM-*] gates PENDING in `08-LLM-VERIFY.md` — run on the Proxmox VM + RTX 5090 after `docker compose build web agent && up -d` and `./ollama/pull-and-pin.sh`: Gate 1 [VM-INTROSPECT] swap-surface probe, Gate A (LLM-05 `verify-build.sh` both tags), Gate B (LLM-06 persona red-team), Gate C (live Fast↔Better swap + num_predict cap), Gate D (per-tag q8_0→F16 re-check via `vram-validate.sh`). marked passed by the executor.
- [RESOLVED 2026-06-26] Phase 8 Gate A gemma4 load blocker: pinned Ollama 0.6.8 could not load the gemma4 architecture (both community tags + stock gemma4:e2b/e4b all 500'd: `unknown model architecture: 'gemma4'`). FIXED by bumping `docker-compose.yml:47` `ollama/ollama:0.6.8 → 0.30.10` (user-approved option 1; Ollama 0.30+ ships gemma4/GGUF support). Model volume survived; agent re-registered. Post-bump all 3 gemma4 tags load + serve cleanly on `/v1`, multi-turn role tracking verified, think=false artifact scan CLEAN on all 3. q8_0 KV + flash-attn re-confirmed engaged on 0.30.10 (no silent F16 fallback). Gate 1 PASSED. Gates B/C/D now runnable (operator-pending).
- [RESOLVED 2026-06-26 — Phase 8 follow-up] `verify-build.sh` Check A was OBSOLETE for gemma4 on Ollama 0.30: `ollama show --template` returns bare `{{ .Prompt }}` (no role-turn markers) for ALL gemma4 tags incl. official stock — the engine applies the chat template internally — so the old scrape would false-FAIL every gemma4 build. FIXED: Check A rewritten to a BEHAVIORAL role-tracking probe (deterministic 3-turn `/v1` recall of token `ZEBRA-7`); broken role rendering → failed recall → FAIL. All 3 tags PASS; negative controls (non-recall answer, nonexistent tag) FAIL cleanly via a hardened JSON parser. Check B (artifact scan) unchanged + still load-bearing.
- [Phase 8 SAFETY — Gate B FAIL → RISK ACCEPTED 2026-06-26] The UNCHANGED Cybersecurity-Trainer persona is NOT a sufficient content guardrail against either abliterated model. Driven through the live `/v1` + `reasoning_effort=none` path with the rendered default persona as system prompt, ALL 4 boundary shapes FAILED on BOTH tags. Fast (`evalengine/unbound-e2b`) is worst — emits concrete actionable detail unprompted incl. a NAMED-TARGET intrusion path (Mimikatz/Pass-the-Hash/LSASS). Better (`defyma85/...heretic`) Socratically engages every ask incl. named-target. **DECISION: ACCEPT RISK, document only** — local single-user training tool, operator == user, abliterated models are an intentional unrestricted-coaching choice. Persona stays UNCHANGED, no guard model, no filter; the tags remain. KNOWN ACCEPTED LIMITATION: models will produce actionable attack guidance when asked. Revisit ONLY if the deployment model changes (multi-user / hosted / shared). Recorded in 08-LLM-VERIFY.md Gate B. NOT an open action item.
- [RESOLVED 2026-06-26 — Phase 8 Gate C] LLM-04 num_predict cap was a SILENT NO-OP on Ollama 0.30: shipped code set `_opts.max_completion_tokens=256` but Ollama's `/v1` ignores `max_completion_tokens` (only honors top-level `max_tokens`). Fast tag masked it (55-tok replies); verbose Better tag exposed it (1892 tok uncapped). FIXED in `agent/main.py`: set `_opts.extra_body={"max_tokens": LIVE_NUM_PREDICT_CAP}` (plugin forwards extra_body verbatim; survives the model swap). Agent rebuilt + re-registered; both tags now truncate at 256.
- [RESOLVED 2026-06-26 — Phase 8 Gate D] Two `scripts/vram-validate.sh` fixes needed for the bumped engine: (1) positive KV matcher only knew 0.6.x phrasing — extended to accept 0.30.x `flash_attn = enabled` / `K (q8_0)`/`V (q8_0)` / `--cache-type-k q8_0` runner flags; (2) LATENT pipefail/SIGPIPE bug surfaced by the larger 0.30 logs — `echo "$logs" | grep -q` under `set -o pipefail` read a TRUE match as a MISS (grep closes pipe → echo SIGPIPE 141 → pipefail propagates); switched to here-string `grep <<< "$logs"`. Both tags now PASS Gate D: Fast 7408 MB, Better 8912 MB, q8_0 engaged, 3 GPU procs (after `restart ollama` between tags to clear keep_alive=-1 pinned models).
- [RESOLVED 2026-06-26 — Phase 8 whisper STT cold-start, commit 06920c5] Gate C live retry: agent stuck at "Listening" after talking, despite a healthy WebRTC connect (signal connected, track published). Agent logs showed `stt_ms: null` on every turn — no transcription. ROOT CAUSE: `fedirz/faster-whisper-server` defaults to `WHISPER__TTL=300`, OFFLOADING the `Systran/faster-whisper-large-v3` model after 300s idle and paying a ~60s cold reload on the next utterance; the speaker's first turn is silently dropped during reload (the earlier `docker compose up` that removed the proxy had restarted whisper, which then idled out). FIXED: added `WHISPER__MODEL` + `WHISPER__TTL=-1` to the whisper service in docker-compose.yml — pins the model resident forever (mirrors `OLLAMA_KEEP_ALIVE=-1`), correct for a single-user local tool. Confirmed via log `is idle, not unloading`. Operator re-ran Gate C successfully ("it is working now"). Lesson saved (lsn_ed652180c3212c1a). NOT an open action item.
- [RESOLVED 2026-06-26 — Phase 8 SHIPPED] All five deferred operator gates signed on the RTX 5090. Final verdict PASS: Gate 1 (swap-surface) PASS, Gate A (verify-build both tags) PASS, Gate B (persona red-team) FAIL→RISK ACCEPTED (document-only), Gate C (live mid-TTS swap + cap) PASS, Gate D (q8_0 KV both tags) PASS. `08-VERIFICATION.md` status human_needed→passed (resolution section appended; original audit body untouched), `08-UAT.md` status testing→passed (4 passed / 1 risk-accepted / 0 blocking gaps). Local-only repo (no `origin` remote) so `/gsd-ship`'s PR path N/A — shipped via state-close. STATE frontmatter: status executing→shipped, completed_phases 1→2, percent 17→33. NEXT: `/gsd-plan-phase 9` (v1.1 Part B — Nemotron STT) per build order 8→9→10→11→12→13.
- [Phase 9 / 09-02] Operator GPU gates PENDING in `09-STT-VERIFY.md` (status: pending-operator) — run on the consumer RTX 5090 after `docker compose build nemo-stt agent && up -d`: Gate 1 `conformer_stream_step` signature confirmation vs in-container NeMo; Gate 2 Blackwell sm_120 torch (no "no kernel image" — Kokoro-class); Gate 3 live growing-interim + native PnC + ~100ms finalize + `stt_ms` non-null; Gate 4 voice-to-voice P50<1.0s (PERF-04 headline); Gate 5 RNNT stall watchdog no-premature-FINAL on a run-on; Gate 6 VRAM co-residency (3 procs ollama/nemo-stt/kokoro under 16GB with +2.4GB model). NONE marked passed by the executor. `stt_ms` semantics PINNED = finalize latency (flush→final). Sandbox has no GPU/Docker/NeMo so all 6 are legitimately deferred (mirrors Phase 8 pre-operator-sign).
- [Phase 9 design note] Endpoint authority UNCHANGED: Silero VAD + MultilingualModel turn detector remain sole finalize authority; the nemo-stt server NEVER auto-finalizes (stall watchdog recycles decoder state, no FINAL) — FINAL only on the agent's `flush` (turn-detector-driven). Per-turn decode state resets on flush (C1 fix) so each FINAL is that turn only, not cumulative-session.
- [Phase 10 / 10-02] Operator GPU gates PENDING in `10-PLACEMENT-VERIFY.md` (status: pending-operator, 8 gates UNSIGNED) — run on the consumer RTX 5090 after `docker compose build nemo-stt-cpu agent && up -d` (and `--profile stt-gpu` for the GPU cells): Gate 1 ONNX export(cache_support=True)+int8 quant size ~0.88GB (+int4-kquant ~0.67GB stretch); Gate 2 MEL-PARITY (HIGHEST RISK — baked filterbank.bin vs NeMo preprocessor incl. per_feature norm / STFT center / Hann periodicity / log-offset, WER within ~0.17% abs); Gate 3 >6× realtime CPU under contention; Gate 4 byte-identical WS contract GPU vs CPU; Gate 5 placement resolves once / no mid-session thrash on Fast↔Better swap; Gate 6 STT_FORCE_CPU pins CPU both LLMs; Gate 7 the 4-cell {E2B,E4B}×{GPU,CPU} co-residency matrix at KB-load peak (q8_0, peak < total−1GB); Gate 8 safe-default flip (only flip off global CPU-ONNX if E4B+GPU-STT+Kokoro proves to co-fit). NONE marked passed by the executor. KOKORO_MB in the placement table is an UNMEASURED placeholder — the GPU branch stays gated behind STT_HEADROOM_MEASURED until Gate 7 pins it.
- [Phase 10 design note] CPU-ONNX is the SHIPPED SAFE DEFAULT (STT_FORCE_CPU=1, picker VRAM-safe out of the box); GPU `nemo-stt` is behind the `stt-gpu` compose profile so the default deploy boots only the ~0.67-0.88GB off-GPU CPU STT. int8-dynamic (~0.88GB, stock quantize_dynamic, encoder-only) is the reproducible default; int4-kquant (~0.67GB literal STT-05) is an operator-gated stretch (custom k-quant + MHA-fusion, not stock — export_onnx.py SystemExits rather than fakes it). C1 fix: backend_onnx imports the tag-free `stt/backend_common.py` (NOT backend_nemo) so the CPU server starts without STT_MODEL set.
- [RESOLVED 2026-06-26 — deployment simplification, commit 615a6e7] Gate C live-test surfaced an ICE/WebRTC connect failure in Firefox ("could not establish pc connection") even on-box. Root cause PROVEN via headless Chromium over CDP (Chromium connected over the identical stack, Firefox did not): **Firefox refuses loopback ICE by default** (`media.peerconnection.ice.loopback=false`) and silently drops the server's `127.0.0.1` host candidate. Initial fix advertised the LAN IP — but that's wrong for a local-first tool. FINAL FIX (user-directed): **removed the TLS reverse proxy (Caddy + mkcert) entirely from the default stack.** The whole TLS chain existed ONLY to give the mic a secure context over `https://<lan-ip>`; `localhost` is ALREADY a secure context, so mic + WebRTC work over plain `http://localhost` with NO certs. `proxy` service deleted (docker-compose.yml, 7→6 services); `NEXT_PUBLIC_LIVEKIT_URL` → `ws://localhost:7880`; `livekit.yaml node_ip` back to `127.0.0.1`. mkcert/Caddy reframed as OPTIONAL for serving OTHER LAN devices (`certs/README.md`, `proxy/Caddyfile`, README "Serving other LAN devices (optional TLS)"). Verified end-to-end via CDP against `http://localhost:3000`: ICE paired on `ws://localhost:7880`, agent joined room, TTS reply generated, all on the RTX 5090. Default install is now `cp .env.example .env && docker compose up` → open `http://localhost:3000` in Chromium. KNOWN: Firefox local use still needs the `about:config` loopback pref (we recommend Chromium instead); the Firefox-global pref I briefly set was reverted on user direction. Also bumped livekit-server v1.10.0→v1.10.1 (v1.10.0 mis-formats the embedded-TURN NodeIP URL). NOT an open action item.

## Deferred Items

Acknowledged at v1.0-rc1 close (2026-06-26) and carried into Phase 7 / v1.0:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| requirement | SESS-01 new session | Pending (Phase 7) | v1.0-rc1 |
| requirement | SESS-02 reset session | Pending (Phase 7) | v1.0-rc1 |
| requirement | SESS-03 end session (clear KB) | Pending (Phase 7) | v1.0-rc1 |
| requirement | SESS-04 transcript export | Pending (Phase 7) | v1.0-rc1 |
| requirement | REL-01 mic-denial prompt | Pending (Phase 7) | v1.0-rc1 |
| requirement | REL-02 garbled-STT reprompt | Pending (Phase 7) | v1.0-rc1 |
| uat | Phase 02 UAT (0 pending scenarios) | passed | v1.0-rc1 |
| uat | Phase 04 UAT (0 pending scenarios) | gaps_resolved | v1.0-rc1 |
| verification | KB/history/interview/latency VM operator gates | Documented runbooks, unsigned | v1.0-rc1 |

## Session Continuity

Last session: 2026-06-26T21:30:00.000Z
Stopped at: Phase 10 code-complete (10-01 + 10-02 executed, reviewed, fixed, verified); 10-PLACEMENT-VERIFY.md pending-operator
Resume file: None

## Operator Next Steps

- v1.1 roadmap created (Phases 8-13). The unstarted v1.0 Phase 7 is SUPERSEDED — its SESS/REL/latency scope is folded into v1.1 Phase 13. Do not plan a standalone Phase 7.
- Phase 9 is CODE-COMPLETE. When on the RTX 5090: `docker compose build nemo-stt agent && docker compose up -d`, then walk the 6 gates in `09-STT-VERIFY.md` (expect the multi-GB nemo-stt image build + first conformer_stream_step signature confirmation). Sign each gate result table when passed.
- Phase 10 is CODE-COMPLETE. Default deploy is CPU-ONNX STT (`docker compose build nemo-stt-cpu agent && up -d`); add `--profile stt-gpu` for the GPU cells. Walk the 8 gates in `10-PLACEMENT-VERIFY.md` — Gate 2 (mel-parity) is the highest-risk; Gate 7 (4-cell co-residency matrix) pins KOKORO_MB and decides whether to flip the safe default off global CPU-ONNX.
- v1.1 build order: 8 (Part A LLM) ✓ → 9 (Part B Nemotron STT) ✓ code-complete → 10 (Part C placement) ✓ code-complete → 11 (Part E deployment) → 12 (Part D avatar, frontend-only/isolated) → 13 (rolled-in polish + final latency tuning).
- Two phases carry operator GPU gates verifiable only on the real consumer GPU: Phase 10 (16GB co-residency matrix, global-CPU-ONNX default) and Phase 13 (PERF-04 P50<1.0s for both LLMs).
- Operator-gated VM proofs from v1.0 remain (KB flat-TTFT, three-models-under-16GB, P50<1.0s, interview strong-vs-weak critique) — run the documented runbooks on the target GPU when available.
