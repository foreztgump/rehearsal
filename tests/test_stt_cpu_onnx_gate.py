"""O6: the CPU STT image must not force the multi-GB legacy-ONNX export by default.

Dockerfile.cpu's export-builder stage does `FROM nvcr.io/nvidia/nemo` (multi-GB) and
runs export_onnx.py to bake the four artifacts backend_onnx loads for LEGACY STREAMING.
The shipped default (STT_ENGINE=buffered) never loads those — it uses the sherpa bundle
from fetch_parakeet_onnx.sh — so that stage is pure dead weight for the default build.

Gate it behind a build ARG (default OFF) using the BuildKit selected-stage idiom: the
runtime `COPY --from=export-builder` points at an ARG-selected alias that resolves to a
LIGHTWEIGHT stub stage by default (empty onnx dir, no NeMo pull) and to the heavy real
builder only when the operator opts in. BuildKit then prunes the unreferenced heavy
stage, so the default CPU build skips the nvcr NeMo pull entirely.

Structure is asserted by Dockerfile/compose inspection (no docker build in the sandbox).
Run: python3 -m pytest tests/test_stt_cpu_onnx_gate.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "stt" / "Dockerfile.cpu").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

GATE_ARG = "STT_INCLUDE_LEGACY_ONNX"


def _from_lines() -> list[str]:
    return [ln.strip() for ln in DOCKERFILE.splitlines() if ln.strip().startswith("FROM ")]


def test_gate_arg_declared_and_defaults_off() -> None:
    """A build ARG must gate the legacy export and default to OFF ('0')."""
    m = re.search(rf"^ARG\s+{GATE_ARG}=(\S+)", DOCKERFILE, re.MULTILINE)
    assert m, f"Dockerfile.cpu must declare ARG {GATE_ARG}"
    assert m.group(1) == "0", f"{GATE_ARG} must default to '0' (skip the multi-GB export)"


def test_heavy_nemo_stage_is_not_directly_copied_from() -> None:
    """The nvcr NeMo builder must NOT be the direct COPY --from source, or it would be
    built unconditionally. It must sit behind the ARG-selected alias."""
    # The heavy stage exists but under its OWN alias (not the bare 'export-builder').
    assert re.search(r"FROM nvcr\.io/nvidia/nemo:\S+ AS export-builder-1", DOCKERFILE), (
        "the heavy NeMo export stage must be named export-builder-1 (opt-in alias)"
    )
    # The runtime COPY must come from the selected alias, never from export-builder-1.
    copy = re.search(r"COPY --from=(\S+)\s+/build/onnx", DOCKERFILE)
    assert copy, "runtime stage must COPY the onnx bundle from a builder stage"
    assert copy.group(1) == "export-builder", (
        f"runtime must COPY from the ARG-selected 'export-builder' alias, got {copy.group(1)!r}"
    )


def test_lightweight_default_stub_stage_exists() -> None:
    """A cheap default stage must provide /build/onnx WITHOUT pulling NeMo, so the
    default COPY has a source and the heavy stage stays unreferenced/pruned."""
    assert re.search(r"FROM \S+ AS export-builder-0", DOCKERFILE), (
        "a lightweight export-builder-0 stub stage must exist for the default build"
    )
    # The stub must not be the NeMo image.
    stub = re.search(r"FROM (\S+) AS export-builder-0", DOCKERFILE)
    assert stub and "nvcr.io/nvidia/nemo" not in stub.group(1), (
        "the default stub stage must NOT be the multi-GB NeMo image"
    )


def test_alias_selects_stage_by_arg() -> None:
    """The 'export-builder' alias must be chosen by the ARG so 0/1 flips real vs stub."""
    assert re.search(
        rf"FROM export-builder-\$\{{{GATE_ARG}\}} AS export-builder", DOCKERFILE
    ), "an ARG-interpolated `FROM export-builder-${STT_INCLUDE_LEGACY_ONNX} AS export-builder` selector is required"


def test_compose_passes_the_gate_arg_defaulting_off() -> None:
    """Compose must expose the gate (default off) so operators can opt in via env."""
    assert re.search(
        rf"{GATE_ARG}:\s*\$\{{{GATE_ARG}:-0\}}", COMPOSE
    ), f"docker-compose.yml must pass {GATE_ARG} to the CPU build, defaulting to 0"


if __name__ == "__main__":
    test_gate_arg_declared_and_defaults_off()
    test_heavy_nemo_stage_is_not_directly_copied_from()
    test_lightweight_default_stub_stage_exists()
    test_alias_selects_stage_by_arg()
    test_compose_passes_the_gate_arg_defaulting_off()
    print("ok: CPU STT legacy-ONNX export gate (O6)")
