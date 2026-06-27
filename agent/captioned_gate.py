"""Pure gate logic for captioned TTS (AVTR-12) — no httpx/livekit import.

Kept separate from captioned_tts.py so the gate decision (request timestamps? build a
publishable word list?) is unit-testable in the GPU-less sandbox, mirroring how
agent/endpointing.py isolates the mode→endpointing decision.
"""
from __future__ import annotations

KOKORO_MODEL = "kokoro"
RESPONSE_FORMAT = "wav"


def captioned_request_body(
    text: str, voice: str, speed: float, *, avatar_enabled: bool
) -> dict:
    """Kokoro /dev/captioned_speech body. Avatar OFF ⇒ no timestamps requested (the
    audio inference is identical either way; only this flag + the publish differ)."""
    return {
        "model": KOKORO_MODEL,
        "input": text,
        "voice": voice,
        "response_format": RESPONSE_FORMAT,
        "speed": speed,
        "stream": False,
        "return_timestamps": avatar_enabled,
    }


def lipsync_words(timestamps: list[dict]) -> list[dict]:
    """Sentence-relative [{w,s,e}] for the data channel; drop empty words."""
    return [
        {"w": t.get("word", ""), "s": t.get("start_time", 0.0), "e": t.get("end_time", 0.0)}
        for t in timestamps
        if t.get("word")
    ]
