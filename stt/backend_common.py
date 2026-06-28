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
# STILL arriving, recycle decoder state and CONTINUE — the server NEVER auto-emits
# FINAL (the turn detector owns finalize). STT_RECYCLE_* bound the recycle so it
# stays stall-recovery only. BOTH backends import these so the watchdog thresholds
# (and thus the stall semantics) are identical across the GPU and CPU runtimes.
STALL_FRAMES = int(os.environ.get("STT_STALL_FRAMES", "50"))
RECYCLE_MIN_CHARS = int(os.environ.get("STT_RECYCLE_MIN_CHARS", "120"))
RECYCLE_HARD_CHARS = int(os.environ.get("STT_RECYCLE_HARD_CHARS", "400"))

# Diagnosis switch for the Item-1 trailing-word cut-off (15a). When truthy, both
# backends log the drained transcript + held-token count at finalize and the encoder
# streaming config at load, so the operator can confirm the cut-off's root cause on
# the GPU box WITHOUT guessing the API. Default OFF — pure no-op in production.
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
# workaround). FINALIZE_PAD_MS is generous on purpose: it covers up to a [70,6] right
# context (6 encoder frames x 80 ms = 480 ms) plus preprocessor/8x-subsampling edge,
# regardless of the configured att_context_size (shipped default is [70,1] = 80 ms).
FINALIZE_PAD = os.environ.get("STT_FINALIZE_PAD", "0") == "1"
FINALIZE_PAD_MS = int(os.environ.get("STT_FINALIZE_PAD_MS", "640"))


def finalize_pad_pcm() -> bytes:
    """Zero int16 mono PCM of FINALIZE_PAD_MS at SAMPLE_RATE — the trailing-silence drain frame."""
    return b"\x00\x00" * (SAMPLE_RATE * FINALIZE_PAD_MS // 1000)
