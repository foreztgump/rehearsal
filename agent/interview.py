"""Pure, livekit-free Interview-mode prompt module for Adept (Plan 06-01).

Owns the Interview system-block RENDER as a pure function of a ``role_key: str``.
The EFFECT (``update_instructions``, ``generate_reply``, the ``mode.update`` RPC)
lives in ``agent/main.py``, never here — exactly how ``history.py`` owns the
windowing decision while ``HistoryWindowAgent`` owns the effect, and how
``persona.py`` renders while ``main.py`` applies.

Design rules (mirror ``agent/persona.py``; the #1 constraint is byte-stability):
  * ``ROLES`` maps role keys to FIXED-STRING descriptors, never interpolated data —
    enum->fixed-string exactly like ``persona.DIFFICULTY``. Each key renders
    identical bytes every call.
  * ``render_interview_prompt`` joins FROZEN CONSTANTS in a FIXED tuple order with a
    single space. No interpolation on runtime data, no dict-iteration ordering risk,
    no volatile data (clocks / counters / ids) — this protects the frozen-prefix KB
    cache the toggle re-prefills into (Pitfall 7).
  * ``MODE_LEARN`` is the default mode (MODE-01), exactly as ``DEFAULT_PERSONA`` is
    the default-on-load persona.

This slice is Layer 1 (prompt-only, RESEARCH §4 / §9 q3): the Interview prompt
itself encodes the ``ask ONE question -> wait -> critique -> strong model answer ->
next`` contract; the LLM follows it. No explicit state-enum / per-turn-directive
machinery (Layer 2) and no numeric grading rubric here — both are deliberately out
of scope (REQUIREMENTS line 107; Layer 2 only if 06-02's quality gate shows drift).
"""
from __future__ import annotations

import sys

from persona import SPOKEN_STYLE_FOOTER

# Byte-stable mode keys. MODE_LEARN is the default (MODE-01) — open conversation,
# unchanged from Phases 2–5. MODE_INTERVIEW selects the Interview system block.
MODE_LEARN: str = "learn"
MODE_INTERVIEW: str = "interview"

# Role key -> fixed role descriptor (enum->fixed-string, like persona.DIFFICULTY).
# Hand-authored prose, no interpolated values; identical bytes per key. Each value
# frames the interview target (kind of role, seniority, and the topic areas the
# questions should cover) so render_interview_prompt can compose the role into the
# Interview system block.
ROLES: dict[str, str] = {
    "soc_analyst": (
        "The role is a Security Operations Center (SOC) analyst — a tier-one to "
        "tier-two defender who monitors alerts, triages incidents, and escalates "
        "threats. Draw your questions from alert triage, SIEM and log analysis, the "
        "MITRE ATT&CK framework, phishing and malware investigation, and incident "
        "escalation procedures."
    ),
    "security_engineer": (
        "The role is a security engineer — a hands-on builder who designs, hardens, "
        "and automates defensive systems. Draw your questions from secure architecture "
        "and network segmentation, identity and access management, vulnerability "
        "management, cloud and infrastructure hardening, and security automation and "
        "tooling."
    ),
    "grc": (
        "The role is a governance, risk, and compliance (GRC) specialist — a "
        "practitioner who aligns the security program with frameworks, regulations, "
        "and business risk. Draw your questions from risk assessment and treatment, "
        "control frameworks such as NIST and ISO 27001, audit and compliance evidence, "
        "policy development, and third-party and vendor risk."
    ),
}

# The role the picker seeds to (MODE-03 default selection).
DEFAULT_ROLE: str = "soc_analyst"

# Frozen framing constants (multiline prose like kb/distill.DISTILL_INSTRUCTION).
# Opening framing for the Interview system block.
INTERVIEW_FRAMING: str = (
    "You are conducting a realistic spoken mock interview for the role described "
    "below. Play the part of an experienced, professional interviewer who probes "
    "the candidate's depth with focused, role-relevant questions."
)

# The one-question-at-a-time contract (MODE-04).
ONE_QUESTION_RULE: str = (
    "Ask EXACTLY ONE role-relevant question at a time, then STOP and WAIT for the "
    "candidate's spoken answer. Do not ask several questions at once, do not answer "
    "your own question, and do not move on until they have responded."
)

# The rubric-structured critique contract (MODE-05 DEPTH, Plan 06-02). Replaces
# 06-01's basic contract in the SAME render slot (join order unchanged, byte-stability
# preserved — only the bytes of this constant change). The depth comes from PROMPT
# STRUCTURE, not model size or reasoning tokens (thinking stays OFF on the hot path):
# an explicit QUALITATIVE rubric the 4B model assesses against, then a fixed
# critique -> strong model answer -> next question template. Frozen multiline prose
# mirroring kb/distill.DISTILL_INSTRUCTION (explicit structure + an example-of-shape).
#
# NUMERIC SCORING IS PERMANENTLY OUT OF SCOPE (REQUIREMENTS line 107): no number, no
# rating, no "X out of ten" anywhere — a number invites gaming and is less instructive
# than a concrete qualitative critique plus a strong model answer. The rubric is a
# QUALITATIVE structure of four dimensions, never a graded number. (This comment is the
# only place the word appears; the rendered prompt carries no scoring token — asserted
# in _self_check.)
CRITIQUE_CONTRACT: str = (
    "After the candidate answers, assess their answer against four qualitative "
    "dimensions: technical accuracy — is what they said correct; completeness — did "
    "they cover the parts that matter or leave gaps; precise practitioner terminology "
    "— did they use the right terms exactly or stay vague; and the structure and "
    "clarity of the answer — was it organised and easy to follow. Do NOT attach a "
    "number or grade; judge the answer qualitatively, in words only. Then respond in "
    "this fixed order, spoken aloud and never as a written list. First, give a SHORT "
    "critique that names what was genuinely strong AND what was missing or imprecise — "
    "be concrete and specific to what they actually said, not generic praise. Second, "
    "demonstrate a STRONG model answer to the same question, the kind an expert in this "
    "role would give. Third, ask the next single role-relevant question, then stop and "
    "wait. Example of the shape only (use their real answer, not this): you were "
    "accurate on the detection step and used the right term, but you skipped the "
    "containment stage; a strong answer would also walk through isolating the host; "
    "next question, …"
)


def render_interview_prompt(role_key: str) -> str:
    """Deterministic, byte-stable Interview system block for ``role_key``.

    Joins FROZEN CONSTANTS in a FIXED tuple order with a single space. The role
    descriptor is looked up from ``ROLES`` (enum->fixed-string); no interpolation on
    runtime data, no volatile data — same ``role_key`` -> identical bytes, always.
    Reuses ``persona.SPOKEN_STYLE_FOOTER`` so spoken-style rules are not duplicated.
    """
    return " ".join((
        INTERVIEW_FRAMING,
        ROLES[role_key],
        ONE_QUESTION_RULE,
        CRITIQUE_CONTRACT,
        SPOKEN_STYLE_FOOTER,
    ))


# Golden string: the literal expected ``render_interview_prompt(DEFAULT_ROLE)``
# output (soc_analyst). Mirrors persona.EXPECTED_DEFAULT — a byte-for-byte golden so
# any drift in the framing constants or the default role descriptor trips the
# self-check.
EXPECTED_DEFAULT_INTERVIEW: str = (
    "You are conducting a realistic spoken mock interview for the role described "
    "below. Play the part of an experienced, professional interviewer who probes "
    "the candidate's depth with focused, role-relevant questions. "
    "The role is a Security Operations Center (SOC) analyst — a tier-one to "
    "tier-two defender who monitors alerts, triages incidents, and escalates "
    "threats. Draw your questions from alert triage, SIEM and log analysis, the "
    "MITRE ATT&CK framework, phishing and malware investigation, and incident "
    "escalation procedures. "
    "Ask EXACTLY ONE role-relevant question at a time, then STOP and WAIT for the "
    "candidate's spoken answer. Do not ask several questions at once, do not answer "
    "your own question, and do not move on until they have responded. "
    "After the candidate answers, assess their answer against four qualitative "
    "dimensions: technical accuracy — is what they said correct; completeness — did "
    "they cover the parts that matter or leave gaps; precise practitioner terminology "
    "— did they use the right terms exactly or stay vague; and the structure and "
    "clarity of the answer — was it organised and easy to follow. Do NOT attach a "
    "number or grade; judge the answer qualitatively, in words only. Then respond in "
    "this fixed order, spoken aloud and never as a written list. First, give a SHORT "
    "critique that names what was genuinely strong AND what was missing or imprecise — "
    "be concrete and specific to what they actually said, not generic praise. Second, "
    "demonstrate a STRONG model answer to the same question, the kind an expert in this "
    "role would give. Third, ask the next single role-relevant question, then stop and "
    "wait. Example of the shape only (use their real answer, not this): you were "
    "accurate on the detection step and used the right term, but you skipped the "
    "containment stage; a strong answer would also walk through isolating the host; "
    "next question, … "
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document."
)


def _self_check() -> None:
    """Pure-stdlib byte-stability test (``python3 agent/interview.py``).

    Asserts determinism (same role twice -> identical bytes), the golden default
    render, no format-placeholder leak, and that every ``ROLES`` descriptor lands in
    its render and renders identically across repeated calls. Mirrors
    ``persona.py``'s ``_self_check``; no livekit import (fully sandbox-verifiable).
    """
    a = render_interview_prompt(DEFAULT_ROLE)
    b = render_interview_prompt(DEFAULT_ROLE)
    assert a == b, "render_interview_prompt is not deterministic"
    assert a == EXPECTED_DEFAULT_INTERVIEW, "default interview text drifted from golden"
    assert "{" not in a and "}" not in a, "format placeholder leaked into prefix"

    # The four QUALITATIVE rubric dimensions must land in the render (the depth that
    # compensates for the 4B model's shallow default critique — Pitfall 11 / §6).
    for dimension in ("technical accuracy", "completeness", "terminology", "structure"):
        assert dimension in a, f"rubric dimension {dimension!r} missing from render"

    # The fixed critique -> strong model answer -> next question ordering phrasing.
    assert "critique" in a, "critique step missing from render"
    assert "model answer" in a, "strong model answer step missing from render"
    assert "next single role-relevant question" in a, "next-question step missing from render"
    crit_at = a.index("critique")
    model_at = a.index("model answer")
    next_at = a.index("next single role-relevant question")
    assert crit_at < model_at < next_at, "critique/model-answer/next ordering drifted"

    # NO numeric-score token may leak into the spoken prompt — scoring is permanently
    # out of scope (REQUIREMENTS line 107); the rubric is qualitative structure only.
    lowered = a.lower()
    for token in ("score", "rating", "/10", "out of 10", "points", "grade out of"):
        assert token not in lowered, f"numeric-score token {token!r} leaked into prompt"

    # Every role descriptor must land in its render and render byte-stably.
    for role_key, descriptor in ROLES.items():
        r1 = render_interview_prompt(role_key)
        r2 = render_interview_prompt(role_key)
        assert r1 == r2, f"render not byte-stable for role={role_key}"
        assert descriptor in r1, f"role={role_key} descriptor missing from render"

    print("interview _self_check OK", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
