"""O10: the agent image must install deps with `uv pip install --no-cache`.

uv keeps a wheel/download cache under ~/.cache/uv; in a single-shot image build that
cache is never reused but still bloats the layer. `--no-cache` drops it — smaller image,
faster pulls, zero functional change. Asserted by Dockerfile inspection (no docker build
in the sandbox). Run: python3 -m pytest tests/test_agent_uv_no_cache.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")


def test_uv_pip_install_uses_no_cache() -> None:
    """Every `uv pip install` in the agent build must carry --no-cache."""
    installs = re.findall(r"uv pip install[^\n&|]*", DOCKERFILE)
    assert installs, "agent Dockerfile must install deps with `uv pip install`"
    for cmd in installs:
        assert "--no-cache" in cmd, f"`{cmd.strip()}` must use --no-cache (O10)"


if __name__ == "__main__":
    test_uv_pip_install_uses_no_cache()
    print("ok: agent uv --no-cache (O10)")
