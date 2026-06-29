"""Content-safe transcript event summaries for local logs."""
from __future__ import annotations

import hashlib

DIGEST_CHARS = 12


def transcript_debug_values(event) -> tuple[bool, int, str]:
    text = getattr(event, "transcript", "") or ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_CHARS]
    return bool(getattr(event, "is_final", False)), len(text), digest
