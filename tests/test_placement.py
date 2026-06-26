"""Exhaustive pure-fn unit tests for agent/placement.resolve_stt_placement (Plan 10-02).

Sandbox-only (no GPU, no livekit, no nvidia-smi): drives the resolver as a PURE
function with ``env`` passed as a plain dict, covering the full
``llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED`` truth table:

  * force-cpu-first beats measured + gpu-fits,
  * default CPU when unmeasured (both fast and better),
  * measured + gpu-fits → gpu,
  * the worst-case-LLM lock (identical decision for fast and better),
  * a tightened table (high KOKORO_MB) pins BOTH choices to cpu,
  * unknown choice never raises + is CPU-safe,
  * truthy normalization, and
  * the no-exception/return-membership invariant across the whole matrix.

Run: ``python3 tests/test_placement.py`` (a __main__ assert harness, matching the
repo's stt/test_dispatch.py convention — no pytest dependency) or
``python3 -m pytest tests/test_placement.py``.
"""
from __future__ import annotations

import os
import sys

# placement.py lives in agent/ (a flat module, imported as `placement` by main.py).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

import placement  # noqa: E402
from placement import resolve_stt_placement  # noqa: E402

_VALID = ("gpu", "cpu")


def test_force_cpu_first_beats_measured() -> None:
    """STT_FORCE_CPU pins CPU even when measured + the math would fit GPU (force wins)."""
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        env = {"STT_FORCE_CPU": truthy, "STT_HEADROOM_MEASURED": "1"}
        assert resolve_stt_placement("fast", env) == "cpu", f"force={truthy!r} must pin cpu"
        assert resolve_stt_placement("better", env) == "cpu", f"force={truthy!r} must pin cpu"


def test_default_cpu_when_unmeasured() -> None:
    """No force, no measured flag → CPU for BOTH choices (the safe default)."""
    env: dict[str, str] = {}
    assert resolve_stt_placement("fast", env) == "cpu", "unmeasured default must be cpu"
    assert resolve_stt_placement("better", env) == "cpu", "unmeasured default must be cpu"
    # STT_FORCE_CPU=0 (falsy) does NOT enable GPU on its own — measured still gates it.
    env_force_off = {"STT_FORCE_CPU": "0"}
    assert resolve_stt_placement("fast", env_force_off) == "cpu", "falsy force still defaults cpu"
    assert resolve_stt_placement("better", env_force_off) == "cpu", "falsy force still defaults cpu"


def test_measured_fits_gpu() -> None:
    """STT_HEADROOM_MEASURED=1, no force → with the placeholder table → GPU for both."""
    env = {"STT_HEADROOM_MEASURED": "1"}
    assert placement._gpu_fits() is True, "placeholder table must fit GPU"
    assert resolve_stt_placement("fast", env) == "gpu", "measured + fits → gpu"
    assert resolve_stt_placement("better", env) == "gpu", "measured + fits → gpu"


def test_worst_case_llm_lock_identical_fast_better() -> None:
    """STT-06: the decision is IDENTICAL for fast and better under the same env, across
    the whole matrix — proving a mid-session swap can never strand placement."""
    for force in ("", "0", "1"):
        for measured in ("", "0", "1"):
            env = {"STT_FORCE_CPU": force, "STT_HEADROOM_MEASURED": measured}
            assert resolve_stt_placement("fast", env) == resolve_stt_placement("better", env), \
                f"fast/better must match under {env!r} (worst-case-LLM lock)"


def test_tightened_table_pins_cpu_for_both() -> None:
    """If the table is tightened so _gpu_fits is False, BOTH choices → cpu even when
    measured (the worst-case math denies GPU for the whole session)."""
    env = {"STT_HEADROOM_MEASURED": "1"}
    original = placement.KOKORO_MB
    try:
        # Push Kokoro huge so worst_llm + KOKORO + STT_GPU > ceiling.
        placement.KOKORO_MB = 9000
        assert placement._gpu_fits() is False, "tightened table must NOT fit GPU"
        assert resolve_stt_placement("fast", env) == "cpu", "tightened → cpu"
        assert resolve_stt_placement("better", env) == "cpu", "tightened → cpu"
        assert resolve_stt_placement("fast", env) == resolve_stt_placement("better", env), \
            "tightened decision still identical for fast/better"
    finally:
        placement.KOKORO_MB = original


def test_unknown_choice_cpu_safe_never_raises() -> None:
    """An unknown llm_choice never raises and resolves to a valid placement."""
    assert resolve_stt_placement("nonsense", {}) == "cpu", "unknown → cpu when unmeasured"
    assert resolve_stt_placement("", {}) == "cpu", "empty choice → cpu when unmeasured"
    measured = {"STT_HEADROOM_MEASURED": "1"}
    assert resolve_stt_placement("nonsense", measured) in _VALID, "unknown never raises"


def test_truthy_normalization() -> None:
    """Truthy values pin CPU via STT_FORCE_CPU; falsy/blank values do not."""
    for truthy in ("1", "true", "TRUE", "Yes", "on", " on "):
        assert resolve_stt_placement("fast", {"STT_FORCE_CPU": truthy}) == "cpu", \
            f"{truthy!r} must be truthy"
    for falsy in ("0", "false", "", "no", "off"):
        # Falsy force + measured → GPU (force does NOT pin; measured gate passes).
        env = {"STT_FORCE_CPU": falsy, "STT_HEADROOM_MEASURED": "1"}
        assert resolve_stt_placement("fast", env) == "gpu", f"{falsy!r} must NOT pin cpu"


def test_no_exception_return_membership_invariant() -> None:
    """Every combination in the matrix returns a value in {"gpu","cpu"}, never raises."""
    for choice in ("fast", "better", "nonsense", ""):
        for force in ("", "0", "1", "true", "yes", "on", "no"):
            for measured in ("", "0", "1", "true"):
                env = {"STT_FORCE_CPU": force, "STT_HEADROOM_MEASURED": measured}
                result = resolve_stt_placement(choice, env)
                assert result in _VALID, f"{choice!r}/{env!r} → {result!r} not in {_VALID}"


def _run_all() -> None:
    test_force_cpu_first_beats_measured()
    test_default_cpu_when_unmeasured()
    test_measured_fits_gpu()
    test_worst_case_llm_lock_identical_fast_better()
    test_tightened_table_pins_cpu_for_both()
    test_unknown_choice_cpu_safe_never_raises()
    test_truthy_normalization()
    test_no_exception_return_membership_invariant()
    print("test_placement OK — full llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED matrix",
          file=sys.stderr)


if __name__ == "__main__":
    _run_all()
