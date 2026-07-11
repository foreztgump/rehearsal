"""Per-sentence avatar mood mapping (emotion.py). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import emotion  # noqa: E402


def test_praise_maps_to_happy():
    assert emotion.mood_for_text("That was excellent work.") == "happy"


def test_warmth_maps_to_love():
    assert emotion.mood_for_text("Of course, take your time.") == "love"


def test_concern_maps_to_sad():
    assert emotion.mood_for_text("Unfortunately that is a problem.") == "sad"


def test_neutral_default():
    assert emotion.mood_for_text("The meeting is at noon.") == "neutral"


def test_empty_string_is_neutral():
    assert emotion.mood_for_text("") == "neutral"


def test_praise_beats_concern_by_priority():
    assert emotion.mood_for_text("Great job, but there is a problem.") == "happy"


if __name__ == "__main__":
    test_praise_maps_to_happy()
    test_warmth_maps_to_love()
    test_concern_maps_to_sad()
    test_neutral_default()
    test_empty_string_is_neutral()
    test_praise_beats_concern_by_priority()
    print("ok: emotion mood mapping")
