---
phase: 08-llm-speed-selector-part-a
plan: 08-01
subsystem: llm
tags: [ollama, livekit, rpc, react, model-swap, num_predict]

requires:
  - phase: 06-interview-mode
    provides: handle_mode_update validate-before-mutate RPC template + current_mode/current_role holders + InterviewPanel side-panel clone target
  - phase: 03-persona-layer
    provides: session.tts.update_options in-place swap pattern + persona.update RPC + resolved_llm_tag env resolver
provides:
  - Fast/Better response-model resolver (resolved_model_tag) reading OLLAMA_MODEL_FAST/OLLAMA_MODEL_BETTER (no hardcoded tag)
  - model.update RPC performing a validate-before-mutate in-place session.llm._opts.model swap (no teardown, next-turn effective)
  - current_model[0] per-session holder defaulting to Fast
  - LIVE_NUM_PREDICT_CAP applied once via session.llm._opts.max_completion_tokens (closes the live num_predict gap, both models)
  - web/app/ModelPanel.tsx two-option picker with OUTCOME labels only, mounted in VoiceRoom
  - .env.example documenting both picker tags + OLLAMA_MODEL Fast back-compat alias
  - livekit-plugins-openai pinned ==1.6.4 (deterministic swap surface)
affects: [08-02-pull-pin-verify-build, phase-10-co-residency]

tech-stack:
  added: []
  patterns:
    - "In-place LLM retarget: session.llm._opts.model = tag (re-read per chat(), same instance ⇒ metrics_collected survives) — mirrors the proven TTS voice swap"
    - "model.update RPC clones handle_mode_update's validate-before-mutate but drops update_instructions + generate_reply (a model swap touches only the LLM tag, lands next turn)"
    - "num_predict cap mapped via OpenAI max_completion_tokens on _opts, set once after metrics.attach"

key-files:
  created:
    - web/app/ModelPanel.tsx
  modified:
    - agent/main.py
    - agent/requirements.txt
    - web/app/VoiceRoom.tsx
    - .env.example

key-decisions:
  - "num_predict cap sized at 256 to the SPOKEN_STYLE_FOOTER 'a sentence or two' budget; named constant LIVE_NUM_PREDICT_CAP (no magic value)"
  - "Cap pinned to the single entrypoint site after metrics.attach (session.llm reachable there); NOT in build_session (returns AgentSession inline)"
  - "current_model holder does NOT feed compose_instructions() — it is the simpler axis driving only _opts.model"
  - "Fast tag (evalengine/unbound-e2b:latest) is both the picker default and the OLLAMA_MODEL back-compat alias so warmup/vram/distill/Modelfile keep working"

patterns-established:
  - "Hand-mirrored choice-key seam (web CHOICES ↔ agent MODEL_CHOICES) with duplication-seam warning — no model.get RPC, RPC ack only (MVP)"
  - "OUTCOME-label-only picker: never surface a raw Ollama tag or latency/token number in the UI"

requirements-completed: [LLM-01, LLM-02, LLM-03, LLM-04]

duration: 18 min
completed: 2026-06-26
status: complete
---

# Phase 8 Plan 01: LLM Picker + In-Place Agent Swap Summary

**Fast/Better Ollama response-model picker wired end-to-end — ModelPanel → model.update RPC → validate-before-mutate in-place `session.llm._opts.model` swap (no session teardown, next-turn effective) + a one-site `max_completion_tokens` num_predict cap.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-26T06:27Z
- **Completed:** 2026-06-26
- **Tasks:** 4
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- Generalized the env tag resolver into a Fast/Better `resolved_model_tag(choice)` with the same SystemExit-if-unset posture (no hardcoded gemma tag).
- Added the `model.update` RPC: validates `{choice}` against `MODEL_CHOICES` before mutating, then retargets the SAME `openai.LLM` instance in place — so the `metrics_collected` subscription survives, no teardown, no agent turn injected, current TTS uninterrupted, thinking stays off.
- Closed the pre-existing live num_predict gap with a single `session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP` after `metrics.attach`, applying to both models.
- Created `web/app/ModelPanel.tsx` (cloned from InterviewPanel) — two-option picker, OUTCOME labels only, defaults Fast, reuses the ApplyState ack — and mounted it in VoiceRoom.
- Documented both picker env vars and kept `OLLAMA_MODEL` as the Fast back-compat alias; pinned `livekit-plugins-openai==1.6.4`.

## Task Commits

1. **Task 1: Pin openai plugin** - `f18fc16` (build)
2. **Task 2: Resolver + holder + RPC + swap + cap** - `9123478` (feat)
3. **Task 3: ModelPanel + VoiceRoom mount** - `01be8c5` (feat)
4. **Task 4: .env.example env vars** - `7d39a67` (docs)

## Files Created/Modified
- `agent/main.py` - MODEL_CHOICES/DEFAULT_MODEL_CHOICE/_MODEL_ENV/LIVE_NUM_PREDICT_CAP constants; `resolved_model_tag`; build_session at Fast tag; `_opts.max_completion_tokens` cap; `current_model` holder; `handle_model_update` registered on `model.update`.
- `web/app/ModelPanel.tsx` (new) - two-option `<select>`, OUTCOME labels, `model.update {choice}` RPC, ApplyState ack.
- `web/app/VoiceRoom.tsx` - import + `<ModelPanel />` in the side-panel row.
- `agent/requirements.txt` - `livekit-plugins-openai==1.6.4`.
- `.env.example` - `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`; `OLLAMA_MODEL` repointed to Fast.

## Decisions Made
- num_predict cap = 256, sized to the spoken "sentence or two" budget; named constant, no magic value.
- Cap set at exactly one site (entrypoint, after metrics.attach) — not build_session, which returns the AgentSession inline.
- `current_model` is a standalone axis (does not feed compose_instructions).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. The `livekit.*` import LSP errors in agent/main.py are expected (the sandbox cannot import livekit) and do not affect `py_compile`.

## User Setup Required
None - no external service configuration required in this plan (the live `.env` pull/pin is Wave 2).

## Next Phase Readiness
- Sandbox-verifiable gates all PASS: `py_compile agent/main.py`, persona/interview self-checks, `tsc --noEmit` in web/.
- **DEFERRED to Wave 2 (08-02 `08-LLM-VERIFY.md`) — operator/VM gates, NOT run here:**
  - `[VM-INTROSPECT]` Gate 1: confirm `has update_options: False`, `_opts` has `model`/`reasoning_effort`/`max_completion_tokens`, frozen `False`, plugin `1.6.4`.
  - Live swap Gate C: toggle Fast↔Better mid-session applies, lands next turn, no TTS interrupt, no injected agent turn, logs show new tag.
  - num_predict cap: "count to 500" probe truncates on both models.
  - Requires `docker compose build web agent && docker compose up -d` first (baked-image invariant).
- Plan 08-02 (Wave 2) pulls/pins both tags, adds the per-build verify gate, and authors the operator runbook.

## Self-Check: PASSED

- `python3 -m py_compile agent/main.py` → exit 0
- `python3 agent/persona.py` → `persona _self_check OK`
- `python3 agent/interview.py` → `interview _self_check OK`
- `npx tsc --noEmit` (web/) → exit 0
- All key files exist on disk; 4 task commits present under `08-01`.

---
*Phase: 08-llm-speed-selector-part-a*
*Completed: 2026-06-26*
