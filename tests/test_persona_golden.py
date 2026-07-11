"""Persona byte-stability golden (persona.py). Pure stdlib, no LiveKit.

Runs persona._self_check in the normal test sweep so a prompt edit that forgets to
regenerate EXPECTED_DEFAULT fails HERE, not silently at runtime. (The self-check lives
in persona.py as `python3 agent/persona.py`; this wrapper makes the sweep cover it.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import persona  # noqa: E402


def test_default_render_matches_golden():
    assert persona.render_persona(persona.DEFAULT_PERSONA) == persona.EXPECTED_DEFAULT


def test_render_is_deterministic():
    assert persona.render_persona(persona.DEFAULT_PERSONA) == persona.render_persona(
        persona.DEFAULT_PERSONA
    )


def test_no_format_placeholder_leak():
    rendered = persona.render_persona(persona.DEFAULT_PERSONA)
    assert "{" not in rendered and "}" not in rendered


def test_self_check_passes():
    # The full in-module self-check (golden + KB seam + knob permutations).
    persona._self_check()


if __name__ == "__main__":
    test_default_render_matches_golden()
    test_render_is_deterministic()
    test_no_format_placeholder_leak()
    test_self_check_passes()
    print("ok: persona golden")
