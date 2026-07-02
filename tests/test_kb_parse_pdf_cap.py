"""F16: PDF extraction must reject on page count BEFORE walking every page.

The 25 MB raw cap bounds on-the-wire size, but PDF content streams are Flate-
compressed: a small PDF can declare ~100k pages, and pymupdf4llm.to_markdown walks
every page doing layout analysis under ingest_lock in an uncancellable thread — one
pathological PDF pins a CPU indefinitely and blocks every later upload. Reject on
doc.page_count over a named cap before extraction.

fitz/pymupdf is not importable in the sandbox, so the pure page-count DECISION is
tested directly, plus source-inspection that _extract_pdf enforces the cap before
to_markdown. Run: python3 -m pytest tests/test_kb_parse_pdf_cap.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

import importlib  # noqa: E402

parse = importlib.import_module("kb.parse")


def test_pdf_page_cap_constant_exists_and_is_sane() -> None:
    """A named page ceiling must exist (no magic value) and be a positive int."""
    assert hasattr(parse, "PDF_MAX_PAGES"), "kb.parse must define PDF_MAX_PAGES"
    assert isinstance(parse.PDF_MAX_PAGES, int) and parse.PDF_MAX_PAGES > 0


def test_page_count_over_cap_is_rejected() -> None:
    """F16: the pure decision rejects a page count over the cap and accepts one under."""
    assert parse._pdf_pages_over_cap(parse.PDF_MAX_PAGES + 1) is True
    assert parse._pdf_pages_over_cap(parse.PDF_MAX_PAGES) is False
    assert parse._pdf_pages_over_cap(1) is False


def test_extract_pdf_checks_page_count_before_to_markdown() -> None:
    """Source-inspection: the page-count guard must run BEFORE to_markdown so a
    pathological page count never reaches the per-page layout walk."""
    src = (ROOT / "agent" / "kb" / "parse.py").read_text(encoding="utf-8")
    idx = src.index("def _extract_pdf(")
    body = src[idx:idx + 900]
    assert "page_count" in body, "_extract_pdf must inspect doc.page_count"
    assert "_pdf_pages_over_cap" in body, "_extract_pdf must use the named cap decision"
    # The guard CALL must precede the to_markdown CALL (ignore docstring mentions by
    # matching the call/keyword forms, not the prose).
    guard_call = body.index("if _pdf_pages_over_cap(")
    markdown_call = body.index("pymupdf4llm.to_markdown(")
    assert guard_call < markdown_call, "page-count guard must run before to_markdown"
    assert "_OversizeExtraction" in body, "over-cap must raise the oversize path"


def test_oversize_pdf_page_count_maps_to_oversize_reason() -> None:
    """An _OversizeExtraction from the page guard surfaces as a typed oversize error,
    exactly like the DOCX zip-bomb ceiling (readable, just too big to inline)."""
    # _OversizeExtraction is caught inside parse() and converted; assert the mapping
    # exists in the parse() body (the branch the DOCX bomb already exercises).
    src = (ROOT / "agent" / "kb" / "parse.py").read_text(encoding="utf-8")
    idx = src.index("def parse(")
    body = src[idx:idx + 1500]
    assert "except _OversizeExtraction:" in body
    assert '"oversize"' in body[body.index("except _OversizeExtraction:"):]


if __name__ == "__main__":
    test_pdf_page_cap_constant_exists_and_is_sane()
    test_page_count_over_cap_is_rejected()
    test_extract_pdf_checks_page_count_before_to_markdown()
    test_oversize_pdf_page_count_maps_to_oversize_reason()
    print("ok: PDF page-count cap (F16)")
