---
phase: 14
plan: 14-01
slug: conversation-feel-retune
depends_on: []
status: ready
files_modified:
  - agent/endpointing.py        # NEW — pure mode→endpointing selector
  - agent/main.py               # wire selector; extract VAD/interrupt constants
  - stt/server.py               # name chunk/silence env knobs (already env-driven)
  - stt/backend_nemo.py         # att_context_size already env-driven (no change expected)
  - .env.example                # surface + document the STT feel knobs
  - tests/test_endpointing.py   # NEW — selector truth table
requirements: [FEEL-01, FEEL-02]
---

# Plan 14-01 — Conversation Feel Retune

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to execute this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax. Read `14-00-STATE-AND-SEQUENCING.md` first.

**Goal:** Make endpointing mode-aware (snappy Converse / deliberate Interview,
switched live with no session teardown) and lift the NeMo-era barge-in / dropped-word
knobs into named, documented, tunable constants — so normal chat feels as responsive
as the Whisper era while Interview keeps its patience.

**Architecture:** A pure `endpointing_for_mode(mode)` selector (sandbox-testable, no
LiveKit import) returns the endpointing dict for the current mode. `agent/main.py`
uses it at session build (for the initial mode) and inside the existing
`handle_mode_update` RPC to mutate the live session option **in place** — the same
runtime-mutation pattern the repo already uses for `session.llm._opts.model` and
`session.tts.update_options(voice=…)`. VAD/interrupt/STT knobs become named constants
with a documented rationale block; final empirical values are operator-tuned (14-09).

**Tech Stack:** Python 3, `livekit-agents ~=1.5/1.6`, `livekit-plugins-silero`, NeMo
streaming STT sidecar. uv-managed.

**Current state (vs PRD §2):** Confirmed accurate. `agent/main.py:107-108` pins
`ENDPOINTING_*` to the INTERVIEW constants; the CONVERSATIONAL constants (78-79) are
dead. VAD `activation_threshold=0.65` is inline at line 312; interrupt `min_duration`
0.3 is inline in the `turn_handling` dict (288-292). `STT_STREAM_CHUNK_MS` (560) and
`STT_ENDPOINT_SILENCE_MS` (700) are env-driven defaults in `stt/server.py` but absent
from `.env.example`. `STT_ATT_CONTEXT_SIZE` ships `[56,3]` in `.env.example` while the
`docker-compose.yml` default and the `stt/backend_nemo.py` fallback are `[70,6]`, and
the code comment warns `[56,3]` is **not a trained setting** and "silently degrades
accuracy" — a latent inconsistency this plan reconciles.

## Global Constraints

Inherit all of `14-00 §5`. Plan-specific:
- Latency budgets are named constants (`agent/metrics.py:BUDGET_MS`) — never inline.
  The raised Interview `min_delay` (0.7s) intentionally exceeds `BUDGET_MS["eou"]`
  (300); that `over_budget:["eou"]` flag on Interview turns is **expected, not a
  regression** (see `agent/main.py:84-87`). Do not "fix" it; `agent/metrics.py` is
  READ-ONLY here.
- Keep the local `MultilingualModel` turn detector — never the cloud default.
- No change to RPC method names or payload keys (`mode.update` stays `{mode, role_key}`).

---

## Task 1: Pure mode→endpointing selector (`agent/endpointing.py`) + test

**Files:**
- Create: `agent/endpointing.py`
- Test: `tests/test_endpointing.py`

**Interfaces:**
- Produces: `endpointing_for_mode(mode: str) -> dict[str, float | str]` returning
  `{"mode": "dynamic", "min_delay": float, "max_delay": float}`. Also exports the four
  profile constants `CONVERSE_MIN_DELAY`, `CONVERSE_MAX_DELAY`, `INTERVIEW_MIN_DELAY`,
  `INTERVIEW_MAX_DELAY`.
- Consumes: `interview.MODE_LEARN`, `interview.MODE_INTERVIEW` (pure module, no LiveKit).

- [ ] **Step 1: Write the failing test**

Create `tests/test_endpointing.py`:

```python
"""Truth table for the mode→endpointing selector (FEEL-01). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import endpointing  # noqa: E402
import interview  # noqa: E402


def test_learn_mode_uses_snappy_converse_floor():
    # Arrange / Act
    result = endpointing.endpointing_for_mode(interview.MODE_LEARN)
    # Assert
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY == 0.3
    assert result["max_delay"] == endpointing.CONVERSE_MAX_DELAY == 3.0
    assert result["mode"] == "dynamic"


def test_interview_mode_uses_deliberate_floor():
    result = endpointing.endpointing_for_mode(interview.MODE_INTERVIEW)
    assert result["min_delay"] == endpointing.INTERVIEW_MIN_DELAY == 0.7
    assert result["max_delay"] == endpointing.INTERVIEW_MAX_DELAY == 5.0


def test_unknown_mode_falls_back_to_snappy_converse():
    # An unknown mode must not strand the agent on the slow interview floor.
    result = endpointing.endpointing_for_mode("bogus")
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY


if __name__ == "__main__":
    test_learn_mode_uses_snappy_converse_floor()
    test_interview_mode_uses_deliberate_floor()
    test_unknown_mode_falls_back_to_snappy_converse()
    print("ok: endpointing selector truth table")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 tests/test_endpointing.py`
Expected: `ModuleNotFoundError: No module named 'endpointing'`.

- [ ] **Step 3: Write the minimal implementation**

Create `agent/endpointing.py`:

```python
"""Mode-aware endpointing profiles (FEEL-01).

Pure module — NO LiveKit import — so the truth table runs in the GPU-less sandbox.
`agent/main.py` applies the returned dict to the live AgentSession turn-handling.

The deliberate floor stays ONLY where it belongs: long, considered interview answers.
Normal Converse uses the snappy floor so chat feels as live as the Whisper era.
"""
from __future__ import annotations

import interview

# Snappy Converse floor: reply ~0.3s after the user stops (Whisper-era feel).
CONVERSE_MIN_DELAY: float = 0.3
CONVERSE_MAX_DELAY: float = 3.0

# Deliberate Interview floor: leave room for a considered, multi-sentence answer.
INTERVIEW_MIN_DELAY: float = 0.7
INTERVIEW_MAX_DELAY: float = 5.0

# Dynamic mode adapts within [min,max] from pause statistics (livekit-agents).
ENDPOINTING_MODE: str = "dynamic"


def endpointing_for_mode(mode: str) -> dict[str, float | str]:
    """Endpointing dict for the current conversation mode.

    Interview → deliberate floor; everything else (Learn/Converse, or an unknown
    value) → snappy floor. Defaulting unknown modes to snappy avoids stranding a
    misconfigured session on the slow interview delay.
    """
    if mode == interview.MODE_INTERVIEW:
        return {
            "mode": ENDPOINTING_MODE,
            "min_delay": INTERVIEW_MIN_DELAY,
            "max_delay": INTERVIEW_MAX_DELAY,
        }
    return {
        "mode": ENDPOINTING_MODE,
        "min_delay": CONVERSE_MIN_DELAY,
        "max_delay": CONVERSE_MAX_DELAY,
    }
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python3 tests/test_endpointing.py`
Expected: `ok: endpointing selector truth table`

- [ ] **Step 5: Commit**

```bash
git add agent/endpointing.py tests/test_endpointing.py
git commit -m "feat(14-01): pure mode-aware endpointing selector + truth table"
```

---

## Task 2: Wire the selector into session build + live `mode.update`

**Files:**
- Modify: `agent/main.py` (imports; the `turn_handling` endpointing dict ~281-293;
  the pinned constants 107-108; `handle_mode_update` ~509-535)

**Interfaces:**
- Consumes: `endpointing.endpointing_for_mode`, `current_mode[0]`.
- Produces: live, mode-correct endpointing on the running session with no teardown.

- [ ] **Step 1: Confirm the live endpointing option holder (one-line introspection)**

The repo already mutates live session options at runtime (`session.llm._opts.model`
at ~562; `session.tts.update_options(voice=…)` at ~492). Endpointing follows the same
pattern; confirm the attribute on the installed version before wiring:

Run (in the agent container or uv env):
```bash
python -c "import inspect; from livekit.agents import AgentSession; print([a for a in dir(AgentSession) if 'turn' in a.lower() or 'endpoint' in a.lower() or 'opt' in a.lower()])"
```
Expected: an options/turn-handling attribute (e.g. `options`, `_turn_handling`, or
similar) carrying the `endpointing` dict passed at construction. Note the exact path
(call it `<SESSION_ENDPOINTING_PATH>` below). If a *public* setter exists, prefer it;
otherwise mutate the option dict in place (consistent with the existing `_opts`
mutations).

- [ ] **Step 2: Import the selector and replace the dead pinned constants**

In `agent/main.py`, add to the agent-local imports:
```python
import endpointing
```
Delete the now-redundant dead pin at lines 107-108:
```python
# REMOVE these two lines (the CONVERSATIONAL constants are now in endpointing.py):
ENDPOINTING_MIN_DELAY: float = INTERVIEW_ENDPOINTING_MIN_DELAY
ENDPOINTING_MAX_DELAY: float = INTERVIEW_ENDPOINTING_MAX_DELAY
```
…and the four now-duplicated `*_ENDPOINTING_*_DELAY` constants at lines 78-83 (they
live in `endpointing.py` now). Leave the `METRICS INTERPRETATION` comment (84-87).

- [ ] **Step 3: Build the session endpointing from the initial mode**

In `build_session(...)`, replace the static endpointing dict (currently lines
~283-287) with the selector seeded by the default mode:
```python
"endpointing": endpointing.endpointing_for_mode(interview.MODE_LEARN),
```
(The session starts in Learn/Converse — `current_mode` defaults to `MODE_LEARN` at
line 417 — so it boots on the snappy floor.)

- [ ] **Step 4: Apply the mode-correct endpointing inside `handle_mode_update`**

In `handle_mode_update` (~509-535), after `current_mode[0] = new_mode` and the
`update_instructions` call, mutate the live endpointing using the path confirmed in
Step 1. Mirror the existing in-place pattern:
```python
# Switch the endpointing floor live (FEEL-01) — same in-place runtime-mutation
# pattern as session.llm._opts.model / session.tts.update_options. No teardown.
new_endpointing = endpointing.endpointing_for_mode(current_mode[0])
<SESSION_ENDPOINTING_PATH>.update(new_endpointing)  # e.g. session.options.endpointing
```
Keep the existing Interview first-question `generate_reply` branch unchanged.

- [ ] **Step 5: Byte-compile + import-check (sandbox-safe)**

Run:
```bash
python3 -m py_compile agent/main.py agent/endpointing.py
python3 tests/test_endpointing.py
```
Expected: no output from `py_compile` (success); `ok:` line from the test.

- [ ] **Step 6: Commit**

```bash
git add agent/main.py
git commit -m "feat(14-01): mode-aware endpointing live-switched on mode.update (no teardown)"
```

---

## Task 3: Name the VAD + interrupt feel knobs (no magic values)

**Files:**
- Modify: `agent/main.py` (VAD instantiation ~304-312; interruption dict ~288-292)

**Interfaces:**
- Produces: `VAD_ACTIVATION_THRESHOLD`, `INTERRUPT_MIN_DURATION_S`,
  `FALSE_INTERRUPT_TIMEOUT_S` named constants with documented rationale.

- [ ] **Step 1: Extract the VAD threshold to a named constant**

In `agent/main.py`, near the other top-level constants, add:
```python
# Silero VAD speech-onset bar (FEEL-02). Lower = catches quiet/soft onsets so the
# first word isn't swallowed; higher = fewer open-mic false triggers from playout
# tail + room noise. 0.6 is the documented start (down from the 0.65 echo-defense
# value) to recover dropped openings; operator A/B-tunes in 14-09. Headphones (the
# recommended setup) make a lower bar safe.
VAD_ACTIVATION_THRESHOLD: float = 0.6
```
Replace the inline `silero.VAD.load(activation_threshold=0.65)` at line 312 with:
```python
proc.userdata["vad"] = silero.VAD.load(activation_threshold=VAD_ACTIVATION_THRESHOLD)
```

- [ ] **Step 2: Extract the interruption knobs to named constants**

Add near the constants:
```python
# Barge-in gate (FEEL-02). min_duration = real speech required before cancelling
# TTS: low enough that a genuine interrupt reliably cuts the agent, high enough to
# ignore the agent's own echo tail + "mm-hmm" backchannels. resume_false_interruption
# + a 2.0s timeout make a no-transcript noise blip resume the agent, not drop the turn.
INTERRUPT_MIN_DURATION_S: float = 0.25
FALSE_INTERRUPT_TIMEOUT_S: float = 2.0
```
Replace the inline interruption dict (lines 288-292) with:
```python
"interruption": {
    "min_duration": INTERRUPT_MIN_DURATION_S,
    "resume_false_interruption": True,
    "false_interruption_timeout": FALSE_INTERRUPT_TIMEOUT_S,
},
```

- [ ] **Step 3: Byte-compile**

Run: `python3 -m py_compile agent/main.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add agent/main.py
git commit -m "refactor(14-01): name VAD + interrupt feel knobs with tuning rationale"
```

---

## Task 4: Surface + reconcile the STT feel knobs in `.env.example`

**Files:**
- Modify: `.env.example` (STT section, ~58-67)
- Modify: `docker-compose.yml` only if the `STT_ATT_CONTEXT_SIZE` default disagrees
  with the reconciled value (verify first; do not broaden scope).

**Interfaces:**
- Produces: documented, operator-tunable `STT_STREAM_CHUNK_MS`,
  `STT_ENDPOINT_SILENCE_MS`, and a **trained** `STT_ATT_CONTEXT_SIZE`.

- [ ] **Step 1: Reconcile `STT_ATT_CONTEXT_SIZE` to a trained setting**

`stt/backend_nemo.py` warns the cache-aware Conformer was trained ONLY on
`[[70,13],[70,6],[70,1],[70,0]]`; `[56,3]` is untrained and silently degrades
accuracy. The deployed `.env.example` value `[56,3]` is therefore wrong for both feel
and correctness. In `.env.example`, change the line to the snappy trained setting and
document it:
```bash
# att_context_size = [left, right] in 80 ms encoder frames (STT-04). MUST be a
# trained setting: one of [70,13] [70,6] [70,1] [70,0]. [70,1] = 80 ms right-context
# lookahead — snappiest finalize that stays trained (vs [70,6]'s 480 ms). [70,6] is
# the accuracy-first alternate. [56,3] is UNTRAINED — do not use. Operator A/Bs
# [70,1] vs [70,6] in 14-09 against the felt regression.
STT_ATT_CONTEXT_SIZE=[70,1]
```

- [ ] **Step 2: Verify the compose default agrees**

Run:
```bash
grep -n "STT_ATT_CONTEXT_SIZE" docker-compose.yml
```
Expected: `${STT_ATT_CONTEXT_SIZE:-[70,6]}`. The `.env.example` value now overrides it
to `[70,1]`; the compose fallback `[70,6]` is an acceptable trained default. No edit
required unless you want the fallback to match — leave as-is (both are trained).

- [ ] **Step 3: Add the chunk + silence knobs to `.env.example`**

Append to the STT section of `.env.example`:
```bash
# --- STT conversation-feel knobs (FEEL-02; defaults live in stt/server.py) --------
# Live encoder step. Buffer incoming PCM to this size before the FastConformer
# encoder (sub-chunk frames error post-8x-subsampling). Lower = snappier partials but
# more encoder calls; 560 is the validated floor. Operator-tunable.
STT_STREAM_CHUNK_MS=560
# Autonomous end-of-utterance window: transcript stalled this long (the NeMo path has
# no client flush) emits a final. Too low = premature finals mid-sentence; too high =
# late replies. Balanced against the turn-detector min_delay above. 700 is the start.
STT_ENDPOINT_SILENCE_MS=700
```

- [ ] **Step 4: Confirm `stt/server.py` reads these (no code change expected)**

Run:
```bash
grep -n "STT_STREAM_CHUNK_MS\|STT_ENDPOINT_SILENCE_MS" stt/server.py
```
Expected: both already read via `os.environ.get(...)` (lines 75, 90). The `.env.example`
additions only surface them; no `stt/server.py` edit needed.

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "docs(14-01): surface + reconcile STT feel knobs (trained att_context_size, chunk, silence)"
```

---

## Task 5: Tuned-values rationale block + metrics-validation note

**Files:**
- Modify: `agent/main.py` (add a single consolidated rationale comment near the new
  constants)
- Modify: `.planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-01-conversation-feel-retune-PLAN.md`
  (append the operator tuning table — or keep it here; do not duplicate into code)

**Interfaces:**
- Produces: the documented feel-knob table so values aren't silently regressed
  (FEEL-02 "document the tuned values with rationale").

- [ ] **Step 1: Add the consolidated rationale block**

In `agent/main.py`, above the feel constants, add ONE block (don't restate per
constant — link to this table):
```python
# ============================ CONVERSATION-FEEL KNOBS ============================
# Retuned for the NeMo era (14-01). Starting values below; FINAL values are
# operator-empirical on the RTX 5090 (14-09) against the felt regression. Do not
# silently change without re-reading agent/metrics rolling_summary.
#   endpointing      : mode-aware (agent/endpointing.py) — Converse 0.3/3.0, Interview 0.7/5.0
#   VAD threshold    : 0.6  (down from 0.65) — recover swallowed openings
#   interrupt min_dur: 0.25 (down from 0.30) — interrupts cut TTS reliably
#   STT chunk        : 560 ms (.env STT_STREAM_CHUNK_MS) — snappy partials, stays valid
#   STT silence      : 700 ms (.env STT_ENDPOINT_SILENCE_MS) — vs turn-detector flush
#   att_context_size : [70,1] (.env STT_ATT_CONTEXT_SIZE) — trained, 80 ms lookahead
# ================================================================================
```

- [ ] **Step 2: Record the operator tuning + validation procedure (OPERATOR — 14-09)**

Append to this plan file an "Operator tuning" subsection (below) so 14-09 can execute
it. No code change. The procedure: run a Converse A/B against the pre-retune build,
read `rolling_summary` from agent logs, and confirm no stage regresses beyond the
intended Interview `eou` allowance.

- [ ] **Step 3: Byte-compile + commit**

```bash
python3 -m py_compile agent/main.py
git add agent/main.py .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-01-conversation-feel-retune-PLAN.md
git commit -m "docs(14-01): consolidated feel-knob rationale + operator tuning procedure"
```

---

## Verification

**Self-checkable (sign in-plan):**
- `python3 tests/test_endpointing.py` → `ok:` line (selector truth table).
- `python3 -m py_compile agent/main.py agent/endpointing.py` → clean.
- `git grep -n "0.65\|0.3," agent/main.py` shows no surviving inline feel magic
  numbers in the VAD/interrupt sites (all named).
- The CONVERSATIONAL profile is no longer dead: `endpointing_for_mode(MODE_LEARN)`
  returns the 0.3/3.0 floor and is what the session boots on.

**OPERATOR (RTX 5090, discharged in 14-09):**
- Converse A/B vs the pre-retune build: normal chat replies feel ~Whisper-era snappy;
  interrupts reliably cut TTS; opening words transcribed; Interview keeps its patience.
- `docker compose logs agent | grep rolling_summary | tail` shows no stage P50/P95
  regression beyond the intended Interview `eou` allowance.

## Operator tuning (executed in 14-09)

| Knob | Start | Direction if symptom | Symptom it fixes |
|---|---|---|---|
| `endpointing` Converse min_delay | 0.3s | ↓ to 0.2 if still feels laggy | "long pause before reply" |
| `VAD_ACTIVATION_THRESHOLD` | 0.6 | ↓ to 0.5 if onsets missed; ↑ if open-mic self-trigger | "dropped the words I said" |
| `INTERRUPT_MIN_DURATION_S` | 0.25 | ↓ to 0.2 if interrupts ignored; ↑ if echo self-interrupts | "interrupt didn't register" |
| `STT_ATT_CONTEXT_SIZE` | [70,1] | → [70,6] if accuracy suffers | finalize accuracy vs latency |
| `STT_ENDPOINT_SILENCE_MS` | 700 | ↓ if replies feel late; ↑ if premature finals | premature/late finals |

## Artifacts this plan produces
- **NEW** `agent/endpointing.py` — pure mode→endpointing selector.
- **NEW** `tests/test_endpointing.py` — selector truth table (stdlib).
- **MODIFIED** `agent/main.py` — mode-aware endpointing wired live; VAD/interrupt
  knobs named; consolidated feel-knob rationale block.
- **MODIFIED** `.env.example` — trained `STT_ATT_CONTEXT_SIZE=[70,1]`; surfaced
  `STT_STREAM_CHUNK_MS` / `STT_ENDPOINT_SILENCE_MS`.
