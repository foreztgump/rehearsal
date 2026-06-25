"""Per-stage latency metrics scaffold for the Adept voice loop (Plan 01-03).

Walking-skeleton scope: the plumbing exists and emits ONE real line at startup
(the warmup LLM TTFT) — no live voice turn yet. Per-turn fields that need a real
call (eou_ms, stt_ms, tts_ttfb_ms, e2e_ms) are null until Phase 2.

Design rules baked in here:
  * Subscribe to the NON-deprecated PER-PLUGIN `metrics_collected` event on each
    plugin instance (llm/stt/tts/vad) — never the deprecated session-level event.
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
from collections import defaultdict, deque
from statistics import quantiles
from typing import Any

# Per-stage latency budgets (milliseconds). These encode the flat-TTFT
# invariant: each stage must stay under budget for voice-to-voice P50 < 1.0s.
BUDGET_MS: dict[str, int] = {
    "eou": 300,         # end-of-utterance / turn-detection decision
    "stt": 150,         # speech-to-text transcription
    "llm_ttft": 300,    # LLM time-to-first-token
    "tts_ttfb": 150,    # TTS time-to-first-byte
    "playout": 100,     # audio playout scheduling
}

# Rolling window size for the P50/P95 aggregation stub.
ROLLING_WINDOW = 100
_MS_PER_SECOND = 1000.0

# Per-stage rolling samples for the P50/P95 aggregation stub.
_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=ROLLING_WINDOW))


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


def emit_warmup_metric(ttft_ms: float) -> dict[str, Any]:
    """Walking-skeleton gate: route the startup warmup LLM TTFT through the
    scaffold as the first real metric line — proves emission without a voice
    turn. `ttft_ms` is the measured first-token latency in milliseconds.
    """
    return emit_turn(llm_ttft_ms=round(float(ttft_ms), 1))


def _on_llm_metrics(metric: Any) -> None:
    """Per-plugin LLM handler: emit the real TTFT (LiveKit reports seconds)."""
    emit_turn(llm_ttft_ms=_seconds_to_ms(getattr(metric, "ttft", None)))


def _on_stt_metrics(metric: Any) -> None:
    """Per-plugin STT handler: record transcription duration."""
    emit_turn(stt_ms=_seconds_to_ms(getattr(metric, "duration", None)))


def _on_tts_metrics(metric: Any) -> None:
    """Per-plugin TTS handler: record time-to-first-byte."""
    emit_turn(tts_ttfb_ms=_seconds_to_ms(getattr(metric, "ttfb", None)))


def _on_vad_metrics(metric: Any) -> None:
    """Per-plugin VAD/EOU handler: record the end-of-utterance delay."""
    delay = getattr(metric, "end_of_utterance_delay", None)
    emit_turn(eou_ms=_seconds_to_ms(delay))


def attach(session: Any) -> None:
    """Subscribe the per-plugin `metrics_collected` events on an AgentSession.

    Uses the NON-deprecated per-plugin surface (session.llm/stt/tts/vad) — never
    the deprecated session-level `metrics_collected`. Plugins that are unset are
    skipped so the scaffold attaches cleanly even before a full pipeline exists.
    """
    handlers = {
        "llm": _on_llm_metrics,
        "stt": _on_stt_metrics,
        "tts": _on_tts_metrics,
        "vad": _on_vad_metrics,
    }
    for plugin_name, handler in handlers.items():
        plugin = getattr(session, plugin_name, None)
        if plugin is not None:
            plugin.on("metrics_collected", handler)
