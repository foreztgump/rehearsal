"""Append trailing silence to a WAV clip — the expressive-voice between-sentence breath.

Chatterbox returns one WAV per sentence and the agent plays those clips back-to-back
with zero gap, so multi-sentence replies sound breathless. Adding SILENCE (not a
time-stretch like `speed_factor`, which warps the waveform and sounds robotic) leaves the
model audio byte-for-byte untouched and just inserts a real pause after each clip.

Pure stdlib (`wave`) so it's unit-testable in the GPU-less sandbox, mirroring
emotion.py / emotion_voice.py.
"""
from __future__ import annotations

import io
import wave

MS_PER_SECOND = 1000


def pad_wav_tail(wav_bytes: bytes, pad_ms: int) -> bytes:
    """Return `wav_bytes` with `pad_ms` of silence appended at its own PCM format.

    A no-op (returns the input unchanged) when `pad_ms <= 0`, so a zero-pad mood costs
    nothing. The silence is written at the clip's OWN sample rate / width / channels, so
    the result is a valid WAV regardless of the source format.
    """
    if pad_ms <= 0:
        return wav_bytes

    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())

    pad_frames = round(sample_rate * pad_ms / MS_PER_SECOND)
    silence = b"\x00" * (pad_frames * channels * sample_width)

    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(frames + silence)
    return out.getvalue()
