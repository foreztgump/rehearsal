"""F6 guards for the KB byte-stream accumulation in agent/main.py.

ingest_kb is a livekit-coupled closure inside entrypoint(), so — like
test_agent_session_options.py — the loop-level invariants are asserted by source
inspection. The behavioral half (the byte ceiling is a single-sourced import, not a
re-declared magic number) is exercised directly against the pure kb package.

Run: `python3 tests/test_kb_ingest_bytes.py` or `python3 -m pytest tests/test_kb_ingest_bytes.py`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))


def test_kb_max_raw_bytes_is_exported_from_package() -> None:
    """main.py imports the ceiling from `kb`, so it must be on the package surface."""
    import kb

    assert hasattr(kb, "KB_MAX_RAW_BYTES"), "kb package must export KB_MAX_RAW_BYTES"
    assert "KB_MAX_RAW_BYTES" in kb.__all__
    from kb.parse import KB_MAX_RAW_BYTES as parse_value

    assert kb.KB_MAX_RAW_BYTES == parse_value, "export must be the same single-sourced value"


def test_ingest_loop_accumulates_into_bytearray() -> None:
    """F6: the accumulator must be a bytearray (amortized O(n)), not `bytes()`+=."""
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    assert "raw = bytearray()" in source, "ingest must accumulate into a bytearray"
    assert "raw = bytes()" not in source, "the O(n^2) `raw = bytes()` accumulator must be gone"


def test_ingest_loop_enforces_cap_inside_the_loop() -> None:
    """F6: the byte ceiling must be checked WHILE reading (with an early break), using
    the single-sourced KB_MAX_RAW_BYTES — not only inside kb_parse after full buffering."""
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    # The in-loop guard + break must appear inside the async-for accumulation block.
    idx_for = source.index("async for chunk in reader:")
    window = source[idx_for:idx_for + 600]
    assert "len(raw) > KB_MAX_RAW_BYTES" in window, "cap must be checked inside the read loop"
    assert "break" in window, "the read loop must break early on oversize"


def test_ingest_oversize_sets_error_state_before_returning() -> None:
    """F6: an oversize stream must surface a kb.state error and return (not fall through
    into parse). The oversize branch must set status='error' and then return."""
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    idx_for = source.index("async for chunk in reader:")
    window = source[idx_for:idx_for + 900]
    assert "if oversize:" in window, "oversize must be handled before parse"
    error_idx = window.index("if oversize:")
    tail = window[error_idx:error_idx + 300]
    assert 'status="error"' in tail, "oversize must set kb.state=error"
    assert "return" in tail, "oversize must return before parse/distill"


if __name__ == "__main__":
    test_kb_max_raw_bytes_is_exported_from_package()
    test_ingest_loop_accumulates_into_bytearray()
    test_ingest_loop_enforces_cap_inside_the_loop()
    test_ingest_oversize_sets_error_state_before_returning()
    print("ok: KB ingest byte-cap + bytearray (F6)")
