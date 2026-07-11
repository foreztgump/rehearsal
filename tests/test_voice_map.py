"""Kokoro-id → Chatterbox-voice mapping (voice_map.py). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import voice_map  # noqa: E402

# Chatterbox voices grouped by gender — the mapping must keep gender.
FEMALE_VOICES = {"Emily.wav", "Olivia.wav", "Alice.wav", "Abigail.wav", "Cora.wav",
                 "Elena.wav", "Jade.wav"}
MALE_VOICES = {"Michael.wav", "Adrian.wav", "Austin.wav", "Alexander.wav",
               "Gabriel.wav", "Thomas.wav"}


def test_female_id_maps_to_female_voice():
    assert voice_map.chatterbox_voice_for("af_bella") in FEMALE_VOICES


def test_male_id_maps_to_male_voice():
    assert voice_map.chatterbox_voice_for("am_michael") in MALE_VOICES


def test_b_prefix_female_maps_to_female_voice():
    assert voice_map.chatterbox_voice_for("bf_emma") in FEMALE_VOICES


def test_unknown_female_prefix_falls_back_to_female_default():
    assert voice_map.chatterbox_voice_for("af_unknown") == voice_map.FEMALE_DEFAULT_VOICE


def test_unknown_male_prefix_falls_back_to_male_default():
    assert voice_map.chatterbox_voice_for("bm_unknown") == voice_map.MALE_DEFAULT_VOICE


def test_unrecognized_id_falls_back_to_default():
    assert voice_map.chatterbox_voice_for("xx_nobody") == voice_map.DEFAULT_VOICE


if __name__ == "__main__":
    test_female_id_maps_to_female_voice()
    test_male_id_maps_to_male_voice()
    test_b_prefix_female_maps_to_female_voice()
    test_unknown_female_prefix_falls_back_to_female_default()
    test_unknown_male_prefix_falls_back_to_male_default()
    test_unrecognized_id_falls_back_to_default()
    print("ok: voice_map gender-matched mapping")
