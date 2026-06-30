"""Pure, livekit-free LLM model-CHOICE resolution for the Rehearsal voice loop (v1.2 R2).

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
_DEFAULT_MODEL_ENV: str = "REHEARSAL_DEFAULT_MODEL"
_FALLBACK_DEFAULT_CHOICE: str = "fast"

# Install-set env: the R7 installer writes the comma list of installed choice keys
# so the web picker + agent only surface models that were actually pulled. Unset
# -> the full shipped set (back-compat for pre-R7 deploys).
_INSTALL_SET_ENV: str = "REHEARSAL_MODEL_CHOICES"


def effective_model_choices(env: Mapping[str, str]) -> tuple[str, ...]:
    """Resolve the effective choice set from the installed-set env.

    Unset/empty -> the full shipped MODEL_CHOICES (back-compat). Unknown keys are
    dropped so a typo never surfaces a choice with no pinned tag.
    """
    raw = env.get(_INSTALL_SET_ENV, "").strip()
    if not raw:
        return MODEL_CHOICES
    keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
    installed = tuple(k for k in keys if k in MODEL_CHOICES)
    return installed if installed else MODEL_CHOICES


def default_model_choice(env: Mapping[str, str]) -> str:
    """Resolve the session default choice from env, falling back to the first
    effective choice (Fast in the full set).

    A default not in the narrowed effective set falls back — never raises, so a
    profile typo cannot brick startup (a genuine misconfig surfaces in
    resolved_model_tag).
    """
    choices = effective_model_choices(env)
    choice = env.get(_DEFAULT_MODEL_ENV, "").strip().lower()
    if choice in choices:
        return choice
    return choices[0] if choices else _FALLBACK_DEFAULT_CHOICE


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
