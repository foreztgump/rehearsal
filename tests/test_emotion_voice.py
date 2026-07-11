"""Mood→Chatterbox-exaggeration mapping (emotion_voice.py). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import emotion_voice  # noqa: E402


def test_happy_is_most_exaggerated():
    assert emotion_voice.exaggeration_for_mood("happy") == emotion_voice.HAPPY_EXAGGERATION


def test_love_exaggeration():
    assert emotion_voice.exaggeration_for_mood("love") == emotion_voice.LOVE_EXAGGERATION


def test_neutral_is_default():
    assert emotion_voice.exaggeration_for_mood("neutral") == emotion_voice.DEFAULT_EXAGGERATION


def test_sad_is_most_subdued():
    assert emotion_voice.exaggeration_for_mood("sad") == emotion_voice.SAD_EXAGGERATION


def test_unknown_mood_falls_back_to_default():
    assert emotion_voice.exaggeration_for_mood("furious") == emotion_voice.DEFAULT_EXAGGERATION


if __name__ == "__main__":
    test_happy_is_most_exaggerated()
    test_love_exaggeration()
    test_neutral_is_default()
    test_sad_is_most_subdued()
    test_unknown_mood_falls_back_to_default()
    print("ok: emotion_voice exaggeration mapping")
