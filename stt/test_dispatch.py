"""Sandbox stubbed-backend dispatch test for the STT_RUNTIME=cpu WS path (Plan 10-01).

Proves — WITHOUT onnxruntime/NeMo/fastapi installed — that:
  * server.py reads STT_RUNTIME=cpu and lazily imports the `backend_onnx` module,
  * the frozen WS framing round-trips config→ready, a binary PCM frame→delta, a
    flush→final, and a bad control frame→error against a STUB backend.

It installs a minimal `fastapi` stub (decorators + WebSocketDisconnect) and a stub
`backend_onnx` (decode_chunk echoes the pcm length as text; finalize returns the last
text) into sys.modules BEFORE importing server, then drives ws_stream with a fake
WebSocket. No GPU, no ORT download. Run: `python3 stt/test_dispatch.py`.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import types


def _install_fastapi_stub() -> None:
    """Minimal fastapi shim so server.py imports + builds `app` in the sandbox."""
    mod = types.ModuleType("fastapi")

    class _App:
        def __init__(self, *a, **k) -> None:
            pass

        def _decorator(self, *a, **k):
            return lambda fn: fn

        get = post = websocket = _decorator

    class WebSocketDisconnect(Exception):
        pass

    mod.FastAPI = _App
    mod.Response = type("Response", (), {})
    mod.UploadFile = type("UploadFile", (), {})
    mod.WebSocket = type("WebSocket", (), {})
    mod.WebSocketDisconnect = WebSocketDisconnect
    sys.modules["fastapi"] = mod


def _install_backend_stub() -> list:
    """Stub `backend_onnx`: echoes pcm length as cumulative text; records calls."""
    mod = types.ModuleType("backend_onnx")

    def load_model():
        return {"stub": True}

    def new_stream_state(model):
        return {"text": ""}

    def decode_chunk(model, state, pcm):
        state["text"] = f"len={len(pcm)}"
        return state["text"]

    def finalize(model, state):
        return state["text"]

    def reset_turn_state(state):
        state["text"] = ""

    mod.load_model = load_model
    mod.new_stream_state = new_stream_state
    mod.decode_chunk = decode_chunk
    mod.finalize = finalize
    mod.reset_turn_state = reset_turn_state
    sys.modules["backend_onnx"] = mod
    return []


class _FakeWebSocket:
    """Scripted WS double: yields queued frames, captures every send_json payload."""

    def __init__(self, frames: list) -> None:
        self._frames = list(frames)
        self.sent: list = []

    async def accept(self) -> None:
        return None

    async def receive_json(self):
        return {"type": "config", "language": "en"}

    async def receive(self):
        return self._frames.pop(0)

    async def send_json(self, payload) -> None:
        self.sent.append(payload)


def _run_exchange():
    """Drive ws_stream through delta/final/error then a disconnect; return sends."""
    server = importlib.import_module("server")
    assert server.RUNTIME == "cpu", f"expected cpu runtime, got {server.RUNTIME!r}"
    assert sys.modules["backend_onnx"] is server._primary, "dispatch must use the stub backend_onnx"
    frames = [
        {"bytes": b"\x00\x01\x02\x03"},          # binary PCM → delta
        {"text": '{"type":"flush"}'},            # flush → final
        {"text": "not-json"},                    # bad control → error
        {"type": "websocket.disconnect"},        # end the loop
    ]
    ws = _FakeWebSocket(frames)
    asyncio.run(server.ws_stream(ws))
    return ws.sent


def _assert_cpu_import_needs_no_stt_model() -> None:
    """C1 regression: the REAL backend_onnx must import with only STT_ONNX_MODEL set.

    The stub backend in _run_exchange masks the real backend_onnx→backend_nemo
    coupling (L1), so assert separately that importing the real module with
    STT_MODEL UNSET does NOT SystemExit. Phase 10 C1 made this pass by routing the
    shared constants through the tag-free backend_common module.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.run(
        [sys.executable, "-c", "import backend_onnx"],
        cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_MODEL"}
        | {"STT_ONNX_MODEL": "x", "STT_QUANT": "int8-dynamic", "STT_RUNTIME": "cpu"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"real backend_onnx must import without STT_MODEL (C1), got rc={proc.returncode}: "
        f"{proc.stderr.strip()}")


def _self_check() -> None:
    os.environ["STT_RUNTIME"] = "cpu"
    os.environ.setdefault("STT_ONNX_MODEL", "stub-onnx-model")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _assert_cpu_import_needs_no_stt_model()
    _install_fastapi_stub()
    _install_backend_stub()
    sent = _run_exchange()
    kinds = [m.get("type") for m in sent]
    assert kinds[0] == "ready", f"first frame must be ready, got {kinds}"
    assert "delta" in kinds, f"binary frame must yield delta, got {kinds}"
    assert "final" in kinds, f"flush must yield final, got {kinds}"
    assert "error" in kinds, f"bad control frame must yield error, got {kinds}"
    delta = next(m for m in sent if m.get("type") == "delta")
    # The 4-byte PCM frame is sub-chunk; _drain_buffer pads it to _STREAM_CHUNK_BYTES on flush.
    server = sys.modules["server"]
    assert delta["text"] == f"len={server._STREAM_CHUNK_BYTES}", (
        f"delta must echo padded chunk size, got {delta!r}")
    # R3: default engine is streaming and keeps primary==final (byte-compat).
    assert server.ENGINE == "streaming", f"default engine must be streaming, got {server.ENGINE!r}"
    assert server._primary is server._final, "streaming engine must share one backend"
    assert server._primary is sys.modules["backend_onnx"], "streaming+cpu must dispatch backend_onnx"
    print(f"dispatch _self_check OK — frames: {kinds}", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
