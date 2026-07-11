"""Pure mood→Chatterbox-Turbo prosody mapping for the expressive-voice engine.

Turbo IGNORES `exaggeration`/`cfg`/`min_p` (verified in the model source —
chatterbox/tts_turbo.py logs a warning and drops them). Its only honored expressiveness
lever is `temperature`: higher = livelier, more varied prosody. So the SAME per-sentence
lexicon mood that drives the avatar face (emotion.mood_for_text) maps to a temperature
here — animated for praise, subdued for sympathy — with a lifted NEUTRAL baseline so
expressive mode is reliably warmer than Kokoro on EVERY sentence, not just keyword hits.
The same mood also sets a between-sentence silence pad (pad_ms_for_mood, applied via
agent/wav_pad.py) so multi-sentence replies breathe instead of running together.

(`speed_factor` is NOT mapped: the server applies it as a post-hoc librosa time-stretch
that sounds robotic — see agent/expressive_tts.py. Between-sentence pace comes from the
silence pad and the persona's sentence rhythm, never from warping the waveform.)

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


# Trailing-silence pad (milliseconds) appended after each sentence's clip so multi-sentence
# replies get a natural breath instead of running together (see agent/wav_pad.py). Scaled by
# the SAME lexicon mood: sympathy gets the longest pause (room to breathe), praise the
# shortest (livelier, less dead air), neutral in between. Named — never inlined.
DEFAULT_PAD_MS = 180  # emotion.DEFAULT_MOOD ("neutral")
HAPPY_PAD_MS = 120
LOVE_PAD_MS = 180
SAD_PAD_MS = 280

_PAD_MS_BY_MOOD: dict[str, int] = {
    "happy": HAPPY_PAD_MS,
    "love": LOVE_PAD_MS,
    "neutral": DEFAULT_PAD_MS,
    "sad": SAD_PAD_MS,
}


def pad_ms_for_mood(mood: str) -> int:
    """Map a lexicon mood label to a between-sentence silence pad (ms); unknown → default."""
    return _PAD_MS_BY_MOOD.get(mood, DEFAULT_PAD_MS)
