"""backend_nemo — the STT_RUNTIME=gpu backend (the Phase-9 NeMo decode body, moved).

This is the GPU NeMo decode body factored VERBATIM out of `stt/server.py` (Phase 9)
behind the four-callable seam `server.py` now dispatches through (RESEARCH §2):

    load_model() -> Any
    new_stream_state(model) -> dict
    decode_chunk(model, state, pcm) -> str
    finalize(model, state) -> str
    reset_turn_state(state) -> None

The ONLY change vs. the Phase-9 functions is the call shape: the single model handle
is now passed IN by the server (no module-global `_model` inside the backend), so the
cumulative `hyps[0].text` output is byte-identical to Phase 9 — this is a relocation,
not a behaviour change. The frozen `ready`/`delta`/`final`/`error` WS contract, the
`/health` gate, the `_gpu_lock` serialize, and the stall watchdog semantics are all
preserved by `server.py` + this backend's per-chunk recycle.

Heavy imports (`nemo.collections.asr`, `torch`, `numpy`, `omegaconf`) live INSIDE the
functions so this module byte-compiles in the GPU-less sandbox; the real decode is an
operator GPU gate (10-PLACEMENT-VERIFY).
"""
from __future__ import annotations

import ast
import logging
import os
from typing import Any

logger = logging.getLogger("nemo-stt")

# --- Config (module scope, no hardcoded tag) ----------------------------------
# Single-source the model tag the SAME way agent/main.py:resolved_llm_tag does:
# KeyError → SystemExit if unset, so the baked weights and the loaded model can
# never drift (the v1.0 no-hardcoded-tag invariant).
try:
    MODEL_NAME: str = os.environ["STT_MODEL"]
except KeyError as exc:  # pragma: no cover - exercised only at process start
    raise SystemExit("STT_MODEL is not set — supplied by docker-compose build/env") from exc


# att_context_size = [left, right] in 80 ms encoder frames (STT-04). Balanced
# default [56,3]; set ONCE on the encoder at load. `right` trades latency vs
# accuracy (lower = snappier, higher = more accurate).
def _parse_att_context_size(raw: str) -> list[int]:
    """Parse + validate the [left, right] env value, failing fast on bad input.

    ast.literal_eval is code-exec-safe (not eval); we additionally require a
    2-element list of ints so a malformed value fails at import with a clear
    message instead of deep inside set_default_att_context_size at the GPU gate
    (matches the STT_MODEL SystemExit posture).
    """
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise SystemExit(f"STT_ATT_CONTEXT_SIZE is not a valid literal: {raw!r}") from exc
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(n, int) for n in value)):
        raise SystemExit(f"STT_ATT_CONTEXT_SIZE must be a 2-element list of ints, got {raw!r}")
    return value


ATT_CONTEXT_SIZE = _parse_att_context_size(os.environ.get("STT_ATT_CONTEXT_SIZE", "[56,3]"))

# RNNT decoder-stall watchdog (09-RESEARCH §1, PITFALL B2). Named constants, no
# magic values. If cumulative text stops growing for STALL_FRAMES while audio is
# STILL arriving, recycle decoder state and CONTINUE — the server NEVER auto-emits
# FINAL (the turn detector owns finalize). STT_RECYCLE_* bound the recycle so it
# stays stall-recovery only. backend_onnx imports these so both backends share the
# watchdog thresholds.
STALL_FRAMES = int(os.environ.get("STT_STALL_FRAMES", "50"))
RECYCLE_MIN_CHARS = int(os.environ.get("STT_RECYCLE_MIN_CHARS", "120"))
RECYCLE_HARD_CHARS = int(os.environ.get("STT_RECYCLE_HARD_CHARS", "400"))

SAMPLE_RATE = 16000
INT16_FULL_SCALE = 32768.0


def load_model() -> Any:
    """Load the Nemotron streaming model resident, set the att_context_size knob.

    Heavy imports are local so the GPU-less sandbox can byte-compile this module.
    The exact `conformer_stream_step` signature + preprocessing are confirmed
    against the in-container `nemo.collections.asr` source at the operator GPU
    gate (10-PLACEMENT-VERIFY) — the sandbox cannot import NeMo.
    """
    import nemo.collections.asr as nemo_asr  # noqa: PLC0415 - GPU-only dep

    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    model.eval()
    model.encoder.set_default_att_context_size(ATT_CONTEXT_SIZE)
    # Greedy single-step RNNT decoding — lowest latency for streaming.
    _set_greedy_decoding(model)
    logger.info("nemo-stt model loaded: %s att_context_size=%s", MODEL_NAME, ATT_CONTEXT_SIZE)
    return model


def _set_greedy_decoding(model: Any) -> None:
    """Switch the RNNT head to greedy single-step decoding (alignments off)."""
    from omegaconf import open_dict  # noqa: PLC0415 - GPU-only dep

    cfg = model.cfg.decoding
    with open_dict(cfg):
        cfg.strategy = "greedy"
        cfg.preserve_alignments = False
    model.change_decoding_strategy(decoding_cfg=cfg)


def new_stream_state(model) -> dict:
    """Fresh per-connection streaming state (cache + stall-tracking counters)."""
    channel, time_state, channel_len = model.encoder.get_initial_cache_state(batch_size=1)
    return {
        "cache_last_channel": channel,
        "cache_last_time": time_state,
        "cache_last_channel_len": channel_len,
        "prev_hyps": None,
        "frames_since_growth": 0,
        "last_text_len": 0,
    }


def _extract_features(model, pcm: bytes) -> tuple[Any, Any]:
    """int16 PCM bytes → mel features via the model's own preprocessor."""
    import numpy as np  # noqa: PLC0415 - GPU-only dep
    import torch  # noqa: PLC0415 - GPU-only dep

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / INT16_FULL_SCALE
    signal = torch.tensor(samples).unsqueeze(0)
    length = torch.tensor([signal.shape[1]])
    feats, feat_len = model.preprocessor(input_signal=signal, length=length)
    return feats, feat_len


def decode_chunk(model, state, pcm) -> str:
    """Run one cache-aware stream step; return the CUMULATIVE transcript.

    Native PnC is surfaced AS-IS (no strip/lowercase — STT-03). Recycles decoder
    state on a stall but NEVER emits FINAL (the turn detector owns finalize).
    """
    import torch  # noqa: PLC0415 - GPU-only dep

    feats, feat_len = _extract_features(model, pcm)
    with torch.inference_mode():
        text, channel, time_state, channel_len, hyps = model.conformer_stream_step(
            processed_signal=feats,
            processed_signal_length=feat_len,
            cache_last_channel=state["cache_last_channel"],
            cache_last_time=state["cache_last_time"],
            cache_last_channel_len=state["cache_last_channel_len"],
            keep_all_outputs=True,
            previous_hypotheses=state["prev_hyps"],
            return_transcription=True,
        )
    state["cache_last_channel"] = channel
    state["cache_last_time"] = time_state
    state["cache_last_channel_len"] = channel_len
    state["prev_hyps"] = hyps
    cumulative = hyps[0].text if hyps else ""
    _track_stall(state, cumulative)
    return cumulative


def _track_stall(state: dict, cumulative: str) -> None:
    """Stall watchdog: recycle decoder state if text stops growing (no FINAL)."""
    grew = len(cumulative) > state["last_text_len"]
    state["last_text_len"] = len(cumulative)
    if grew:
        state["frames_since_growth"] = 0
        return
    state["frames_since_growth"] += 1
    stalled = state["frames_since_growth"] >= STALL_FRAMES
    if stalled and len(cumulative) >= RECYCLE_MIN_CHARS:
        # Reset prev_hyps, carry the encoder cache forward, continue. Log only —
        # do NOT emit FINAL (single-turn-source invariant, 09-RESEARCH §1/§4).
        logger.info("nemo-stt RNNT stall recycle at %d chars (cache carried forward)", len(cumulative))
        state["prev_hyps"] = None
        state["frames_since_growth"] = 0


def finalize(model, state) -> str:
    """Drain the stream and return the final transcript (flush→final response)."""
    cumulative = ""
    if state["prev_hyps"]:
        cumulative = state["prev_hyps"][0].text
    return cumulative


def reset_turn_state(state: dict) -> None:
    """Clear per-turn decode state after a FINAL so the next utterance starts clean.

    Resets the RNNT hypotheses + stall counters but CARRIES THE ENCODER CACHE
    forward (cache_last_*) — same as the stall recycle — so cache-aware streaming
    semantics are preserved across the turn boundary. Without this, prev_hyps is
    fed back into the next decode and every FINAL accumulates the whole session.
    """
    state["prev_hyps"] = None
    state["frames_since_growth"] = 0
    state["last_text_len"] = 0
