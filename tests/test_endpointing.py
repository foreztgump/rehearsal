"""Truth table for the mode→endpointing selector (FEEL-01). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import endpointing  # noqa: E402
import interview  # noqa: E402


def test_learn_mode_uses_snappy_converse_floor():
    # Arrange / Act
    result = endpointing.endpointing_for_mode(interview.MODE_LEARN)
    # Assert
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY == 0.3
    assert result["max_delay"] == endpointing.CONVERSE_MAX_DELAY == 3.0
    assert result["mode"] == "dynamic"


def test_interview_mode_uses_deliberate_floor():
    result = endpointing.endpointing_for_mode(interview.MODE_INTERVIEW)
    assert result["min_delay"] == endpointing.INTERVIEW_MIN_DELAY == 0.7
    assert result["max_delay"] == endpointing.INTERVIEW_MAX_DELAY == 5.0


def test_unknown_mode_falls_back_to_snappy_converse():
    # An unknown mode must not strand the agent on the slow interview floor.
    result = endpointing.endpointing_for_mode("bogus")
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY


if __name__ == "__main__":
    test_learn_mode_uses_snappy_converse_floor()
    test_interview_mode_uses_deliberate_floor()
    test_unknown_mode_falls_back_to_snappy_converse()
    print("ok: endpointing selector truth table")
