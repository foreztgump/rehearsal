"""O3 Part 1: pre-parse aggregate short-circuit.

ingest_kb re-distills the FULL concatenation of every accepted doc, so a session
already at KB_AGGREGATE_MAX_TOKENS can never accept another doc — the post-parse M2
guard is guaranteed to reject it. Every ParsedDoc that clears the extraction gate has
token_estimate >= 1 (MIN_USEFUL_CHARS forces >= 8 tokens at CHARS_PER_TOKEN=4), so
`current_total >= KB_AGGREGATE_MAX_TOKENS` proves the next doc overflows BEFORE the
CPU-heavy PyMuPDF/docx parse runs. Expose that decision as a pure predicate so
ingest_kb can skip the guaranteed-rejected parse, and assert main.py wires it in
before kb_parse.

kb is livekit-free, so the DECISION is tested directly; main.py is a livekit-coupled
closure, so its wiring is asserted by source inspection (matches
test_kb_ingest_bytes.py). Run: python3 -m pytest tests/test_kb_aggregate_shortcircuit.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

parse = importlib.import_module("kb.parse")


def test_predicate_true_at_and_over_the_aggregate_budget() -> None:
    """At or over KB_AGGREGATE_MAX_TOKENS, any further doc is guaranteed to overflow."""
    cap = parse.KB_AGGREGATE_MAX_TOKENS
    assert parse.kb_aggregate_is_full(cap) is True, "exactly at the cap must short-circuit"
    assert parse.kb_aggregate_is_full(cap + 1) is True, "over the cap must short-circuit"
    assert parse.kb_aggregate_is_full(cap + 10_000) is True


def test_predicate_false_below_the_budget() -> None:
    """Below the cap there is still room for at least one more (small) doc, so the
    parse must proceed — the post-parse M2 guard makes the exact accept/reject call."""
    cap = parse.KB_AGGREGATE_MAX_TOKENS
    assert parse.kb_aggregate_is_full(0) is False, "empty session must never short-circuit"
    assert parse.kb_aggregate_is_full(cap - 1) is False, "one under the cap still has room"


def test_predicate_soundness_no_accepted_doc_is_zero_tokens() -> None:
    """The short-circuit is only SOUND because every accepted doc adds >= 1 token: a
    doc that clears the extraction gate has >= MIN_USEFUL_CHARS chars. Guard that
    coupling so a future MIN_USEFUL_CHARS=0 can't silently make the short-circuit
    drop a doc that would actually have fit."""
    assert parse.MIN_USEFUL_CHARS // parse.CHARS_PER_TOKEN >= 1, (
        "a gate-clearing doc must estimate >= 1 token or the short-circuit is unsound"
    )


def test_main_wires_shortcircuit_before_parse() -> None:
    """ingest_kb must consult the predicate BEFORE the CPU-heavy kb_parse call (the
    whole point of O3 Part 1 is skipping the guaranteed-rejected parse)."""
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    assert "kb_aggregate_is_full" in source, "ingest must use the pre-parse short-circuit"
    idx_guard = source.index("kb_aggregate_is_full")
    idx_parse = source.index("kb_parse, info.name")
    assert idx_guard < idx_parse, "the short-circuit must run BEFORE kb_parse"


if __name__ == "__main__":
    test_predicate_true_at_and_over_the_aggregate_budget()
    test_predicate_false_below_the_budget()
    test_predicate_soundness_no_accepted_doc_is_zero_tokens()
    test_main_wires_shortcircuit_before_parse()
    print("ok: KB aggregate pre-parse short-circuit (O3 Part 1)")
