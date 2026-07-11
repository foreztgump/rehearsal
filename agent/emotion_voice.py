"""Pure mood→Chatterbox-exaggeration mapping for the expressive-voice engine.

Kept separate from expressive_tts.py — with NO livekit/httpx import — so the
intensity decision is unit-testable in the GPU-less sandbox, mirroring
agent/emotion.py (the sentence→mood lexicon this consumes) and agent/captioned_gate.py.

The SAME per-sentence lexicon mood that drives the avatar face (emotion.mood_for_text)
also sets Chatterbox-Turbo's `exaggeration` knob (emotional intensity, 0..1). Coarse
by design: a miss just yields the neutral default, which is inaudible.
"""
from __future__ import annotations

# Chatterbox `exaggeration` per lexicon mood (0..1). NEUTRAL is the engine default;
# praise is the most animated, concern the most subdued. Named — never inlined.
DEFAULT_EXAGGERATION = 0.5  # emotion.DEFAULT_MOOD ("neutral")
HAPPY_EXAGGERATION = 0.8
LOVE_EXAGGERATION = 0.7
SAD_EXAGGERATION = 0.4

_EXAGGERATION_BY_MOOD: dict[str, float] = {
    "happy": HAPPY_EXAGGERATION,
    "love": LOVE_EXAGGERATION,
    "neutral": DEFAULT_EXAGGERATION,
    "sad": SAD_EXAGGERATION,
}


def exaggeration_for_mood(mood: str) -> float:
    """Map a lexicon mood label to a Chatterbox exaggeration; unknown → default."""
    return _EXAGGERATION_BY_MOOD.get(mood, DEFAULT_EXAGGERATION)
