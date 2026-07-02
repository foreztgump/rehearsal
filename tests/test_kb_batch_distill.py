"""O3 Part 2: coalesced multi-file KB distill.

The old ingest ran one distill per file over the GROWING concatenation of every
accepted doc — O(N^2) distill tokens, serialized under the lock, for a multi-file
pick. KbBatchDistiller keeps parse serialized (arrival order preserved) but coalesces
the DISTILL: while one distill runs, later-arriving parsed docs pile into `pending`
and are drained together in ONE batch. Timer-free and deterministic — worst case (a
file arrives after the prior distill finishes) is the old per-file behavior; best case
(a burst) collapses to ~2 distills total.

The distiller is livekit-free (side effects are injected async callables), so the
concurrency is exercised directly with real asyncio here. main.py's wiring is asserted
by source inspection (it is a livekit-coupled closure — same convention as
test_kb_ingest_bytes.py). Run: python3 -m pytest tests/test_kb_batch_distill.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

from kb.distill import DistillError  # noqa: E402
from kb.parse import ParsedDoc  # noqa: E402
from kb_ingest import KbBatchDistiller  # noqa: E402


def _doc(name: str, tokens: int) -> ParsedDoc:
    return ParsedDoc(name=name, text=name * 4, token_estimate=tokens, oversize_warn=False)


class _Sink:
    """Records the injected side effects; can gate the FIRST distill on an event so a
    burst is forced to arrive while that distill is in flight."""

    def __init__(self, release: asyncio.Event | None = None, fail: bool = False) -> None:
        self.distill_calls: list[list[str]] = []
        self.applied: list[str] = []
        self.states: list[tuple[str, int, str]] = []
        self.release = release
        self.fail = fail
        self.started = asyncio.Event()

    async def distill_docs(self, docs: list[ParsedDoc]) -> str:
        self.distill_calls.append([d.name for d in docs])
        self.started.set()
        if self.release is not None and len(self.distill_calls) == 1:
            await self.release.wait()  # gate ONLY the first distill
        if self.fail:
            raise DistillError("boom")
        return "brief:" + ",".join(d.name for d in docs)

    async def apply_brief(self, brief: str) -> None:
        self.applied.append(brief)

    async def publish_state(self, *, status: str, docs: int = 0, error: str = "") -> None:
        self.states.append((status, docs, error))


def _make(committed: list[ParsedDoc], sink: _Sink, max_tokens: int = 10_000) -> KbBatchDistiller:
    return KbBatchDistiller(
        committed=committed,
        max_tokens=max_tokens,
        distill_docs=sink.distill_docs,
        apply_brief=sink.apply_brief,
        publish_state=sink.publish_state,
    )


async def _submit(d: KbBatchDistiller, doc: ParsedDoc) -> bool:
    """Mirror main.py's ingest flow: guard+append, then the coalesced distill."""
    if not await d.try_add(doc):
        return False
    return await d.drain_and_distill()


def test_single_doc_distills_once_and_primes() -> None:
    committed: list[ParsedDoc] = []
    sink = _Sink()
    d = _make(committed, sink)
    fired = asyncio.run(_submit(d, _doc("a", 100)))
    assert sink.distill_calls == [["a"]], sink.distill_calls
    assert sink.applied == ["brief:a"]
    assert [x.name for x in committed] == ["a"]
    assert fired is True, "a completed single ingest must fire exactly one priming turn"
    assert ("ready", 1, "") in sink.states


def test_burst_coalesces_into_two_distills_and_one_prime() -> None:
    """Three files whose first distill is in flight when the other two arrive must
    collapse to TWO distills ([a] then [b,c]) and exactly ONE priming turn."""

    async def run():
        release = asyncio.Event()
        committed: list[ParsedDoc] = []
        sink = _Sink(release=release)
        d = _make(committed, sink)
        t1 = asyncio.create_task(_submit(d, _doc("a", 100)))
        await sink.started.wait()  # distill([a]) is running and holds the distill lock
        t2 = asyncio.create_task(_submit(d, _doc("b", 100)))
        t3 = asyncio.create_task(_submit(d, _doc("c", 100)))
        await asyncio.sleep(0.02)  # let b, c parse-append to pending + block on the lock
        release.set()
        fired = await asyncio.gather(t1, t2, t3)
        return sink, committed, fired

    sink, committed, fired = asyncio.run(run())
    # Coalesced to TWO distills (not three): [a] alone, then ONE batch that sweeps b+c.
    # Each distill covers the FULL doc set (the brief replaces the KB slot and must
    # describe everything), so the second call is over a+b+c — O(N) total tokens across
    # the burst instead of the old per-file O(N^2).
    assert len(sink.distill_calls) == 2, f"burst must coalesce, got {sink.distill_calls}"
    assert sink.distill_calls[0] == ["a"]
    assert sorted(sink.distill_calls[1]) == ["a", "b", "c"], sink.distill_calls
    assert [x.name for x in committed] == ["a", "b", "c"]
    assert sum(1 for f in fired if f) == 1, f"a burst must prime exactly once, got {fired}"
    assert sink.applied[-1] == "brief:a,b,c"


def test_aggregate_overflow_is_rejected_without_distilling() -> None:
    committed = [_doc("big", 9000)]
    sink = _Sink()
    d = _make(committed, sink, max_tokens=10_000)
    fired = asyncio.run(_submit(d, _doc("more", 2000)))  # 9000 + 2000 > 10000
    assert fired is False
    assert sink.distill_calls == [], "an overflowing doc must never be distilled"
    assert [x.name for x in committed] == ["big"], "committed must be unchanged"
    assert any(s[0] == "error" and "full" in s[2] for s in sink.states), sink.states


def test_distill_error_rolls_back_the_batch() -> None:
    committed: list[ParsedDoc] = []
    sink = _Sink(fail=True)
    d = _make(committed, sink)
    fired = asyncio.run(_submit(d, _doc("a", 100)))
    assert fired is False
    assert [x.name for x in committed] == [], "a failed distill must roll the batch back out"
    assert any(s[0] == "error" for s in sink.states)
    assert sink.applied == [], "no brief may be injected on a failed distill"


def test_current_total_counts_committed_and_pending() -> None:
    async def run():
        committed = [_doc("a", 100)]
        sink = _Sink()
        d = _make(committed, sink)
        await d.try_add(_doc("b", 250))  # sits in pending until a drain
        return d.current_total()

    assert asyncio.run(run()) == 350


def test_main_wires_the_batch_distiller_and_conditional_prime() -> None:
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    assert "KbBatchDistiller" in source, "ingest must use the coalescing batch distiller"
    assert "kb_distiller.try_add" in source, "ingest must enqueue via the distiller"
    # The priming turn must be GUARDED by the drain result (a coalesced-away, rejected,
    # or failed upload must NOT fire its own 'acknowledge the material' reply): the
    # `fired = drain_and_distill()` + `if not fired: return` guard must precede the prime.
    idx_drain = source.index("fired = await kb_distiller.drain_and_distill()")
    idx_prime = source.index("acknowledge the loaded material")
    assert idx_drain < idx_prime, "the coalesced distill must run before the priming turn"
    guard_window = source[idx_drain:idx_prime]
    assert "if not fired:" in guard_window and "return" in guard_window, (
        "the priming turn must be gated by `if not fired: return`"
    )


if __name__ == "__main__":
    test_single_doc_distills_once_and_primes()
    test_burst_coalesces_into_two_distills_and_one_prime()
    test_aggregate_overflow_is_rejected_without_distilling()
    test_distill_error_rolls_back_the_batch()
    test_current_total_counts_committed_and_pending()
    test_main_wires_the_batch_distiller_and_conditional_prime()
    print("ok: KB coalesced batch distill (O3 Part 2)")
