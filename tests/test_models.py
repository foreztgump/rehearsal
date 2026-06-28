"""Pure-fn unit tests for agent/models.py (v1.2 R2 — floor model choice).

Sandbox-only: models.py is deliberately livekit-free (mirrors placement.py), so this
imports it directly. Run: `python3 tests/test_models.py` or `python3 -m pytest tests/test_models.py`.
"""
from __future__ import annotations

import os
import sys

# models.py lives in agent/ (flat module, imported as `models` by main.py).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

from models import MODEL_CHOICES, default_model_choice, resolved_model_tag  # noqa: E402


def test_floor_is_a_valid_choice() -> None:
    """v1.2 R2 adds 'floor' alongside the Phase-8 fast/better."""
    assert set(MODEL_CHOICES) == {"fast", "better", "floor"}


def test_resolved_tag_reads_floor_env() -> None:
    """floor resolves to OLLAMA_MODEL_FLOOR (no hardcoded tag)."""
    env = {"OLLAMA_MODEL_FLOOR": "hf.co/example/abliterated-qwen3-4b:Q4_K_M"}
    assert resolved_model_tag("floor", env) == "hf.co/example/abliterated-qwen3-4b:Q4_K_M"


def test_resolved_tag_missing_env_exits() -> None:
    """An unset floor tag is a deploy error (SystemExit), not a silent fallback."""
    try:
        resolved_model_tag("floor", {})
    except SystemExit:
        return
    raise AssertionError("missing OLLAMA_MODEL_FLOOR must raise SystemExit")


def test_resolved_tag_unknown_choice_exits() -> None:
    """An unknown choice raises SystemExit (validate-before-use)."""
    try:
        resolved_model_tag("nonsense", {"OLLAMA_MODEL_FAST": "x"})
    except SystemExit:
        return
    raise AssertionError("unknown choice must raise SystemExit")


def test_default_choice_env_override() -> None:
    """ADEPT_DEFAULT_MODEL lets the installer boot a host on floor; bad/unset → fast."""
    assert default_model_choice({"ADEPT_DEFAULT_MODEL": "floor"}) == "floor"
    assert default_model_choice({"ADEPT_DEFAULT_MODEL": "FLOOR"}) == "floor"
    assert default_model_choice({}) == "fast"
    assert default_model_choice({"ADEPT_DEFAULT_MODEL": "bogus"}) == "fast"


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("models _self_check OK", file=sys.stderr)


if __name__ == "__main__":
    _run_all()
