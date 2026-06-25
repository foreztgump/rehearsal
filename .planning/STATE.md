---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 02
current_phase_name: bare-voice-loop-mvp-gate
status: verifying
stopped_at: Completed 02-03-PLAN.md
last_updated: "2026-06-25T16:10:20.861Z"
last_activity: 2026-06-25
last_activity_desc: Phase 02 execution started
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 6
  completed_plans: 6
  percent: 29
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-24)

**Core value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.
**Current focus:** Phase 02 — bare-voice-loop-mvp-gate

## Current Position

Phase: 02 (bare-voice-loop-mvp-gate) — EXECUTING
Plan: 3 of 3
Status: Phase complete — ready for verification
Last activity: 2026-06-25 — Phase 02 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 3
- Average duration: —
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |

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

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 1]: Pin `gemma4:e4b-it-q4_K_M` (smaller quant for the tight 16GB floor) with thinking/reasoning mode OFF
- [Phase 1 / 01-02]: Model-pin RESOLVED — fallback ladder rung 1 wins. `gemma4:e4b-it-q4_K_M` is a real published Ollama tag: `ollama pull` advanced past `pulling manifest` into the 9.6GB blob on the RTX 5090 host (a non-existent tag errors instantly at the manifest step). PERF-02's literal tag is CONFIRMED VERBATIM — not superseded. Pinned to `.env` OLLAMA_MODEL; `ollama/pull-and-pin.sh` encodes the ladder for the operator's container-side full pull.
- [Phase 1]: Self-host LiveKit from day one including the local `MultilingualModel` turn detector (deprecated cloud path avoided)
- [Phase 3]: Establish frozen-prefix prompt layout `[persona] + [KB] + [history] + [turn]` before KB depends on it
- [Phase 4]: Inline-and-cache KB (distill once, inject once) — not per-turn RAG — to protect the flat-TTFT invariant
- [Phase 01]: 01-03: LiveKit ICE pinned via node_ip + --node-ip flag (use_external_ip:false) — STUN discovery is WAN egress; udp mux 7882 single firewall rule. Keys via LIVEKIT_KEYS env, not committed. Turn detector = local MultilingualModel, weights baked offline. Metrics scaffold subscribes per-plugin metrics_collected (session-level deprecated); warmup LLM TTFT emitted in worker prewarm as the one real metric. — Local-first WebRTC requires pinning the advertised IP (node_ip) instead of STUN discovery; bake model weights at build for offline startup.
- [Phase 02]: Phase 2 / 02-02: thinking-OFF on live LLM turns plumbed via with_ollama(reasoning_effort="none") — Ollama /v1 ignores native think but maps reasoning_effort=none to internal Think=false. Path (a) chosen over a Modelfile <think> strip: no Modelfile change, tag still resolves from OLLAMA_MODEL. preemptive_generation NOT passed (livekit not importable in sandbox — introspection deferred to VM). Greeting via session.generate_reply after session.start. — Keeps the no-second-hardcoded-LLM-tag prohibition; avoids unverified-kwarg risk per sandbox conservative-path guidance.
- [Phase ?]: Phase 2 / 02-03: endpointing pinned on the non-deprecated turn_handling dict (dynamic, min_delay 0.3s) with MultilingualModel nested; the plan's claimed two-incompatible-surfaces TypeError BLOCKER is disproven by reading livekit-agents@1.5.0/1.5.17/1.6.4 source (direct kwargs are deprecated-but-migrated, no TypeError). Barge-in tuned (interruption min_duration 0.3s + resume_false_interruption); Silero VAD activation_threshold 0.5->0.65. Per-turn metrics consolidated via a speech_id-keyed buffer computing real e2e_ms (no LiveKit v2v field exists) + rolling P50/P95. Client-side AEC is the sole echo defense (headphones hint added); no server noise-cancellation plugin.

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 / 01-02]: Flash-attn allowlist + VRAM-under-load are now INSTRUMENTED, not assumed — `scripts/vram-validate.sh` warms all 3 models, drives concurrent load, asserts peak used-VRAM < 16384 MB (with 1GB headroom), greps ollama logs and FAILS LOUDLY if q8_0 silently falls back to F16, and asserts exactly 3 GPU processes (no embedder/vector store). The empirical run is an OPERATOR GATE: this sandbox has no Docker daemon (same limit as 01-01), so the full-stack co-residency measurement must be captured on the Proxmox VM. Rung-1 tag itself was verified against the real RTX 5090 host Ollama (manifest resolved). Record peak VRAM + q8_0-engaged result here when the operator runs the script on the VM.
- [Phase 6]: E4B critique depth unproven — gate on a strong-vs-weak answer check; keep 24GB larger-model swap behind LiveKit's interface

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-25T16:10:03.975Z
Stopped at: Completed 02-02-PLAN.md
Resume file: None
