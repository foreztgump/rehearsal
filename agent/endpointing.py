"""Mode-aware endpointing profiles (FEEL-01).

Pure module — NO LiveKit import — so the truth table runs in the GPU-less sandbox.
`agent/main.py` applies the returned dict to the live AgentSession turn-handling.

The deliberate floor stays ONLY where it belongs: long, considered interview answers.
Non-Interview modes use the snappy floor so chat feels as live as the Whisper era.
"""
from __future__ import annotations

import interview

# Snappy non-Interview floor: reply ~0.3s after the user stops (Whisper-era feel).
CONVERSE_MIN_DELAY: float = 0.3
CONVERSE_MAX_DELAY: float = 1.0

# Deliberate Interview floor: leave room for a considered, multi-sentence answer.
INTERVIEW_MIN_DELAY: float = 0.7
INTERVIEW_MAX_DELAY: float = 5.0

# Dynamic mode adapts within [min,max] from pause statistics (livekit-agents).
ENDPOINTING_MODE: str = "dynamic"


def endpointing_for_mode(mode: str) -> dict[str, float | str]:
    """Endpointing dict for the current conversation mode.

    Interview → deliberate floor; everything else (non-Interview modes, or an unknown
    value) → snappy floor. Defaulting unknown modes to snappy avoids stranding a
    misconfigured session on the slow interview delay.
    """
    if mode == interview.MODE_INTERVIEW:
        return {
            "mode": ENDPOINTING_MODE,
            "min_delay": INTERVIEW_MIN_DELAY,
            "max_delay": INTERVIEW_MAX_DELAY,
        }
    return {
        "mode": ENDPOINTING_MODE,
        "min_delay": CONVERSE_MIN_DELAY,
        "max_delay": CONVERSE_MAX_DELAY,
    }
