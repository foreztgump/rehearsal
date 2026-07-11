"""Session-lifetime TTS that switches between Kokoro and Chatterbox engines LIVE.

WHY A DELEGATING WRAPPER (not a hot instance swap):
`AgentSession.tts` is a read-only property bound at session start — the metrics
subscription (agent/metrics.py attach()) and the AgentActivity error/metrics handlers
both bind to THAT instance when the session starts. Reassigning the session's TTS
mid-run would orphan those subscriptions. So instead the session owns ONE stable TTS —
this wrapper — for its whole life, and the wrapper delegates synthesis to whichever
engine (Kokoro CaptionedTTS or Chatterbox ExpressiveTTS) is active. The `tts.update`
RPC just flips the active engine; the next turn synthesizes through the new one with no
teardown.

Both engines are cheap in the AGENT process (each holds only an httpx client — the model
VRAM lives in the kokoro/chatterbox compose services, resident regardless), so holding
both costs the agent nothing. Metrics from the active inner engine are re-emitted on this
wrapper (the exact pattern livekit's own StreamAdapter uses) so the session-level metrics
subscription keeps working across a swap.
"""

from __future__ import annotations

import logging
from typing import Any

from livekit import rtc
from livekit.agents import (
    APIConnectOptions,
    tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from captioned_tts import CaptionedTTS
from expressive_tts import ExpressiveTTS

logger = logging.getLogger("rehearsal.expressive_mode_tts")


class ExpressiveModeTTS(tts.TTS):
    """Routes synthesis to the active engine; flips live via set_expressive().

    Kokoro (default) is the fast, lip-sync engine; Chatterbox is the opt-in expressive
    engine. Both are non-streaming 24 kHz mono, so capabilities/rates match and livekit's
    StreamAdapter sentence-tokenizes the wrapper exactly as it did the bare engine.
    """

    def __init__(self, *, kokoro: CaptionedTTS, chatterbox: ExpressiveTTS) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=kokoro.sample_rate,
            num_channels=kokoro.num_channels,
        )
        self._kokoro = kokoro
        self._chatterbox = chatterbox
        self._active: tts.TTS = kokoro
        # Re-emit each engine's metrics/errors on THIS wrapper so the session-level
        # subscription (bound to session.tts at start) survives a live engine swap.
        for engine in (kokoro, chatterbox):
            engine.on("metrics_collected", self._forward_metrics)
            engine.on("error", self._forward_error)

    def _forward_metrics(self, *args: Any, **kwargs: Any) -> None:
        self.emit("metrics_collected", *args, **kwargs)

    def _forward_error(self, *args: Any, **kwargs: Any) -> None:
        self.emit("error", *args, **kwargs)

    def set_expressive(self, on: bool) -> None:
        """Flip the active engine: Chatterbox when on, Kokoro when off."""
        self._active = self._chatterbox if on else self._kokoro
        logger.info("expressive engine -> %s", type(self._active).__name__)

    def attach_room(self, room: rtc.Room) -> None:
        """Give BOTH engines the room so either can publish avatar data live."""
        self._kokoro.attach_room(room)
        self._chatterbox.attach_room(room)

    def set_avatar_enabled(self, on: bool) -> None:
        """Gate avatar publishing on BOTH engines so it works regardless of engine."""
        self._kokoro.set_avatar_enabled(on)
        self._chatterbox.set_avatar_enabled(on)

    def update_options(self, *, voice: str | None = None) -> None:
        """Apply a persona voice edit to BOTH engines (each maps it as it needs)."""
        self._kokoro.update_options(voice=voice)
        self._chatterbox.update_options(voice=voice)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return self._active.synthesize(text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._kokoro.aclose()
        await self._chatterbox.aclose()
