"""F34: agent + web images run non-root, HEALTHCHECK, and pin the agent base by digest.

Both Dockerfiles previously ran as root with no HEALTHCHECK, and the agent base
`ghcr.io/astral-sh/uv:python3.12-bookworm-slim` was a moving tag (floats uv + the
python patch). The agent parses untrusted uploads with native-code parsers as
container root. These invariants are checked by Dockerfile source inspection (no
docker build in the sandbox). Run: python3 -m pytest tests/test_dockerfile_hardening.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DOCKERFILE = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")
WEB_DOCKERFILE = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")


def test_agent_base_is_digest_pinned() -> None:
    """F34: the agent base must be pinned by @sha256 digest, not a floating tag alone."""
    assert "ghcr.io/astral-sh/uv" in AGENT_DOCKERFILE
    assert "@sha256:" in AGENT_DOCKERFILE, "agent base must be digest-pinned"
    # The bare moving tag must not be the FROM reference (it may remain in a comment).
    from_lines = [ln for ln in AGENT_DOCKERFILE.splitlines() if ln.startswith("FROM ")]
    assert from_lines, "agent Dockerfile must have a FROM line"
    assert all("@sha256:" in ln for ln in from_lines), "every FROM must carry a digest"


def test_agent_runs_as_non_root() -> None:
    """F34: the agent must drop to a non-root USER after creating an unprivileged user."""
    assert "useradd" in AGENT_DOCKERFILE, "agent must create a non-root user"
    assert "\nUSER app" in AGENT_DOCKERFILE or AGENT_DOCKERFILE.rstrip().endswith("USER app") \
        or "USER app\n" in AGENT_DOCKERFILE, "agent must switch to the non-root user"
    # The USER switch must precede the CMD (so the worker runs unprivileged).
    assert AGENT_DOCKERFILE.index("USER app") < AGENT_DOCKERFILE.rindex("CMD ")


def test_agent_has_healthcheck() -> None:
    """F34: the agent (no HTTP port) must still declare a HEALTHCHECK probing imports."""
    assert "HEALTHCHECK" in AGENT_DOCKERFILE, "agent must declare a HEALTHCHECK"
    assert "livekit.agents" in AGENT_DOCKERFILE, "the probe should verify the import graph"


def test_web_runs_as_non_root() -> None:
    """F34: the web runner must run as the built-in non-root `node` user."""
    # Only inspect the runner stage (after the last FROM).
    runner = WEB_DOCKERFILE[WEB_DOCKERFILE.rindex("FROM "):]
    assert "USER node" in runner, "web runner must switch to the non-root node user"
    assert runner.index("USER node") < runner.rindex("CMD "), "USER must precede CMD"


def test_web_has_healthcheck() -> None:
    """F34: the web runner must declare a HEALTHCHECK on the standalone server."""
    runner = WEB_DOCKERFILE[WEB_DOCKERFILE.rindex("FROM "):]
    assert "HEALTHCHECK" in runner, "web runner must declare a HEALTHCHECK"


if __name__ == "__main__":
    test_agent_base_is_digest_pinned()
    test_agent_runs_as_non_root()
    test_agent_has_healthcheck()
    test_web_runs_as_non_root()
    test_web_has_healthcheck()
    print("ok: Dockerfile hardening (F34)")
