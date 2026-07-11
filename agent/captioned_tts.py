"""Kokoro captioned-TTS plugin — audio + word-level timestamps for avatar lip-sync.

WHY THIS EXISTS (Phase 12 lip-sync, ISOLATION GATE deliberately relaxed):
The 3D avatar's lip-sync was originally constrained to "Path-A" — energy/audio only,
no transcription, no timestamps, zero server change. That ceiling is real: with only
loudness + formant estimation the mouth moves on the right syllables and makes rough
vowel shapes, but it never reads as true lip-sync because the browser cannot know WHICH
phoneme is spoken at WHICH millisecond. The user explicitly chose to relax the gate and
source real word timing from the TTS.

Kokoro-FastAPI exposes /dev/captioned_speech, which returns the synthesized WAV PLUS
word-level timestamps ([{word,start_time,end_time}]) from its internal phonemizer — one
inference, no extra audio round-trip. This plugin is a drop-in livekit-agents TTS that:
  1. calls /dev/captioned_speech instead of /v1/audio/speech,
  2. feeds the decoded audio to LiveKit's AudioEmitter EXACTLY as the stock OpenAI TTS
     does (playout path unchanged — same 24 kHz mono WAV the room already plays), and
  3. publishes the per-utterance word schedule over a LiveKit data-channel topic so the
     browser avatar can convert words -> visemes and align them to the played audio.

The browser locks each schedule to the ACTUAL audio onset it measures on the inbound
track (see web/app/AvatarStage.tsx), so network/buffer jitter never desyncs the mouth —
the timestamps only carry the *relative* timing within an utterance.

ISOLATION (Phase 14, AVTR-12): the Phase-12 "avatar never touches the server pipeline"
gate is intentionally RETIRED for avatar-ON only. When the avatar is OFF this plugin
requests no timestamps and publishes nothing (voice-only is byte-for-byte the same
Kokoro audio with zero lk.avatar.* traffic — the new auditable invariant). When ON it
publishes word schedules over lk.avatar.lipsync; that server-side addition is the
documented, deliberate relaxation.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass, replace

import httpx

import captioned_gate
import emotion
from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

logger = logging.getLogger("rehearsal.captioned_tts")

# Kokoro-FastAPI synthesis params. 24 kHz mono WAV matches the stock OpenAI-plugin path
# the room already consumes, so nothing downstream of the emitter changes.
SAMPLE_RATE = 24000
NUM_CHANNELS = 1

# Data-channel topic the browser avatar subscribes to for word schedules. Reliable
# delivery (not lossy) — a dropped schedule would silently kill lip-sync for a sentence.
LIPSYNC_TOPIC = "lk.avatar.lipsync"


@dataclass
class _Opts:
    base_url: str  # Kokoro root, e.g. http://kokoro:8880  (NOT the /v1 suffix)
    voice: str
    speed: float = 1.0
    response_format: str = "wav"


class CaptionedTTS(tts.TTS):
    """livekit-agents TTS backed by Kokoro /dev/captioned_speech.

    Mirrors the stock OpenAI AudioChunkedStream contract (initialize -> push -> flush)
    so the agent's playout/transcription/turn pipeline is untouched, and additionally
    publishes a word schedule per utterance over LIPSYNC_TOPIC.
    """

    def __init__(
        self,
        *,
        base_url: str,
        voice: str,
        speed: float = 1.0,
    ) -> None:
        super().__init__(
            # Non-streaming (chunked) like the tts-1 path; word timing comes back with
            # the full clip, so we synthesize per input segment and emit in one shot.
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        # base_url arrives as the OpenAI-style ".../v1" root; strip it — the captioned
        # endpoint lives at the server root under /dev, not under /v1.
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        self._opts = _Opts(base_url=root, voice=voice, speed=speed)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        # Set once after room connect (see attach_room). Until then schedules are
        # dropped — the agent never speaks before the room is up, so this is safe.
        self._room: rtc.Room | None = None
        self._seq = 0
        # Avatar-ON gate (AVTR-12). Default OFF so voice-only is isolated out of the
        # box: no word-timestamp request, no lk.avatar.lipsync publish. Flipped by the
        # avatar.update RPC (agent/main.py) — same runtime-mutation pattern as voice.
        self._avatar_enabled = False

    def attach_room(self, room: rtc.Room) -> None:
        """Wire the LiveKit room so utterance word schedules can be published.

        Called once from the entrypoint after ctx.connect(). Mirrors how the stock
        plugins gain room access; kept off __init__ so build_session stays room-free.
        """
        self._room = room

    def update_options(self, *, voice: str | None = None) -> None:
        """In-place voice swap (matches openai.TTS.update_options used on persona edit).

        main.py calls session.tts.update_options(voice=...) without recreating the TTS,
        so the metrics subscription bound at session start survives. We only support the
        voice knob — the single option the agent actually mutates at runtime.
        """
        if voice is not None:
            self._opts.voice = voice

    def set_avatar_enabled(self, on: bool) -> None:
        """Enable/disable captioned word-timestamp publishing for avatar lip-sync."""
        self._avatar_enabled = bool(on)

    async def _publish_schedule(
        self, request_id: str, words: list[dict], mood: str
    ) -> None:
        """Send one utterance's word schedule to the browser avatar over the data channel."""
        room = self._room
        if room is None or not words:
            return
        self._seq += 1
        payload = {
            "seq": self._seq,
            "request_id": request_id,
            # [{w, s, e}] — sentence-relative seconds; the browser re-anchors to the
            # measured audio onset, so absolute clock skew is irrelevant.
            "words": words,
            # Coarse per-sentence facial mood for the avatar; piggybacks this same
            # schedule (no extra topic), so it too is gated by _avatar_enabled.
            "mood": mood,
        }
        try:
            await room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True,
                topic=LIPSYNC_TOPIC,
            )
        except Exception as e:  # never let a lip-sync hiccup break speech
            logger.warning("failed to publish lipsync schedule: %s", e)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _CaptionedStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aclose()


class _CaptionedStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: CaptionedTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: CaptionedTTS = tts
        self._opts = replace(tts._opts)
        # Snapshot the gate per utterance so a mid-utterance toggle can't split one
        # clip's behaviour (timestamps requested but publish skipped, or vice versa).
        self._avatar_enabled = tts._avatar_enabled

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        url = f"{self._opts.base_url}/dev/captioned_speech"
        # Avatar OFF ⇒ return_timestamps False: the audio inference is identical, only
        # the timestamp request + publish are suppressed (the voice-only invariant).
        body = captioned_gate.captioned_request_body(
            self.input_text,
            self._opts.voice,
            self._opts.speed,
            avatar_enabled=self._avatar_enabled,
        )
        try:
            resp = await self._tts._client.post(
                url,
                json=body,
                headers={"x-raw-response": "stream"},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            raise APITimeoutError() from None
        except httpx.HTTPStatusError as e:
            raise APIStatusError(
                str(e),
                status_code=e.response.status_code,
                request_id=None,
                body=e.response.text,
            ) from None
        except Exception as e:
            raise APIConnectionError() from e

        audio_b64 = data.get("audio", "")
        if not audio_b64:
            raise APIConnectionError()
        audio_bytes = base64.b64decode(audio_b64)

        request_id = uuid.uuid4().hex
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/wav",
        )
        output_emitter.push(audio_bytes)
        output_emitter.flush()

        # Voice-only isolation (AVTR-12): publish the word schedule ONLY when the avatar
        # is on. OFF ⇒ no return_timestamps was requested, so we never build a word list
        # and never touch the lk.avatar.lipsync channel. Published AFTER pushing audio so
        # the data-channel round-trip never delays first audio; the browser re-anchors
        # each schedule to the measured audio onset, so ordering slack is harmless.
        if self._avatar_enabled:
            words = captioned_gate.lipsync_words(data.get("timestamps", []))
            if words:
                mood = emotion.mood_for_text(self.input_text)
                await self._tts._publish_schedule(request_id, words, mood)
