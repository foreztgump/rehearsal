"""Trailing-silence WAV pad (wav_pad.py). Pure stdlib, no LiveKit."""
import io
import os
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import wav_pad  # noqa: E402

SAMPLE_RATE = 24000
NUM_CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM


def _make_wav(frames: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(NUM_CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x01\x02" * frames)  # non-zero body so we can find the silent tail
    return out.getvalue()


def _frames(wav_bytes: bytes) -> int:
    with wave.open(io.BytesIO(wav_bytes), "rb") as r:
        return r.getnframes()


def test_pad_adds_expected_frame_count():
    # Arrange
    src = _make_wav(SAMPLE_RATE)  # exactly 1 second
    # Act
    padded = wav_pad.pad_wav_tail(src, 200)
    # Assert — 200ms at 24kHz == 4800 extra frames
    assert _frames(padded) == SAMPLE_RATE + 4800


def test_padded_output_is_a_valid_wav():
    # Arrange
    src = _make_wav(1000)
    # Act
    padded = wav_pad.pad_wav_tail(src, 150)
    # Assert — re-reads without error and preserves format
    with wave.open(io.BytesIO(padded), "rb") as r:
        assert r.getframerate() == SAMPLE_RATE
        assert r.getnchannels() == NUM_CHANNELS
        assert r.getsampwidth() == SAMPLE_WIDTH


def test_tail_is_silence():
    # Arrange
    src = _make_wav(500)
    pad_ms = 100
    pad_frames = round(SAMPLE_RATE * pad_ms / 1000)
    # Act
    padded = wav_pad.pad_wav_tail(src, pad_ms)
    # Assert — the appended tail is all zero bytes
    with wave.open(io.BytesIO(padded), "rb") as r:
        r.readframes(500)  # skip the original body
        tail = r.readframes(pad_frames)
    assert tail == b"\x00" * (pad_frames * NUM_CHANNELS * SAMPLE_WIDTH)


def test_zero_pad_is_a_noop():
    # Arrange
    src = _make_wav(300)
    # Act / Assert — unchanged bytes, no re-encode
    assert wav_pad.pad_wav_tail(src, 0) is src
    assert wav_pad.pad_wav_tail(src, -50) is src


if __name__ == "__main__":
    test_pad_adds_expected_frame_count()
    test_padded_output_is_a_valid_wav()
    test_tail_is_silence()
    test_zero_pad_is_a_noop()
    print("ok: wav_pad trailing silence")
