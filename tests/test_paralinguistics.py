"""Paralinguistic-tag handling (paralinguistics.py). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import paralinguistics  # noqa: E402


def test_strip_tags_removes_laugh_for_kokoro():
    assert paralinguistics.strip_tags("That's a good one [laugh].") == "That's a good one."


def test_strip_tags_removes_chuckle_for_kokoro():
    assert paralinguistics.strip_tags("[chuckle] I hear you.") == "I hear you."


def test_strip_tags_removes_multiple_tags():
    assert paralinguistics.strip_tags("Sorry [cough], that's funny [laugh].") == "Sorry, that's funny."


def test_strip_tags_leaves_plain_text_unchanged():
    plain = "Let's begin."
    assert paralinguistics.strip_tags(plain) == plain


def test_wants_laugh_detects_direct_request():
    assert paralinguistics.wants_laugh("Just laugh, please.") is True
    assert paralinguistics.wants_laugh("Okay, let me hear you laugh.") is True


def test_wants_laugh_false_on_normal_speech():
    assert paralinguistics.wants_laugh("Let's talk about my project.") is False


if __name__ == "__main__":
    test_strip_tags_removes_laugh_for_kokoro()
    test_strip_tags_removes_chuckle_for_kokoro()
    test_strip_tags_removes_multiple_tags()
    test_strip_tags_leaves_plain_text_unchanged()
    test_wants_laugh_detects_direct_request()
    test_wants_laugh_false_on_normal_speech()
    print("ok: paralinguistics tag handling")
