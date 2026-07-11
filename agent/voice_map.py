"""Pure Kokoro-voice-id → Chatterbox-named-voice mapping for expressive mode.

Kept separate from expressive_tts.py — with NO livekit/httpx import — so the voice
choice is unit-testable in the GPU-less sandbox, mirroring agent/voice_map's sibling
pure modules (emotion.py, captioned_gate.py).

The persona picks a Kokoro voice id (persona.VOICE_IDS) whose prefix encodes gender:
af_/bf_ = female, am_/bm_ = male. Chatterbox-TTS-Server has its own 28 named voices
(gendered by name), so the expressive engine needs a gender-matched translation. The
explicit table below is the single source; unknown ids fall back by prefix gender, and
finally to the female default.
"""
from __future__ import annotations

# Chatterbox default voices per gender (used as fallbacks and the final default).
FEMALE_DEFAULT_VOICE = "Emily.wav"
MALE_DEFAULT_VOICE = "Michael.wav"
DEFAULT_VOICE = FEMALE_DEFAULT_VOICE

# Kokoro id prefixes → gender (persona encodes gender in the first two chars).
FEMALE_PREFIXES = ("af_", "bf_")
MALE_PREFIXES = ("am_", "bm_")

# Explicit persona-id → Chatterbox-voice table (single source). Every id in
# persona.VOICE_IDS is mapped to a gender-matched Chatterbox named voice.
_CHATTERBOX_VOICE_BY_KOKORO_ID: dict[str, str] = {
    # female (af_/bf_)
    "af_heart": "Emily.wav",
    "af_bella": "Olivia.wav",
    "af_nicole": "Alice.wav",
    "af_sarah": "Abigail.wav",
    "af_kore": "Cora.wav",
    "bf_emma": "Elena.wav",
    "bf_alice": "Jade.wav",
    # male (am_/bm_)
    "am_michael": "Michael.wav",
    "am_fenrir": "Adrian.wav",
    "am_puck": "Austin.wav",
    "am_adam": "Alexander.wav",
    "bm_george": "Gabriel.wav",
    "bm_daniel": "Thomas.wav",
}


def chatterbox_voice_for(kokoro_voice_id: str) -> str:
    """Translate a Kokoro voice id to a gender-matched Chatterbox named voice.

    Falls back by prefix gender for ids absent from the table, then to DEFAULT_VOICE.
    """
    mapped = _CHATTERBOX_VOICE_BY_KOKORO_ID.get(kokoro_voice_id)
    if mapped is not None:
        return mapped
    if kokoro_voice_id.startswith(FEMALE_PREFIXES):
        return FEMALE_DEFAULT_VOICE
    if kokoro_voice_id.startswith(MALE_PREFIXES):
        return MALE_DEFAULT_VOICE
    return DEFAULT_VOICE
