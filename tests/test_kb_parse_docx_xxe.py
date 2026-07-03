"""F39: DOCX extraction must reject XML DTD/entity declarations (defense-in-depth).

The DOCX guard covers zip inflation (DOCX_MAX_UNCOMPRESSED_BYTES) but not XML entity
expansion inside document.xml. Valid OOXML never carries a DTD or internal entities,
so any <!DOCTYPE / <!ENTITY in a member is either malicious (billion-laughs / XXE) or
so malformed it maps to the 'corrupt' boundary anyway. Modern libxml2 blunts the
classic exponential case, but rejecting the declaration outright — on stdlib zipfile,
BEFORE python-docx / lxml parses — is the cheap, deterministic defense.

python-docx is not importable in the sandbox, so the pure scan DECISION is tested
directly over an in-memory .docx-shaped zip. Run: python3 -m pytest tests/test_kb_parse_docx_xxe.py
"""
from __future__ import annotations

import importlib
import io
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

parse = importlib.import_module("kb.parse")

_BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE lolz [\n"
    '  <!ENTITY lol "lol">\n'
    '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">\n'
    "]>\n"
    "<w:document><w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>"
)

_CLEAN_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    "<w:document><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>"
)


def _docx_bytes(document_xml: str) -> bytes:
    """Build a minimal .docx-shaped zip carrying the given word/document.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_docx_entity_scan_helper_exists() -> None:
    """A named, pure decision must exist so the DTD/entity check is unit-testable."""
    assert hasattr(parse, "_docx_has_xml_entities"), "kb.parse must define _docx_has_xml_entities"


def test_billion_laughs_docx_is_detected() -> None:
    """F39: a document.xml carrying a DTD + internal entities must be flagged."""
    assert parse._docx_has_xml_entities(_docx_bytes(_BILLION_LAUGHS)) is True


def test_clean_docx_is_not_flagged() -> None:
    """A normal OOXML document (no DTD/entities) must NOT be flagged."""
    assert parse._docx_has_xml_entities(_docx_bytes(_CLEAN_DOCUMENT)) is False


def test_entity_docx_maps_to_corrupt_via_parse() -> None:
    """End-to-end through parse(): an entity-bearing .docx surfaces as a typed error
    (never a raise, never a successful ParsedDoc), so the voice loop keeps running."""
    result = parse.parse("bomb.docx", "", _docx_bytes(_BILLION_LAUGHS))
    assert isinstance(result, parse.KbParseError), f"entity DOCX must be a typed error, got {result!r}"
    assert result.reason in ("corrupt", "oversize"), result.reason


def test_extract_docx_scans_before_python_docx() -> None:
    """Source-inspection: the entity scan must run BEFORE `from docx import Document`,
    so a malicious document.xml never reaches the lxml parser."""
    src = (ROOT / "agent" / "kb" / "parse.py").read_text(encoding="utf-8")
    idx = src.index("def _extract_docx(")
    body = src[idx:idx + 2000]
    scan_call = body.index("if _docx_has_xml_entities(")
    # The real import (not the prose mention in the zip-bomb comment) is the LAST one.
    import_docx = body.rindex("from docx import Document")
    assert scan_call < import_docx, "entity scan must run before python-docx import"


if __name__ == "__main__":
    test_docx_entity_scan_helper_exists()
    test_billion_laughs_docx_is_detected()
    test_clean_docx_is_not_flagged()
    test_entity_docx_maps_to_corrupt_via_parse()
    test_extract_docx_scans_before_python_docx()
    print("ok: DOCX XML entity defense (F39)")
