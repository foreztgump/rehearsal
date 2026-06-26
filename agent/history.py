"""Pure, livekit-free sliding-window DECISION module for the Adept voice loop (Plan 05-01).

This owns the windowing DECISION only — *does the conversation history item list
exceed budget, and how many items should be kept?* — as a pure function of an
integer count. The EFFECT (``ChatContext.truncate`` + ``update_chat_ctx``) lives in
the ``HistoryWindowAgent`` subclass in ``agent/main.py``; this module never references
``instructions``, so byte-stability of the frozen persona+KB prefix is preserved BY
CONSTRUCTION (it is physically incapable of touching the prefix).

Design rules (mirror ``agent/persona.py`` / ``agent/metrics.py`` / ``agent/kb/parse.py``):
  * Frozen module-level constants, typed returns, ``_self_check()`` guarded by
    ``if __name__ == "__main__":`` — runnable in the sandbox (no livekit import).
  * Cut from the FRONT (drop the OLDEST items) — the cache-safe edge that shifts only
    the small history tail, never the cached persona+KB block. Never rewrite the middle.
  * Window-only is the MVP floor (YAGNI / CODE_PRINCIPLES §7). The optional token-budget
    gate and the async-condensation stretch are deferred refinements — NOT built here.
"""
from __future__ import annotations

import sys

# Sliding-window size in MESSAGE ITEMS — the history budget lever. This is the
# FOURTH coupled constant alongside OLLAMA_CONTEXT_LENGTH=8192, BRIEF_TOKEN_BUDGET=1500,
# and KB_MAX_TOKENS: the Modelfile reserves ~5000 tok for the live history window, and
# ~20 items (~10 short spoken exchanges) stays well under that 5000-tok budget. Maps
# 1:1 to ChatContext.truncate(max_items=). [VM-INTROSPECT]: tune the exact N on the VM
# against real spoken-turn token sizes + the measured flat-TTFT curve, then pin it.
HISTORY_MAX_ITEMS: int = 20


def should_trim(item_count: int) -> bool:
    """True when the live history item list has grown past the window budget."""
    return item_count > HISTORY_MAX_ITEMS


def window_target() -> int:
    """The ``max_items`` value to pass to ``ChatContext.truncate`` (the last-N kept)."""
    return HISTORY_MAX_ITEMS


def _self_check() -> None:
    """Pure-stdlib check (``python3 agent/history.py``). Mirrors persona/metrics/parse.

    Asserts: an over-budget count trips ``should_trim``; at-budget and empty do NOT;
    ``window_target()`` returns ``HISTORY_MAX_ITEMS``; the decision is deterministic.
    No livekit import — fully sandbox-verifiable.
    """
    assert should_trim(HISTORY_MAX_ITEMS + 1) is True, "over-budget must trim"
    assert should_trim(HISTORY_MAX_ITEMS) is False, "at-budget must not trim"
    assert should_trim(0) is False, "empty history must not trim"
    assert window_target() == HISTORY_MAX_ITEMS, "target must keep the last N"
    assert should_trim(50) == should_trim(50), "should_trim is not deterministic"
    print("history _self_check OK", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
