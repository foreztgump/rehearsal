---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Local-First Pipeline Swap + Avatar
current_phase: 08
current_phase_name: llm-speed-selector-part-a
status: executing
stopped_at: Completed 08-01-PLAN.md
last_updated: "2026-06-26T06:32:57.368Z"
last_activity: 2026-06-26
last_activity_desc: Phase 08 execution started
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 2
  completed_plans: 1
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-25)

**Core value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.
**Current focus:** Phase 08 — llm-speed-selector-part-a

## Current Position

Phase: 08 (llm-speed-selector-part-a) — EXECUTING
Plan: 2 of 2
Status: Ready to execute
Last activity: 2026-06-26 — Phase 08 execution started

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
- [Phase 06]: 06-02: Rubric-structured critique (4 qualitative dims, no numeric score) + slow-speech interview endpointing (min_delay 0.7/max_delay 5.0, mechanism-3 single session profile, [VM-INTROSPECT] for the switch setter). The E4B critique-depth blocker (line 101) is now GATED by Gate A (scripted strong-vs-weak discrimination) in 06-INTERVIEW-VERIFY.md but NOT yet discharged — deferred operator gate; FAIL triggers the documented 24GB OLLAMA_MODEL fallback (no 24GB code in v1). — Prompt structure compensates for the 4B model depth; the strong-vs-weak gate is the operator-verifiable bar the STATE.md blocker demands; over_budget:[eou] on interview turns is expected.

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 / 01-02]: Flash-attn allowlist + VRAM-under-load are now INSTRUMENTED, not assumed — `scripts/vram-validate.sh` warms all 3 models, drives concurrent load, asserts peak used-VRAM < 16384 MB (with 1GB headroom), greps ollama logs and FAILS LOUDLY if q8_0 silently falls back to F16, and asserts exactly 3 GPU processes (no embedder/vector store). The empirical run is an OPERATOR GATE: this sandbox has no Docker daemon (same limit as 01-01), so the full-stack co-residency measurement must be captured on the Proxmox VM. Rung-1 tag itself was verified against the real RTX 5090 host Ollama (manifest resolved). Record peak VRAM + q8_0-engaged result here when the operator runs the script on the VM.
- [Phase 6]: E4B critique depth unproven — gate on a strong-vs-weak answer check; keep 24GB larger-model swap behind LiveKit's interface

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
Stopped at: Completed 08-01-PLAN.md
Resume file: None

## Operator Next Steps

- v1.1 roadmap created (Phases 8-13). The unstarted v1.0 Phase 7 is SUPERSEDED — its SESS/REL/latency scope is folded into v1.1 Phase 13. Do not plan a standalone Phase 7.
- Begin v1.1 by planning Phase 8 (LLM Speed Selector / Part A): `/gsd-plan-phase 8`
- v1.1 build order: 8 (Part A LLM) → 9 (Part B Nemotron STT) → 10 (Part C placement) → 11 (Part E deployment) → 12 (Part D avatar, frontend-only/isolated) → 13 (rolled-in polish + final latency tuning).
- Two phases carry operator GPU gates verifiable only on the real consumer GPU: Phase 10 (16GB co-residency matrix, global-CPU-ONNX default) and Phase 13 (PERF-04 P50<1.0s for both LLMs).
- Operator-gated VM proofs from v1.0 remain (KB flat-TTFT, three-models-under-16GB, P50<1.0s, interview strong-vs-weak critique) — run the documented runbooks on the target GPU when available.
