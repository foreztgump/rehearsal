"""Pure mood→Chatterbox-Turbo temperature mapping for the expressive-voice engine.

Turbo IGNORES `exaggeration`/`cfg`/`min_p` (verified in the model source —
chatterbox/tts_turbo.py logs a warning and drops them). Its only honored expressiveness
lever is `temperature`: higher = livelier, more varied prosody. So the SAME per-sentence
lexicon mood that drives the avatar face (emotion.mood_for_text) maps to a temperature
here — animated for praise, subdued for sympathy — with a lifted NEUTRAL baseline so
expressive mode is reliably warmer than Kokoro on EVERY sentence, not just keyword hits.

Pure by design (no livekit/httpx) so it's unit-testable in the GPU-less sandbox, mirroring
emotion.py (the lexicon it consumes) and captioned_gate.py.
"""
from __future__ import annotations

# Chatterbox-Turbo `temperature` per lexicon mood (model default is 0.8). NEUTRAL is
# lifted to 0.9 so expressive mode is livelier than Kokoro even when nothing matches;
# praise is the most animated, sympathy the most subdued. Named — never inlined.
DEFAULT_TEMPERATURE = 0.9  # emotion.DEFAULT_MOOD ("neutral")
HAPPY_TEMPERATURE = 1.1
LOVE_TEMPERATURE = 1.0
SAD_TEMPERATURE = 0.7

_TEMPERATURE_BY_MOOD: dict[str, float] = {
    "happy": HAPPY_TEMPERATURE,
    "love": LOVE_TEMPERATURE,
    "neutral": DEFAULT_TEMPERATURE,
    "sad": SAD_TEMPERATURE,
}


def temperature_for_mood(mood: str) -> float:
    """Map a lexicon mood label to a Chatterbox-Turbo temperature; unknown → default."""
    return _TEMPERATURE_BY_MOOD.get(mood, DEFAULT_TEMPERATURE)
