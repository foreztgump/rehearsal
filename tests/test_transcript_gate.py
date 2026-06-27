"""REL-02 garbled-finalize predicate. Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import transcript_gate  # noqa: E402


def test_empty_and_whitespace_are_garbled():
    assert transcript_gate.is_garbled("")
    assert transcript_gate.is_garbled("   \n\t ")


def test_pure_punctuation_is_garbled():
    assert transcript_gate.is_garbled("...")
    assert transcript_gate.is_garbled(" -- ")


def test_short_real_replies_are_not_garbled():
    # Legitimate one-word answers carry alphanumerics and must get a real reply.
    assert not transcript_gate.is_garbled("Hi")
    assert not transcript_gate.is_garbled("No")
    assert not transcript_gate.is_garbled("Ok")


def test_real_utterance_is_not_garbled():
    assert not transcript_gate.is_garbled("what is a SOC")
    assert not transcript_gate.is_garbled("explain ATT&CK")


if __name__ == "__main__":
    test_empty_and_whitespace_are_garbled()
    test_pure_punctuation_is_garbled()
    test_short_real_replies_are_not_garbled()
    test_real_utterance_is_not_garbled()
    print("ok: transcript gate truth table")
