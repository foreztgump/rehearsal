"""GPU buffered Parakeet via NeMo ASRModel.transcribe().

This is the Modal-style path: stream audio transport, buffer one utterance, then
run the non-streaming Parakeet model once on the completed segment.
"""
from __future__ import annotations

import os
from typing import Any

STREAMS = False

try:
    MODEL_NAME: str = os.environ["STT_MODEL"]
except KeyError as exc:  # pragma: no cover - process-start guard
    raise SystemExit("STT_MODEL is not set — use nvidia/parakeet-tdt-0.6b-v2") from exc


def load_model() -> Any:
    """Load the non-streaming Parakeet model resident on GPU."""
    import nemo.collections.asr as nemo_asr
    import torch

    model = nemo_asr.models.ASRModel.from_pretrained(model_name=MODEL_NAME)
    if torch.cuda.is_available():
        model = model.cuda()
    return model.eval()


def new_stream_state(model: Any) -> dict:
    """Per-turn state. The server appends raw PCM to _turn_pcm."""
    return {"_turn_pcm": bytearray()}


def decode_chunk(model: Any, state: dict, pcm: bytes) -> str:
    """Buffered mode emits no partials."""
    return ""


def finalize(model: Any, state: dict) -> str:
    """Transcribe the completed turn buffer once."""
    pcm = bytes(state.get("_turn_pcm", b""))
    if not pcm:
        return ""
    import numpy as np

    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    with _quiet_nemo():
        result = model.transcribe([audio])
    first = result[0] if result else None
    return getattr(first, "text", first or "")


def reset_turn_state(state: dict) -> None:
    """Clear the per-turn buffer so the next turn is independent."""
    state["_turn_pcm"] = bytearray()


class _quiet_nemo:
    """Suppress NeMo's per-transcribe stdout/stderr chatter."""

    def __enter__(self):
        import sys

        self._devnull = open(os.devnull, "w", encoding="utf-8")
        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = self._devnull, self._devnull

    def __exit__(self, exc_type, exc_value, traceback):
        import sys

        sys.stdout, sys.stderr = self._stdout, self._stderr
        self._devnull.close()
