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


def _run_buffered_exchange():
    """Drive ws_stream with a STREAMS=False stub: voiced→silence must yield ONE final,
    sourced from the final backend, with no deltas."""
    import asyncio, importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket

    voiced = b"\x40\x10" * 8960   # ~loud 560ms @16k int16 (17920 bytes = 1 stream chunk)
    silence = b"\x00\x00" * 8960  # ~silent 560ms (17920 bytes = 1 stream chunk)
    stub = types.ModuleType("backend_parakeet")
    stub.STREAMS = False
    stub.load_model = lambda: {"stub": True}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""           # no partials
    stub.finalize = lambda m, s: f"buffered:{len(s['_turn_pcm'])}"
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server._primary is stub and server._final is stub, "buffered must use parakeet stub"
    # 2 voiced chunks (build buffer, mark voiced) then enough silence to cross the window.
    frames = [{"bytes": voiced}, {"bytes": voiced}] + \
             [{"bytes": silence} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    asyncio.run(server.ws_stream(ws))
    return [m for m in ws.sent if m.get("type") in ("delta", "final")]


def _assert_buffered_eou() -> None:
    msgs = _run_buffered_exchange()
    kinds = [m["type"] for m in msgs]
    assert "delta" not in kinds, f"buffered must emit NO deltas, got {kinds}"
    assert kinds.count("final") == 1, f"buffered must emit exactly one final, got {kinds}"
    assert msgs[-1]["text"].startswith("buffered:"), "final must come from the buffered backend"


def _self_check() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _assert_parakeet_imports_without_ort()
    _assert_buffered_eou()
    print("engine _self_check OK — backend_parakeet seam", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
