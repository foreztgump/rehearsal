"""Sandbox self-checks for the R3 STT_ENGINE composition (no ORT/NeMo/fastapi).

Run: python3 stt/test_engine.py
"""
from __future__ import annotations

import base64
import io
import os
import struct
import subprocess
import sys
import wave


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


def _assert_no_dead_recycle_hard_chars() -> None:
    """F27: RECYCLE_HARD_CHARS was dead config — defined in backend_common, imported by
    backend_nemo, referenced by no decode code. It must be GONE from both, while
    RECYCLE_MIN_CHARS (the live stall floor) stays. Both backends must still import."""
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import backend_common as c; "
        "assert not hasattr(c, 'RECYCLE_HARD_CHARS'), 'F27: RECYCLE_HARD_CHARS must be deleted'; "
        "assert hasattr(c, 'RECYCLE_MIN_CHARS'), 'RECYCLE_MIN_CHARS is live — keep it'; "
        "import backend_nemo as n; "
        "assert not hasattr(n, 'RECYCLE_HARD_CHARS'), 'F27: backend_nemo must not re-export it'; "
        "assert n.RECYCLE_MIN_CHARS == c.RECYCLE_MIN_CHARS"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_PARAKEET_MODEL"}
        | {"STT_MODEL": "nvidia/parakeet-tdt-0.6b-v2"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"F27 dead-config check failed: {proc.stderr.strip()}"


def _assert_stall_recycle_preserves_committed_text() -> None:
    """F22: on a decoder stall the watchdog clears prev_hyps, restarting the cumulative
    transcript from empty. The pre-recycle text was only ever emitted as interim deltas
    (LiveKit commits FINALs only), so it was permanently lost; and the first post-recycle
    decode returned empty, flipping the server's _final_pending False → a turn that ends
    right after the recycle never commits. Fix: fold the held text forward as a committed
    prefix so decode_chunk keeps returning prefix+new (text preserved AND non-empty).

    Drives the REAL _track_stall/decode_chunk with _stream_step monkeypatched to a
    scripted cumulative sequence (no torch). Runs for BOTH backends via subprocess."""
    here = os.path.dirname(os.path.abspath(__file__))
    for module, model_env, step_name in (
        ("backend_nemo", {"STT_MODEL": "nvidia/parakeet-tdt-0.6b-v2"}, "_stream_step"),
        ("backend_onnx", {"STT_ONNX_MODEL": "x", "STT_QUANT": "int8-dynamic", "STT_RUNTIME": "cpu"},
         "_encode_decode_step"),
    ):
        code = (
            f"import backend_common as c; c.STALL_FRAMES = 2; c.RECYCLE_MIN_CHARS = 3\n"
            f"import {module} as b\n"
            f"b.STALL_FRAMES = 2; b.RECYCLE_MIN_CHARS = 3\n"
            # Scripted decode: grow to a long held string, stall (repeat it) until the\n"
            # watchdog recycles, then the underlying step returns '' (post-recycle empty)\n"
            # then a new word. A correct fold keeps the held text as a committed prefix.\n"
            f"seq = iter(['hello world foo', 'hello world foo', 'hello world foo', '', 'bar'])\n"
            f"b.{step_name} = lambda *a, **k: next(seq)\n"
            f"st = {{'last_text_len': 0, 'frames_since_growth': 0,\n"
            f"      'prev_hyps': 1, 'prev_pred_out': None,\n"
            f"      'emitted_token_ids': [1], 'dec_state': None,\n"
            f"      'cache_last_channel': None, 'cache_last_time': None, 'cache_last_channel_len': None}}\n"
            f"outs = [b.decode_chunk(None, st, b'x') for _ in range(5)]\n"
            # After the recycle the held 'hello world foo' must NOT vanish, and the\n"
            # final decode must still contain both the committed prefix and 'bar'.\n"
            f"assert outs[-1], f'F22: post-recycle decode went empty (turn would wedge): {{outs!r}}'\n"
            f"assert 'hello world foo' in outs[-1], f'F22: committed text lost on recycle: {{outs!r}}'\n"
            f"assert 'bar' in outs[-1], f'F22: post-recycle growth lost: {{outs!r}}'\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=here,
            env={k: v for k, v in os.environ.items() if k not in ("STT_MODEL", "STT_ONNX_MODEL")}
            | model_env,
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"F22 {module} stall-recycle fold failed: {proc.stderr.strip()}"


def _assert_parakeet_nemo_imports_without_nemo() -> None:
    """GPU buffered backend must byte-import without NeMo until load_model()."""
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import backend_parakeet_nemo as b; "
        "assert b.STREAMS is False; "
        "assert all(hasattr(b, n) for n in "
        "('load_model','new_stream_state','decode_chunk','finalize','reset_turn_state')); "
        "st = b.new_stream_state(None); "
        "before = bytes(st['_turn_pcm']); "
        "assert b.decode_chunk(None, st, b'\\x01\\x02') == ''; "
        "assert bytes(st['_turn_pcm']) == before; "
        "st['_turn_pcm'] = bytearray(b'abc'); b.reset_turn_state(st); "
        "assert bytes(st['_turn_pcm']) == b''"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_PARAKEET_MODEL"}
        | {"STT_MODEL": "nvidia/parakeet-tdt-0.6b-v2"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"backend_parakeet_nemo seam import failed: {proc.stderr.strip()}"


def _assert_parakeet_nemo_real_body() -> None:
    """NeMo Parakeet finalize passes one float32 waveform to model.transcribe()."""
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import backend_parakeet_nemo as backend\n"
        "calls = {}\n"
        "class Model:\n"
        "    def transcribe(self, audio):\n"
        "        calls['count'] = len(audio)\n"
        "        calls['dtype'] = str(audio[0].dtype)\n"
        "        calls['samples'] = audio[0].tolist()\n"
        "        return [type('R', (), {'text': 'parakeet text'})()]\n"
        "state = backend.new_stream_state(Model())\n"
        "state['_turn_pcm'] = bytearray(b'\\x01\\x00\\xff\\xff')\n"
        "assert backend.finalize(Model(), state) == 'parakeet text'\n"
        "assert calls == {'count': 1, 'dtype': 'float32', 'samples': [1.0, -1.0]}, calls\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=here,
        env={k: v for k, v in os.environ.items() if k != "STT_PARAKEET_MODEL"}
        | {"STT_MODEL": "nvidia/parakeet-tdt-0.6b-v2"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"backend_parakeet_nemo real body failed: {proc.stderr.strip()}"


def _assert_gpu_buffered_uses_nemo_parakeet() -> None:
    """GPU buffered means NeMo Parakeet; CPU buffered keeps sherpa ONNX."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub

    gpu = types.ModuleType("backend_parakeet_nemo"); gpu.STREAMS = False
    gpu.load_model = lambda: {}
    gpu.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    gpu.decode_chunk = lambda m, s, pcm: ""
    gpu.finalize = lambda m, s: "gpu"
    gpu.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    cpu = types.ModuleType("backend_parakeet"); cpu.STREAMS = False
    cpu.load_model = lambda: {}
    cpu.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    cpu.decode_chunk = lambda m, s, pcm: ""
    cpu.finalize = lambda m, s: "cpu"
    cpu.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet_nemo"] = gpu
    sys.modules["backend_parakeet"] = cpu
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "nvidia/parakeet-tdt-0.6b-v2"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server._primary is gpu and server._final is gpu, "GPU buffered must use NeMo Parakeet"


def _assert_default_engine_is_buffered() -> None:
    """Unset STT_ENGINE must default to GPU buffered Parakeet, not legacy streaming."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub

    gpu = types.ModuleType("backend_parakeet_nemo"); gpu.STREAMS = False
    gpu.load_model = lambda: {}
    gpu.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    gpu.decode_chunk = lambda m, s, pcm: ""
    gpu.finalize = lambda m, s: "gpu"
    gpu.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet_nemo"] = gpu
    _install_fastapi_stub()
    os.environ.pop("STT_ENGINE", None)
    os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "nvidia/parakeet-tdt-0.6b-v2"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server.ENGINE == "buffered", f"default engine must be buffered, got {server.ENGINE!r}"
    assert server._primary is gpu and server._final is gpu, "default GPU backend must be NeMo Parakeet"


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


def _run_buffered_leading_silence_exchange():
    """Buffered engine with MANY inter-turn silence chunks BEFORE the voiced turn.
    The finalized PCM must reflect the turn (+ a small pre-voice lead-in), not every
    silence chunk accumulated since the last final (F7). The stub finalize encodes
    the turn-PCM byte count so the test can assert on what Parakeet would decode."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    stub = types.ModuleType("backend_parakeet")
    stub.STREAMS = False
    stub.load_model = lambda: {}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""
    stub.finalize = lambda m, s: f"buffered:{len(s['_turn_pcm'])}"
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    chunk = server._STREAM_CHUNK_BYTES
    voiced = b"\x40\x10" * (chunk // 2)   # exactly one stream chunk, loud
    silence = b"\x00\x00" * (chunk // 2)  # exactly one stream chunk, silent
    # 10 inter-turn silence chunks, then 2 voiced, then silence across the EOU window.
    frames = [{"bytes": silence} for _ in range(10)] + \
             [{"bytes": voiced}, {"bytes": voiced}] + \
             [{"bytes": silence} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    return server, [m for m in ws.sent if m.get("type") in ("delta", "final")]


def _assert_buffered_trims_leading_silence() -> None:
    server, msgs = _run_buffered_leading_silence_exchange()
    kinds = [m["type"] for m in msgs]
    assert kinds.count("final") == 1, f"buffered must emit exactly one final, got {kinds}"
    chunk = server._STREAM_CHUNK_BYTES
    final_bytes = int(msgs[-1]["text"].split(":")[1])
    assert final_bytes >= 2 * chunk, (
        f"buffered final must retain the voiced turn, got {final_bytes} bytes (<2 chunks)")
    assert final_bytes < 8 * chunk, (
        f"buffered final must trim the 10 leading-silence chunks, got {final_bytes} bytes (>=8 chunks)")


def _assert_buffered_never_voiced_stays_bounded() -> None:
    """Never-voiced silence must neither fire a spurious final at the max-buffer cap
    nor grow the buffer unboundedly (F7/O2). Drives _emit_buffered directly so the
    per-connection turn buffer is observable after the run."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    stub = types.ModuleType("backend_parakeet")
    stub.STREAMS = False
    stub.load_model = lambda: {}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""
    stub.finalize = lambda m, s: f"buffered:{len(s['_turn_pcm'])}"
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    chunk = server._STREAM_CHUNK_BYTES
    silence = b"\x00\x00" * (chunk // 2)
    # Enough pure-silence chunks to exceed _MAX_BUFFER_BYTES under the buggy
    # unconditional-accumulate code, which would then fire a spurious silence final.
    n = server._MAX_BUFFER_BYTES // chunk + 5
    ws = _FakeWebSocket([])
    state = server._primary.new_stream_state(None)

    async def _drive():
        for _ in range(n):
            await server._emit_buffered(ws, state, silence)

    _run_async(_drive())
    assert not any(m.get("type") == "final" for m in ws.sent), (
        f"never-voiced silence must emit no final, got {ws.sent!r}")
    assert len(state["_turn_pcm"]) <= 2 * chunk, (
        f"never-voiced buffer must stay ring-bounded, grew to {len(state['_turn_pcm'])} bytes")


def _assert_hybrid_turn_pcm_stays_bounded() -> None:
    """F23: hybrid/streaming _turn_pcm had no cap. Continuous above-threshold NON-speech
    noise (fan/music) decodes to empty text, so _final_pending never flips and no EOU
    fires — the buffer grew ~1.9 MB/min per connection forever. Drives _emit_streaming
    directly with noise that never decodes; _turn_pcm must stay bounded by the cap."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": ""}
    prim.decode_chunk = lambda m, s, pcm: ""      # noise never decodes to text
    prim.finalize = lambda m, s: ""
    prim.reset_turn_state = lambda s: s.update(text="")
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
    chunk = server._STREAM_CHUNK_BYTES
    noise = b"\x40\x10" * (chunk // 2)   # RMS 4160 >= ENERGY_SILENCE_RMS: above threshold, non-silent
    n = server._MAX_BUFFER_BYTES // chunk + 5
    ws = _FakeWebSocket([])
    state = server._primary.new_stream_state(None)
    state.setdefault("_turn_pcm", bytearray())

    async def _drive():
        for _ in range(n):
            await server._emit_streaming(ws, state, noise)

    _run_async(_drive())
    assert len(state["_turn_pcm"]) <= server._MAX_BUFFER_BYTES, (
        f"F23: hybrid _turn_pcm must stay <= _MAX_BUFFER_BYTES, grew to {len(state['_turn_pcm'])} bytes")


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
    assert final["text"].startswith("word"), f"hybrid final must be streaming text, got {final!r}"
    assert final.get("dur_ms") == 0, f"hybrid streaming final must not wait for Parakeet, got {final!r}"
    correction = next((m for m in sent if m.get("type") == "correction"), None)
    assert correction is not None, f"hybrid must emit Parakeet correction, got {sent!r}"
    assert correction["text"].startswith("PARAKEET:"), (
        f"hybrid correction must be Parakeet, got {correction!r}")
    assert int(correction["text"].split(":")[1]) > 0, (
        "hybrid correction must see accumulated _turn_pcm")
    assert "dur_ms" in correction and isinstance(correction["dur_ms"], int) and correction["dur_ms"] >= 0, (
        f"hybrid final must carry dur_ms int >= 0, got {final!r}")


def _assert_hybrid_stall_waits_for_silence() -> None:
    """Voiced audio with stalled NeMo text must not cut the turn before silence."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    chunk = b"\x40\x10" * 8960
    silence = b"\x00\x00" * 8960
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": ""}
    def _dec(m, s, pcm):
        s["text"] = s.get("text") or "stuck"
        return s["text"]
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: ""
    prim.reset_turn_state = lambda s: s.update(text="")
    fin = types.ModuleType("backend_parakeet"); fin.STREAMS = False
    fin.load_model = lambda: {}
    fin.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    fin.decode_chunk = lambda m, s, pcm: ""
    fin.finalize = lambda m, s: f"P:{len(s['_turn_pcm'])}"
    fin.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_nemo"] = prim; sys.modules["backend_parakeet"] = fin
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "hybrid"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [{"bytes": chunk}] + \
             [{"bytes": chunk} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"bytes": silence} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    final = next((m for m in ws.sent if m.get("type") == "final"), None)
    assert final is not None, f"silence after voiced stall must emit final, got {ws.sent!r}"
    correction = next((m for m in ws.sent if m.get("type") == "correction"), None)
    assert correction is not None, f"silence after voiced stall must emit correction, got {ws.sent!r}"
    final_bytes = int(correction["text"].split(":")[1])
    min_voiced_bytes = (server._ENDPOINT_SILENCE_CHUNKS + 2) * len(chunk)
    assert final_bytes >= min_voiced_bytes, (
        f"hybrid must wait for silence before correcting, got {correction!r}")


def _assert_hybrid_skips_leading_silence_for_final_pcm() -> None:
    """Hybrid Parakeet audio must start with the voiced turn, not connection idle."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    chunk = b"\x40\x10" * 8960
    silence = b"\x00\x00" * 8960
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": ""}
    def _dec(m, s, pcm):
        if pcm.strip(b"\x00"):
            s["text"] = "voice"
        return s["text"]
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: ""
    prim.reset_turn_state = lambda s: s.update(text="")
    fin = types.ModuleType("backend_parakeet"); fin.STREAMS = False
    fin.load_model = lambda: {}
    fin.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    fin.decode_chunk = lambda m, s, pcm: ""
    fin.finalize = lambda m, s: f"P:{len(s['_turn_pcm'])}"
    fin.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_nemo"] = prim; sys.modules["backend_parakeet"] = fin
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "hybrid"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [{"bytes": silence}, {"bytes": silence}, {"bytes": silence}, {"bytes": chunk}] + \
             [{"bytes": silence} for _ in range(server._ENDPOINT_SILENCE_CHUNKS + 1)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    final = next((m for m in ws.sent if m.get("type") == "final"), None)
    assert final is not None, f"silence after voice must emit final, got {ws.sent!r}"
    correction = next((m for m in ws.sent if m.get("type") == "correction"), None)
    assert correction is not None, f"silence after voice must emit correction, got {ws.sent!r}"
    final_bytes = int(correction["text"].split(":")[1])
    assert final_bytes >= server._STREAM_CHUNK_BYTES, (
        f"hybrid correction PCM must include voiced audio, got {correction!r}")
    assert final_bytes < 3 * len(silence) + len(chunk), (
        f"hybrid correction PCM must omit leading silence, got {correction!r}")


def _assert_debug_sample_wav() -> None:
    """Hybrid debug payload must preserve stream text, final text, and playable WAV."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub

    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {}
    prim.decode_chunk = lambda m, s, pcm: ""
    prim.finalize = lambda m, s: ""
    prim.reset_turn_state = lambda s: None
    fin = types.ModuleType("backend_parakeet"); fin.STREAMS = False
    fin.load_model = lambda: {}
    fin.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    fin.decode_chunk = lambda m, s, pcm: ""
    fin.finalize = lambda m, s: "parakeet words"
    fin.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_nemo"] = prim; sys.modules["backend_parakeet"] = fin
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "hybrid"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    silence = b"\x00\x00" * 160
    voice = struct.pack("<h", 1000) * 320 + struct.pack("<h", -1000) * 320
    pcm = silence + voice + silence
    sample = server._debug_sample({"_turn_pcm": bytearray(pcm), "_last_delta_text": "stream words"},
                                  "parakeet words", 42)
    assert sample["stream_transcript"] == "stream words"
    assert sample["parakeet_transcript"] == "parakeet words"
    assert sample["dur_ms"] == 42 and sample["pcm_bytes"] == len(pcm)
    assert sample["audio_peak"] == 1000
    assert sample["audio_rms"] == 816
    assert sample["audio_clip_pct"] == 0.0
    assert sample["leading_silence_ms"] == 10
    assert sample["trailing_silence_ms"] == 10
    with wave.open(io.BytesIO(base64.b64decode(sample["audio_wav_b64"])), "rb") as wav:
        assert wav.getframerate() == server.SAMPLE_RATE
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == pcm


def _assert_buffered_debug_sample_is_retained() -> None:
    """Buffered Parakeet is now the selected path, so debug capture must work there."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub

    stub = types.ModuleType("backend_parakeet_nemo")
    stub.STREAMS = False
    stub.load_model = lambda: {}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""
    stub.finalize = lambda m, s: "buffered words"
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet_nemo"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_DEBUG_HYBRID"] = "1"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    server._remember_debug_sample_from_pcm("", "buffered words", 11, b"\x00\x00" * 160)
    assert server._debug_samples[-1]["parakeet_transcript"] == "buffered words"


def _load_server_with_buffered_stub(finalize=None):
    """Import server with a buffered backend_parakeet stub for offline-route tests (F8)."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub

    stub = types.ModuleType("backend_parakeet")
    stub.STREAMS = False
    stub.load_model = lambda: {}
    stub.new_stream_state = lambda m: {"_turn_pcm": bytearray()}
    stub.decode_chunk = lambda m, s, pcm: ""  # server owns _turn_pcm via _ACCUMULATE_PCM
    stub.finalize = finalize or (lambda m, s: f"buffered:{len(s['_turn_pcm'])}")
    stub.reset_turn_state = lambda s: s.update(_turn_pcm=bytearray())
    sys.modules["backend_parakeet"] = stub
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_PARAKEET_MODEL"] = "x"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    server._primary_model = server._primary.load_model()
    server._final_model = server._primary_model
    return server


def _wav_bytes(*, framerate=16000, nchannels=1, sampwidth=2, frames=1600) -> bytes:
    """Build a small in-memory WAV with the given parameters."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(nchannels)
        wav.setsampwidth(sampwidth)
        wav.setframerate(framerate)
        wav.writeframes(b"\x00\x01" * (frames * nchannels * (sampwidth // 2)))
    return buf.getvalue()


def _assert_offline_valid_wav_transcribes() -> None:
    server = _load_server_with_buffered_stub()

    class _Upload:
        def __init__(self, data): self._data = data
        async def read(self, *a): return self._data

    result = _run_async_return(lambda: server.transcribe_file(_Upload(_wav_bytes())))
    assert result["text"].startswith("buffered:"), f"valid WAV must transcribe, got {result!r}"


def _assert_offline_rejects_oversize_upload() -> None:
    server = _load_server_with_buffered_stub()
    fastapi = sys.modules["fastapi"]

    class _Upload:
        # read(limit) returns limit+1 bytes so the route sees it exceeded the cap
        async def read(self, *a):
            return b"\x00" * (server._OFFLINE_MAX_BYTES + 1)

    raised = None
    try:
        _run_async_return(lambda: server.transcribe_file(_Upload()))
    except fastapi.HTTPException as exc:
        raised = exc
    assert raised is not None and raised.status_code == 413, (
        f"oversize upload must raise HTTP 413, got {raised!r}")


def _assert_offline_rejects_wrong_wav_params() -> None:
    server = _load_server_with_buffered_stub()
    fastapi = sys.modules["fastapi"]

    class _Upload:
        def __init__(self, data): self._data = data
        async def read(self, *a): return self._data

    for label, wav in (
        ("44.1kHz", _wav_bytes(framerate=44100)),
        ("stereo", _wav_bytes(nchannels=2)),
        ("8-bit", _wav_bytes(sampwidth=1)),
    ):
        raised = None
        try:
            _run_async_return(lambda: server.transcribe_file(_Upload(wav)))
        except fastapi.HTTPException as exc:
            raised = exc
        assert raised is not None and raised.status_code == 400, (
            f"{label} WAV must raise HTTP 400, got {raised!r}")


def _assert_offline_decode_holds_gpu_lock() -> None:
    """F8/F11: the offline decode must run under _gpu_lock, like the WS path — otherwise
    an offline+WS overlap runs the model from two threads and arms the _quiet_nemo race."""
    observed = {"locked_during_finalize": None}

    def _finalize(m, s):
        observed["locked_during_finalize"] = server._gpu_lock.locked()
        return "ok"

    server = _load_server_with_buffered_stub(finalize=_finalize)

    class _Upload:
        def __init__(self, data): self._data = data
        async def read(self, *a): return self._data

    _run_async_return(lambda: server.transcribe_file(_Upload(_wav_bytes())))
    assert observed["locked_during_finalize"] is True, (
        "offline finalize must run while _gpu_lock is held")


def _run_async_return(make_coro):
    """Like test_dispatch._run_async but returns the coroutine result."""
    import asyncio
    loop = asyncio.new_event_loop()
    original_to_thread = asyncio.to_thread

    async def inline_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    try:
        asyncio.to_thread = inline_to_thread
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(make_coro())
    finally:
        asyncio.to_thread = original_to_thread
        asyncio.set_event_loop(None)
        loop.close()


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


def _assert_no_spurious_empty_delta_after_final() -> None:
    """F26: after a final, _send_final resets the per-turn dedup marker. The next
    silent chunk decodes to '' — that must NOT be re-emitted as a delta. Previously
    the marker was popped (None), so `'' != None` counted as growth and a spurious
    {"type":"delta","text":""} was sent after EVERY final. No empty delta may appear
    at all in this exchange (the stub only ever decodes '' or 'wordN')."""
    sent = _run_streaming_eou_exchange()
    empties = [m for m in sent if m.get("type") == "delta" and m.get("text") == ""]
    assert not empties, f"F26: no empty-text delta may follow a final, got {sent}"
    # And a final must still fire (we did not break EOU).
    assert any(m.get("type") == "final" for m in sent), f"EOU final still required, got {sent}"


def _run_handshake(mode: str):
    """Drive ws_stream's config handshake with a fake WS that fails in `mode`:
    'disconnect' (client drops mid-handshake), 'binary' (bytes first frame ->
    Starlette KeyError('text')), or 'hang' (silent socket). Returns (ws, raised)."""
    import asyncio, importlib, types
    from test_dispatch import _install_fastapi_stub, _run_async

    _install_fastapi_stub()
    disconnect_exc = sys.modules["fastapi"].WebSocketDisconnect
    prim = types.ModuleType("backend_onnx"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": ""}
    prim.decode_chunk = lambda m, s, pcm: ""
    prim.finalize = lambda m, s: ""
    prim.reset_turn_state = lambda s: None
    sys.modules["backend_onnx"] = prim
    os.environ["STT_ENGINE"] = "streaming"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_HANDSHAKE_TIMEOUT_S"] = "0.05"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")

    class _HandshakeWS:
        def __init__(self) -> None:
            self.sent: list = []
            self.closed = False
        async def accept(self) -> None: return None
        async def receive_json(self):
            if mode == "disconnect":
                raise disconnect_exc()
            if mode == "binary":
                raise KeyError("text")           # Starlette raises this on a bytes first frame
            if mode == "hang":
                await asyncio.sleep(5)            # never returns before the 0.05 s timeout
            return {"type": "config"}
        async def receive(self):
            return {"type": "websocket.disconnect"}
        async def send_json(self, payload) -> None: self.sent.append(payload)
        async def close(self, *a, **k) -> None: self.closed = True

    ws = _HandshakeWS()
    raised = None
    try:
        _run_async(server.ws_stream(ws))
    except BaseException as exc:  # noqa: BLE001 - capture ANY leak for the assertion
        raised = exc
    return ws, raised


def _assert_debug_hybrid_exposure_warning() -> None:
    """F37: STT_DEBUG_HYBRID=1 serves recent raw mic audio + transcripts unauthenticated
    on the published port. It is default-off, but when enabled the server must emit a
    loud startup warning so the operator knows the exposure is live. The decision is a
    pure helper: a non-empty warning iff the flag is on."""
    import importlib
    from test_dispatch import _install_fastapi_stub

    _install_fastapi_stub()
    for flag, want_warning in (("1", True), ("0", False)):
        os.environ["STT_ENGINE"] = "buffered"; os.environ["STT_RUNTIME"] = "cpu"
        os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_DEBUG_HYBRID"] = flag
        sys.modules.pop("server", None)
        server = importlib.import_module("server")
        warning = server._debug_hybrid_warning()
        if want_warning:
            assert warning, "STT_DEBUG_HYBRID=1 must produce a startup exposure warning"
            assert "STT_DEBUG_HYBRID" in warning and "audio" in warning.lower(), warning
        else:
            assert warning == "", f"default-off flag must produce no warning, got {warning!r}"
    os.environ["STT_DEBUG_HYBRID"] = "0"


def _assert_max_connections_guard() -> None:
    """G8: each live streaming connection pins persistent encoder cache (~8 MB VRAM in
    legacy modes) and can monopolize the single global decode lock, so many idle/noise
    LAN connections can exhaust VRAM. Bound concurrent streams by STT_MAX_CONNECTIONS.

    A new connection ABOVE the cap must be rejected during the handshake (closed, no
    'ready'); the live-connection counter must decrement when a stream ends so slots
    are reclaimed (no permanent leak)."""
    import importlib
    from test_dispatch import (
        _install_fastapi_stub, _install_backend_stub, _FakeWebSocket, _run_async,
    )

    _install_fastapi_stub(); _install_backend_stub()
    os.environ["STT_ENGINE"] = "streaming"; os.environ["STT_RUNTIME"] = "cpu"
    os.environ["STT_ONNX_MODEL"] = "x"; os.environ["STT_MAX_CONNECTIONS"] = "1"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server.STT_MAX_CONNECTIONS == 1

    # Pure admission decision: at/over the cap is refused, under is admitted.
    assert server._connection_slot_available(0) is True
    assert server._connection_slot_available(1) is False

    # End-to-end: with the cap already saturated, a new connection is rejected during
    # the handshake — no 'ready', socket closed — without touching the decode path.
    server._live_connections = server.STT_MAX_CONNECTIONS
    ws = _FakeWebSocket([{"type": "websocket.disconnect"}])
    ws.closed = False
    orig_close = getattr(ws, "close", None)
    async def _close(*a, **k): ws.closed = True
    ws.close = _close
    _run_async(server.ws_stream(ws))
    assert not any(m.get("type") == "ready" for m in ws.sent), (
        f"over-cap connection must not get ready, got {ws.sent}")
    assert ws.closed, "over-cap connection must be closed"
    # The rejected over-cap connection must NOT change the counter (it never took a slot).
    assert server._live_connections == server.STT_MAX_CONNECTIONS, (
        f"rejected connection must not alter the live count, got {server._live_connections}")

    # A normal connection under the cap runs and RELEASES its slot on exit.
    server._live_connections = 0
    ws2 = _FakeWebSocket([{"bytes": b"\x00\x01\x02\x03"}, {"type": "websocket.disconnect"}])
    _run_async(server.ws_stream(ws2))
    assert any(m.get("type") == "ready" for m in ws2.sent), "under-cap connection must get ready"
    assert server._live_connections == 0, (
        f"a finished stream must release its slot, got {server._live_connections}")
    os.environ.pop("STT_MAX_CONNECTIONS", None)


def _assert_config_handshake_is_guarded() -> None:
    """F25: the config handshake was outside any guard and unbounded. Assert all three
    failure modes are now handled cleanly: no exception leaks out of ws_stream, no
    'ready' is sent on a failed handshake, and a hanging client is bounded by timeout."""
    for mode in ("disconnect", "binary", "hang"):
        ws, raised = _run_handshake(mode)
        assert raised is None, f"F25[{mode}]: handshake failure must not leak, got {type(raised).__name__}: {raised}"
        assert not any(m.get("type") == "ready" for m in ws.sent), (
            f"F25[{mode}]: no ready may be sent on a failed handshake, got {ws.sent}")


def _assert_raw_silence_endpoint_is_not_chunk_quantized() -> None:
    """700 ms of raw silence must end a turn without waiting for two 560 ms decodes."""
    import importlib, types
    from test_dispatch import _install_fastapi_stub, _FakeWebSocket, _run_async

    chunk = b"\x40\x10" * 8960
    raw_silence = b"\x00\x00" * 320  # 20 ms at 16 kHz mono int16
    prim = types.ModuleType("backend_nemo"); prim.STREAMS = True
    prim.load_model = lambda: {}
    prim.new_stream_state = lambda m: {"text": ""}
    def _dec(m, s, pcm):
        if pcm.strip(b"\x00"):
            s["text"] = "voice"
        return s["text"]
    prim.decode_chunk = _dec
    prim.finalize = lambda m, s: s.get("text", "")
    prim.reset_turn_state = lambda s: s.update(text="")
    sys.modules["backend_nemo"] = prim
    _install_fastapi_stub()
    os.environ["STT_ENGINE"] = "streaming"; os.environ["STT_RUNTIME"] = "gpu"
    os.environ["STT_MODEL"] = "x"; os.environ["STT_STREAM_CHUNK_MS"] = "560"
    os.environ["STT_ENDPOINT_SILENCE_MS"] = "700"
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    frames = [{"bytes": chunk}] + [{"bytes": raw_silence} for _ in range(35)] + \
             [{"type": "websocket.disconnect"}]
    ws = _FakeWebSocket(frames)
    _run_async(server.ws_stream(ws))
    final = next((m for m in ws.sent if m.get("type") == "final"), None)
    assert final is not None, f"raw 700 ms silence must emit final, got {ws.sent!r}"


def _self_check() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _assert_parakeet_imports_without_ort()
    _assert_parakeet_real_body()
    _assert_no_dead_recycle_hard_chars()
    _assert_stall_recycle_preserves_committed_text()
    _assert_parakeet_nemo_imports_without_nemo()
    _assert_parakeet_nemo_real_body()
    _assert_default_engine_is_buffered()
    _assert_gpu_buffered_uses_nemo_parakeet()
    _assert_buffered_eou()
    _assert_buffered_trims_leading_silence()
    _assert_buffered_never_voiced_stays_bounded()
    _assert_offline_valid_wav_transcribes()
    _assert_offline_rejects_oversize_upload()
    _assert_offline_rejects_wrong_wav_params()
    _assert_offline_decode_holds_gpu_lock()
    _assert_hybrid()
    _assert_hybrid_turn_pcm_stays_bounded()
    _assert_hybrid_stall_waits_for_silence()
    _assert_hybrid_skips_leading_silence_for_final_pcm()
    _assert_debug_sample_wav()
    _assert_buffered_debug_sample_is_retained()
    _assert_finalize_error_boundary()
    _assert_reset_turn_pcm_safe()
    _assert_streaming_eou_dur_ms()
    _assert_no_spurious_empty_delta_after_final()
    _assert_debug_hybrid_exposure_warning()
    _assert_max_connections_guard()
    _assert_config_handshake_is_guarded()
    _assert_raw_silence_endpoint_is_not_chunk_quantized()
    print("engine _self_check OK — seam, GPU buffered Parakeet, hybrid, voiced-stall EOU, trimmed PCM, debug WAV, I1 finalize-boundary, M2 reset-pcm, F2 streaming-dur-ms, raw-silence EOU, F7 buffered-silence-trim, F8 offline-lock+size+wav-validation",
          file=sys.stderr)


if __name__ == "__main__":
    _self_check()
