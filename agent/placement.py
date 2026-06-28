"""Pure, livekit-free STT-PLACEMENT decision module for the Adept voice loop (Plan 10-02).

This owns the placement DECISION only — *should STT run as full GPU NeMo
(``nemo-stt``) or as the off-GPU CPU-ONNX port (``nemo-stt-cpu``)?* — as a pure
function of the selected LLM choice + the process environment. The EFFECT (picking
``NEMO_STT_URL`` vs ``NEMO_STT_CPU_URL`` and constructing ``NemoSTT``) lives in
``build_session`` in ``agent/main.py``. This is the SAME DECISION-owns-here /
EFFECT-in-main.py split as ``agent/history.py`` (window decision) and
``agent/interview.py`` (mode/role render) — this module never imports livekit and
never touches the WS contract.

Design rules (mirror ``agent/history.py`` / ``agent/interview.py``):
  * Frozen module-level UPPER_CASE constants, typed pure returns, ``_self_check()``
    guarded by ``if __name__ == "__main__":`` — runnable in the sandbox (no livekit
    import, no ``nvidia-smi``, no live VRAM probe).
  * The resolver NEVER raises — it ALWAYS returns ``"gpu"`` or ``"cpu"``. It is a
    hot-path session decision, not a startup precondition (unlike
    ``resolved_model_tag``'s SystemExit posture).

Resolution order is LOCKED (RESEARCH §3 / CONTEXT):
  1. ``STT_FORCE_CPU`` FIRST — truthy → ``"cpu"`` immediately, before any headroom
     logic (STT-07). The global pin that makes the LLM picker VRAM-safe.
  2. ``STT_HEADROOM_MEASURED`` gate — the GPU branch is LOCKED OFF until the operator
     sets this (truthy) after the 4-cell co-residency matrix passes. Until then the
     default is CPU (the default-CPU-when-unmeasured lock).
  3. Worst-case-LLM headroom math (STT-06) — compute against the HEAVIEST LLM that
     could be selected this session (E4B/Better) so a mid-session Fast↔Better swap is
     always VRAM-safe; if the worst case cannot co-fit GPU-STT, return ``"cpu"`` for
     the WHOLE session. Because the math keys off ``max(LLM_PEAK_MB)``, placement is
     read ONCE at session start and NEVER re-resolved on an LLM swap.
"""
from __future__ import annotations

import sys
from typing import Mapping

# --- The static measured-headroom VRAM table (RESEARCH §3) ---------------------
# All values in MB. The LLM peaks are MEASURED (Phase 8 Gate D, STATE.md:114) at the
# q8_0 KB-load prefill peak — grounded, not guessed. The Kokoro footprint is an
# UNMEASURED PLACEHOLDER, which is exactly why the GPU branch stays gated behind the
# operator STT_HEADROOM_MEASURED flag (the arithmetic *says* GPU fits, but the LLM
# peaks were measured WITHOUT a co-resident GPU-STT and Kokoro is a guess).
VRAM_TOTAL_MB: int = 16384      # 16 GB consumer-GPU floor (PERF-02 target)
VRAM_HEADROOM_MB: int = 1024    # peak must stay < total − 1 GB (vram-validate ceiling)
LLM_PEAK_MB: dict[str, int] = {
    "fast": 7408,               # E2B, MEASURED Phase 8 Gate D (STATE.md:114)
    "better": 8912,             # E4B, MEASURED Phase 8 Gate D (STATE.md:114)
    "floor": 2600,              # ⚠️ PLACEHOLDER (abliterated Qwen3-4B q4 ~2.6GB) — PIN
    #                             via Task 5 GPU measure; gated like KOKORO_MB. Below
    #                             `better`, so it never changes the worst-case math.
}
STT_GPU_MB: int = 2400          # GPU-NeMo .nemo + activations (~2.4 GB, Phase 9)
STT_CPU_GPU_MB: int = 0         # CPU-ONNX uses NO VRAM (runs off-GPU; ~0.67–0.88 GB RAM)
KOKORO_MB: int = 2048           # ⚠️ UNMEASURED PLACEHOLDER — Kokoro-82M GPU footprint;
#                                  the operator co-residency gate pins the real number.

# Derived ceiling: the peak must stay strictly under total − 1 GB headroom.
_CEILING_MB: int = VRAM_TOTAL_MB - VRAM_HEADROOM_MB  # 15360

# Env booleans normalize to this truthy set (lower/strip) — the single source for
# both STT_FORCE_CPU and STT_HEADROOM_MEASURED.
_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def _truthy(env: Mapping[str, str], key: str) -> bool:
    """Parse an env flag: True iff the lower/stripped value is in the truthy set."""
    return env.get(key, "").strip().lower() in _TRUTHY


def _gpu_fits() -> bool:
    """Worst-case-LLM headroom math (STT-06): does the HEAVIEST LLM + Kokoro + GPU-STT
    fit under the ceiling? Keying off ``max(LLM_PEAK_MB)`` means the decision is the
    SAME for fast and better, so a mid-session swap can never strand placement.
    """
    worst_llm = max(LLM_PEAK_MB.values())
    return worst_llm + KOKORO_MB + STT_GPU_MB <= _CEILING_MB


def resolve_stt_placement(llm_choice: str, env: Mapping[str, str]) -> str:
    """Resolve STT placement to ``"gpu"`` or ``"cpu"`` — pure, never raises.

    Read ONCE at session start (build_session). The worst-case-LLM math makes a later
    Fast↔Better swap VRAM-safe, so placement is never re-consulted (STT-06).
    """
    # NOTE (L3): `llm_choice` is intentionally UNUSED — the decision keys off
    # max(LLM_PEAK_MB) (the worst-case-LLM no-thrash lock, STT-06), so it is identical
    # for fast/better. The param is kept to document the call site's intent (placement
    # is a function of the chosen LLM) and to keep the signature stable if a future
    # non-worst-case policy needs it; it is NOT a bug that it goes unread.
    # (1) STT_FORCE_CPU first — the global pin, before ANY headroom logic (STT-07).
    if _truthy(env, "STT_FORCE_CPU"):
        return "cpu"
    # (2) Default CPU until the operator measures Kokoro + the co-residency matrix.
    if not _truthy(env, "STT_HEADROOM_MEASURED"):
        return "cpu"
    # (3) Worst-case-LLM headroom decision. An unknown choice is irrelevant to the
    # math (which uses the heaviest LLM) — it is treated as worst-case, CPU-safe.
    return "gpu" if _gpu_fits() else "cpu"


def _self_check() -> None:
    """Pure-stdlib check (``python3 agent/placement.py``). Mirrors history.py.

    Asserts: STT_FORCE_CPU wins even when measured + the math fits; unmeasured →
    CPU for both choices; measured + gpu-fits → GPU for both; an unknown choice never
    raises; the decision is identical for fast/better (the worst-case-LLM lock); and
    every result is in {"gpu","cpu"}. No livekit import — fully sandbox-verifiable.
    """
    force = {"STT_FORCE_CPU": "1", "STT_HEADROOM_MEASURED": "1"}
    assert resolve_stt_placement("better", force) == "cpu", "force-cpu must beat measured"
    assert resolve_stt_placement("fast", force) == "cpu", "force-cpu must beat measured"

    unmeasured: dict[str, str] = {}
    assert resolve_stt_placement("fast", unmeasured) == "cpu", "unmeasured default must be cpu"
    assert resolve_stt_placement("better", unmeasured) == "cpu", "unmeasured default must be cpu"

    measured = {"STT_HEADROOM_MEASURED": "1"}
    assert _gpu_fits() is True, "placeholder table must fit GPU (gated by measured flag)"
    assert resolve_stt_placement("fast", measured) == "gpu", "measured + fits → gpu"
    assert resolve_stt_placement("better", measured) == "gpu", "measured + fits → gpu"

    # Worst-case-LLM lock: identical decision for fast and better under the same env.
    assert resolve_stt_placement("fast", measured) == resolve_stt_placement("better", measured), \
        "placement must be identical for fast/better (no mid-session thrash)"

    # Unknown choice never raises and is a valid placement.
    assert resolve_stt_placement("nonsense", unmeasured) == "cpu", "unknown → cpu when unmeasured"
    assert resolve_stt_placement("nonsense", measured) in ("gpu", "cpu"), "unknown never raises"

    print("placement _self_check OK", file=sys.stderr)


if __name__ == "__main__":
    _self_check()
