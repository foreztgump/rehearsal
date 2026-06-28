"""Pure, livekit-free LLM model-CHOICE resolution for the Adept voice loop (v1.2 R2).

Owns the mapping from a plain picker CHOICE key (fast/better/floor) to its pinned
Ollama tag, plus the session DEFAULT choice — a pure function of the process
environment, with NO livekit/openai import so it is unit-testable in the sandbox
(mirrors agent/placement.py, agent/history.py, agent/interview.py).

No hardcoded model tag lives here: every choice resolves to its own env var
(resolved_model_tag), the v1.0 no-hardcoded-tag invariant. resolved_model_tag keeps the
SystemExit-if-unset STARTUP posture (a missing tag is a deploy error, not a hot-path
fallback) — distinct from placement.resolve_stt_placement, which never raises.
"""
from __future__ import annotations

import os
from typing import Mapping

# Plain OUTCOME-label choice keys the picker/agent use — NEVER a raw Ollama tag from the
# client (LLM-01). v1.2 R2 adds "floor" (the ~6GB tier's abliterated small model).
MODEL_CHOICES: tuple[str, ...] = ("fast", "better", "floor")

# Per-choice env var holding the pinned tag (resolved by ollama/pull-and-pin.sh).
_MODEL_ENV: dict[str, str] = {
    "fast": "OLLAMA_MODEL_FAST",
    "better": "OLLAMA_MODEL_BETTER",
    "floor": "OLLAMA_MODEL_FLOOR",
}

# Session default choice. Env-overridable so the R7 installer can boot a weak-hardware
# host on "floor" without a code change; falls back to "fast" (the Phase-8 default).
_DEFAULT_MODEL_ENV: str = "ADEPT_DEFAULT_MODEL"
_FALLBACK_DEFAULT_CHOICE: str = "fast"


def default_model_choice(env: Mapping[str, str]) -> str:
    """Resolve the session default choice from env, falling back to "fast".

    Unset/unknown ADEPT_DEFAULT_MODEL yields the fallback — never raises, so a profile
    typo cannot brick startup (a genuine misconfig surfaces in resolved_model_tag).
    """
    choice = env.get(_DEFAULT_MODEL_ENV, "").strip().lower()
    return choice if choice in MODEL_CHOICES else _FALLBACK_DEFAULT_CHOICE


def resolved_model_tag(choice: str, env: Mapping[str, str] | None = None) -> str:
    """Resolve a picker CHOICE to its pinned Ollama tag from env (no hardcoded tag).

    Raises SystemExit on an unknown choice or an unset/empty env var — the startup
    precondition posture (run ollama/pull-and-pin.sh first).
    """
    environ = os.environ if env is None else env
    env_var = _MODEL_ENV.get(choice)
    if env_var is None:
        raise SystemExit(f"unknown model choice {choice!r} (expected one of {MODEL_CHOICES})")
    tag = environ.get(env_var, "").strip()
    if not tag:
        raise SystemExit(f"{env_var} is not set — run ollama/pull-and-pin.sh first")
    return tag
