"""KB package seam (Plan 04-01): re-export the pure parser surface.

Callers do ``from kb import parse, ParsedDoc, KbParseError`` (module-local import
style matching ``import metrics`` / ``from persona import ...``). The package is
importable WITHOUT livekit — nothing under ``agent/kb/`` imports livekit, so the
pure core stays sandbox-verifiable. 04-02 adds the distill surface
(``distill`` / ``build_distill_prompt`` / ``DistillError``) to this re-export.
"""
from kb.distill import DistillError, build_distill_prompt, distill
from kb.parse import (
    KB_AGGREGATE_MAX_TOKENS,
    KB_MAX_RAW_BYTES,
    KB_MAX_TOKENS,
    KB_WARN_TOKENS,
    KbParseError,
    ParsedDoc,
    kb_aggregate_is_full,
    parse,
)

__all__ = [
    "parse",
    "ParsedDoc",
    "KbParseError",
    "KB_WARN_TOKENS",
    "KB_MAX_TOKENS",
    "KB_MAX_RAW_BYTES",
    "KB_AGGREGATE_MAX_TOKENS",
    "kb_aggregate_is_full",
    "build_distill_prompt",
    "distill",
    "DistillError",
]
