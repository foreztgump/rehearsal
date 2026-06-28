"""Custom streaming STT plugin (NemoSTT) over the Wave-1 nemo-stt websocket.

A true ``livekit.agents.stt.STT`` streaming subclass — NOT an ``openai.STT``
shim. The AgentSession streams 48 kHz mono frames into ``push_frame``; we pass
``sample_rate=16000`` to ``super().__init__`` so LiveKit auto-resamples to the
16 kHz mono int16 PCM the server expects, then forward the bytes over the
websocket frozen by Wave 1 (Plan 09-01):

  client → ``{"type":"config","language":"en"}`` then binary int16 PCM frames +
           control ``{"type":"flush"}`` / ``{"type":"reset"}``
  server → ``{"type":"ready"}``, ``{"type":"delta","text":<cumulative>}``,
           ``{"type":"final","text":...}``, ``{"type":"error","message":...}``

End-of-utterance contract (verified against livekit-agents 1.6.4 source — an
EARLIER version of this module assumed the opposite and the agent never replied):
AgentSession does NOT send a _FlushSentinel on turn end in VAD/dynamic mode. On
end-of-speech ``audio_recognition.commit_user_turn`` pushes SILENCE into the
stream and waits for the plugin to emit ``FINAL_TRANSCRIPT`` on its own (the same
provider-side-endpointing contract Deepgram/AssemblyAI satisfy). ``_audio_transcript``
— the value ``_run_eou_detection`` guards on — is populated ONLY by FINAL events,
so an interim-only plugin deadlocks the turn. Therefore the SERVER emits ``final``
autonomously when the transcript stops growing through silence (see server.py
ENDPOINT_SILENCE_MS); we forward it as FINAL_TRANSCRIPT here. The ``flush`` control
path is still honored (session-close / manual commit) but is not the hot path.
Silero VAD + the local MultilingualModel turn detector still own the SEMANTIC
reply decision — the autonomous final just unblocks the framework's turn machinery.

Native punctuation + capitalization are surfaced AS-IS (no lowercase/strip/
recapitalize) to both the transcript and the LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import aiohttp
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectOptions,
    NotGivenOr,
    stt,
)
from livekit.agents.metrics import STTMetrics
from livekit.agents.types import NOT_GIVEN

logger = logging.getLogger("nemo-stt")


class NemoSTT(stt.STT):
    """Streaming STT facade for the nemo-stt service.

    Declares ``streaming``/``interim_results`` capabilities so AgentSession uses
    the ``stream()`` path; ``_recognize_impl`` is a stub (this plugin is
    streaming-only). The ``model``/``provider`` properties supply the metrics
    ``label`` (no hardcoded tag drives behaviour — the real model is single-
    sourced server-side via ``STT_MODEL``; this string is a label only).
    """

    def __init__(self, *, ws_url: str, language: str = "en") -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._ws_url = ws_url
        self._language = language

    @property
    def model(self) -> str:
        # STT_ENGINE=streaming (or unset) keeps the pre-R3 label "nemotron-streaming"
        # for byte-identical metrics. Buffered/hybrid return their engine name.
        engine = os.environ.get("STT_ENGINE", "streaming")
        return "nemotron-streaming" if engine == "streaming" else engine

    @property
    def provider(self) -> str:
        return "nemo"

    async def _recognize_impl(self, *args, **kwargs) -> stt.SpeechEvent:
        raise NotImplementedError("NemoSTT is streaming-only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "NemoSpeechStream":
        return NemoSpeechStream(
            stt=self,
            ws_url=self._ws_url,
            language=self._language,
            conn_options=conn_options,
        )


class NemoSpeechStream(stt.RecognizeStream):
    """One websocket-backed recognition stream for a single connection.

    ``sample_rate=16000`` makes ``push_frame`` auto-resample LiveKit's 48 kHz
    mono frames to the 16 kHz mono int16 PCM the server's input contract
    requires (RESEARCH §3). Heavy work is split across the small
    ``_run``/``_recv_loop``/``_emit_final`` methods (AGENTS.md ≤40 lines / ≤3
    nesting), with an early-``continue`` on the flush sentinel to cap nesting.
    """

    def __init__(self, *, stt, ws_url, language, conn_options) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16000)
        self._ws_url = ws_url
        self._language = language
        # Wall-clock start of the flush→final finalize span (set on the flush
        # sentinel). None until the first flush so _emit_final guards it.
        self._flush_started: float | None = None

    async def _run(self) -> None:
        """Forward audio + flush over the websocket; receive transcripts."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self._ws_url) as ws:
                await ws.send_json({"type": "config", "language": self._language})
                recv = asyncio.create_task(self._recv_loop(ws))
                async for data in self._input_ch:
                    if isinstance(data, self._FlushSentinel):
                        # Mark the finalize-latency start, then ask the server to
                        # drain. The server replies `final` only in response.
                        self._flush_started = time.perf_counter()
                        await ws.send_json({"type": "flush"})
                        continue
                    # int16 PCM, already resampled to 16 kHz mono by push_frame.
                    await ws.send_bytes(data.data.tobytes())
                # Input exhausted (session ending). The server holds the ws open
                # after `final`, so unconditionally awaiting recv would hang
                # forever — close the ws so _recv_loop drains to its CLOSED break.
                await ws.close()
                await recv

    async def _recv_loop(self, ws) -> None:
        """Map server messages → INTERIM (delta) / FINAL (final) SpeechEvents."""
        async for msg in ws:
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue  # ignore PING/PONG/BINARY — only TEXT carries our JSON
            try:
                evt = json.loads(msg.data)
            except (json.JSONDecodeError, ValueError):
                continue
            kind = evt.get("type")
            if kind == "delta":
                # Cumulative growing interim; native PnC passed through as-is.
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                        alternatives=[
                            stt.SpeechData(language=self._language, text=evt["text"])
                        ],
                    )
                )
            elif kind == "final":
                # Autonomous finals carry server-measured dur_ms; flush finals
                # carry dur_ms=0 (agent's _flush_started span is used instead).
                self._emit_final(evt["text"], evt.get("dur_ms"))
            elif kind == "error":
                # Log only; do NOT synthesize a transcript event on error.
                logger.error("nemo-stt error: %s", evt.get("message", ""))

    def _emit_final(self, text: str, dur_ms: int | None = None) -> None:
        """Emit FINAL_TRANSCRIPT, then an explicit STTMetrics with finalize dur.

        LOAD-BEARING: the streaming path does NOT auto-emit a timed STTMetrics
        (the base monitor hardcodes duration=0.0 for streamed=True). metrics.py
        is READ-ONLY and ``_on_stt_metrics`` reads ``STTMetrics.duration``, so
        WITHOUT this explicit emit ``stt_ms`` stays NULL forever. ``duration``
        is the finalize latency — agent's flush span when present (explicit flush
        path), else server-stamped dur_ms/1000 (autonomous buffered/hybrid path).
        """
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(language=self._language, text=text)],
            )
        )
        # Prefer the agent's own flush span (includes network RTT) when available;
        # fall back to the server-measured EOU→finalize span for autonomous finals.
        # Consume _flush_started so later autonomous finals don't reuse a stale span.
        dur = (time.perf_counter() - self._flush_started if self._flush_started is not None
               else (dur_ms / 1000.0 if dur_ms is not None else 0.0))
        self._flush_started = None  # ponytail: reset so subsequent autonomous finals use server dur_ms
        self._stt.emit(
            "metrics_collected",
            STTMetrics(
                request_id="",
                timestamp=time.time(),
                duration=dur,
                label=self._stt.label,
                audio_duration=0.0,
                streamed=True,
            ),
        )
