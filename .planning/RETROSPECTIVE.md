# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0-rc1 — MVP Release Candidate

**Shipped:** 2026-06-26
**Phases:** 6 | **Plans:** 15 | **Tasks:** 56 | **Commits:** 112

### What Was Built
- Self-hosted six-service GPU Compose stack (LiveKit/Ollama/Whisper/Kokoro/agent/web), LAN-only, pinned `gemma4:e4b-it-q4_K_M` under a defended 16GB VRAM budget with a per-stage metrics scaffold.
- Fully streamed voice loop: open-mic VAD → semantic turn-detect → STT → LLM → first-sentence TTS, with instant barge-in and real per-turn P50/P95 voice-to-voice latency metrics.
- Live-editable persona (role/name/difficulty/verbosity/correction knobs/voice) hot-swapped in-session over a byte-stable frozen prefix via the `persona.update` RPC.
- Ephemeral KB: per-file upload → parse + size-guard → distill-once → inject-once into the cached frozen prefix (no per-turn RAG), plus aggregate-budget, atomic-ingest, and prompt-injection hardening.
- Sliding-window history behind the frozen prefix (`HistoryWindowAgent`) and a one-question-at-a-time Interview Mode with a four-dimension qualitative critique rubric.

### What Worked
- **Frozen-prefix discipline from Phase 3 onward.** Establishing the byte-stable `[persona]+[KB]+[history]+[turn]` layout before KB depended on it meant persona edits, KB injection, history capping, and interview-mode swaps all composed without ever busting the prefix cache.
- **Source-grounding API surfaces against tagged library source** (e.g., livekit-agents 1.5.0–1.6.4) disproved a claimed `turn_handling` TypeError blocker and avoided guessed-kwarg risk — reading the real source beat trusting the plan's assumption.
- **Vertical slices per plan** (ingest → parse → distill → verify) kept each plan independently reviewable and let UAT surface the GAP-1 4096-truncation bug before it shipped.

### What Was Inefficient
- **The silent 4096 `num_ctx` truncation** (default dropping the KB brief) wasn't caught until live Phase-4 UAT — a context-budget assertion at distill time would have surfaced it earlier than a gap-closure plan (04-04).
- **Roadmap/state drift:** Phase 4 sat at `[ ]` "awaiting UAT" in the roadmap phase-list while the progress table said `4/4 Complete`, and STATE.md velocity tables had inconsistent phase keys — manual reconciliation needed at milestone close.
- **Heavy reliance on operator-gated VM proofs:** the keystone claims (flat-TTFT, three-models-under-16GB, P50<1.0s, critique discrimination) are documented runbooks, not yet signed — verification debt carried into v1.0.

### Patterns Established
- **Off-hot-path-only LLM calls** (distillation, summarization) — anything that isn't a live turn runs where latency is invisible, never on the voice loop.
- **`asyncio.to_thread` for all blocking CPU/httpx work** in the agent's single event-loop, protecting audio/turn-detection/RPC.
- **Typed errors + `kb.state` attribute channel** for surfacing ingest failures to the UI while the session continues unchanged.
- **Operator runbook (`NN-*-VERIFY.md`) for any proof requiring the live GPU VM** the sandbox can't run.

### Key Lessons
1. Validate context-window budgets with an explicit assertion at injection time — a silently-truncated `num_ctx` fails open and is invisible until a model "forgets" pinned material.
2. Keep the roadmap phase-list checkbox and the progress table updated in the same edit; divergence forces reconciliation at milestone close.
3. When a plan asserts a library-level blocker, read the pinned source before accepting it — assumptions about deprecated-vs-removed APIs were repeatedly wrong in the safe direction.

### Cost Observations
- Model mix: not tracked this milestone.
- Sessions: not tracked (112 commits over 2026-06-24 → 06-26).
- Notable: interim RC close — Phase 7 (Polish & Reliability) deferred to v1.0; 36/42 v1 requirements complete.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0-rc1 | — | 6 | Established frozen-prefix + off-hot-path + operator-runbook patterns |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|-------------------|
| v1.0-rc1 | inline self-checks (metrics/parse/distill) | — | — |

### Top Lessons (Verified Across Milestones)

1. (Pending a second milestone to cross-validate.)
