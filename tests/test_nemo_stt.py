"""Behavioral tests for agent/nemo_stt.py reconnect + correction-callback resilience.

nemo_stt is a livekit-agents STT plugin, so it hard-imports the framework. Like the
STT server tests stub fastapi, this installs a minimal `livekit.agents` stub into
sys.modules BEFORE importing nemo_stt, then drives `_run`/`_recv_loop` directly with
fake aiohttp transports. No GPU, no livekit install, no network.

Covers:
  * F9  — aiohttp/OS transport errors from connect/send map to APIConnectionError so
          the base RecognizeStream retry machinery (which retries only APIError) kicks
          in instead of permanently killing STT for the session.
  * G3  — a connect timeout maps to APITimeoutError (conn_options.timeout is applied).
  * F24 — an exception raised by the correction callback is logged and swallowed so
          _recv_loop keeps mapping later transcripts instead of dying silently.

Run: `python3 tests/test_nemo_stt.py` or `python3 -m pytest tests/test_nemo_stt.py`.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))


def _install_livekit_stub() -> None:
    """Minimal livekit.agents surface so nemo_stt imports + instantiates in the sandbox."""
    if "livekit.agents" in sys.modules:
        return

    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class APIConnectOptions:
        def __init__(self, timeout: float = 10.0) -> None:
            self.timeout = timeout

    class NotGivenOr:
        def __class_getitem__(cls, item):
            return cls

    class _EventChan:
        def __init__(self) -> None:
            self.events: list = []

        def send_nowait(self, evt) -> None:
            self.events.append(evt)

    class STTCapabilities:
        def __init__(self, *, streaming: bool, interim_results: bool) -> None:
            self.streaming = streaming
            self.interim_results = interim_results

    class STT:
        def __init__(self, *, capabilities) -> None:
            self._capabilities = capabilities
            self.emitted: list = []

        @property
        def label(self) -> str:
            return "nemo.test"

        def emit(self, name, obj) -> None:
            self.emitted.append((name, obj))

    class RecognizeStream:
        class _FlushSentinel:
            pass

        def __init__(self, *, stt, conn_options, sample_rate) -> None:
            self._stt = stt
            self._sample_rate = sample_rate
            self._event_ch = _EventChan()
            self._input_ch: list = []

    class SpeechData:
        def __init__(self, *, language, text) -> None:
            self.language = language
            self.text = text

    class SpeechEvent:
        def __init__(self, *, type, alternatives) -> None:
            self.type = type
            self.alternatives = alternatives

    class SpeechEventType:
        INTERIM_TRANSCRIPT = "interim"
        FINAL_TRANSCRIPT = "final"

    stt_ns = types.ModuleType("livekit.agents.stt")
    stt_ns.STT = STT
    stt_ns.RecognizeStream = RecognizeStream
    stt_ns.STTCapabilities = STTCapabilities
    stt_ns.SpeechData = SpeechData
    stt_ns.SpeechEvent = SpeechEvent
    stt_ns.SpeechEventType = SpeechEventType

    agents = types.ModuleType("livekit.agents")
    agents.DEFAULT_API_CONNECT_OPTIONS = APIConnectOptions(timeout=10.0)
    agents.APIConnectOptions = APIConnectOptions
    agents.APIConnectionError = APIConnectionError
    agents.APITimeoutError = APITimeoutError
    agents.NotGivenOr = NotGivenOr
    agents.stt = stt_ns

    metrics = types.ModuleType("livekit.agents.metrics")
    metrics.STTMetrics = type("STTMetrics", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)})

    agents_types = types.ModuleType("livekit.agents.types")
    agents_types.NOT_GIVEN = object()

    livekit = types.ModuleType("livekit")
    livekit.agents = agents

    sys.modules["livekit"] = livekit
    sys.modules["livekit.agents"] = agents
    sys.modules["livekit.agents.stt"] = stt_ns
    sys.modules["livekit.agents.metrics"] = metrics
    sys.modules["livekit.agents.types"] = agents_types


_install_livekit_stub()

import nemo_stt  # noqa: E402
from livekit.agents import APIConnectionError, APITimeoutError  # noqa: E402


def _make_stream(correction_cb=None) -> "nemo_stt.NemoSpeechStream":
    lk = sys.modules["livekit.agents"]
    return nemo_stt.NemoSpeechStream(
        stt=nemo_stt.NemoSTT(ws_url="ws://stt/x"),
        ws_url="ws://stt/x",
        language="en",
        conn_options=lk.APIConnectOptions(timeout=5.0),
        correction_cb=correction_cb,
    )


class _RaisingWSConnect:
    def __init__(self, exc) -> None:
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, exc) -> None:
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def ws_connect(self, url, **kw):
        return _RaisingWSConnect(self._exc)


def _run_with_connect_error(exc):
    """Drive NemoSpeechStream._run with a ClientSession whose ws_connect raises `exc`."""
    stream = _make_stream()
    original = aiohttp.ClientSession
    aiohttp.ClientSession = lambda *a, **k: _FakeSession(exc)
    try:
        asyncio.run(stream._run())
    finally:
        aiohttp.ClientSession = original


def test_connect_client_error_maps_to_api_connection_error() -> None:
    raised = None
    try:
        _run_with_connect_error(aiohttp.ClientError("boom"))
    except BaseException as exc:  # noqa: BLE001
        raised = exc
    assert isinstance(raised, APIConnectionError), (
        f"aiohttp.ClientError must map to APIConnectionError, got {type(raised).__name__}: {raised}")


def test_connect_os_error_maps_to_api_connection_error() -> None:
    raised = None
    try:
        _run_with_connect_error(ConnectionResetError("reset"))
    except BaseException as exc:  # noqa: BLE001
        raised = exc
    assert isinstance(raised, APIConnectionError), (
        f"ConnectionResetError must map to APIConnectionError, got {type(raised).__name__}: {raised}")


def test_connect_timeout_maps_to_api_timeout_error() -> None:
    raised = None
    try:
        _run_with_connect_error(asyncio.TimeoutError())
    except BaseException as exc:  # noqa: BLE001
        raised = exc
    assert isinstance(raised, APITimeoutError), (
        f"a connect timeout must map to APITimeoutError, got {type(raised).__name__}: {raised}")


class _Msg:
    def __init__(self, type, data) -> None:
        self.type = type
        self.data = data


class _FakeWS:
    """Async-iterable fake aiohttp websocket yielding scripted server messages."""

    def __init__(self, messages) -> None:
        self._messages = messages

    def __aiter__(self):
        self._it = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def test_correction_callback_exception_does_not_kill_recv_loop() -> None:
    """F24: a raising correction_cb must be logged + swallowed; a later delta is still
    mapped to an interim event (proving the loop continued)."""
    calls = {"n": 0}

    async def _boom(text: str) -> None:
        calls["n"] += 1
        raise RuntimeError("correction consumer exploded")

    stream = _make_stream(correction_cb=_boom)
    ws = _FakeWS([
        _Msg(aiohttp.WSMsgType.TEXT, json.dumps({"type": "correction", "text": "fix me"})),
        _Msg(aiohttp.WSMsgType.TEXT, json.dumps({"type": "delta", "text": "after correction"})),
        _Msg(aiohttp.WSMsgType.CLOSE, ""),
    ])

    raised = None
    try:
        asyncio.run(stream._recv_loop(ws))
    except BaseException as exc:  # noqa: BLE001
        raised = exc

    assert raised is None, f"_recv_loop must not propagate the callback error, got {raised!r}"
    assert calls["n"] == 1, "correction callback must have been invoked once"
    texts = [a[0].text for e in stream._event_ch.events for a in [e.alternatives]]
    assert "after correction" in texts, (
        f"delta after a failing correction must still be mapped, got {texts}")


def test_successful_correction_callback_is_awaited() -> None:
    received: list[str] = []

    async def _ok(text: str) -> None:
        received.append(text)

    stream = _make_stream(correction_cb=_ok)
    ws = _FakeWS([
        _Msg(aiohttp.WSMsgType.TEXT, json.dumps({"type": "correction", "text": "corrected text"})),
        _Msg(aiohttp.WSMsgType.CLOSE, ""),
    ])
    asyncio.run(stream._recv_loop(ws))
    assert received == ["corrected text"], f"correction cb must receive the text, got {received}"


if __name__ == "__main__":
    test_connect_client_error_maps_to_api_connection_error()
    test_connect_os_error_maps_to_api_connection_error()
    test_connect_timeout_maps_to_api_timeout_error()
    test_correction_callback_exception_does_not_kill_recv_loop()
    test_successful_correction_callback_is_awaited()
    print("ok: nemo_stt reconnect + correction-cb resilience")
