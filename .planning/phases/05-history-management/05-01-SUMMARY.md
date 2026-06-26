---
phase: 05-history-management
plan: 05-01
subsystem: api
tags: [livekit, chatcontext, sliding-window, ttft, prefix-cache, gemma]

# Dependency graph
requires:
  - phase: 03-persona-layer
    provides: frozen-prefix render_prompt(persona, brief) carried in Agent.instructions
  - phase: 04-knowledge-base-layer
    provides: KB brief inject-once into the frozen prefix; num_ctx=8192 coupled-constants pin; metrics.py llm_ttft_ms read on time axis
provides:
  - Sliding-window conversation history capped each turn behind the frozen persona+KB prefix (SESS-05)
  - First Agent subclass in the repo (HistoryWindowAgent) with a per-turn on_user_turn_completed window-trim hook
  - Pure livekit-free windowing decision module agent/history.py (sandbox-verifiable _self_check)
  - Operator runbook 05-HISTORY-VERIFY.md for the flat-TTFT-over-time + cache-hold VM proofs
affects: [phase-06-critique, history, ttft, prefix-cache]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure windowing DECISION module (history.py) + EFFECT-owning Agent subclass (main.py) split"
    - "Per-turn ChatContext item-list trim via truncate(max_items=) + update_chat_ctx; never touch instructions"

key-files:
  created:
    - agent/history.py
    - .planning/phases/05-history-management/05-HISTORY-VERIFY.md
  modified:
    - agent/main.py

key-decisions:
  - "Window-only is the MVP floor; async summarization is OUT of scope (SESS-05 'and/or' satisfied by the deterministic item-count window)"
  - "HISTORY_MAX_ITEMS=20 — the fourth coupled constant (num_ctx 8192 / BRIEF_TOKEN_BUDGET 1500 / ~5000-tok history budget); exact N is a [VM-INTROSPECT] tuning gate"
  - "Cut from the FRONT (drop oldest items) via truncate; never rewrite the middle (cache-safe edge)"
  - "HistoryWindowAgent NEVER calls update_instructions — Criterion 3 (behind the frozen prefix) is structurally guaranteed because truncate preserves system instructions"

patterns-established:
  - "Pattern A: pure decision module mirrors persona.py/metrics.py/kb/parse.py (_self_check, no livekit import)"
  - "Pattern B: thin Agent subclass owns the effect; on_user_turn_completed runs the cheap synchronous trim + update_chat_ctx to persist across turns"

requirements-completed: [SESS-05]

# Metrics
duration: 5 min
completed: 2026-06-26
status: complete
---

# Phase 5 Plan 01: Sliding-window conversation history behind the frozen prefix (HistoryWindowAgent) Summary

**Per-turn ChatContext item-list capping via `truncate(max_items=20)` + `update_chat_ctx` in the repo's first `Agent` subclass, keeping TTFT flat over a long session without ever touching the cached persona+KB `instructions` prefix.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-26T02:57:41Z
- **Completed:** 2026-06-26T03:02:21Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- New pure, livekit-free `agent/history.py` — the windowing DECISION (`HISTORY_MAX_ITEMS`, `should_trim`, `window_target`, `_self_check`) over an integer count; sandbox-verifiable (`history _self_check OK`).
- New `HistoryWindowAgent(Agent)` in `agent/main.py` (the repo's first `Agent` subclass) overriding `on_user_turn_completed` to run a cheap synchronous front-trim and persist the window across turns via `update_chat_ctx`; the bare `Agent(...)` at the session-agent construction swapped for it with the `instructions` argument byte-identical.
- New `05-HISTORY-VERIFY.md` operator runbook: Proof A (flat-TTFT-over-time, 30–50 turns), Proof B (Ollama cache-hold / no mid-session KB re-prefill), Proof C (window persists + composes with persona/KB edits), the [VM-INTROSPECT] history-API signature checks, and the build/deploy-before-verify reminder.

## Task Commits

Each task was committed atomically:

1. **Task 05-01-1: pure windowing decision module** - `77d2c1b` (feat)
2. **Task 05-01-2: wire HistoryWindowAgent into the session** - `60d1e3c` (feat)
3. **Task 05-01-3: operator runbook 05-HISTORY-VERIFY.md** - `764add5` (docs)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `agent/history.py` (new) - Pure windowing decision: `HISTORY_MAX_ITEMS=20`, `should_trim(item_count)`, `window_target()`, `_self_check()`; no livekit import.
- `agent/main.py` (modified) - `import history`; `class HistoryWindowAgent(Agent)` with `on_user_turn_completed` (truncate + update_chat_ctx, never update_instructions); session-agent construction swapped to the subclass.
- `.planning/phases/05-history-management/05-HISTORY-VERIFY.md` (new) - Operator runbook for the deferred VM proofs (A flat-TTFT, B cache-hold, C window-persists/composes) + [VM-INTROSPECT] signature checks.

## Decisions Made
- **Window-only MVP floor:** async summarization deliberately NOT built — the deterministic item-count window alone satisfies SESS-05 ("sliding-window and/or summarized") and Criteria 1–3 (YAGNI / CODE_PRINCIPLES §7).
- **`HISTORY_MAX_ITEMS=20`** documented as the fourth coupled constant (alongside `OLLAMA_CONTEXT_LENGTH=8192` / `BRIEF_TOKEN_BUDGET=1500` / the ~5000-tok history budget); exact N is a `[VM-INTROSPECT]` tuning gate against the measured flat-TTFT curve.
- **Decision/effect split:** the pure module owns the decision; the subclass owns the effect (`truncate` + `update_chat_ctx`) — mirrors the persona/metrics/parse pure-module convention.
- **Criterion 3 by construction:** the subclass NEVER calls `update_instructions`; `truncate` preserves system instructions, so windowing is physically incapable of touching the cached persona+KB prefix.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. The acceptance grep for `summariz` initially matched a docstring word ("summarization") in `history.py`; reworded the comment to "async-condensation stretch" so the no-summarization-code grep stays clean. (Cosmetic wording fix, not a behavior change — folded into the Task-1 commit before it was made.)

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SESS-05 sandbox-verifiable core is complete and committed: `python3 agent/history.py`, `python3 -m py_compile agent/main.py`, and `python3 agent/persona.py` all green; `agent/persona.py` / `agent/metrics.py` byte-identical (read-only analogs untouched).
- **Deferred OPERATOR GATE (VM):** the keystone flat-TTFT-over-time proof, the Ollama cache-hold cross-check, the window-persists/composes check, and the installed-livekit signature checks are captured in `05-HISTORY-VERIFY.md` — they need the live Docker/GPU/Ollama/browser loop (the sandbox cannot import livekit or run the stack). NOT marked passed in this plan.
- Phase 5 is a single-plan phase (05-01); with this plan complete the phase is ready for verification.

---
*Phase: 05-history-management*
*Completed: 2026-06-26*
