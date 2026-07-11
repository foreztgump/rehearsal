"""Mood→Chatterbox-Turbo temperature mapping (emotion_voice.py). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import emotion_voice  # noqa: E402


def test_happy_is_most_animated():
    assert emotion_voice.temperature_for_mood("happy") == emotion_voice.HAPPY_TEMPERATURE


def test_love_temperature():
    assert emotion_voice.temperature_for_mood("love") == emotion_voice.LOVE_TEMPERATURE


def test_neutral_is_lifted_default():
    assert emotion_voice.temperature_for_mood("neutral") == emotion_voice.DEFAULT_TEMPERATURE


def test_sad_is_most_subdued():
    assert emotion_voice.temperature_for_mood("sad") == emotion_voice.SAD_TEMPERATURE


def test_neutral_baseline_beats_kokoro_default():
    # Expressive mode must be livelier than the model's 0.8 default on EVERY sentence.
    assert emotion_voice.DEFAULT_TEMPERATURE > 0.8


def test_unknown_mood_falls_back_to_default():
    assert emotion_voice.temperature_for_mood("furious") == emotion_voice.DEFAULT_TEMPERATURE


def test_sad_has_longest_pause():
    assert emotion_voice.pad_ms_for_mood("sad") == emotion_voice.SAD_PAD_MS


def test_happy_has_shortest_pause():
    assert emotion_voice.pad_ms_for_mood("happy") == emotion_voice.HAPPY_PAD_MS


def test_neutral_pause_is_default():
    assert emotion_voice.pad_ms_for_mood("neutral") == emotion_voice.DEFAULT_PAD_MS


def test_pause_scales_with_mood_energy():
    # Sympathy breathes longest, praise shortest, neutral in between.
    assert (
        emotion_voice.pad_ms_for_mood("happy")
        <= emotion_voice.pad_ms_for_mood("neutral")
        < emotion_voice.pad_ms_for_mood("sad")
    )


def test_unknown_mood_pause_falls_back_to_default():
    assert emotion_voice.pad_ms_for_mood("furious") == emotion_voice.DEFAULT_PAD_MS


if __name__ == "__main__":
    test_happy_is_most_animated()
    test_love_temperature()
    test_neutral_is_lifted_default()
    test_sad_is_most_subdued()
    test_neutral_baseline_beats_kokoro_default()
    test_unknown_mood_falls_back_to_default()
    test_sad_has_longest_pause()
    test_happy_has_shortest_pause()
    test_neutral_pause_is_default()
    test_pause_scales_with_mood_energy()
    test_unknown_mood_pause_falls_back_to_default()
    print("ok: emotion_voice temperature + pad mapping")
