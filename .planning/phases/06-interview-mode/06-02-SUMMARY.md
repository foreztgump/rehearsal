---
phase: 06-interview-mode
plan: 02
subsystem: ai
tags: [interview, prompt-engineering, critique-rubric, endpointing, byte-stability, vm-introspect, ollama]

# Dependency graph
requires:
  - phase: 06-interview-mode
    provides: 06-01 Interview Mode slice (interview.py CRITIQUE_CONTRACT/render_interview_prompt/_self_check, main.py mode.update RPC + handle_mode_update + turn_handling dict, InterviewPanel)
provides:
  - Rubric-structured critique constant (four qualitative dimensions → critique → strong model answer → next question) in agent/interview.py, byte-stable, NO numeric score
  - Extended interview _self_check asserting rubric dimensions land, the critique→model-answer→next ordering, and no score-token leak
  - Slow-speech interview endpointing profile (min_delay 0.7 / max_delay 5.0) as named constants in agent/main.py, applied as the single session profile (mechanism-3 fallback)
  - A [VM-INTROSPECT] switch-mechanism comment block (three ordered candidates, no runtime turn_handling setter assumed)
  - 06-INTERVIEW-VERIFY.md operator runbook — Gate A (strong-vs-weak critique discrimination), Gate B (slow-speech endpointing), Gate C (per-role loop), [VM-INTROSPECT] endpointing-setter probes, 24GB fallback documentation
affects: [interview-mode, critique-quality, endpointing, operator-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rubric-as-prompt-structure: qualitative four-dimension critique block (no numeric score) compensates for the 4B model's shallow default critique — frozen constant in the same render slot as 06-01's basic contract (join order unchanged, byte-stability preserved)"
    - "Endpointing profiles as named constants (conversational vs interview floor) with the profile-switch mechanism flagged [VM-INTROSPECT] (three ordered candidates) and the MVP shipping mechanism-3 (single session profile)"
    - "Property-style strong-vs-weak discrimination gate (scripted held-out answers) as the operator-verifiable quality bar, with a documented 24GB OLLAMA_MODEL swap as the FAIL escalation"

key-files:
  created:
    - .planning/phases/06-interview-mode/06-INTERVIEW-VERIFY.md
  modified:
    - agent/interview.py
    - agent/main.py

key-decisions:
  - "Critique depth via PROMPT STRUCTURE (rubric), not model size or reasoning tokens — thinking stays OFF (reasoning_effort=none)"
  - "Endpointing profile-switch ships mechanism 3 (interview floor as the single session profile) because Option B keeps one agent and no runtime turn_handling setter is assumed; mechanisms 1/2 captured as [VM-INTROSPECT] probes"
  - "over_budget:[eou] on interview turns is EXPECTED (raised min_delay 0.7s > BUDGET_MS[eou]=300), not a regression — documented in code and verify doc"
  - "24GB larger-model swap is DOCUMENTED only (OLLAMA_MODEL config change behind LiveKit's interface), triggered by Gate A failure — no 24GB code path in v1"

patterns-established:
  - "Rubric constant replaces the basic critique contract in the SAME fixed-tuple join slot — only the constant's bytes change, render_interview_prompt order is invariant"
  - "_self_check extended with rubric-dimension landing + ordering + no-score-leak assertions alongside the existing determinism/golden/no-placeholder/every-ROLES checks"

requirements-completed: [MODE-04, MODE-05]

# Metrics
duration: 9 min
completed: 2026-06-26
status: complete
---

# Phase 6 Plan 2: Rubric-structured critique depth + slow-speech endpointing re-tune + 24GB fallback doc Summary

**A four-dimension qualitative critique rubric (no numeric score) frozen into `agent/interview.py`, a slow-speech interview endpointing profile (min_delay 0.7 / max_delay 5.0) with the profile-switch mechanism flagged `[VM-INTROSPECT]`, and a strong-vs-weak critique discrimination operator runbook that gates the E4B-depth blocker and documents (not builds) the 24GB `OLLAMA_MODEL` fallback.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-26
- **Completed:** 2026-06-26
- **Tasks:** 3
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- **Rubric-structured critique (MODE-05 depth, the E4B blocker mitigation).** Replaced 06-01's basic `CRITIQUE_CONTRACT` with a frozen rubric constant: the model assesses the answer against four QUALITATIVE dimensions — technical accuracy, completeness, precise practitioner terminology, and answer structure/clarity — then responds in a fixed order (short concrete critique → strong model answer → next single question), spoken-friendly, with an example-of-shape. NO numeric score / rating / points anywhere (REQUIREMENTS line 107). `render_interview_prompt`'s join tuple order is unchanged; `EXPECTED_DEFAULT_INTERVIEW` golden updated.
- **Extended `_self_check`.** Asserts the four rubric dimensions land in the render, asserts the critique → model-answer → next ordering by index, asserts no numeric-score token leaks into the spoken prompt, and keeps the determinism + golden + no-`{}`-leak + every-ROLES-descriptor assertions. `python3 agent/interview.py` → `interview _self_check OK`.
- **Slow-speech endpointing (MODE-05).** Named constants `INTERVIEW_ENDPOINTING_MIN_DELAY=0.7` (∈ [0.6,0.8]) / `INTERVIEW_ENDPOINTING_MAX_DELAY=5.0` (∈ [5.0,6.0]) plus the conversational pair, wired into the `turn_handling` endpointing dict via `ENDPOINTING_MIN_DELAY`/`MAX_DELAY`. A `[VM-INTROSPECT]` comment block enumerates the three ordered switch mechanisms (per-Agent override → runtime `update_options` → single session profile), states NO runtime `turn_handling` setter is assumed, and that the shipped path is mechanism 3 (single session profile), finalized against the VM probe. `MultilingualModel()` and VAD `activation_threshold=0.65` unchanged; `agent/metrics.py` untouched.
- **06-INTERVIEW-VERIFY.md operator runbook.** Build/deploy stale-deploy reminder; `[VM-INTROSPECT]` `inspect.signature(Agent.__init__)` / `AgentSession` endpointing-setter probes + three-mechanism decision rule; Gate A (scripted STRONG and WEAK SOC-analyst answers + concrete discrimination pass/fail rubric, FAIL → 24GB fallback); Gate B (slow-speech no-cut-in + the expected `over_budget:["eou"]` caveat with the `docker compose logs` grep); Gate C (per-role loop contract for all three roles); the 24GB fallback documentation (`OLLAMA_MODEL` swap, VRAM math, model-by-mode v2 idea, Gate-A trigger); results-capture tables; and the metrics-read-only + thinking-OFF notes.

## Task Commits

Each task was committed atomically:

1. **Task 06-02-1: rubric-structured critique constant + rubric self-check** - `6275e9d` (feat)
2. **Task 06-02-2: slow-speech interview endpointing profile + [VM-INTROSPECT] block** - `27cb019` (feat)
3. **Task 06-02-3: 06-INTERVIEW-VERIFY.md operator runbook** - `285b024` (docs)

**Plan metadata:** this SUMMARY commit (docs: complete plan)

## Files Created/Modified
- `agent/interview.py` (modified) - `CRITIQUE_CONTRACT` replaced by the rubric-structured frozen constant; `EXPECTED_DEFAULT_INTERVIEW` golden updated; `_self_check` extended with rubric/ordering/no-score assertions
- `agent/main.py` (modified) - named endpointing profile constants + `[VM-INTROSPECT]` switch-mechanism block + the `over_budget:["eou"]`-is-expected note; `turn_handling` endpointing now uses the named constants
- `.planning/phases/06-interview-mode/06-INTERVIEW-VERIFY.md` (new) - operator runbook for the deferred VM gates

## Decisions Made
- **Depth from prompt structure, thinking OFF** — the rubric runs through the existing `reasoning_effort="none"` session LLM; no `think=true`, no new reasoning effort.
- **Mechanism 3 ships (single session profile)** — Option B (06-01) keeps one agent, so the per-Agent override (mechanism 1) has no clean carrier and no runtime `turn_handling` setter is assumed; the interview floor serves both modes for now, with mechanisms 1/2 captured as VM probes.
- **`over_budget:["eou"]` is expected, not a bug** — the raised `min_delay` (0.7s) deliberately exceeds `BUDGET_MS["eou"]=300`; documented in both code and the verify doc so the metrics line isn't misread.
- **24GB fallback documented, not built** — the LLM stays behind LiveKit's interface; a larger model is an `OLLAMA_MODEL` config change triggered only by a Gate A failure.

## Deviations from Plan

None - plan executed exactly as written.

(One in-task wording adjustment: the rubric constant's "Do NOT attach a number, grade, or rating" phrasing was reworded to "Do NOT attach a number or grade; judge the answer qualitatively, in words only" so the rendered/golden text carries no `rating` token — the acceptance grep for score-leak stays clean. The word `score`/`rating` now appears only in code comments and the `_self_check` assertion tuple, never in the spoken prompt. Comment/wording-only; no behavior change.)

## Issues Encountered
None.

## Authentication Gates
None — all work was sandbox-local (py_compile, the interview self-check, grep acceptance checks).

## Verification Results

Sandbox-runnable acceptance criteria (all PASS):
- `python3 agent/interview.py` → `interview _self_check OK`, exit 0
- `python3 -m py_compile agent/main.py` → exit 0
- `agent/interview.py`: rubric names the four dimensions (accuracy/completeness/terminology/structure); enforces critique → strong model answer → next ordering; NO score/`/10`/rating/points token in the rendered prompt or golden; `render_interview_prompt` join order unchanged (framing, ROLES, one-question rule, rubric, footer); imports no livekit
- `agent/main.py`: `INTERVIEW_ENDPOINTING_MIN_DELAY=0.7` ∈ [0.6,0.8], `INTERVIEW_ENDPOINTING_MAX_DELAY=5.0` ∈ [5.0,6.0]; `[VM-INTROSPECT]` block enumerates the three mechanisms and asserts no runtime `turn_handling` setter; `over_budget`/`eou`/`BUDGET_MS`/`expected` documented; `MultilingualModel()` + `activation_threshold=0.65` unchanged
- `git diff agent/metrics.py` → empty (metrics is read-only)
- `06-INTERVIEW-VERIFY.md`: Gates A–C + 24GB fallback section, each gate a numbered operator step with commands + results tables; Gate A scripted strong/weak answers + discrimination rubric + FAIL→24GB; `inspect.signature(Agent.__init__)` probe + three-mechanism decision rule; Gate B slow-speech + `over_budget:["eou"]` caveat; 24GB section names `OLLAMA_MODEL`/`gemma4:26b`/24GB/16GB/model-by-mode/Qwen; build/deploy + read-only + thinking-OFF notes

## Deferred Operator / VM Gates (NOT marked passed)

These require Docker/GPU/Ollama/browser/livekit and the Proxmox VM — out of sandbox scope, deferred per the `[VM-INTROSPECT]`/OPERATOR-VERIFICATION precedent. Authored in `06-INTERVIEW-VERIFY.md`, NOT marked passed:
- **Gate 1 ([VM-INTROSPECT]):** which endpointing switch mechanism the installed pin supports (`inspect.signature(Agent.__init__)` / `AgentSession`); the shipped code uses mechanism 3.
- **Gate A:** the critique DISCRIMINATES the scripted strong vs weak answer (praises the strong, names the weak's gaps) — discharges the STATE.md line-101 E4B-depth blocker, or triggers the documented 24GB fallback.
- **Gate B:** a deliberate pause-heavy answer is NOT cut mid-thought; prompt response after a clear finish; `over_budget:["eou"]` confirmed expected.
- **Gate C:** one question at a time per role → critique → model answer → next; Learn toggle restores the conversational contract.

## Next Phase Readiness
- Phase 6 (interview-mode) plans 06-01 and 06-02 are both implemented and sandbox-verified. The Interview Mode loop, rubric-structured critique, and slow-speech endpointing are landed; the strong-vs-weak quality gate, the endpointing-setter `[VM-INTROSPECT]` probes, and the 24GB fallback trigger are the deferred operator/VM verification owned by `06-INTERVIEW-VERIFY.md`. Phase complete pending operator sign-off; ready for phase verification / next step.

---
*Phase: 06-interview-mode*
*Completed: 2026-06-26*
