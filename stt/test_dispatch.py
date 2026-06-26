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
    assert sys.modules["backend_onnx"] is server.backend, "dispatch must use the stub backend_onnx"
    frames = [
        {"bytes": b"\x00\x01\x02\x03"},          # binary PCM → delta
        {"text": '{"type":"flush"}'},            # flush → final
        {"text": "not-json"},                    # bad control → error
        {"type": "websocket.disconnect"},        # end the loop
    ]
    ws = _FakeWebSocket(frames)
    asyncio.run(server.ws_stream(ws))
    return ws.sent


def _self_check() -> None:
    os.environ["STT_RUNTIME"] = "cpu"
    os.environ.setdefault("STT_ONNX_MODEL", "stub-onnx-model")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _install_fastapi_stub()
    _install_backend_stub()
    sent = _run_exchange()
    kinds = [m.get("type") for m in sent]
    assert kinds[0] == "ready", f"first frame must be ready, got {kinds}"
    assert "delta" in kinds, f"binary frame must yield delta, got {kinds}"
    assert "final" in kinds, f"flush must yield final, got {kinds}"
    assert "error" in kinds, f"bad control frame must yield error, got {kinds}"
    delta = next(m for m in sent if m.get("type") == "delta")
    assert delta["text"] == "len=4", f"delta must echo pcm length, got {delta!r}"
    print(f"dispatch _self_check OK — frames: {kinds}", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
