"""Regression: both STT images bake Parakeet bundle + carry the backend module."""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIRED_FETCH_TOOLS = ("bash", "bzip2", "ca-certificates", "curl")


def read_file(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        return handle.read()


def test_no_gate_placeholder_and_bake_wired() -> None:
    for dockerfile in ("Dockerfile", "Dockerfile.cpu"):
        text = read_file(dockerfile)
        assert "operator gate G1" not in text, f"{dockerfile}: stale operator-gate placeholder"
        assert "scripts/export_parakeet_onnx.py" not in text, f"{dockerfile}: stale export-script gate"
        assert "fetch_parakeet_onnx.sh" in text, f"{dockerfile}: must COPY+RUN fetch script"
        assert "backend_parakeet.py" in text, f"{dockerfile}: must COPY backend_parakeet.py"
        if dockerfile == "Dockerfile":
            assert "backend_parakeet_nemo.py" in text, (
                "GPU image must COPY backend_parakeet_nemo.py"
            )
        assert "STT_PARAKEET_MODEL" in text, f"{dockerfile}: must set STT_PARAKEET_MODEL"
        install_cmd = _apt_install_command(text)
        for tool in REQUIRED_FETCH_TOOLS:
            assert tool in install_cmd, f"{dockerfile}: fetch script needs apt install {tool}"


def _apt_install_command(text: str) -> str:
    match = re.search(r"apt-get install\b(?P<cmd>.*?)(?:&&|$)", text, flags=re.S)
    assert match, "Dockerfile must install fetch-script runtime tools"
    return match.group("cmd")


def test_requirements_carry_sherpa() -> None:
    assert "sherpa-onnx" in read_file("requirements-cpu.txt"), "CPU image must install sherpa-onnx"
    assert "sherpa-onnx" in read_file("requirements.txt"), "GPU image must install sherpa-onnx"
    assert "onnxruntime-gpu" not in read_file("requirements.txt"), "drop D17 onnxruntime-gpu leftover"


if __name__ == "__main__":
    test_no_gate_placeholder_and_bake_wired()
    test_requirements_carry_sherpa()
    print("test_parakeet_bake OK — bundle bake wired, backend copied, sherpa-onnx pinned",
          file=sys.stderr)
