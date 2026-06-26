---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Local-First Pipeline Swap + Avatar
current_phase: 08
current_phase_name: llm-speed-selector-part-a
status: executing
stopped_at: Completed 08-02-PLAN.md
last_updated: "2026-06-26T18:25:00.000Z"
last_activity: 2026-06-26
last_activity_desc: "Deployment simplified to zero-cert localhost (TLS proxy removed, 7→6 services); Phase 8 operator gates ran on RTX 5090 (Gates 1/A/D PASS, B risk-accepted, C cap fixed)"
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
  percent: 17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-25)

**Core value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.
**Current focus:** Phase 08 — llm-speed-selector-part-a

## Current Position

Phase: 08 (llm-speed-selector-part-a) — EXECUTING
Plan: 2 of 2
Status: All plans executed; operator gates RUN on RTX 5090 — Gate 1/A/D PASS, Gate B FAIL→risk-accepted, Gate C num_predict cap fixed (live mid-TTS swap sign-off still pending in 08-LLM-VERIFY.md). Deployment simplified to zero-cert localhost (commit 615a6e7).
Last activity: 2026-06-26 — Removed TLS reverse proxy; default install is now `docker compose up` → http://localhost:3000 (6 services, no certs)

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

Last session: 2026-06-26T06:32:57.364Z
Stopped at: Completed 08-02-PLAN.md
Resume file: None

## Operator Next Steps

- v1.1 roadmap created (Phases 8-13). The unstarted v1.0 Phase 7 is SUPERSEDED — its SESS/REL/latency scope is folded into v1.1 Phase 13. Do not plan a standalone Phase 7.
- Begin v1.1 by planning Phase 8 (LLM Speed Selector / Part A): `/gsd-plan-phase 8`
- v1.1 build order: 8 (Part A LLM) → 9 (Part B Nemotron STT) → 10 (Part C placement) → 11 (Part E deployment) → 12 (Part D avatar, frontend-only/isolated) → 13 (rolled-in polish + final latency tuning).
- Two phases carry operator GPU gates verifiable only on the real consumer GPU: Phase 10 (16GB co-residency matrix, global-CPU-ONNX default) and Phase 13 (PERF-04 P50<1.0s for both LLMs).
- Operator-gated VM proofs from v1.0 remain (KB flat-TTFT, three-models-under-16GB, P50<1.0s, interview strong-vs-weak critique) — run the documented runbooks on the target GPU when available.
