"""Content-safe transcript debug summaries."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from transcript_debug import transcript_debug_values  # noqa: E402


def test_debug_values_avoid_raw_transcript_text() -> None:
    event = SimpleNamespace(transcript="hello parakeet", is_final=True)

    is_final, chars, digest = transcript_debug_values(event)

    assert is_final is True
    assert chars == 14
    assert digest == "fe21b0046c64"


def test_entrypoint_registers_user_transcript_debug_handler() -> None:
    main_source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")

    assert 'session.on("user_input_transcribed", log_user_input_transcribed)' in main_source


if __name__ == "__main__":
    test_debug_values_avoid_raw_transcript_text()
    test_entrypoint_registers_user_transcript_debug_handler()
    print("ok: transcript debug summaries")
