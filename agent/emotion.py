"""Pure sentence→mood mapping for the avatar (piggybacks the lip-sync schedule).

Kept separate from captioned_tts.py — with NO livekit/httpx import — so the mood
decision is unit-testable in the GPU-less sandbox, mirroring agent/captioned_gate.py.

Coarse by design: a low-stakes keyword lexicon that defaults to "neutral". It only
nudges a TalkingHead facial mood per sentence; a miss is invisible, so we favour a
tiny, obvious lexicon over any model or clever NLP.
"""
from __future__ import annotations

DEFAULT_MOOD = "neutral"

# Priority order matters: the first list whose keyword appears wins (praise > warmth >
# concern > neutral), so praise beats concern when both show up in one sentence.
_MOOD_LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "happy",
        (
            "great", "excellent", "perfect", "well done", "nice", "awesome",
            "impressive", "fantastic", "good job", "exactly", "brilliant",
        ),
    ),
    (
        "love",
        (
            "welcome", "happy to", "glad", "of course", "no worries",
            "take your time", "you've got this", "i'm here", "don't worry",
        ),
    ),
    (
        "sad",
        # Sympathy/apology ONLY — never topic words. A coach constantly says
        # "problem", "mistake", "issue", "risk", "difficult" about the SUBJECT under
        # discussion, not their own feeling; matching those turned the face sad for no
        # reason. Match genuine empathetic phrasing instead. NOTE: "i hear you" was
        # removed — as an acknowledgment opener ("i hear you have concerns…") it made
        # the face sad on plain agreement, which is far more common than the empathetic
        # standalone "I hear you."; the unambiguous empathy phrases below cover sympathy.
        (
            "unfortunately", "i'm sorry", "so sorry", "sorry to hear",
            "that's tough", "that must be hard", "that's a shame",
            "that's rough", "that sounds hard", "hang in there",
            "i know it's", "that's frustrating",
        ),
    ),
)


def mood_for_text(text: str) -> str:
    """Map a sentence to a TalkingHead mood label; DEFAULT_MOOD when nothing matches."""
    lowered = text.lower()
    for mood, keywords in _MOOD_LEXICON:
        if any(keyword in lowered for keyword in keywords):
            return mood
    return DEFAULT_MOOD
