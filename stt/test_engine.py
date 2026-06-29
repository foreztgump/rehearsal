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
        "before = bytes(st['_turn_pcm']); "
        "assert b.decode_chunk(None, st, b'\\x01\\x02') == ''; "
        "assert bytes(st['_turn_pcm']) == before, 'server owns _turn_pcm — decode_chunk must not mutate'; "
        "b.reset_turn_state(st); assert bytes(st['_turn_pcm']) == b''"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_MODEL"}
        | {"STT_PARAKEET_MODEL": "stub", "STT_BUFFERED_DEVICE": "cpu"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"backend_parakeet seam import failed: {proc.stderr.strip()}"


def _assert_parakeet_real_body() -> None:
    """Real load/finalize body wires sherpa-onnx and float32 PCM (stubbed sherpa_onnx)."""
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import sys, types, numpy as np\n"
        "calls = {}\n"
        "class _Stream:\n"
        "    def __init__(self): self.result = types.SimpleNamespace(text='hello world')\n"
        "    def accept_waveform(self, sr, samples): "
        "calls.update(sr=sr, n=len(samples), dtype=str(samples.dtype))\n"
        "def _from_transducer(**kw):\n"
        "    calls.update(kw)\n"
        "    recognizer = types.SimpleNamespace()\n"
        "    recognizer.create_stream = lambda: _Stream()\n"
        "    recognizer.decode_stream = lambda stream: calls.__setitem__('decoded', True)\n"
        "    return recognizer\n"
        "shim = types.ModuleType('sherpa_onnx')\n"
        "shim.OfflineRecognizer = types.SimpleNamespace(from_transducer=_from_transducer)\n"
        "sys.modules['sherpa_onnx'] = shim\n"
        "import backend_parakeet as backend\n"
        "model = backend.load_model()\n"
        "assert calls['encoder'].endswith('/encoder.int8.onnx'), calls['encoder']\n"
        "assert calls['decoder'].endswith('/decoder.int8.onnx')\n"
        "assert calls['joiner'].endswith('/joiner.int8.onnx')\n"
        "assert calls['tokens'].endswith('/tokens.txt')\n"
        "assert calls['model_type'] == 'nemo_transducer', calls['model_type']\n"
        "assert calls['decoding_method'] == 'greedy_search'\n"
        "assert calls['provider'] == 'cpu', calls['provider']\n"
        "state = backend.new_stream_state(model)\n"
        "state['_turn_pcm'] = bytearray(b'\\x00\\x01' * 16)\n"
        "assert backend.finalize(model, state) == 'hello world'\n"
        "assert calls.get('decoded') is True\n"
        "assert calls['sr'] == 16000 and calls['n'] == 16 and calls['dtype'] == 'float32', calls\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_MODEL"}
        | {"STT_PARAKEET_MODEL": "/models/pk", "STT_BUFFERED_DEVICE": "cpu"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"parakeet real body failed: {proc.stderr.strip()}"


def _run_buffered_exchange():
    """Drive ws_stream with a STREAMS=False stub: voiced→silence must yield ONE final,
    sourced from the final backend, with no deltas."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

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
    _run_async(server.ws_stream(ws))
    return [m for m in ws.sent if m.get("type") in ("delta", "final")]


def _assert_buffered_eou() -> None:
    msgs = _run_buffered_exchange()
    kinds = [m["type"] for m in msgs]
    assert "delta" not in kinds, f"buffered must emit NO deltas, got {kinds}"
    assert kinds.count("final") == 1, f"buffered must emit exactly one final, got {kinds}"
    assert msgs[-1]["text"].startswith("buffered:"), "final must come from the buffered backend"
    assert "dur_ms" in msgs[-1], "autonomous final must carry server-measured dur_ms"
    assert isinstance(msgs[-1]["dur_ms"], int) and msgs[-1]["dur_ms"] >= 0


def _run_hybrid_exchange():
    """Streaming stub primary (emits growing deltas + stalls) + buffered stub final.
    Deltas must come from primary; the final must come from the buffered final over
    the server-accumulated _turn_pcm."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    # Full stream chunk (17920 bytes = 560ms @16kHz int16) so two voiced frames fill
    # one stream chunk and each silence frame fills one — matching _ENDPOINT_SILENCE_CHUNKS.
    # ponytail: brief had * 4480 (half-chunk); that yields only 1 silence stream chunk
    # for _ENDPOINT_SILENCE_CHUNKS=2, so EOU never fires. Fixed to * 8960.
    chunk = b"\x40\x10" * 8960
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {"n": 0}
    prim.new_stream_state = lambda m: {"text": "", "n": 0}
    def _dec(m, s, pcm):
        if pcm.strip(b"\x00"):                 # grow only on voiced audio
            s["n"] += 1; s["text"] = ("word " * s["n"]).strip()
        return s["text"]                       # silence → unchanged → text-stall EOU
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: "NEMO-FINAL-should-not-be-used"
    prim.reset_turn_state = lambda s: s.update(text="", n=0)
    fin = types.ModuleType("backend_parakeet"); fin.STREAMS = False
    fin.load_model = lambda: {"p": True}
    fin.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    fin.decode_chunk = lambda m, s, pcm: ""
    fin.finalize = lambda m, s: f"PARAKEET:{len(s['_turn_pcm'])}"
    fin.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_nemo"] = prim; sys.modules["backend_parakeet"] = fin
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "hybrid"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server._primary is prim and server._final is fin, "hybrid must split primary/final"
    # growing deltas, then repeated identical decode → text-stall → autonomous final.
    frames = [{"bytes": chunk}, {"bytes": chunk}] + \
             [{"bytes": b"\x00\x00" * 8960} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    return ws.sent


def _assert_hybrid() -> None:
    sent = _run_hybrid_exchange()
    kinds = [m.get("type") for m in sent]
    assert "delta" in kinds, f"hybrid must emit Nemotron deltas, got {kinds}"
    final = next((m for m in sent if m.get("type") == "final"), None)
    assert final is not None, "hybrid must emit a final"
    assert final["text"].startswith("PARAKEET:"), f"hybrid final must be Parakeet, got {final!r}"
    assert int(final["text"].split(":")[1]) > 0, "hybrid final must see accumulated _turn_pcm"
    assert "dur_ms" in final and isinstance(final["dur_ms"], int) and final["dur_ms"] >= 0, (
        f"hybrid final must carry dur_ms int >= 0, got {final!r}")


def _run_finalize_error_exchange():
    """I1 proof: stub finalize RAISES → ws_stream must emit both error + final (turn unblocks)."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    def _raise_finalize(m, s):
        raise RuntimeError("finalize exploded")

    voiced = b"\x40\x10" * 8960
    silence = b"\x00\x00" * 8960
    stub = types.ModuleType("backend_parakeet")
    stub.STREAMS = False
    stub.load_model = lambda: {}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""
    stub.finalize = _raise_finalize
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [{"bytes": voiced}, {"bytes": voiced}] + \
             [{"bytes": silence} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    return ws.sent


def _assert_finalize_error_boundary() -> None:
    sent = _run_finalize_error_exchange()
    types_sent = [m.get("type") for m in sent]
    assert "error" in types_sent, f"finalize exception must emit error frame, got {types_sent}"
    assert "final" in types_sent, f"finalize exception must still emit final (unblocks turn), got {types_sent}"
    error_idx = next(i for i, m in enumerate(sent) if m.get("type") == "error")
    final_idx = next(i for i, m in enumerate(sent) if m.get("type") == "final")
    assert error_idx < final_idx, "error frame must precede final"


def _run_reset_pcm_exchange():
    """M2 proof: reset then PCM must not KeyError (hybrid new_stream_state omits _turn_pcm)."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    chunk = b"\x40\x10" * 8960
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": "", "n": 0}  # intentionally no _turn_pcm
    def _dec(m, s, pcm):
        if pcm.strip(b"\x00"): s["n"] += 1; s["text"] = f"w{s['n']}"
        return s["text"]
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: s.get("text", "")
    prim.reset_turn_state = lambda s: s.update(text="", n=0)
    fin = types.ModuleType("backend_parakeet"); fin.STREAMS = False
    fin.load_model = lambda: {}
    fin.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    fin.decode_chunk = lambda m, s, pcm: ""
    fin.finalize = lambda m, s: f"P:{len(s.get('_turn_pcm', b''))}"
    fin.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_nemo"] = prim; sys.modules["backend_parakeet"] = fin
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "hybrid"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [
        {"bytes": chunk},
        {"text": '{"type":"reset"}'},  # new_stream_state omits _turn_pcm
        {"bytes": chunk},              # would KeyError without M2 fix
        {"type": "websocket.disconnect"},
    ]
    ws = _FakeWebSocket(frames)
    raised = None
    try:
        _run_async(server.ws_stream(ws))
    except Exception as exc:
        raised = exc
    return raised


def _assert_reset_turn_pcm_safe() -> None:
    raised = _run_reset_pcm_exchange()
    assert raised is None, f"reset+PCM must not raise, got {type(raised).__name__}: {raised}"


def _run_streaming_eou_exchange():
    """Streaming stub: text-stall EOU must yield a final with dur_ms == 0 (pre-R3 compat, F2)."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    chunk = b"\x40\x10" * 8960   # 17920 bytes = 1 stream chunk @ 16kHz int16
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {"n": 0}
    prim.new_stream_state = lambda m: {"text": "", "n": 0}
    def _dec(m, s, pcm):
        if pcm.strip(b"\x00"):
            s["n"] += 1; s["text"] = f"word{s['n']}"
        return s["text"]
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: s.get("text", "")
    prim.reset_turn_state = lambda s: s.update(text="", n=0)
    sys.modules["backend_nemo"] = prim
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "streaming"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [{"bytes": chunk}, {"bytes": chunk}] + \
             [{"bytes": b"\x00\x00" * 8960} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    return ws.sent


def _assert_streaming_eou_dur_ms() -> None:
    """F2: streaming autonomous final must carry dur_ms==0 (pre-R3 stt_ms byte-identity)."""
    sent = _run_streaming_eou_exchange()
    final = next((m for m in sent if m.get("type") == "final"), None)
    assert final is not None, "streaming EOU must yield a final"
    assert final.get("dur_ms") == 0, (
        f"streaming autonomous final must carry dur_ms==0 (pre-R3 compat), got {final!r}")


def _self_check() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _assert_parakeet_imports_without_ort()
    _assert_parakeet_real_body()
    _assert_buffered_eou()
    _assert_hybrid()
    _assert_finalize_error_boundary()
    _assert_reset_turn_pcm_safe()
    _assert_streaming_eou_dur_ms()
    print("engine _self_check OK — seam, hybrid, I1 finalize-boundary, M2 reset-pcm, F2 streaming-dur-ms",
          file=sys.stderr)


if __name__ == "__main__":
    _self_check()
