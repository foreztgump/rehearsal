"""Coalescing KB batch distiller (O3 Part 2) — livekit-free so it is sandbox-testable.

A multi-file pick arrives as N independent byte streams; the old ingest ran one
distill per file over the GROWING concatenation of every accepted doc — O(N^2) distill
tokens, serialized under the ingest lock. KbBatchDistiller keeps the parse serialized
(arrival order preserved) but COALESCES the distill: while one distill is in flight,
later-arriving parsed docs pile into `pending` and are drained together in ONE batch.

Timer-free and deterministic:
  * best case (a burst) — the first doc distills alone, everything that arrived during
    that distill drains in a single second distill → ~2 distills instead of N.
  * worst case (a doc arrives only after the prior distill finished) — degrades exactly
    to the old one-distill-per-file behavior, never worse.

All side effects (the network distill, the instruction injection, the kb.state
publish) are injected as async callables, so this module imports nothing from livekit
or main and the concurrency can be exercised with real asyncio in tests.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from kb.distill import DistillError
from kb.parse import ParsedDoc, kb_aggregate_is_full

DistillDocs = Callable[[list[ParsedDoc]], Awaitable[str]]
ApplyBrief = Callable[[str], Awaitable[None]]
PublishState = Callable[..., Awaitable[None]]


class KbBatchDistiller:
    """Owns the session's committed docs + a pending queue, and serializes the distill
    while coalescing everything that piles up during an in-flight distill.

    Callers use it in two steps per upload (so the CPU-heavy parse stays OUTSIDE the
    distill lock, exactly like the pre-existing ingest):
        if not await d.try_add(parsed): return          # budget guard + enqueue
        fired = await d.drain_and_distill()             # coalesced distill + inject
        if fired: <prime once>
    """

    def __init__(
        self,
        *,
        committed: list[ParsedDoc],
        max_tokens: int,
        distill_docs: DistillDocs,
        apply_brief: ApplyBrief,
        publish_state: PublishState,
    ) -> None:
        self._committed = committed  # the live session doc list (owned by the caller)
        self._max_tokens = max_tokens
        self._distill_docs = distill_docs
        self._apply_brief = apply_brief
        self._publish_state = publish_state
        self._pending: list[ParsedDoc] = []
        self._distill_lock = asyncio.Lock()

    def current_total(self) -> int:
        """Estimated tokens already committed PLUS everything queued but not yet
        distilled — the number the aggregate guard must see so a burst can't slip past
        the budget by racing (each doc measured against an empty session)."""
        return sum(d.token_estimate for d in self._committed) + sum(
            d.token_estimate for d in self._pending
        )

    async def try_add(self, doc: ParsedDoc) -> bool:
        """Aggregate-budget guard + enqueue. Returns False (and publishes the 'KB is
        full' error) when adding `doc` would overflow the running total — counting the
        already-pending docs so two bursty uploads can't both think there is room."""
        if kb_aggregate_is_full(self.current_total()) or (
            self.current_total() + doc.token_estimate > self._max_tokens
        ):
            await self._publish_state(
                status="error",
                docs=len(self._committed),
                error="KB is full — remove material or upload less to add more",
            )
            return False
        self._pending.append(doc)
        return True

    async def drain_and_distill(self) -> bool:
        """Run ONE coalesced distill over every currently-committed + pending doc.

        Returns True iff THIS call was the TERMINAL drain of a burst — i.e. it committed
        the batch AND no further docs are queued behind it — so the caller fires exactly
        ONE priming turn per burst. A call that was coalesced away (its docs already
        swept by a concurrent drain), that failed, or that still has followers queued
        returns False, so the burst primes once (on its last batch), not once per file.
        """
        async with self._distill_lock:
            batch = self._pending
            self._pending = []
            if not batch:
                # Another drain (holding the lock ahead of us) already swept our docs.
                return False
            candidate = [*self._committed, *batch]
            try:
                brief = await self._distill_docs(candidate)
            except DistillError:
                # Roll the batch back OUT (M3 atomicity): committed is left exactly as
                # it was so the prior brief stays valid and the session continues.
                await self._publish_state(
                    status="error",
                    docs=len(self._committed),
                    error="Couldn't build the brief — continuing without KB",
                )
                return False
            # Commit + inject so `committed` and the applied brief always agree, even for
            # an intermediate batch (a later drain will re-distill the full set and the
            # brief it injects then supersedes this one).
            self._committed[:] = candidate
            await self._apply_brief(brief)
            await self._publish_state(status="ready", docs=len(self._committed))
            # Prime only when this was the last batch. Docs that arrived DURING this
            # distill sit in _pending with their own drain queued on the lock behind us;
            # that terminal drain re-distills the full set and fires the single prime.
            return not self._pending
