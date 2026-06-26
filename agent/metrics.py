"""Per-stage latency metrics scaffold for the Adept voice loop (Plan 01-03).

Walking-skeleton scope: the plumbing exists and emits ONE real line at startup
(the warmup LLM TTFT) — no live voice turn yet. Per-turn fields that need a real
call (eou_ms, stt_ms, tts_ttfb_ms, e2e_ms) are null until Phase 2.

Design rules baked in here:
  * Subscribe to the NON-deprecated PER-PLUGIN `metrics_collected` event on each
    stage plugin instance (llm/stt/tts). EOUMetrics (end_of_utterance_delay +
    speech_id) is emitted ONLY on the session-level `metrics_collected` event — not
    by the VAD plugin — so EOU is taken from the session event, filtered by type.
  * LiveKit metric objects report seconds; we emit milliseconds.
  * Budget constants are the flat-TTFT alert thresholds; a stage over budget is
    flagged in the emitted line.
  * Local logs ONLY — stdout / local file. No external telemetry export of any
    kind (no metrics-scraper, tracer, or dashboard push); PERF-03 requires that
    nothing leaves the LAN.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import quantiles
from typing import Any

# Per-stage latency budgets (milliseconds). These encode the flat-TTFT
# invariant: each stage must stay under budget for voice-to-voice P50 < 1.0s.
# `e2e` is the phase-2 voice-to-voice gate (P50 < ~1.2s this phase).
BUDGET_MS: dict[str, int] = {
    "eou": 300,         # end-of-utterance / turn-detection decision
    "stt": 150,         # speech-to-text transcription
    "llm_ttft": 300,    # LLM time-to-first-token
    "tts_ttfb": 150,    # TTS time-to-first-byte
    "playout": 100,     # audio playout scheduling
    "e2e": 1200,        # end-to-end voice-to-voice (Phase 2 gate: P50 < ~1.2s)
}

# Rolling window size for the P50/P95 aggregation stub.
ROLLING_WINDOW = 100
_MS_PER_SECOND = 1000.0

# Per-stage rolling samples for the P50/P95 aggregation.
_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=ROLLING_WINDOW))

# Emit a rolling P50/P95 summary line once every N consolidated turns.
SUMMARY_EVERY_TURNS = 10


# --- Per-turn consolidation (Plan 02-03-4, option (a): turn-keyed buffer) ----
# The per-plugin handlers each fire with ONE stage populated, so without a
# buffer there is no single per-turn record and nowhere to anchor a real
# `e2e_ms`. We buffer each stage by the LiveKit `speech_id` (present on the
# EOU/LLM/TTS metric objects — verified in metrics/base.py) and flush ONE
# consolidated emit_turn() per turn when the TTS stage fires (the last stage of
# the voice-to-voice span). e2e_ms is sourced from THIS buffer's handler
# timestamps, NOT a LiveKit field: source introspection (metrics/base.py across
# livekit-agents@1.5.0..@1.6.4) shows NO single end-to-end v2v field on
# MetricsReport/EOUMetrics — only per-stage timings — so we compute
# e2e_ms = agent_audio_start - user_audio_end from monotonic timestamps captured
# when the EOU handler (user finished) and the first TTS handler (agent starts
# speaking) fire. STTMetrics carries NO speech_id (only request_id), so its
# duration is attached to the most-recently-touched open buffer (documented
# limitation; STT is a small, bounded stage).
@dataclass
class _TurnBuffer:
    eou_ms: float | None = None
    stt_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttfb_ms: float | None = None
    user_audio_end: float | None = None     # monotonic ts at EOU handler
    agent_audio_start: float | None = None   # monotonic ts at first TTS handler


_PENDING_KEY = "_pending"
_turns: dict[str, _TurnBuffer] = {}
_last_turn_key: str = _PENDING_KEY
_turns_emitted = 0

# Cap on simultaneously-open (un-flushed) turn buffers. A buffer is only popped on
# the TTS flush (_flush_turn), so any turn that never reaches a TTS metric — a
# barge-in / false-interruption cancel, an errored/aborted generation, or an
# internal priming/greeting/mode-enter generate_reply whose stages don't end in a
# TTS flush — would otherwise leak in `_turns` forever (unbounded dict growth +
# stale half-filled buffers over a long open-mic session). We bound the dict by
# dropping the OLDEST open buffer (insertion order) once the cap is exceeded:
# cancelled turns are reclaimed and memory stays bounded. The cap is generous
# enough that no in-flight real turn is evicted before its TTS flush.
_MAX_OPEN_TURNS = 8


def _turn_key(metric: Any) -> str:
    """Resolve a turn key from the metric's speech_id (falls back to pending)."""
    return getattr(metric, "speech_id", None) or _PENDING_KEY


def _buffer_for(metric: Any) -> _TurnBuffer:
    """Get-or-create the turn buffer for a metric, tracking the active key."""
    global _last_turn_key
    key = _turn_key(metric)
    buffer = _turns.get(key)
    if buffer is None:
        buffer = _TurnBuffer()
        _turns[key] = buffer
        _evict_stale_turns()
    _last_turn_key = key
    return buffer


def _evict_stale_turns() -> None:
    """Bound the open-buffer dict by dropping the oldest un-flushed turns.

    Turns that never reach the TTS flush (barge-in / errored / internal turns) are
    never popped by `_flush_turn`, so without this the dict grows unbounded. dict
    preserves insertion order, so the oldest open buffers are the leftmost keys;
    drop them (never the just-inserted newest) once we exceed the cap. The pending
    no-speech_id buffer is also reclaimed this way so it cannot accumulate forever.
    """
    while len(_turns) > _MAX_OPEN_TURNS:
        oldest_key = next(iter(_turns))
        del _turns[oldest_key]


def _flush_turn(key: str) -> None:
    """Flush ONE consolidated emit_turn() for a completed turn + periodic P50/P95."""
    global _turns_emitted
    buffer = _turns.pop(key, None)
    if buffer is None:
        return
    e2e_ms: float | None = None
    if buffer.user_audio_end is not None and buffer.agent_audio_start is not None:
        e2e_ms = round((buffer.agent_audio_start - buffer.user_audio_end) * _MS_PER_SECOND, 1)
    emit_turn(
        eou_ms=buffer.eou_ms,
        stt_ms=buffer.stt_ms,
        llm_ttft_ms=buffer.llm_ttft_ms,
        tts_ttfb_ms=buffer.tts_ttfb_ms,
        e2e_ms=e2e_ms,
    )
    _turns_emitted += 1
    if _turns_emitted % SUMMARY_EVERY_TURNS == 0:
        emit_rolling_summary()


def _seconds_to_ms(value: float | None) -> float | None:
    """Convert a LiveKit metric (seconds) to milliseconds, preserving None."""
    if value is None:
        return None
    return round(value * _MS_PER_SECOND, 1)


def _over_budget(stage: str, value_ms: float | None) -> bool:
    """True when a stage timing breaches its budget (None never alerts)."""
    if value_ms is None:
        return False
    return value_ms > BUDGET_MS[stage]


def _record(stage: str, value_ms: float | None) -> None:
    """Add a sample to the stage's rolling window (skips None)."""
    if value_ms is not None:
        _samples[stage].append(value_ms)


def rolling_percentiles(stage: str) -> dict[str, float | None]:
    """P50/P95 over the stage's rolling window (None until enough samples)."""
    window = _samples.get(stage)
    if not window or len(window) < 2:
        return {"p50": None, "p95": None}
    cuts = quantiles(window, n=100, method="inclusive")
    return {"p50": round(cuts[49], 1), "p95": round(cuts[94], 1)}


def emit_turn(
    *,
    eou_ms: float | None = None,
    stt_ms: float | None = None,
    llm_ttft_ms: float | None = None,
    tts_ttfb_ms: float | None = None,
    e2e_ms: float | None = None,
) -> dict[str, Any]:
    """Emit one structured JSON line for a turn; return the emitted record.

    Null/zero stages are allowed (no voice loop in Phase 1). Each stage is
    recorded into its rolling window and flagged if it breaches budget. Logs go
    to stdout only — no external telemetry export.
    """
    stages = {
        "eou": eou_ms,
        "stt": stt_ms,
        "llm_ttft": llm_ttft_ms,
        "tts_ttfb": tts_ttfb_ms,
        # e2e is now recorded into its rolling window so rolling_percentiles("e2e")
        # works — it was previously excluded (Pattern E3 fix).
        "e2e": e2e_ms,
    }
    for stage, value in stages.items():
        _record(stage, value)
    record = {
        "eou_ms": eou_ms,
        "stt_ms": stt_ms,
        "llm_ttft_ms": llm_ttft_ms,
        "tts_ttfb_ms": tts_ttfb_ms,
        "e2e_ms": e2e_ms,
        "over_budget": [s for s, v in stages.items() if _over_budget(s, v)],
    }
    print(json.dumps(record), file=sys.stdout, flush=True)
    return record


def emit_rolling_summary() -> dict[str, Any]:
    """Emit ONE periodic P50/P95 summary line over the rolling windows.

    Local stdout only (PERF-03 — no external telemetry export of any kind).
    The `e2e` percentiles are the Phase-2 voice-to-voice gate (P50 < ~1.2s).
    """
    summary = {
        "rolling_summary": {
            stage: rolling_percentiles(stage)
            for stage in ("eou", "stt", "llm_ttft", "tts_ttfb", "e2e")
        },
        "window": ROLLING_WINDOW,
    }
    print(json.dumps(summary), file=sys.stdout, flush=True)
    return summary


def emit_warmup_metric(ttft_ms: float) -> dict[str, Any]:
    """Walking-skeleton gate: route the startup warmup LLM TTFT through the
    scaffold as the first real metric line — proves emission without a voice
    turn. `ttft_ms` is the measured first-token latency in milliseconds.
    """
    return emit_turn(llm_ttft_ms=round(float(ttft_ms), 1))


def _on_llm_metrics(metric: Any) -> None:
    """Per-plugin LLM handler: buffer the real TTFT (LiveKit reports seconds)."""
    _buffer_for(metric).llm_ttft_ms = _seconds_to_ms(getattr(metric, "ttft", None))


def _on_stt_metrics(metric: Any) -> None:
    """Per-plugin STT handler: buffer transcription duration on the active turn.

    STTMetrics has no speech_id, so attach to the most-recently-touched buffer.
    """
    buffer = _turns.get(_last_turn_key)
    if buffer is not None:
        buffer.stt_ms = _seconds_to_ms(getattr(metric, "duration", None))


def _on_tts_metrics(metric: Any) -> None:
    """Per-plugin TTS handler: buffer TTFB, anchor agent-audio-start, flush turn.

    TTS is the last stage of the voice-to-voice span — the first agent audio
    frame — so we stamp agent_audio_start here and flush the consolidated turn.
    """
    buffer = _buffer_for(metric)
    buffer.tts_ttfb_ms = _seconds_to_ms(getattr(metric, "ttfb", None))
    if buffer.agent_audio_start is None:
        buffer.agent_audio_start = time.monotonic()
    _flush_turn(_turn_key(metric))


def _on_eou_metrics(metric: Any) -> None:
    """EOU handler: buffer end_of_utterance_delay + anchor user-audio-end.

    `end_of_utterance_delay` lives on `EOUMetrics` (`type="eou_metrics"`), NOT on
    `VADMetrics` — the VAD plugin's `metrics_collected` emits `VADMetrics`
    (idle_time / inference_*), which carries neither `end_of_utterance_delay` nor
    `speech_id`. EOUMetrics is emitted on the SESSION-level `metrics_collected`
    event (see `_on_session_metrics`), and critically it DOES carry `speech_id`,
    so the buffer key anchors to the same turn as the LLM/TTS metrics and `e2e_ms`
    correlates. The EOU decision marks the last user audio frame — the start of the
    voice-to-voice span — so we stamp user_audio_end here.
    """
    buffer = _buffer_for(metric)
    buffer.eou_ms = _seconds_to_ms(getattr(metric, "end_of_utterance_delay", None))
    if buffer.user_audio_end is None:
        buffer.user_audio_end = time.monotonic()


def _on_session_metrics(ev: Any) -> None:
    """Session-level `metrics_collected` dispatcher — routes EOUMetrics only.

    The session event delivers an object with a `.metrics` field (the agent metric
    union). EOUMetrics is only emitted here, not by any single plugin, so we filter
    on `type == "eou_metrics"` and forward it to the EOU handler. Every other metric
    type (llm/stt/tts/vad) is already handled by its non-deprecated per-plugin
    subscription, so we ignore them here to avoid double counting.
    """
    metric = getattr(ev, "metrics", ev)
    if getattr(metric, "type", None) == "eou_metrics":
        _on_eou_metrics(metric)


def attach(session: Any) -> None:
    """Subscribe per-plugin `metrics_collected` events + the session EOU surface.

    Uses the NON-deprecated per-plugin surface (session.llm/stt/tts) for the stage
    timings, plus the session-level `metrics_collected` event for EOUMetrics (the
    only surface that emits `end_of_utterance_delay`/`speech_id` — it is NOT on the
    VAD plugin). Plugins that are unset are skipped so the scaffold attaches cleanly
    even before a full pipeline exists.
    """
    handlers = {
        "llm": _on_llm_metrics,
        "stt": _on_stt_metrics,
        "tts": _on_tts_metrics,
    }
    for plugin_name, handler in handlers.items():
        plugin = getattr(session, plugin_name, None)
        if plugin is not None:
            plugin.on("metrics_collected", handler)
    # EOUMetrics is emitted on the session, not a plugin — subscribe there for it.
    session.on("metrics_collected", _on_session_metrics)


def _self_check() -> None:
    """Pure-stdlib unit-style check: feed >=2 samples, assert P50/P95 numeric.

    Runnable here without livekit (`python3 agent/metrics.py`) — proves the
    rolling percentile math, the e2e rolling window, and the consolidated
    emit_turn record shape. Not part of the runtime path.
    """
    for e2e in (900.0, 1100.0, 1000.0, 1300.0):
        emit_turn(eou_ms=200.0, stt_ms=120.0, llm_ttft_ms=250.0,
                  tts_ttfb_ms=130.0, e2e_ms=e2e)
    pct = rolling_percentiles("e2e")
    assert isinstance(pct["p50"], (int, float)), f"p50 not numeric: {pct}"
    assert isinstance(pct["p95"], (int, float)), f"p95 not numeric: {pct}"
    # Key-name / shape contract (flat-TTFT for Phase 4/5): keys must be exact.
    rec = emit_turn(eou_ms=1.0, stt_ms=2.0, llm_ttft_ms=3.0, tts_ttfb_ms=4.0, e2e_ms=5.0)
    expected = {"eou_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "e2e_ms", "over_budget"}
    assert set(rec) == expected, f"per-turn keys drifted: {set(rec)}"
    emit_rolling_summary()
    print(f"_self_check OK: e2e p50={pct['p50']} p95={pct['p95']}", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
