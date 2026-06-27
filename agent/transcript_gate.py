"""REL-02: decide whether a finalized STT transcript is too empty/garbled to answer.

Pure module (no LiveKit) so the truth table runs in the sandbox. The agent reprompts
("didn't catch that") instead of generating a reply to noise/silence.
"""
from __future__ import annotations

def is_garbled(text: str) -> bool:
    # Reprompt only on a genuinely contentless finalize: empty/whitespace, or pure
    # punctuation/dots with no spoken word at all. Short real answers ("Hi", "No",
    # "Ok", "Hm") carry alphanumerics and must pass — gating them on length would
    # make normal one-word replies impossible.
    stripped = text.strip()
    if not stripped:
        return True
    return not any(ch.isalnum() for ch in stripped)
