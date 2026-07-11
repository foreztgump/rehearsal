"""Chatterbox-Turbo expressive-voice TTS plugin — opt-in emotional-intensity engine.

WHY THIS EXISTS (opt-in expressive mode):
The default voice is Kokoro (agent/captioned_tts.py), which is fast (~256ms/sentence)
and returns word-level timestamps for true avatar lip-sync. Expressive mode swaps in
Chatterbox-Turbo. Turbo IGNORES the `exaggeration` knob (verified in the model source),
so the SAME per-sentence lexicon mood (emotion.mood_for_text) that drives the avatar face
instead scales Turbo's `temperature` — its only honored expressiveness lever — while a
paralinguistic tag (e.g. <laugh>) is injected into the text for personality on cue. The
tradeoff is latency (~0.8–1.2s/sentence, one forward pass, no streaming), so expressive
mode deliberately exceeds the P50<1.0s budget and is OFF by default.

CONTRACT DIFFERENCES vs CaptionedTTS (Kokoro):
  * Endpoint POST /tts (NOT the OpenAI /v1/audio/speech route, which silently drops
    `temperature`) returns RAW WAV bytes (24 kHz mono 16-bit PCM) — NOT base64 json,
    NO word timestamps. So there is no lip-sync schedule to piggyback.
  * The per-sentence mood is therefore published on its OWN data-channel topic
    (MOOD_TOPIC = lk.avatar.mood), gated by the same avatar-enabled flag as CaptionedTTS
    so voice-only stays isolated (no lk.avatar.* traffic when the avatar is OFF).
  * The Kokoro voice id from the persona is translated to a gender-matched Chatterbox
    named voice via voice_map at synth time.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, replace

import httpx

import emotion
import emotion_voice
import paralinguistics
import voice_map
import wav_pad
from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

logger = logging.getLogger("rehearsal.expressive_tts")

# Chatterbox-TTS-Server synthesis params. 24 kHz mono WAV matches the room's existing
# playout path (identical to Kokoro), so nothing downstream of the emitter changes.
SAMPLE_RATE = 24000
NUM_CHANNELS = 1

# The Chatterbox /tts endpoint contract (verified against the server source). We use
# /tts NOT /v1/audio/speech because the OpenAI-compatible route silently DROPS
# `temperature` (it only reads model/input/voice/format/speed/seed) — and on Turbo,
# `temperature` is the ONLY honored expressiveness lever (`exaggeration` is ignored).
OUTPUT_FORMAT = "wav"
VOICE_MODE = "predefined"

# Data-channel topic the browser avatar subscribes to for per-sentence mood. Chatterbox
# has NO lipsync schedule to piggyback the mood onto (unlike Kokoro), so it rides its own
# reliable topic. Gated by _avatar_enabled — no lk.avatar.* traffic when the avatar is OFF.
MOOD_TOPIC = "lk.avatar.mood"


@dataclass
class _Opts:
    base_url: str  # Chatterbox root, e.g. http://chatterbox:8004  (NO /v1 suffix)
    voice: str  # a Kokoro voice id (persona.VOICE_IDS); mapped at synth time


class ExpressiveTTS(tts.TTS):
    """livekit-agents TTS backed by Chatterbox-Turbo /v1/audio/speech.

    Mirrors CaptionedTTS's chunked contract (initialize → push → flush) so the agent's
    playout/transcription/turn pipeline is untouched. Instead of a word schedule it
    publishes the per-sentence mood over MOOD_TOPIC, gated by the avatar flag.
    """

    def __init__(self, *, base_url: str, voice: str) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._opts = _Opts(base_url=base_url.rstrip("/"), voice=voice)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        # Set once after room connect (see attach_room). Until then mood frames are
        # dropped — the agent never speaks before the room is up, so this is safe.
        self._room: rtc.Room | None = None
        self._seq = 0
        # Avatar-ON gate (AVTR-12), OFF by default so voice-only is isolated: no
        # lk.avatar.mood publish. Flipped by the avatar.update RPC (agent/main.py).
        self._avatar_enabled = False

    def attach_room(self, room: rtc.Room) -> None:
        """Wire the LiveKit room so per-sentence mood frames can be published.

        Called once from the entrypoint after ctx.connect(), same as CaptionedTTS.
        """
        self._room = room

    def update_options(self, *, voice: str | None = None) -> None:
        """In-place voice swap (matches CaptionedTTS.update_options on persona edit).

        `voice` is a Kokoro voice id; it is translated to a Chatterbox named voice at
        synth time, so the persona panel keeps sending Kokoro ids for either engine.
        """
        if voice is not None:
            self._opts.voice = voice

    def set_avatar_enabled(self, on: bool) -> None:
        """Enable/disable per-sentence mood publishing for the avatar (AVTR-12)."""
        self._avatar_enabled = bool(on)

    async def _publish_mood(self, mood: str, laugh: str | None = None) -> None:
        """Send one sentence's mood (and optional laugh cue) to the browser avatar.

        `laugh` ("laugh"/"chuckle"/None) rides the SAME reliable mood packet so the face
        can play a transient laugh expression in sync with the audio the model vocalizes
        from the [laugh]/[chuckle] tag. Absent when the sentence has no laugh tag.
        """
        room = self._room
        if room is None:
            return
        self._seq += 1
        payload: dict = {"seq": self._seq, "mood": mood}
        if laugh is not None:
            payload["laugh"] = laugh
        try:
            await room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True,
                topic=MOOD_TOPIC,
            )
        except Exception as e:  # never let a mood hiccup break speech
            logger.warning("failed to publish avatar mood: %s", e)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _ExpressiveStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aclose()


class _ExpressiveStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: ExpressiveTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: ExpressiveTTS = tts
        self._opts = replace(tts._opts)
        # Snapshot the gate per utterance so a mid-utterance toggle can't split one
        # clip's behaviour (mirrors _CaptionedStream).
        self._avatar_enabled = tts._avatar_enabled

    def _request_body(self, mood: str) -> dict:
        """Chatterbox-Turbo /tts body.

        Turbo ignores `exaggeration`, so expressiveness rides two honored levers: the
        `temperature` (mood-scaled, lifted baseline) and any paralinguistic tag injected
        into the text (e.g. [laugh] on an amused line) for real personality on cue.

        NOTE: `speed_factor` is deliberately NOT sent. The server implements it as a
        post-hoc librosa phase-vocoder time-stretch on the already-generated waveform
        (verified in the server source, utils.apply_speed_factor), which adds a metallic/
        robotic artifact. Pace is shaped instead by the persona's sentence rhythm.
        """
        return {
            # Turbo tags ([laugh]/[chuckle]) are the model's NATIVE syntax — pass the
            # LLM's text through untouched so the model vocalizes them.
            "text": self.input_text,
            "voice_mode": VOICE_MODE,
            "predefined_voice_id": voice_map.chatterbox_voice_for(self._opts.voice),
            "output_format": OUTPUT_FORMAT,
            "temperature": emotion_voice.temperature_for_mood(mood),
        }

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        url = f"{self._opts.base_url}/tts"
        mood = emotion.mood_for_text(self.input_text)
        try:
            resp = await self._tts._client.post(url, json=self._request_body(mood))
            resp.raise_for_status()
            audio_bytes = resp.read()
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

        if not audio_bytes:
            raise APIConnectionError()

        # Append a mood-scaled tail of SILENCE so consecutive sentence clips get a natural
        # breath instead of butting together. Silence never warps the model audio (unlike
        # the server's librosa speed_factor), so it costs quality nothing.
        audio_bytes = wav_pad.pad_wav_tail(audio_bytes, emotion_voice.pad_ms_for_mood(mood))

        request_id = uuid.uuid4().hex
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/wav",
        )
        output_emitter.push(audio_bytes)
        output_emitter.flush()

        # Voice-only isolation (AVTR-12): publish the per-sentence mood ONLY when the
        # avatar is on. Published AFTER pushing audio so the data-channel round-trip
        # never delays first audio. A [laugh]/[chuckle] tag in this sentence rides the
        # same packet so the face can react in sync with the vocalized laugh.
        if self._avatar_enabled:
            await self._tts._publish_mood(mood, paralinguistics.laugh_kind(self.input_text))
