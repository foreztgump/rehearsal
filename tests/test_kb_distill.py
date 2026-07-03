"""F15: distill stream must honor a wall-clock deadline and surface Ollama error chunks.

distill._generate streams /api/generate. Two defects the review found:
  (a) httpx.Client(timeout=...) is a per-OPERATION timeout — during streaming the
      read timer resets on every chunk, so a generation dripping one token just
      under the timeout runs unbounded wall-clock (×2 with the repair pass) while
      ingest_lock is held. num_predict bounds tokens, not token RATE.
  (b) a mid-stream Ollama {"error": ...} chunk is silently ignored: best case the
      generic "produced no output", worst case a truncated partial brief passes the
      FACTS check and is injected as complete.

These drive _generate with an injected fake httpx client (no network), so the pure
stream loop is exercised directly. Run: python3 -m pytest tests/test_kb_distill.py
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

os.environ.setdefault("OLLAMA_MODEL", "test-model:latest")

# kb/__init__.py does `from kb.distill import distill` (the FUNCTION), which shadows
# the submodule attribute — so `import kb.distill as distill` would bind the function.
# Pull the real module object out of sys.modules via importlib.
import importlib  # noqa: E402

distill = importlib.import_module("kb.distill")  # the MODULE, not the function


class _FakeStream:
    """Context manager mimicking httpx client.stream(...) -> response."""

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        yield from self._lines


class _FakeClient:
    """Context manager mimicking httpx.Client; yields a canned stream."""

    def __init__(self, lines: Iterable[str], on_iter=None) -> None:
        self._lines = lines
        self._on_iter = on_iter

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def stream(self, method: str, url: str, json=None):  # noqa: A002 - mirror httpx sig
        if self._on_iter is not None:
            return self._on_iter()
        return _FakeStream(self._lines)


def _install_fake_client(monkeypatch, lines=None, on_iter=None) -> None:
    def _factory(*args, **kwargs):
        return _FakeClient(lines or [], on_iter=on_iter)

    monkeypatch.setattr(distill.httpx, "Client", _factory)


def test_generate_raises_on_error_chunk(monkeypatch) -> None:
    """F15(b): a mid-stream {"error": ...} chunk must raise DistillError, not be dropped."""
    import json

    lines = [
        json.dumps({"response": "partial brief so far"}),
        json.dumps({"error": "model runner has crashed"}),
    ]
    _install_fake_client(monkeypatch, lines=lines)
    raised = False
    try:
        distill._generate("prompt")
    except distill.DistillError as exc:
        raised = True
        assert "crashed" in str(exc) or "error" in str(exc).lower()
    assert raised, "an Ollama error chunk must surface as DistillError"


def test_generate_enforces_wall_clock_deadline(monkeypatch) -> None:
    """F15(a): a slow drip that never sets done must abort on the total wall-clock
    deadline rather than accumulating forever."""
    import json

    # A clock that advances past the deadline after a couple of chunks.
    ticks = iter([0.0, 1.0, distill.DISTILL_TIMEOUT_SECONDS + 1.0, 1e9, 1e9, 1e9])
    monkeypatch.setattr(distill.time, "monotonic", lambda: next(ticks))

    def _endless():
        # Never yields a done=True chunk; keeps dripping tiny responses.
        def gen():
            while True:
                yield json.dumps({"response": "x"})
        return _FakeStream(gen())

    _install_fake_client(monkeypatch, on_iter=_endless)
    raised = False
    try:
        distill._generate("prompt")
    except distill.DistillError as exc:
        raised = True
        assert "deadline" in str(exc).lower() or "timed out" in str(exc).lower() or "timeout" in str(exc).lower()
    assert raised, "a stream past the wall-clock deadline must raise DistillError"


def test_generate_returns_accumulated_text_on_clean_stream(monkeypatch) -> None:
    """A normal stream still accumulates response pieces and returns them (no regression)."""
    import json

    lines = [
        json.dumps({"response": "hello "}),
        json.dumps({"response": "world"}),
        json.dumps({"done": True}),
    ]
    # Clock stays well under the deadline.
    monkeypatch.setattr(distill.time, "monotonic", lambda: 0.0)
    _install_fake_client(monkeypatch, lines=lines)
    assert distill._generate("prompt") == "hello world"


if __name__ == "__main__":
    # Minimal monkeypatch shim for direct-run (pytest provides the real fixture).
    class _MP:
        def __init__(self) -> None:
            self._undo = []

        def setattr(self, obj, name, value) -> None:
            old = getattr(obj, name)
            self._undo.append((obj, name, old))
            setattr(obj, name, value)

        def undo(self) -> None:
            for obj, name, old in reversed(self._undo):
                setattr(obj, name, old)

    for fn in (
        test_generate_raises_on_error_chunk,
        test_generate_enforces_wall_clock_deadline,
        test_generate_returns_accumulated_text_on_clean_stream,
    ):
        mp = _MP()
        try:
            fn(mp)
        finally:
            mp.undo()
    print("ok: distill deadline + error-chunk (F15)")
