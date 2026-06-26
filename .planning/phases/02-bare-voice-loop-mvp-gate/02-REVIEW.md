# Phase 02 — Bare Voice Loop / MVP Gate — Backfill Code Review

**Reviewer:** Claude (static, sandbox — cannot import livekit / run Docker / GPU)
**Date:** backfill (phase executed with code-review capability disabled)
**Diff range:** `db42e5d^..e2b596d` (reviewing the FIXED final state at `e2b596d`)
**Scope:** Phase-02 voice-loop logic only — greeting/per-turn loop, turn-keyed
metrics buffer, endpointing/barge-in tuning, rolling P50/P95, React
transcript/pill/autoplay-gate. `agent/main.py` + `agent/metrics.py` carry
later phase 3–6 additions (KB ingest, persona/mode RPC, interview endpointing
floor); those are **out of scope** here and noted where they touch Phase-02 code.

**Resolution (backfill fixes):** HIGH-1 + HIGH-2 FIXED in `agent/metrics.py`. HIGH-1: `end_of_utterance_delay` is read from `EOUMetrics` (confirmed against livekit-agents `metrics/base.py` — the field + `speech_id` live on `EOUMetrics`, NOT `VADMetrics`) via a new session-level `metrics_collected` dispatcher (`_on_session_metrics` → `_on_eou_metrics`), so `e2e_ms` now populates and correlates by `speech_id`. HIGH-2: open turn buffers are now bounded by `_MAX_OPEN_TURNS` via `_evict_stale_turns` (oldest-first eviction), so barge-in / errored / internal turns that never reach the TTS flush no longer leak. Verified in-sandbox (EOU dispatch+filter, e2e correlation, eviction cap). MED/LOW left as documented findings.

Files reviewed on disk:
- `agent/main.py` (greeting, `build_session` endpointing/barge-in, `prewarm` VAD)
- `agent/metrics.py` (turn-keyed buffer, e2e_ms, rolling percentiles)
- `web/app/VoiceRoom.tsx`, `AgentStatePill.tsx`, `Transcript.tsx`, `page.tsx`
- `web/app/api/token/route.ts` (cross-file identity contract)

---

## Findings summary by severity

| Sev | # | Finding |
|-----|---|---------|
| HIGH | 1 | VAD-plugin handler reads `end_of_utterance_delay` → `eou_ms` & `user_audio_end` likely never set → **`e2e_ms` (the headline v2v gate metric) is always `None`** |
| HIGH | 2 | `_turns` buffer leaks: turns that never reach the TTS flush (barge-in, false interruption, errored/aborted turns) are never popped → unbounded growth + stale state over a long session |
| MED | 3 | Multiple TTS `metrics_collected` events per turn re-create the popped buffer and re-flush → **duplicate/partial per-turn lines + inflated turn count** |
| MED | 4 | STT attribution via global `_last_turn_key` is order/overlap-fragile; STT firing after the flush is silently dropped |
| LOW | 5 | Warmup cold-start TTFT is recorded into the **live** `llm_ttft` rolling window → skews early P50/P95 |
| LOW | 6 | `e2e_ms` is computed from handler-callback wall-clock, not true audio boundaries — approximation overstates latency; misleading field names |
| LOW | 7 | Transcript renders the unbounded segment list (no cap/virtualization/auto-scroll) |
| LOW | 8 | Fragile cross-file `user-` identity-prefix contract between token route and Transcript |
| LOW | 9 | `NEXT_PUBLIC_LIVEKIT_URL!` non-null assertion → opaque runtime failure if unset |
| LOW | 10 | Greeting `generate_reply` fires before browser autoplay unlock is guaranteed |
| INFO | 11 | `turn_handling`/`interruption` are `TypedDict(total=False)` → a wrong/renamed key silently no-ops the tuning (VM-introspection-pending) |
| INFO | 12 | No secrets hardcoded; `api_key="none"` + model tags are intentional & documented |
| INFO | 13 | Rolling P50/P95 indexing is **correct**; module-global mutation is safe under the single asyncio-loop assumption |

---

## HIGH

### 1. `e2e_ms` is almost certainly always `None` — EOU delay is not on VADMetrics
`agent/metrics.py:238-247`, wired in `attach()` at `:257-266`.

`_on_vad_metrics` is subscribed to the **`vad`** plugin (`"vad": _on_vad_metrics`)
and reads `getattr(metric, "end_of_utterance_delay", None)`. In livekit-agents
the per-plugin `vad.metrics_collected` event emits `VADMetrics`
(`inference_duration_total`, `inference_count`, …) — `end_of_utterance_delay`
lives on **`EOUMetrics`**, which is emitted by the turn detector / session span,
not the VAD plugin. VADMetrics also carries no `speech_id`.

Consequences, all on the Phase-02 headline gate:
- `buffer.eou_ms` stays `None` → every turn line reports `eou_ms: null`.
- `buffer.user_audio_end` is never stamped → in `_flush_turn` the
  `user_audio_end is not None and agent_audio_start is not None` guard fails →
  **`e2e_ms` is always `None`.** The "rolling e2e P50 < ~1.2s" MVP gate
  (`02-03-SUMMARY` §gates) can never populate from this path.
- Because EOU lands on `_PENDING_KEY` (no speech_id) when/if it fires at all,
  the turn key correlation the whole buffer is built on doesn't anchor.

This is the single most important correctness issue in the phase. It is
hedged in the summary as "VM-introspection-pending," but the field/plugin
mismatch is determinable statically and should block the metric being trusted.

**Recommend:** subscribe the EOU handler to whatever surface actually emits
`EOUMetrics` (the turn-detector / session `metrics_collected`, filtered by
metric type), or compute `user_audio_end` from the EOU metric that carries a
`speech_id`. Confirm metric types on the installed `~=1.5` via
`inspect`/`isinstance` on the VM before trusting any e2e number.

---

## HIGH

### 2. Turn-buffer leak: buffers are only popped on the TTS flush
`agent/metrics.py:86-95` (`_buffer_for` create), `:98-116` (`_flush_turn` pop),
called only from `_on_tts_metrics` (`:225-235`).

A buffer is created lazily for any metric key and **only ever removed inside
`_flush_turn`, which only runs when a TTS metric fires.** Any turn that produces
EOU/STT/LLM metrics but never reaches a TTS metric leaves its buffer in `_turns`
forever:
- user speech → VAD/turn-detect/LLM start, then **barge-in / false interruption
  cancels** before TTS (exactly the case the barge-in tuning at `main.py:236-240`
  is designed to produce);
- LLM/TTS error or aborted generation;
- the internal `generate_reply` priming/greeting/mode-enter turns
  (`main.py:516`, `:433`, `:527`) whose metric keys may not map to a TTS flush.

Over a long open-mic session this is an **unbounded dict leak** plus stale
half-filled buffers. The `_PENDING_KEY` buffer additionally accumulates
overwritten timestamps that are never cleared.

**Recommend:** cap/evict by inserting order (e.g. flush-or-drop the oldest open
buffers beyond a small N), or tie buffer lifetime to a turn-lifecycle event so
cancelled turns are reclaimed. At minimum, periodically GC `_turns` older than
a few turns.

---

## MEDIUM

### 3. Multiple TTS metric events per turn → duplicate / partial emissions
`agent/metrics.py:225-235`.

`_on_tts_metrics` calls `_buffer_for(metric)` (get-or-create) and then
`_flush_turn(key)` which **pops** the buffer. If the TTS plugin emits more than
one `metrics_collected` for a turn (segmented/streamed synthesis is common),
the second event finds no buffer, `_buffer_for` **re-creates a fresh empty one**,
sets only `tts_ttfb_ms`, stamps a new `agent_audio_start`, and flushes again →
a second per-turn JSON line with `eou/stt/llm/e2e = null`. This:
- emits duplicate/partial turn lines,
- double-counts `_turns_emitted`, throwing off the `% SUMMARY_EVERY_TURNS`
  cadence,
- pollutes the `tts_ttfb` rolling window with extra samples.

**Recommend:** flush a turn at most once (guard on an already-flushed set, or
only flush when the buffer has the expected stages), or anchor flush on an
explicit end-of-turn event rather than "first TTS metric."

---

## MEDIUM

### 4. STT attribution via global `_last_turn_key` is fragile
`agent/metrics.py:215-222`, `_last_turn_key` mutated in `_buffer_for` (`:88-94`).

STTMetrics has no `speech_id`, so STT duration is attached to whatever buffer was
"most recently touched." With barge-in, overlapping/preemptive turns, or simply
STT firing after the TTS flush popped the buffer, `_turns.get(_last_turn_key)`
returns `None` and the STT sample is **silently dropped**, or it lands on the
wrong turn. Documented as a known limitation, but worth recording: `stt_ms` is
the least trustworthy field and shouldn't gate anything.

---

## LOW

### 5. Warmup cold-start TTFT contaminates the live rolling window
`agent/metrics.py:202-207` → `emit_turn(llm_ttft_ms=...)` → `_record("llm_ttft", …)`.

`emit_warmup_metric` routes the startup warmup TTFT through `emit_turn`, which
records it into the same `_samples["llm_ttft"]` deque used for the live
percentile gate. The first cold inference is an outlier that skews early P50/P95
until it rolls out of the 100-sample window. Consider emitting the warmup line
without recording it into the live window.

### 6. `e2e_ms` measures handler wall-clock, not audio boundaries
`agent/metrics.py:71-72`, `:105-106`, `:234`, `:247`.

`user_audio_end`/`agent_audio_start` are `time.monotonic()` stamped at *handler
invocation* (when the EOU/TTS metric event is delivered), not the true last-user-
frame / first-agent-frame timestamps. The EOU metric is delivered after STT +
turn detection, so this systematically **overstates** the v2v span, and the field
names imply a precision the values don't have. Acceptable as a stopgap (no
LiveKit v2v field exists), but label it as an approximation so the < ~1.2s gate
isn't read literally.

### 7. Transcript grows unbounded
`web/app/Transcript.tsx:16-37`. `useTranscriptions()` returns all segments and
the component maps every one with no cap, virtualization, or auto-scroll. Fine
for a short MVP demo; will bloat DOM and scroll awkwardly in a long session.

### 8. Fragile cross-file identity-prefix contract
`web/app/Transcript.tsx:7` (`USER_IDENTITY_PREFIX = "user-"`) vs
`web/app/api/token/route.ts:13,27` (`user-${Date.now()}`). The two-sided split
depends on these strings staying in lock-step. If the token route's identity
scheme changes, Transcript silently mis-attributes **every** message to the agent
side with no error. Consider deriving the local identity from the room/participant
context instead of string-prefix matching.

### 9. `NEXT_PUBLIC_LIVEKIT_URL!` non-null assertion
`web/app/VoiceRoom.tsx:12`. If the env var is missing at build time the `!`
suppresses the type error and the failure surfaces later as an opaque LiveKit
connect error. A guarded check with a clear message would fail faster.

### 10. Greeting may fire before autoplay is unlocked
`agent/main.py:527` fires `generate_reply(GREETING_INSTRUCTIONS)` at the end of
`entrypoint`, immediately after connect/start. The browser autoplay unlock is a
backstop (`<StartAudio/>`, `VoiceRoom.tsx:82`) gated on a user gesture; if the
agent greeting is produced before playback is enabled the learner can miss the
first utterance. The "Start talking" click is the gesture, so this usually works,
but the ordering isn't guaranteed by anything in the code. Worth a live operator
check (already listed as a deferred gate).

---

## INFO / Notes

### 11. TypedDict `total=False` hides config typos
`agent/main.py:229-241` (`turn_handling`) + interruption keys. As the code's own
comment notes, unknown keys degrade by being ignored. The flip side: a wrong key
name (or a key the installed `~=1.5` build dropped/renamed — `mode: "dynamic"`,
`resume_false_interruption`, `false_interruption_timeout`) **silently no-ops the
tuning** with no error. The VM-introspection-pending checks in the summaries are
the right mitigation; flagging that "no exception" ≠ "applied."

### 12. No secrets / no problematic hardcoded tags
- No credentials in source. `api_key="none"` (`main.py:163,184`) are placeholders
  for local OpenAI-compat endpoints, not secrets.
- `WHISPER_MODEL = "Systran/faster-whisper-large-v3"` (`:45`) and
  `KOKORO_MODEL = "tts-1"` (`:51`) are intentional and well-documented (the
  `e2b596d` fix commit explains both: the `-turbo` repo 404s; non-`tts-1` names
  take the SSE path kokoro ignores). The LLM tag still resolves from
  `OLLAMA_MODEL` via `resolved_llm_tag()` (`:114-119`) — no hardcoded gemma tag.
- Token secret stays server-side (`api/token/route.ts:17-25`); only the WS URL is
  `NEXT_PUBLIC_`. Good.

### 13. Things that are correct (verified statically)
- **Rolling percentile math** (`metrics.py:139-145`): `quantiles(window, n=100,
  method="inclusive")` returns 99 cut points; `cuts[49]`→P50, `cuts[94]`→P95 is
  the right indexing, and the `len(window) < 2` guard correctly avoids the
  `quantiles` "at least two data points" error and the empty case.
- **Module-global mutation without locks** (`_turns`, `_last_turn_key`,
  `_turns_emitted`): safe *given* metrics handlers run as sync callbacks on the
  single agent asyncio loop. If any plugin ever dispatches from another thread,
  this becomes racy — worth confirming on the VM, but not a defect under the
  current model.
- **AgentStatePill** (`AgentStatePill.tsx`): `STATE_COLORS[state] ?? fallback`
  handles unknown states; no effect/cleanup needed (pure render off a hook). OK.
- **VoiceRoom autoplay gate**: token-state machine is sound; `LiveKitRoom`
  owns connect/disconnect lifecycle on unmount, so no manual cleanup leak.

---

## Scope note (later-phase code on disk)
The current on-disk `ENDPOINTING_MIN_DELAY` is the **Phase-06 interview floor
(0.7s)** (`main.py:79,104`), not Phase-02's tuned `0.3s`. The barge-in/interruption
dict (`min_duration 0.3`, `resume_false_interruption`, `false_interruption_timeout
2.0`) and VAD `activation_threshold=0.65` (`prewarm`, `:260`) are the Phase-02
values and reviewed as such. KB-ingest, persona/mode RPC handlers, and
`HistoryWindowAgent` are phases 3–6 additions — flagged out of scope per the
review brief; other reviewers cover them.

---

## Recommended priority
1. **Finding 1** — fix the EOU source so `e2e_ms` actually populates; the MVP
   latency gate is unmeasurable otherwise. (HIGH)
2. **Findings 2 & 3** — make the buffer leak-free and idempotent per turn before
   any long-running session. (HIGH/MED)
3. Findings 4–6 — tighten metric attribution/semantics so the numbers are
   trustworthy. (MED/LOW)
4. Findings 7–10 — UI/robustness polish. (LOW)

None of these are security issues. The dominant theme is that the **per-turn
metrics buffer — the phase's marquee deliverable — has a correctness gap (e2e
never computes) and a lifecycle gap (leaks on the very barge-in turns the phase
tunes for)**. The voice-loop wiring, persona/greeting path, endpointing/barge-in
config, and React components are otherwise sound for an MVP, pending the
documented live VM operator gates.
