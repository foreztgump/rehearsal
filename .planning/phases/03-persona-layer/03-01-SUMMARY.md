---
phase: 03-persona-layer
plan: 03-01
subsystem: api
tags: [persona, system-prompt, byte-stability, frozen-prefix, kokoro-voice, dataclass, livekit-agents]

requires:
  - phase: 02-bare-voice-loop-mvp-gate
    provides: live AgentSession (agent/main.py) with static PERSONA_INSTRUCTIONS + per-plugin metrics scaffold (agent/metrics.py)
provides:
  - agent/persona.py — Persona dataclass + enum->fixed-string knob tables (difficulty/verbosity/correction) + curated Kokoro VOICE_IDS + render_persona (byte-stable frozen-prefix) + DEFAULT_PERSONA + _self_check
  - agent/main.py renders DEFAULT_PERSONA, holds a named `agent` ref (RPC seam for 03-02), and sources the TTS voice from the persona
  - frozen-prefix layout (role -> difficulty -> verbosity -> correction -> footer -> empty KB_SLOT) — the Phase-4 KB cache seam
affects: [03-02, 04-kb-cache]

tech-stack:
  added: []
  patterns:
    - "Pure, livekit-free config module mirroring agent/metrics.py (frozen constants + @dataclass + _self_check under __main__)"
    - "Byte-stable prompt assembly: fixed tuple order of frozen constants joined with a fixed separator; knobs are enum->fixed-string lookups, never interpolated numbers"
    - "Empty trailing KB_SLOT as a frozen-prefix seam (persona -> KB -> history -> turn order frozen now)"

key-files:
  created:
    - agent/persona.py
  modified:
    - agent/main.py

key-decisions:
  - "Knobs map to hand-authored fixed prompt fragments (not interpolated dials) so a given Persona renders identical bytes and the small model follows full instruction sentences."
  - "render_persona joins a FIXED tuple of frozen constants (no f-strings on runtime data, no dict.items(), no volatile data); KB_SLOT='' stays last as the Phase-4 seam."
  - "display_name kept OUT of the prompt prefix (UI label only, MVP) — zero cache impact."
  - "DEFAULT_PERSONA reproduces today's Cybersecurity Trainer (gentle correction = PERS-01, af_bella) so default-on-load behavior is unchanged."
  - "main.py holds a single NAMED agent ref so 03-02's RPC handler can close over it for update_instructions hot-swap; RPC handler itself deferred to 03-02."

patterns-established:
  - "Pattern A (03-PATTERNS.md): pure persona config module = metrics.py shape"
  - "Pattern B1 (03-PATTERNS.md): lift PERSONA_INSTRUCTIONS into rendered default + named agent ref + voice from persona"

requirements-completed: [PERS-07]

duration: 12 min
completed: 2026-06-25
status: complete
---

# Phase 3 Plan 01: Persona config → frozen-prefix system prompt + voice id Summary

**Lifted the static PERSONA_INSTRUCTIONS literal into a pure `agent/persona.py` config module — `Persona` dataclass, difficulty/verbosity/correction enum→fixed-string knob tables (CORRECTION is PERS-07), curated Kokoro voice list, and a byte-stable `render_persona` — then wired `main.py` to render `DEFAULT_PERSONA`, hold a named `agent` ref, and source the TTS voice from the persona, with zero behavior change today.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-25
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- New pure, livekit-free `agent/persona.py` mirroring `agent/metrics.py` shape (frozen constants + `@dataclass` + `_self_check()` under `if __name__ == "__main__":`).
- `render_persona` assembles a byte-stable system prompt by joining frozen constants in a fixed tuple order (`role → difficulty → verbosity → correction → footer → KB_SLOT`), with the empty `KB_SLOT` last as the Phase-4 frozen-prefix seam.
- `CORRECTION` enum (`gentle|moderate|aggressive`) is the PERS-07 mechanism; default `gentle` preserves today's PERS-01 gentle-correction behavior.
- `DEFAULT_PERSONA` (intermediate/balanced/gentle/`af_bella`) reproduces today's Cybersecurity Trainer; `EXPECTED_DEFAULT` golden string locks the default render.
- `_self_check` asserts determinism + golden default + no-placeholder leak + knob-permutation byte-stability; `python3 agent/persona.py` prints `persona _self_check OK`.
- `agent/main.py`: removed `PERSONA_INSTRUCTIONS` literal and standalone `KOKORO_VOICE`; imports `DEFAULT_PERSONA, render_persona`; TTS voice now `DEFAULT_PERSONA.voice_id`; `entrypoint()` builds a NAMED `agent = Agent(instructions=render_persona(DEFAULT_PERSONA))` passed to `session.start(agent=agent, room=ctx.room)`.

## Task Commits

Each task was committed atomically:

1. **Task 03-01-1: create agent/persona.py** — `d012402` (feat)
2. **Task 03-01-2: refactor agent/main.py** — `78e2ed7` (refactor)

## Files Created/Modified
- `agent/persona.py` (new) — `Persona` dataclass; `DIFFICULTY`/`VERBOSITY`/`CORRECTION` knob tables; `ROLE_PREAMBLE`/`SPOKEN_STYLE_FOOTER`/`KB_SLOT`; `VOICE_IDS`; `render_persona`; `DEFAULT_PERSONA`; `EXPECTED_DEFAULT`; `_self_check`.
- `agent/main.py` (modified) — removed `PERSONA_INSTRUCTIONS` + `KOKORO_VOICE`; `from persona import DEFAULT_PERSONA, render_persona`; TTS voice from persona; named `agent` ref in `entrypoint()`.

## Decisions Made
- Knobs are fixed prompt fragments, never interpolated numbers (byte-stability + better small-model instruction-following).
- `render_persona` joins a fixed tuple of frozen constants; KB_SLOT stays empty and last (Phase-4 seam, not reordered/filled).
- `display_name` stays out of the prompt prefix (UI label only, MVP).
- `main.py` holds a single named `agent` ref now (the RPC hot-swap seam); the RPC handler / `update_instructions` / `update_options` calls are deliberately deferred to 03-02.

## Deviations from Plan

None - plan executed exactly as written.

(Minor non-functional adjustment: reworded two docstring/comment lines in `persona.py` so the acceptance greps for `f"`/`.format(`/`.items()`/`datetime|time.|uuid|random|now()` return zero matches against prose as well as code — the literal acceptance commands now pass cleanly. No code-path change.)

## Issues Encountered
None. The only LSP diagnostics in `agent/main.py` are the pre-existing unresolved `livekit.*` imports (the sandbox cannot import livekit), unrelated to this plan's edits.

## Verification

Sandbox-verifiable checks (all PASS):
- `python3 agent/persona.py` → exits 0, prints `persona _self_check OK` (determinism + golden default + no-placeholder + knob-permutation byte-stability).
- `python3 -m py_compile agent/main.py agent/persona.py` → exits 0.
- `render_persona` body has no `f"`/`f'`/`.format(`/`.items()`; module has no `datetime|time.|uuid|random|now()`.
- `CORRECTION` has keys `gentle|moderate|aggressive`; `DEFAULT_PERSONA.correction == "gentle"`; `DEFAULT_PERSONA.voice_id == "af_bella"` and `"af_bella" in VOICE_IDS`; `KB_SLOT = ""` last in `render_persona`'s tuple.
- `main.py`: `from persona import` present; `grep -c PERSONA_INSTRUCTIONS agent/main.py == 0`; named `agent = Agent(instructions=render_persona(DEFAULT_PERSONA))`; TTS voice from `DEFAULT_PERSONA.voice_id`; `git diff --stat agent/metrics.py` empty (unchanged).

## Deferred Operator / VM Gate Items (NOT marked passed)

These require the Proxmox VM + a LAN browser device and are explicitly deferred to operator gates — they are **not** verifiable in this sandbox and are recorded here as open:

- **OPERATOR GATE (Task 03-01-2, VM + browser):** on browser join the agent greets and converses identically to before — same Cybersecurity Trainer behavior, gentle correction, `af_bella` voice (PERS-01 / DEPLOY-03 unchanged). **Status: DEFERRED — not run.**
- **`[VM-INTROSPECT]` (carried to 03-02):** confirm on the installed `livekit-agents ~=1.5` build the signatures of `Agent.update_instructions` (coroutine), `openai.TTS.update_options` (accepts `voice=`), and `rtc.LocalParticipant.register_rpc_method`. **Status: DEFERRED — not run.**
- **`[VM-INTROSPECT]` voice list reconcile:** `curl http://kokoro:8880/v1/audio/voices` to validate each `VOICE_IDS` entry returns audio. **Status: DEFERRED — not run.**

## Next Phase Readiness
- Ready for **03-02**: `agent/persona.py` provides `Persona`, `render_persona`, `DEFAULT_PERSONA`, and `VOICE_IDS`; `agent/main.py` exposes the named `agent` ref the RPC handler will close over. 03-02 builds `PersonaPanel.tsx`, mounts it in `VoiceRoom`, and adds the `persona.update` RPC handler doing `update_instructions` + `update_options`.
- Client-side `VOICE_IDS`/default persona in 03-02 must mirror `agent/persona.py` (file-#6 duplication risk noted in 03-PATTERNS.md).

---
*Phase: 03-persona-layer*
*Completed: 2026-06-25*

## Self-Check: PASSED
