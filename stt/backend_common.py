"""backend_common — tag-free shared constants/helpers for BOTH STT backends.

This module holds the streaming constants both `backend_nemo` (GPU) and
`backend_onnx` (CPU) need, with NO module-scope required-env read that could break
the other runtime. Specifically it does NOT read `STT_MODEL` (GPU-only) or
`STT_ONNX_MODEL` (CPU-only) and carries NO hardcoded model tag — so importing it on
the CPU path never triggers the GPU backend's `STT_MODEL` SystemExit (Phase 10 C1).

`backend_onnx` imports the shared constants from HERE instead of from `backend_nemo`,
so the CPU server never transitively imports `backend_nemo` (whose module body
hard-requires `STT_MODEL`, which the CPU image deliberately never sets — it sets
`STT_ONNX_MODEL`). `backend_nemo` re-exports these names so its own public surface is
unchanged.

The only env reads here are the optional, defaulted stall-watchdog knobs
(STT_STALL_FRAMES / STT_RECYCLE_*) — all have safe defaults, none is required, and
none is a model tag.
"""
from __future__ import annotations

import os

SAMPLE_RATE = 16000
INT16_FULL_SCALE = 32768.0

# RNNT decoder-stall watchdog (09-RESEARCH §1, PITFALL B2). Named constants, no
# magic values. If cumulative text stops growing for STALL_FRAMES while audio is
# STILL arriving AND at least RECYCLE_MIN_CHARS are held, recycle decoder state and
# CONTINUE (folding the held text forward so nothing committed is lost — F22). The
# server owns autonomous FINAL (the ENDPOINT_SILENCE_MS energy path), so the recycle
# is stall-recovery only, never a finalize. RECYCLE_MIN_CHARS keeps short partials
# from tripping the recycle. BOTH backends import these so the watchdog thresholds
# (and thus the stall semantics) are identical across the GPU and CPU runtimes.
STALL_FRAMES = int(os.environ.get("STT_STALL_FRAMES", "50"))
RECYCLE_MIN_CHARS = int(os.environ.get("STT_RECYCLE_MIN_CHARS", "120"))

# Diagnosis switch for the Item-1 trailing-word cut-off (15a). When truthy, the GPU
# NeMo backend (backend_nemo) logs the drained transcript + held-token count at finalize
# and the encoder streaming config at load, so the operator can confirm the cut-off's
# root cause on the GPU box WITHOUT guessing the API. The cut-off complaint is on the GPU
# NeMo path, so the CPU/ONNX backend deliberately carries no diagnostic. Default OFF.
DEBUG_DRAIN = os.environ.get("STT_DEBUG_DRAIN", "0") == "1"

# Item-1 candidate A (15a): thread previous_pred_out back into conformer_stream_step
# for RNNT decode continuity, matching NeMo's reference streaming loop (the current
# decode omits it). Default OFF — GPU-measured before it becomes default; likely the
# permanent default once the GPU gate confirms it restores the tail with no WER regress.
THREAD_PRED_OUT = os.environ.get("STT_THREAD_PRED_OUT", "0") == "1"

# Item-1 candidate B (15a): trailing-silence drain. On finalize, optionally feed one
# last stream step of silence so the final real speech frames get a complete right-
# context attention window — the hard end-of-speech cutoff otherwise leaves the
# trailing right-context frames without the future frames they were trained with, so
# the RNNT can emit blanks for the last words. Default OFF (GPU-measured, unofficial
# workaround). FINALIZE_PAD_MS defaults to 560 ms, sized to cover the right-context
# lookahead: up to a [70,6] right context (6 encoder frames x 80 ms = 480 ms), so
# 560 ms drains it fully. NB (F28): 560 ms is LARGER than one live STREAM_CHUNK_MS
# step (default 320 ms — compose), so this is a single oversized drain frame appended
# once at finalize, NOT a live-sized step; that is fine because it is fed only on the
# trailing-silence drain, not into the steady cache-aware stream. The shipped
# att_context_size is [70,1] (80 ms) so 560 ms is generous — tune via STT_FINALIZE_PAD_MS.
FINALIZE_PAD = os.environ.get("STT_FINALIZE_PAD", "0") == "1"
FINALIZE_PAD_MS = int(os.environ.get("STT_FINALIZE_PAD_MS", "560"))


def finalize_pad_pcm() -> bytes:
    """Zero int16 mono PCM of FINALIZE_PAD_MS at SAMPLE_RATE — the trailing-silence drain frame."""
    return b"\x00\x00" * (SAMPLE_RATE * FINALIZE_PAD_MS // 1000)


def join_committed(prefix: str, since_reset: str) -> str:
    """F22: join the folded-forward committed prefix with the current since-reset decode.

    On a stall recycle the decoder's cumulative restarts from empty (prev_hyps/dec_state
    are cleared), so the pre-recycle text — only ever emitted as interim deltas, never
    committed by LiveKit — would be lost from the turn AND the first post-recycle decode
    would return empty (flipping the server's _final_pending False, wedging a turn that
    ends right after). Both backends fold the held text into `committed_prefix` at recycle
    and return prefix+since_reset from decode_chunk/finalize, so the transcript is never
    lost and decode_chunk stays non-empty. Space-join, skipping empties so no leading/
    trailing/double space appears across the boundary."""
    if not prefix:
        return since_reset
    if not since_reset:
        return prefix
    return f"{prefix} {since_reset}"


# R3 buffered/energy-EOU (no numpy: stdlib array+math keeps server.py sandbox-safe).
# When the PRIMARY backend has STREAMS=False there is no growing transcript to
# stall-detect, so end-of-utterance is detected acoustically: chunks whose RMS sits
# below ENERGY_SILENCE_RMS for ENDPOINT_SILENCE_MS (after voiced audio) end the turn.
ENERGY_SILENCE_RMS = float(os.environ.get("STT_ENERGY_SILENCE_RMS", "320"))  # int16 RMS floor
# Bound the per-turn PCM buffer so a missed EOU cannot grow memory unbounded.
BUFFERED_MAX_S = int(os.environ.get("STT_BUFFERED_MAX_S", "60"))


def rms_int16(pcm: bytes) -> float:
    """RMS of int16 mono PCM via stdlib array+math (no numpy, no deprecated audioop)."""
    import array
    import math
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))
