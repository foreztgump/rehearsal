"""Avatar-ON gate truth table for captioned TTS (AVTR-12). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import captioned_gate  # noqa: E402


def test_avatar_on_requests_timestamps():
    body = captioned_gate.captioned_request_body("hi", "af_bella", 1.0, avatar_enabled=True)
    assert body["return_timestamps"] is True
    assert body["input"] == "hi" and body["voice"] == "af_bella"


def test_avatar_off_suppresses_timestamps():
    body = captioned_gate.captioned_request_body("hi", "af_bella", 1.0, avatar_enabled=False)
    assert body["return_timestamps"] is False


def test_words_drop_empty_and_map_fields():
    raw = [
        {"word": "hello", "start_time": 0.0, "end_time": 0.4},
        {"word": "", "start_time": 0.4, "end_time": 0.5},
    ]
    words = captioned_gate.lipsync_words(raw)
    assert words == [{"w": "hello", "s": 0.0, "e": 0.4}]


if __name__ == "__main__":
    test_avatar_on_requests_timestamps()
    test_avatar_off_suppresses_timestamps()
    test_words_drop_empty_and_map_fields()
    print("ok: captioned gate truth table")
