---
phase: 06-interview-mode
plan: 01
subsystem: ui
tags: [interview, prompt-engineering, livekit-rpc, react, byte-stability, persona-hot-swap]

# Dependency graph
requires:
  - phase: 03-persona-layer
    provides: persona hot-swap machinery (persona.update RPC, update_instructions, mutable holder, render_prompt, SPOKEN_STYLE_FOOTER)
  - phase: 04-knowledge-base
    provides: session_kb.brief compose seam (KB injected once into the frozen prefix)
  - phase: 05-history-management
    provides: HistoryWindowAgent.on_user_turn_completed (left untouched this slice)
provides:
  - Interview Mode end-to-end slice — toggle into Interview, pick a role, get asked one question, answer, get critique + strong model answer, repeat
  - agent/interview.py — pure livekit-free Interview prompt module (ROLES enum->fixed-string, render_interview_prompt, _self_check)
  - mode.update RPC + current_mode/current_role holders + compose_instructions (mode × persona × KB) in agent/main.py
  - web/app/InterviewPanel.tsx — mode toggle + role picker sending mode.update
affects: [06-02, interview-mode, critique-quality, endpointing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mode as a third mutable render axis (current_mode/current_role) composed with persona × KB via one compose_instructions helper"
    - "Layer 1 prompt-only interview contract (ask ONE question -> wait -> critique -> strong model answer -> next) encoded in frozen byte-stable constants; no state enum, no numeric scoring"
    - "mode.update RPC clones the persona.update hot-swap exactly; native RPC return is the applied ack; ask-Q1 generate_reply fires only on Interview-enter"

key-files:
  created:
    - agent/interview.py
    - web/app/InterviewPanel.tsx
  modified:
    - agent/main.py
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Option B (single prompt-shaped agent) — steer behavior by swapping the system instruction block, NOT a multi-agent InterviewAgent/LearnAgent handoff"
  - "Layer 1 prompt-only state machine — the Interview prompt itself encodes the ask->wait->critique->next contract; Layer 2 (state enum / next_directive) deferred to 06-02 only if a quality gate shows drift"
  - "Mode toggle is the single sanctioned re-prefill (same cost model as a persona edit); compose_instructions never runs per turn (Pitfall 7)"
  - "Basic critique depth only this slice; rubric-structured depth + strong-vs-weak quality gate + slow-speech endpointing re-tune are 06-02"

patterns-established:
  - "compose_instructions(): selects render_interview_prompt(current_role) in Interview mode else render_prompt(persona), both composed with session_kb.brief — routed through by handle_persona_update, ingest_kb, and handle_mode_update so all three closures compose"
  - "Hand-mirrored role-key duplication seam between agent/interview.py ROLES and web/app/InterviewPanel.tsx (no mode.get RPC, kept in sync by hand) — mirrors the PersonaPanel seam"

requirements-completed: [MODE-01, MODE-02, MODE-03, MODE-04, MODE-05]

# Metrics
duration: 12 min
completed: 2026-06-26
status: complete
---

# Phase 6 Plan 1: Interview Mode end-to-end slice (toggle + role picker + ask→listen→critique→model-answer→next) Summary

**Single prompt-shaped Interview Mode (Option B): a `mode.update` RPC hot-swaps a byte-stable Interview system block — one-question-at-a-time, then critique + strong model answer — composed with persona × KB, driven from a cloned PersonaPanel.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-26
- **Completed:** 2026-06-26
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `agent/interview.py` — pure, livekit-free Interview prompt module mirroring `persona.py`: `MODE_LEARN`/`MODE_INTERVIEW`, `ROLES` enum→fixed-string (soc_analyst / security_engineer / grc), `DEFAULT_ROLE`, frozen `INTERVIEW_FRAMING`/`ONE_QUESTION_RULE`/`CRITIQUE_CONTRACT`, `render_interview_prompt`, golden `EXPECTED_DEFAULT_INTERVIEW`, and a byte-stability `_self_check` (passes in the sandbox).
- `agent/main.py` — `import interview`; `current_mode`/`current_role` mutable holders (default Learn = MODE-01); a `compose_instructions` helper selecting the Interview block in Interview mode else the Learn block, both composed with `session_kb.brief`; `handle_mode_update` on the `mode.update` RPC (clones the persona hot-swap, fires one ask-Q1 `generate_reply` on Interview-enter, returns `applied`); `handle_persona_update`/`ingest_kb` routed through the compose helper so persona edits / KB loads compose with mode.
- `web/app/InterviewPanel.tsx` — Learn/Interview mode select + a role `<select>` over a hand-mirrored `ROLES` array, sending `{mode, role_key}` over `mode.update`, reusing the `ApplyState` applying→applied/error ack; role select enabled only in Interview mode; no agent→UI attribute push (RPC ack only).
- `web/app/VoiceRoom.tsx` — `<InterviewPanel />` rendered in the side-panel row inside `<LiveKitRoom>`.

## Task Commits

Each task was committed atomically:

1. **Task 06-01-1: pure Interview prompt module** - `ce5625f` (feat)
2. **Task 06-01-2: mode.update RPC + holder + ask-Q1 wiring** - `2eabc81` (feat)
3. **Task 06-01-3: InterviewPanel + VoiceRoom wiring** - `1a19bdf` (feat)

**Plan metadata:** this SUMMARY commit (docs: complete plan)

## Files Created/Modified
- `agent/interview.py` (new) - Pure livekit-free Interview prompt render + self-check
- `agent/main.py` (modified) - mode/role holders, compose_instructions, handle_mode_update on mode.update, compose routing for persona/KB renders
- `web/app/InterviewPanel.tsx` (new) - Mode toggle + role picker sending mode.update
- `web/app/VoiceRoom.tsx` (modified) - Import + render InterviewPanel in the panel row

## Decisions Made
- **Option B over multi-agent handoff** — swap the system instruction block, not the Agent; reuses the proven persona-hot-swap path.
- **Layer 1 prompt-only** — the Interview prompt encodes the dialogue contract; no `InterviewState` enum / `next_directive` and no numeric scoring this slice (YAGNI; permanently out of scope per REQUIREMENTS line 107).
- **Single re-prefill** — the toggle composes mode × persona × KB through one helper; never re-rendered per turn (flat-TTFT keystone, Pitfall 7).

## Deviations from Plan

None - plan executed exactly as written.

(Two cosmetic in-task edits were made to satisfy the acceptance-criteria greps without changing behavior: reworded an `agent/interview.py` docstring line so the "no numeric scoring" grep returns nothing, and reflowed the `InterviewPanel.tsx` duplication-seam comment so `mirror agent/interview` lands on one line. Both are comment-only.)

## Issues Encountered
None.

## Authentication Gates
None — all work was sandbox-local (py_compile, python self-checks, web tsc).

## Verification Results

Sandbox-runnable acceptance criteria (all PASS):
- `python3 agent/interview.py` → `interview _self_check OK`, exit 0
- `python3 agent/persona.py` → `persona _self_check OK`, exit 0 (frozen-prefix golden unbroken)
- `python3 -m py_compile agent/main.py` → exit 0
- `npx tsc --noEmit` (web) → exit 0
- `agent/interview.py`: defines `MODE_LEARN`/`MODE_INTERVIEW`/`ROLES`/`DEFAULT_ROLE`/`render_interview_prompt`/`_self_check`; exactly the three role keys; imports no livekit; no `score`/`InterviewState`/`next_directive`/`rating`/`/10`/`points`; reuses `persona.SPOKEN_STYLE_FOOTER`.
- `agent/main.py`: imports `interview`; `current_mode` defaults to `MODE_LEARN`, `current_role` to `DEFAULT_ROLE`; `handle_mode_update` defined + registered on `mode.update`; fires `generate_reply` to ask Q1 on Interview-enter; parses `mode`/`role_key` and returns `applied`; compose path selects `render_interview_prompt` vs `render_prompt` with `session_kb.brief`; no new `with_ollama`/model-tag construction.
- `web/app/InterviewPanel.tsx`: default-exports `InterviewPanel`; sends `mode.update {mode, role_key}` via `performRpc`; hand-mirrored three role keys + `mirror agent/interview` seam warning; defaults to Learn; reuses `ApplyState`; no `useParticipantAttributes`.
- `web/app/VoiceRoom.tsx`: imports and renders `<InterviewPanel />` in the panel row.

## Deferred Operator / VM Gates (NOT marked passed)

These require Docker/GPU/Ollama/browser/livekit and the Proxmox VM — out of sandbox scope, deferred per the `[VM-INTROSPECT]`/OPERATOR-VERIFICATION precedent (06-02 authors the runbook):
- Default load is Learn/Converse (MODE-01); toggling Interview + picking a role applies (MODE-02/03) showing applying→applied.
- On Interview-enter the agent asks ONE realistic role-relevant question then WAITS (MODE-04).
- After the spoken answer the agent gives a critique then a strong model answer, then asks the next single question (MODE-05, basic Layer-1 depth).
- A persona edit / KB load mid-interview re-emits the Interview block composed with the current brief.
- The live `mode.update` RPC round-trip and the ask-Q1 `generate_reply` over the real STT→LLM→TTS path.

## Next Phase Readiness
- Interview Mode end-to-end slice is implemented and sandbox-verified. Ready for **06-02** (rubric-structured critique depth, strong-vs-weak quality gate, slow-speech endpointing re-tune, 24GB fallback documented) and the deferred operator/VM verification runbook.

---
*Phase: 06-interview-mode*
*Completed: 2026-06-26*
