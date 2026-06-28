"""Sandbox self-checks for the R3 STT_ENGINE composition (no ORT/NeMo/fastapi).

Run: python3 stt/test_engine.py
"""
from __future__ import annotations

import os
import subprocess
import sys


def _assert_parakeet_imports_without_ort() -> None:
    """backend_parakeet must byte-import with NO onnxruntime installed (heavy import
    lives inside load_model/finalize), exposing the seam + STREAMS=False."""
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import backend_parakeet as b; "
        "assert b.STREAMS is False; "
        "assert all(hasattr(b, n) for n in "
        "('load_model','new_stream_state','decode_chunk','finalize','reset_turn_state')); "
        "st = b.new_stream_state(None); "
        "assert b.decode_chunk(None, st, b'\\x01\\x02') == ''; "
        "assert bytes(st['_turn_pcm']) == b'\\x01\\x02'; "
        "b.reset_turn_state(st); assert bytes(st['_turn_pcm']) == b''"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_MODEL"}
        | {"STT_PARAKEET_MODEL": "stub", "STT_BUFFERED_DEVICE": "cpu"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"backend_parakeet seam import failed: {proc.stderr.strip()}"


def _self_check() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _assert_parakeet_imports_without_ort()
    print("engine _self_check OK — backend_parakeet seam", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
