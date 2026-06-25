---
phase: 02-bare-voice-loop-mvp-gate
plan: 02-03
subsystem: agent
tags: [livekit, livekit-agents, agentsession, turn_handling, endpointing, barge-in, silero-vad, metrics, latency, aec]

requires:
  - phase: 02-bare-voice-loop-mvp-gate
    provides: 02-02 wired the conversing loop (greeting + per-turn replies + Cybersecurity Trainer persona + thinking-OFF); 02-01 added browser room UI + client-side AEC constraints (audioCaptureDefaults)
provides:
  - Endpointing pinned on the NON-deprecated turn_handling dict surface (dynamic mode, min_delay 0.3s) with MultilingualModel nested as the semantic turn detector
  - Barge-in/interruption gate tuned (interruption.min_duration 0.3s, resume_false_interruption + 2.0s false_interruption_timeout) without disabling interruptions
  - Silero VAD activation_threshold raised 0.5 -> 0.65 in prewarm() to defend open-mic false triggers
  - Real per-turn voice-to-voice metrics: turn-keyed buffer (by speech_id) flushing ONE consolidated emit_turn() per turn with a computed e2e_ms, e2e added to the rolling window, periodic P50/P95 summary line
  - Headphones recommendation in the browser UI (client-side AEC is the sole, local-first echo defense)
affects: [metrics, latency-validation, phase-4, phase-5, kb-injection]

tech-stack:
  added: []
  patterns:
    - "Endpointing/interruption configured via the consolidated turn_handling TypedDict (passed as a plain dict) — the non-deprecated surface; MultilingualModel nested under turn_handling['turn_detection'] (top-level turn_detection is dropped when turn_handling is given)"
    - "Per-turn metric consolidation = turn-keyed buffer keyed by LiveKit speech_id; EOU handler stamps user_audio_end, first TTS handler stamps agent_audio_start and flushes; e2e_ms = agent_audio_start - user_audio_end (computed — no LiveKit v2v field exists)"
    - "Sandbox-conservative kwarg discipline carried from 02-02: surfaces verified against tagged livekit-agents source (1.5.0..1.6.4) since livekit is not importable here; each is flagged VM-introspection-pending in code + summary"

key-files:
  created: []
  modified:
    - agent/main.py
    - agent/metrics.py
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Plan BLOCKER premise ('two mutually-incompatible endpointing surfaces; wrong one = TypeError') is DISPROVEN by reading the real AgentSession source across livekit-agents@1.5.0, @1.5.17, @1.6.4: BOTH surfaces coexist for the whole ~=1.5/1.6 range. Direct kwargs (min_endpointing_delay, min_interruption_duration, etc.) are DEPRECATED-but-accepted (migrated internally via _migrate_turn_handling, NO TypeError); the turn_handling dict is the non-deprecated consolidated surface and the ONLY one exposing dynamic endpointing mode. Chose the dict surface (future-proof + dynamic preferred per Pattern D1)."
  - "Per-turn consolidation: chose option (a) turn-keyed buffer over option (b) per-stage + separate e2e line. The buffer keys by speech_id (verified present on EOU/LLM/TTS metric objects in metrics/base.py), flushes ONE consolidated emit_turn per turn on the TTS stage, and holds the e2e correlation timestamps. Single consolidated line is the cleaner reader contract for Phase 4/5."
  - "e2e_ms source = buffered handler timestamps, NOT a LiveKit field. Source introspection of metrics/base.py (1.5.0..1.6.4) confirms NO single end-to-end voice-to-voice field on MetricsReport/EOUMetrics — only per-stage timings. e2e_ms = agent_audio_start (first TTS handler, time.monotonic) - user_audio_end (EOU handler, time.monotonic)."
  - "STTMetrics carries no speech_id (only request_id), so STT duration attaches to the most-recently-touched open buffer (_last_turn_key). Documented limitation; STT is a small bounded stage."

patterns-established:
  - "turn_handling dict surface for all endpointing/interruption tuning (not the deprecated direct kwargs)"
  - "Turn-keyed (speech_id) metric buffer flushing one consolidated per-turn line + periodic rolling P50/P95"
  - "Runnable pure-stdlib _self_check() in agent/metrics.py (python3 agent/metrics.py) proving percentile math + e2e window + key-name contract without livekit"

requirements-completed: [VOICE-03, VOICE-04, VOICE-08, PERF-01]

duration: 18min
completed: 2026-06-25
status: complete
---

# Phase 2 Plan 02-03: Tune + measure — barge-in, endpointing, AEC, per-turn v2v latency Summary

**Endpointing pinned on the non-deprecated `turn_handling` dict (dynamic, min_delay 0.3s, MultilingualModel nested), barge-in gate tuned (min_duration 0.3s + false-interruption resume), Silero VAD threshold raised to 0.65, and real per-turn voice-to-voice metrics via a speech_id-keyed buffer that computes `e2e_ms` and emits rolling P50/P95 — all API surfaces source-verified against tagged livekit-agents (1.5.0–1.6.4) rather than guessed.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 4
- **Files modified:** 3 (agent/main.py, agent/metrics.py, web/app/VoiceRoom.tsx)

## Accomplishments

- **Resolved the endpointing BLOCKER by reading real source, not guessing.** The sandbox cannot import livekit, so the two-surfaces question was answered by fetching `voice/agent_session.py` + `voice/turn.py` at tags `livekit-agents@1.5.0`, `@1.5.17`, `@1.6.4`. Finding: both surfaces coexist; direct kwargs are deprecated-but-migrated (no `TypeError`); the `turn_handling` dict is non-deprecated and the only one with `mode: "dynamic"`. Configured one surface: `turn_handling={"turn_detection": MultilingualModel(), "endpointing": {"mode": "dynamic", "min_delay": 0.3, "max_delay": 3.0}}`.
- **Tuned the barge-in gate** inside the same dict: `interruption.min_duration = 0.3` (require ~300ms of real speech before cancel — defends against echo tail + "mm-hmm"), `resume_false_interruption = True` + `false_interruption_timeout = 2.0` (a no-transcript noise blip resumes the agent instead of dropping the turn). Interruptions stay ON (no `enabled: False`).
- **Raised Silero VAD `activation_threshold` 0.5 → 0.65** at `silero.VAD.load(...)` in `prewarm()` (param verified present in the plugin's `vad.py`).
- **Implemented real per-turn metrics** (option a): a `speech_id`-keyed `_TurnBuffer` accumulates each stage as its handler fires; the EOU handler stamps `user_audio_end`, the first TTS handler stamps `agent_audio_start` and flushes ONE consolidated `emit_turn(...)`; `e2e_ms = agent_audio_start - user_audio_end`. Added `e2e` to the rolling windows, a periodic P50/P95 summary line every 10 turns, and a runnable `_self_check()` (executed here — percentiles numeric, e2e windowed, key names stable).
- **Confirmed client-side AEC is the sole echo defense** and added a headphones hint to the UI. No server-side noise-cancellation plugin anywhere.

## Task Commits

1. **Task 02-03-1: pin endpointing on turn_handling dict (dynamic, min_delay 0.3s)** - `8f61ab9` (feat)
2. **Task 02-03-2: tune barge-in gate (min_duration, resume false interruptions, VAD 0.65)** - `3c4e4e0` (feat)
3. **Task 02-03-3: headphones hint; client AEC is sole echo defense** - `a318dfb` (feat)
4. **Task 02-03-4: turn-keyed buffer + real e2e_ms + rolling P50/P95** - `3d60553` (feat)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `agent/main.py` (modified):
  - `build_session()` — endpointing + interruption on the `turn_handling` dict; MultilingualModel nested as the semantic turn detector; documenting comment records the verified surface + VM-introspection-pending command
  - `prewarm()` — `silero.VAD.load(activation_threshold=0.65)`
- `agent/metrics.py` (modified):
  - `_TurnBuffer` dataclass + `_turn_key`/`_buffer_for`/`_flush_turn`; handlers rewritten to buffer (not emit independently)
  - `e2e` added to budgets + recorded rolling windows; `emit_rolling_summary()`; `_self_check()` + `__main__`
  - per-turn JSON key names unchanged (`eou_ms/stt_ms/llm_ttft_ms/tts_ttfb_ms/e2e_ms/over_budget`)
- `web/app/VoiceRoom.tsx` (modified): headphones recommendation hint; AEC constraints confirmed unchanged

## Decisions Made

- **Dict surface over direct kwargs** — see key-decisions. The plan allowed either; the dict is non-deprecated and the only path to dynamic endpointing.
- **Option (a) turn-keyed buffer** for per-turn consolidation, keyed by `speech_id`, flushing on the TTS stage.
- **`e2e_ms` computed from handler timestamps** because no LiveKit v2v field exists (introspected in `metrics/base.py`).

## Deviations from Plan

**[Rule 1 - Corrected premise, not a code bug] The plan's stated BLOCKER ("two mutually-incompatible surfaces; passing the wrong one throws TypeError") is factually incorrect for `~=1.5`.**
- **Found during:** Task 02-03-1.
- **Issue:** The plan instructed to pick exactly ONE surface to avoid a `TypeError`. Reading the real tagged source (`livekit-agents@1.5.0/@1.5.17/@1.6.4`) shows the direct kwargs and the `turn_handling` dict BOTH exist in every `__init__` across the range; the direct kwargs are deprecated and migrated internally (`_migrate_turn_handling`), so neither throws. The "TypeError" risk does not exist on this line.
- **Fix:** Still configured exactly one surface (the dict), satisfying the plan's spirit and acceptance criteria, and documented the corrected finding in code + here. No functional risk introduced.
- **Files modified:** agent/main.py
- **Verification:** `python3 -m py_compile agent/main.py` exits 0; grep confirms one surface, min_delay 0.3, MultilingualModel retained.
- **Committed in:** `8f61ab9`

**Total deviations:** 1 (a corrected planning premise, no scope change). **Impact:** None on deliverables — all acceptance criteria met; the correction is documented so the operator does not waste the VM gate chasing a non-existent TypeError.

## Issues Encountered

- A `grep -Ei "prometheus|opik|otel|grafana"` acceptance check initially matched my own explanatory comment ("no Prometheus/Opik/OTEL export"). Reworded the comment to "no external telemetry export of any kind" so the prohibition grep returns nothing while preserving intent.

## Operator Gates (deferred — VM + LAN device)

This sandbox has **no Docker daemon, no GPU, no browser, and `livekit-agents` is not importable** (`ModuleNotFoundError: No module named 'livekit'`). The following are NOT executed here and are **NOT marked passed**.

### VM-introspection-pending kwargs (grounded on tagged source; confirm on the installed build)
All three were verified against `livekit-agents@1.5.0`, `@1.5.17`, `@1.6.4` source, but the exact installed `~=1.5` resolution must be confirmed on the VM:
- **Endpointing surface** — `python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.__init__))"`. Expect `turn_handling: NotGivenOr[TurnHandlingOptions]` present (it is, 1.5.0→1.6.4). Fallback surface if ever needed: the deprecated direct kwargs `min_endpointing_delay=0.3, max_endpointing_delay=3.0` (accepted, migrated — but NO dynamic mode).
- **Interruption keys** — confirm `InterruptionOptions` accepts `min_duration`, `resume_false_interruption`, `false_interruption_timeout` on the installed build (verified in `voice/turn.py` for the range). TypedDict `total=False` means unknown keys are ignored, so this degrades gracefully.
- **Silero VAD** — `python -c "import inspect; from livekit.plugins import silero; print(inspect.signature(silero.VAD.load))"`. Confirm `activation_threshold` (default 0.5; verified in plugin `vad.py`).
- **v2v field** — confirm no single end-to-end field appears on `MetricsReport`/`EOUMetrics` on the installed build (none in 1.5.0→1.6.4). If a future build adds one, prefer it over the computed timestamp.

### Deferred MANUAL operator gates (audible / live — speakers+mic worst case)
- **[02-03-1] Slow-speech endpointing (VOICE-04):** on hesitant speech ("let me think… the answer is…") the agent does not cut in mid-thought and does not leave dead air after a clear finish.
- **[02-03-2] Instant barge-in (VOICE-03):** talking over the agent stops its speech within ~1 frame; the agent does NOT self-interrupt on its own echo tail or a short backchannel.
- **[02-03-3] Acoustic echo (VOICE-08):** laptop speakers + built-in mic in a small room — the agent does not self-interrupt from hearing its own output (Pitfall 5); headphones path is clean.
- **[02-03-4] Live latency (VOICE-08, PERF-01):** over a session of N turns the per-turn lines show populated stage numbers and a rolling e2e **P50 < ~1.2s**.

## Client-Verifiable Criteria (executed here — all PASS)

- `python3 -m py_compile agent/main.py agent/metrics.py` exits 0 — PASS.
- Exactly ONE endpointing surface, `min_delay: 0.3` ∈ [0.25, 0.35] — PASS.
- `MultilingualModel()` retained as the turn detector — PASS.
- `interruption.min_duration` set; VAD `activation_threshold=0.65` — PASS.
- `allow_interruptions` not disabled (no `enabled: False`) — PASS.
- `web/app/VoiceRoom.tsx` keeps `echoCancellation/noiseSuppression/autoGainControl: true` (3 matches) — PASS.
- `grep -Ri "ai_coustics|krisp|noise_cancellation" agent/ web/app` returns nothing — PASS.
- Headphones recommendation present in UI — PASS.
- `e2e` added to recorded rolling windows; `rolling_percentiles("e2e")` numeric given ≥2 samples — PASS (self-check).
- `emit_turn` called with a real `e2e_ms` (from buffer flush) — PASS.
- Periodic P50/P95 summary emitted; `_self_check()` runs (`python3 agent/metrics.py`) — PASS.
- `grep -Ei "prometheus|opik|otel|grafana" agent/metrics.py` returns nothing — PASS.
- Per-turn JSON keys unchanged (`eou_ms/stt_ms/llm_ttft_ms/tts_ttfb_ms/e2e_ms/over_budget`) — PASS.

## Next Phase Readiness

- Phase 2's tuning + measurement layer is in place: endpointing on the correct surface, barge-in gate tuned, VAD hardened, client AEC confirmed sole echo defense, and a stable consolidated per-turn metric line with a real `e2e_ms` + rolling P50/P95. The flat-TTFT measurement contract (stable key names) is preserved for Phase 4/5.
- The Phase-2 hard MVP gate (audible loop: instant barge-in, semantic slow-speech wait, no self-echo, rolling e2e P50 < ~1.2s) closes on the operator's VM + LAN-device run — all such gates recorded above, none fabricated.

## Self-Check: PASSED

- Modified files exist on disk: agent/main.py, agent/metrics.py, web/app/VoiceRoom.tsx — confirmed.
- `git log --oneline --grep="02-03"` returns 4 task commits — confirmed.
- All client-verifiable acceptance criteria re-run and PASS; both `py_compile` exit 0; `_self_check()` passes from committed state.
- Deferred operator gates + VM-introspection-pending kwargs documented above; none fabricated or marked passed.

---
*Phase: 02-bare-voice-loop-mvp-gate*
*Completed: 2026-06-25*
