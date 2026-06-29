"""backend_parakeet — the STT_ENGINE=buffered|hybrid `final` backend.

Parakeet-tdt-0.6b-v2 int8 ONNX (offline/full-utterance) via sherpa-onnx (D22);
real-weights GPU runs are operator-gated on G1. Unlike the streaming backends this
one is NON-STREAMING: `decode_chunk` emits NO partials and the SERVER owns the
per-turn PCM buffer (state["_turn_pcm"]); `finalize` transcribes the whole buffer once.
STREAMS=False tells server.py to skip delta emission and use the RMS energy-EOU.

Heavy imports (sherpa_onnx / numpy) live INSIDE load_model/finalize so this module
byte-imports in the dependency-light sandbox.
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
_ENCODER_FILE = "encoder.int8.onnx"
_DECODER_FILE = "decoder.int8.onnx"
_JOINER_FILE = "joiner.int8.onnx"
_TOKENS_FILE = "tokens.txt"
_SAMPLE_RATE = 16000
_FEATURE_DIM = 80
_NUM_THREADS = int(os.environ.get("STT_PARAKEET_THREADS", "2"))
_DECODING_METHOD = "greedy_search"
_MODEL_TYPE = "nemo_transducer"
_INT16_FULL_SCALE = 32768.0


def load_model() -> Any:
    """Build the sherpa-onnx OfflineRecognizer for the Parakeet int8 transducer."""
    if not _MODEL_DIR:
        raise SystemExit("STT_PARAKEET_MODEL must point at the Parakeet ONNX model dir")
    import sherpa_onnx

    provider = "cuda" if _DEVICE == "gpu" else "cpu"
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=os.path.join(_MODEL_DIR, _ENCODER_FILE),
        decoder=os.path.join(_MODEL_DIR, _DECODER_FILE),
        joiner=os.path.join(_MODEL_DIR, _JOINER_FILE),
        tokens=os.path.join(_MODEL_DIR, _TOKENS_FILE),
        num_threads=_NUM_THREADS,
        sample_rate=_SAMPLE_RATE,
        feature_dim=_FEATURE_DIM,
        decoding_method=_DECODING_METHOD,
        model_type=_MODEL_TYPE,
        provider=provider,
    )


def new_stream_state(model: Any) -> dict:
    """Per-turn state. The server appends raw PCM to _turn_pcm; we transcribe it once."""
    return {"_turn_pcm": bytearray()}


def decode_chunk(model: Any, state: dict, pcm: bytes) -> str:
    """Buffered: no partials. Pure no-op — SERVER owns _turn_pcm accumulation.
    The live buffered path (_emit_buffered) and the offline path (_transcribe_wav)
    both accumulate via server-side _ACCUMULATE_PCM; this backend must not double-append."""
    return ""


def finalize(model: Any, state: dict) -> str:
    """Transcribe the whole accumulated turn buffer once (offline; native PnC)."""
    pcm = bytes(state.get("_turn_pcm", b""))
    if not pcm:
        return ""
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / _INT16_FULL_SCALE
    stream = model.create_stream()
    stream.accept_waveform(_SAMPLE_RATE, samples)
    model.decode_stream(stream)
    return stream.result.text


def reset_turn_state(state: dict) -> None:
    """Clear the per-turn buffer so the next turn is that turn only."""
    state["_turn_pcm"] = bytearray()
