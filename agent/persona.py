"""Pure persona-config module for the Adept voice trainer (Plan 03-01).

Lifts the static ``PERSONA_INSTRUCTIONS`` literal out of ``agent/main.py`` into a
structured, livekit-free config: a ``Persona`` dataclass, three enum->fixed-string
knob tables (difficulty/verbosity/correction), a curated Kokoro voice-id list, and
``render_persona(p)`` which assembles a **byte-stable** system prompt.

Design rules (mirror ``agent/metrics.py``; the #1 constraint is byte-stability):
  * Knobs map to FIXED-STRING lookups, never interpolated numbers. ``expert``
    always renders identical bytes; a small model also follows an instruction
    sentence far better than a bare dial reading.
  * ``render_persona`` joins FROZEN CONSTANTS in a FIXED tuple order with a fixed
    separator. No interpolation on runtime data, no dict-iteration ordering risk,
    no volatile data (clocks / turn counters / unique-ids / current-timestamp).
  * The KB slot is an EMPTY trailing segment — the Phase-4 frozen-prefix seam
    (persona -> KB -> history -> turn order frozen NOW). Do not reorder or fill it.
  * ``DEFAULT_PERSONA`` reproduces today's Cybersecurity Trainer behavior
    (``gentle`` correction = PERS-01, ``af_bella`` voice) so default-on-load is
    unchanged. PERS-07's correction-aggressiveness IS the ``CORRECTION`` enum.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

# Enum -> fixed prompt fragment. Hand-authored prose; iterate the WORDS, not a
# number. Each value renders identical bytes for a given key (byte-stability).
DIFFICULTY: dict[str, str] = {
    "beginner":     "Pitch explanations at an entry level; define jargon as you go.",
    "intermediate": "Assume working familiarity; use standard practitioner terms without over-explaining.",
    "expert":       "Engage at an expert level; skip the basics and probe edge cases.",
}
VERBOSITY: dict[str, str] = {
    "terse":    "Keep replies to one or two sentences.",
    "balanced": "Keep replies short and spoken-friendly, a few sentences at most.",
    "detailed": "You may elaborate to several sentences when the topic warrants, still spoken-friendly.",
}
# PERS-07 mechanism — correction-aggressiveness as an enum. The `gentle` value is
# the gentle-correction sentence lifted verbatim from the old main.py:70-72 so the
# default trainer's PERS-01 behavior is preserved; moderate/aggressive scale up.
CORRECTION: dict[str, str] = {
    "gentle": (
        "When they use sloppy or imprecise terminology, gently correct it toward precise "
        "practitioner phrasing — name the right term, say it plainly, and move on without "
        "scolding."
    ),
    "moderate": (
        "When the learner uses sloppy terminology, correct it toward precise practitioner "
        "phrasing and briefly say why the distinction matters before continuing."
    ),
    "aggressive": (
        "Actively catch imprecise or wrong terminology every time; restate the precise term "
        "and the distinction it carries before you continue."
    ),
}

# The frozen Cybersecurity Trainer role block (from the old main.py:62-69), WITHOUT
# the correction sentence and WITHOUT the spoken-style footer — those are separate
# segments so the knobs and footer can vary/freeze independently.
ROLE_PREAMBLE: str = (
    "You are a Cybersecurity Trainer: a seasoned security practitioner who coaches "
    "learners by voice. You cover the security domain broadly — threats and attacker "
    "tradecraft, defenses and controls, network and application security, identity, "
    "cryptography, incident response, and risk. "
    "Hold a natural spoken conversation. Pull the learner into articulating the subject "
    "out loud: ask focused questions, have them explain concepts back to you, and build on "
    "their answers rather than lecturing."
)

# The frozen "no markdown/bullets" spoken-style footer (from the old main.py:73-74).
SPOKEN_STYLE_FOOTER: str = (
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document."
)

# Phase-4 frozen-prefix seam: an EMPTY trailing segment. Phase 4 fills it (KB is
# appended AFTER the persona). Do NOT reorder or fill it in Phase 3.
KB_SLOT: str = ""

# Curated English Kokoro voice ids (PERS-05). A FROZEN constant — not a live fetch
# (PERF-03 determinism). Includes `af_bella` (today's default). Reconcile against
# `curl http://kokoro:8880/v1/audio/voices` once on the VM ([VM-INTROSPECT]).
VOICE_IDS: tuple[str, ...] = (
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_kore",
    "am_michael", "am_fenrir", "am_puck", "am_adam",
    "bf_emma", "bf_alice", "bm_george", "bm_daniel",
)


@dataclass
class Persona:
    """A renderable persona config. ``render_persona`` turns it into a byte-stable
    system prompt; ``voice_id`` selects the Kokoro voice.
    """

    role_text: str       # the editable base block (PERS-02); falls back to ROLE_PREAMBLE
    display_name: str    # PERS-03 — UI label only (kept OUT of the prompt prefix, MVP)
    difficulty: str      # key into DIFFICULTY
    verbosity: str       # key into VERBOSITY
    correction: str      # key into CORRECTION (PERS-07)
    voice_id: str        # Kokoro voice id (PERS-05)


def render_persona(p: Persona) -> str:
    """Deterministic, byte-stable system prompt. Same ``p`` -> identical bytes, always.

    Joins FROZEN CONSTANTS in a FIXED tuple order with a single space. The KB slot
    is the empty trailing segment (the Phase-4 seam). No interpolation on runtime
    values, no dict iteration, no volatile data.
    """
    return " ".join((
        p.role_text or ROLE_PREAMBLE,   # editable base; default falls back to frozen preamble
        DIFFICULTY[p.difficulty],
        VERBOSITY[p.verbosity],
        CORRECTION[p.correction],
        SPOKEN_STYLE_FOOTER,
        KB_SLOT,                        # "" in Phase 3 — seam, do not reorder
    ))


# Default persona (PERS-01 / DEPLOY-03): reproduces today's Cybersecurity Trainer.
DEFAULT_PERSONA = Persona(
    role_text=ROLE_PREAMBLE,
    display_name="Cybersecurity Trainer",
    difficulty="intermediate",
    verbosity="balanced",
    correction="gentle",          # preserves PERS-01 gentle-correction behavior
    voice_id="af_bella",          # matches the old main.py KOKORO_VOICE
)

# Golden string: the literal expected ``render_persona(DEFAULT_PERSONA)`` output.
# Behaviorally equivalent to the old static PERSONA_INSTRUCTIONS (security-domain
# trainer, pull-into-articulating, gentle correction, spoken-friendly footer), now
# with the intermediate/balanced knob fragments interleaved. The trailing space is
# the join with the empty KB_SLOT seam.
EXPECTED_DEFAULT: str = (
    "You are a Cybersecurity Trainer: a seasoned security practitioner who coaches "
    "learners by voice. You cover the security domain broadly — threats and attacker "
    "tradecraft, defenses and controls, network and application security, identity, "
    "cryptography, incident response, and risk. "
    "Hold a natural spoken conversation. Pull the learner into articulating the subject "
    "out loud: ask focused questions, have them explain concepts back to you, and build on "
    "their answers rather than lecturing. "
    "Assume working familiarity; use standard practitioner terms without over-explaining. "
    "Keep replies short and spoken-friendly, a few sentences at most. "
    "When they use sloppy or imprecise terminology, gently correct it toward precise "
    "practitioner phrasing — name the right term, say it plainly, and move on without "
    "scolding. "
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document. "
)


def _self_check() -> None:
    """Pure-stdlib byte-stability test (``python3 agent/persona.py``).

    Asserts determinism (same persona twice -> identical bytes), the golden default
    render, no format-placeholder leak, and that every knob permutation that shares
    an enum value renders identical bytes. Mirrors ``metrics.py``'s ``_self_check``.
    """
    a = render_persona(DEFAULT_PERSONA)
    b = render_persona(DEFAULT_PERSONA)
    assert a == b, "render_persona is not deterministic"
    assert a == EXPECTED_DEFAULT, "default persona text drifted from golden"
    assert "{" not in a and "}" not in a, "format placeholder leaked into prefix"

    # Knob-permutation byte-stability: for every key in each table, a persona using
    # that knob renders identical bytes across repeated calls.
    knob_tables = (
        ("difficulty", DIFFICULTY),
        ("verbosity", VERBOSITY),
        ("correction", CORRECTION),
    )
    for field, table in knob_tables:
        for key in table:
            kwargs = {
                "role_text": ROLE_PREAMBLE,
                "display_name": "Cybersecurity Trainer",
                "difficulty": "intermediate",
                "verbosity": "balanced",
                "correction": "gentle",
                "voice_id": "af_bella",
            }
            kwargs[field] = key
            p = Persona(**kwargs)
            r1 = render_persona(p)
            r2 = render_persona(p)
            assert r1 == r2, f"render not byte-stable for {field}={key}"
            assert table[key] in r1, f"{field}={key} fragment missing from render"

    print("persona _self_check OK", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
