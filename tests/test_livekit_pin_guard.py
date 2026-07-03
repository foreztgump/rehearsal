"""F17/G4: livekit-agents is pinned EXACTLY and the _opts surface is guarded at startup.

main.py mutates the private session.llm._opts.{model,extra_body} surface for the live
generation cap and the model-swap handler. A floating `livekit-agents~=1.5` could
resolve to 1.7+ against the 1.6.4 plugins and rename/drop that surface, silently
breaking the hot path. Assert the exact pin and the startup tripwire by source
inspection (main.py is livekit-coupled, so — like test_agent_session_options.py —
its invariants are checked against source). Run: python3 -m pytest tests/test_livekit_pin_guard.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_livekit_agents_is_pinned_exactly() -> None:
    """F17: livekit-agents must be ==1.6.4, not a ~= float that can drift off the plugins."""
    reqs = (ROOT / "agent" / "requirements.txt").read_text(encoding="utf-8")
    assert "livekit-agents==1.6.4" in reqs, "livekit-agents must be pinned exactly to 1.6.4"
    assert "livekit-agents~=" not in reqs, "the ~= float on livekit-agents must be gone"


def test_all_livekit_plugins_share_the_exact_pin() -> None:
    """The framework + all three plugins move together on 1.6.4."""
    reqs = (ROOT / "agent" / "requirements.txt").read_text(encoding="utf-8")
    for pkg in (
        "livekit-agents==1.6.4",
        "livekit-plugins-openai==1.6.4",
        "livekit-plugins-silero==1.6.4",
        "livekit-plugins-turn-detector==1.6.4",
    ):
        assert pkg in reqs, f"{pkg} must be pinned exactly"


def test_startup_guards_the_opts_surface_before_mutation() -> None:
    """G4: entrypoint must assert session.llm._opts.{model,extra_body} exists BEFORE the
    first mutation, so a silent version bump fails loudly instead of no-op'ing."""
    src = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    # The guard must reference both attributes and raise.
    assert 'hasattr(_opts, "model")' in src, "guard must check _opts.model"
    assert 'hasattr(_opts, "extra_body")' in src, "guard must check _opts.extra_body"
    # The guard must precede the first extra_body mutation.
    guard = src.index('getattr(session.llm, "_opts"')
    mutation = src.index("session.llm._opts.extra_body =")
    assert guard < mutation, "the _opts guard must run before the first mutation"
    # And it must raise (loud fail), not warn.
    guard_block = src[guard:mutation]
    assert "raise RuntimeError" in guard_block, "a missing surface must raise, not warn"


if __name__ == "__main__":
    test_livekit_agents_is_pinned_exactly()
    test_all_livekit_plugins_share_the_exact_pin()
    test_startup_guards_the_opts_surface_before_mutation()
    print("ok: livekit exact pin + _opts guard (F17/G4)")
