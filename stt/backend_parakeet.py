"""backend_parakeet — the STT_ENGINE=buffered|hybrid `final` backend.

Parakeet-tdt-0.6b-v2 int8 ONNX (offline/full-utterance). NeMo-native model exported
to ONNX (sherpa-onnx style: encoder + a TDT greedy-decode loop); int8 weights run on
the onnxruntime CPU or CUDA EP per STT_BUFFERED_DEVICE. Unlike the streaming backends
this one is NON-STREAMING: `decode_chunk` emits NO partials and the SERVER owns the
per-turn PCM buffer (state["_turn_pcm"]); `finalize` transcribes the whole buffer once.
STREAMS=False tells server.py to skip delta emission and use the RMS energy-EOU.

Heavy imports (onnxruntime / numpy) live INSIDE load_model/finalize so this module
byte-imports in the ORT-less sandbox; the real transcribe is an operator gate (G1).
Single-sourced model dir via STT_PARAKEET_MODEL (KeyError→SystemExit; no hardcoded tag).
"""
from __future__ import annotations

import os
from typing import Any

# Capability flag read by server.py: no live partials; server owns EOU + the PCM buffer.
STREAMS = False

# Single-source the model directory (no hardcoded tag; mirrors STT_ONNX_MODEL posture).
_MODEL_DIR = os.environ.get("STT_PARAKEET_MODEL", "")
_DEVICE = os.environ.get("STT_BUFFERED_DEVICE", "cpu")


def load_model() -> Any:
    """Build the onnxruntime sessions for the Parakeet int8 ONNX graphs.

    OPERATOR GATE (G1): the exact ONNX inputs/outputs + the TDT greedy-decode loop
    must be confirmed against the in-container model (sherpa-onnx export or NeMo
    `model.export()`); see .planning/v1.2-R3-DESIGN.md References. Heavy imports stay
    here so the module byte-imports without onnxruntime in the sandbox.
    """
    if not _MODEL_DIR:
        raise SystemExit("STT_PARAKEET_MODEL must point at the Parakeet ONNX model dir")
    import onnxruntime as ort  # noqa: F401 — operator-gated; provider set per _DEVICE

    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if _DEVICE == "gpu" else ["CPUExecutionProvider"])
    # GATE: wire encoder/decoder/joiner sessions from _MODEL_DIR with `providers`.
    raise NotImplementedError("operator gate G1: build Parakeet ORT sessions")


def new_stream_state(model: Any) -> dict:
    """Per-turn state. The server appends raw PCM to _turn_pcm; we transcribe it once."""
    return {"_turn_pcm": bytearray()}


def decode_chunk(model: Any, state: dict, pcm: bytes) -> str:
    """Buffered: no partials. Accumulate is the SERVER's job (it owns _turn_pcm); we
    keep a defensive append so a direct caller (offline VERIFY path) still buffers."""
    state["_turn_pcm"].extend(pcm)
    return ""


def finalize(model: Any, state: dict) -> str:
    """Transcribe the whole accumulated turn buffer once (offline TDT greedy decode).

    OPERATOR GATE (G1): run the ORT encoder over the buffered PCM mel + the TDT
    greedy-decode loop; return native-PnC text. Heavy import stays inside.
    """
    pcm = bytes(state.get("_turn_pcm", b""))
    if not pcm:
        return ""
    import numpy as np  # noqa: F401 — operator-gated mel + decode
    # GATE: mel(pcm) → encoder → TDT greedy decode → text (native punct/caps as-is).
    raise NotImplementedError("operator gate G1: Parakeet offline transcribe")


def reset_turn_state(state: dict) -> None:
    """Clear the per-turn buffer so the next turn is that turn only."""
    state["_turn_pcm"] = bytearray()
