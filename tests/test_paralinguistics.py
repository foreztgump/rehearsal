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
    assert paralinguistics.wants_laugh("haha that's great") is True
    assert paralinguistics.wants_laugh("lol") is True


def test_wants_laugh_false_on_normal_speech():
    assert paralinguistics.wants_laugh("Let's talk about my project.") is False


def test_wants_laugh_false_on_incidental_mentions():
    # Word-boundary matched: an inflected form or an embedded substring is NOT a command,
    # so it must not force a [laugh] onto the reply (production on_user_turn path).
    assert paralinguistics.wants_laugh("I was laughing about that earlier.") is False
    assert paralinguistics.wants_laugh("That whole plan is laughable.") is False
    assert paralinguistics.wants_laugh("We shared a lot of laughter.") is False
    assert paralinguistics.wants_laugh("She handed me a lollipop.") is False


def test_laugh_kind_detects_full_laugh():
    assert paralinguistics.laugh_kind("[laugh] okay, that's good.") == "laugh"


def test_laugh_kind_detects_chuckle():
    assert paralinguistics.laugh_kind("Well [chuckle], fair enough.") == "chuckle"


def test_laugh_kind_full_laugh_wins_over_chuckle():
    assert paralinguistics.laugh_kind("[chuckle] wait [laugh] no.") == "laugh"


def test_laugh_kind_none_on_plain_text():
    assert paralinguistics.laugh_kind("Let's begin.") is None


if __name__ == "__main__":
    test_strip_tags_removes_laugh_for_kokoro()
    test_strip_tags_removes_chuckle_for_kokoro()
    test_strip_tags_removes_multiple_tags()
    test_strip_tags_leaves_plain_text_unchanged()
    test_wants_laugh_detects_direct_request()
    test_wants_laugh_false_on_normal_speech()
    test_wants_laugh_false_on_incidental_mentions()
    test_laugh_kind_detects_full_laugh()
    test_laugh_kind_detects_chuckle()
    test_laugh_kind_full_laugh_wins_over_chuckle()
    test_laugh_kind_none_on_plain_text()
    print("ok: paralinguistics tag handling")
