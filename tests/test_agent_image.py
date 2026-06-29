"""Regression check for flat agent modules copied into the runtime image."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"


def _main_local_imports() -> set[str]:
    tree = ast.parse((AGENT / "main.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return {f"{name}.py" for name in names if (AGENT / f"{name}.py").exists()}


def test_main_local_imports_are_copied() -> None:
    dockerfile = (AGENT / "Dockerfile").read_text(encoding="utf-8")
    missing = sorted(name for name in _main_local_imports() if name not in dockerfile)
    assert not missing, f"agent/Dockerfile missing COPY for: {', '.join(missing)}"


if __name__ == "__main__":
    test_main_local_imports_are_copied()
    print("test_agent_image OK — main.py local imports are copied", file=sys.stderr)
