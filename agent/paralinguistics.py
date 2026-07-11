"""Pure paralinguistic-tag handling for expressive voice (Chatterbox-Turbo).

Turbo has no numeric emotion knob (it ignores `exaggeration`). Its character —
laughter, chuckles — comes from native inline tags the model was TRAINED on, in a
strict syntax (verified against ResembleAI's Turbo docs):

    lowercase, square brackets: [laugh]  [chuckle]  [cough]

Parentheses or angle brackets DO NOT work — the model tries to speak the literal
characters (an ugly noise), which is exactly the failure we hit with "<laugh>".

The LLM writes these tags directly in its reply (permitted + instructed by the
persona). This module is the seam to the two TTS engines:

  * Chatterbox (expressive): passes tags through untouched — the model vocalizes them.
  * Kokoro (default): `strip_tags` removes them so the fast engine never SPEAKS the
    word "laugh" (it cannot vocalize the tag).

It also detects a direct user request to laugh (`wants_laugh`) so the agent can force a
laugh on command (test/demo path), independent of the LLM.

Pure (no livekit/httpx) so it's unit-testable in the GPU-less sandbox.
"""
from __future__ import annotations

import re

# The tags Turbo vocalizes (its full supported set today). A coach leans on [chuckle]
# (professional-but-warm) and [laugh] (genuine humor); [cough] is available too.
LAUGH_TAG = "[laugh]"
CHUCKLE_TAG = "[chuckle]"

# Strict Turbo syntax: lowercase word in square brackets. Used to strip tags on the
# Kokoro path (which must not speak them) and to sanitize stray parenthesised cues.
_TAG_PATTERN = re.compile(r"\[(?:laugh|chuckle|cough)\]")

# A direct user ask to laugh, in the user's STT transcript (Part B, command path).
# Word-boundary matched so it fires on the COMMAND ("laugh", "lol", "haha…") but not
# on incidental mentions — "laughing"/"laughter"/"laughable" or "lol" inside
# "lollipop" must NOT force a [laugh] onto the reply.
_LAUGH_REQUEST_PATTERN = re.compile(r"\b(?:laugh|lol|(?:ha){2,})\b")


def strip_tags(text: str) -> str:
    """Remove Turbo paralinguistic tags so the Kokoro path never speaks them as words."""
    stripped = _TAG_PATTERN.sub("", text)
    # Drop the space a removed tag left in front of punctuation (" [laugh]." -> ".").
    stripped = re.sub(r"\s+([.,!?;:])", r"\1", stripped)
    return _collapse_spaces(stripped)


def wants_laugh(user_text: str) -> bool:
    """True when the user's transcript is a direct request to laugh (command path)."""
    return _LAUGH_REQUEST_PATTERN.search(user_text.lower()) is not None


def laugh_kind(text: str) -> str | None:
    """Which laugh tag the agent's reply carries, for the avatar's facial reaction.

    Returns "laugh" if the text contains [laugh], "chuckle" if it contains [chuckle]
    (full laugh wins when both appear), else None. The web maps this to a transient
    laugh/smile expression; the audio laugh comes from Chatterbox vocalizing the tag.
    """
    if LAUGH_TAG in text:
        return "laugh"
    if CHUCKLE_TAG in text:
        return "chuckle"
    return None


def _collapse_spaces(text: str) -> str:
    """Tidy the double spaces / stray edge space left after tag removal."""
    return re.sub(r"\s{2,}", " ", text).strip()
