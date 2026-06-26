# Phase 05 — History Management — Backfill Code Review

**Scope:** `agent/history.py` (NEW, 57 lines) and the Phase-05 history-windowing changes in
`agent/main.py` (`HistoryWindowAgent` + the `on_user_turn_completed` trim hook + the session-agent
construction swap). Phase-06 mode/persona/KB code in `main.py` is reviewed ONLY for interaction risk.

**Diff range:** `git diff 839747f^ 1ef391e -- agent/history.py agent/main.py`
**Review type:** Static / sandbox-only (cannot import livekit, no Docker/GPU). Live round-trip is
operator-gated in `05-HISTORY-VERIFY.md` — this review does NOT mark those gates passed/failed.

---

## Verdict

**APPROVE (with VM-INTROSPECT caveats).** The Phase-05 slice is small, correct against the documented
LiveKit history API, and structurally sound. The decision/effect split is clean, the frozen
persona+KB prefix is preserved by construction, and the windowing math has no off-by-one. All findings
are Medium-or-below and most reduce to "confirm the installed livekit signature on the VM" — already
captured as deferred operator gates.

Sandbox checks reproduced green:
- `python3 agent/history.py` → `history _self_check OK` (exit 0)
- Diff matches the planned artifacts; `HistoryWindowAgent` never calls `update_instructions`
  (only `handle_persona_update` and `ingest_kb` do, both Phase 3/4 — unchanged).

---

## Findings by severity

### Critical
None.

### High
None.

### Medium

**M1 — Trim operates on `self.chat_ctx` + `update_chat_ctx`, not the per-turn `turn_ctx`; the
ordering vs the framework's append of `new_message` is unverified (`main.py:313-316`).**
The documented per-turn hook receives `turn_ctx` (edits scoped to THIS turn) and `new_message` (the
just-completed user turn). The implementation ignores both and mutates the persistent `self.chat_ctx`,
persisting via `update_chat_ctx`. Two consequences to confirm on the VM:
- **Effective-next-turn lag (benign):** the trim persists for subsequent turns rather than shrinking
  the *current* prefill. With a cap of 20 and a trip at 21, the worst case is ~21–22 items entering a
  single prefill — negligible for TTFT. Acceptable.
- **Append/persist race (must confirm):** if `new_message` is NOT yet in `self.chat_ctx.items` when
  the hook runs, calling `update_chat_ctx(trimmed)` during `on_user_turn_completed` could race with
  the framework's own commit of `new_message` (drop or double-append the latest user turn). The
  research table explicitly lists `update_chat_ctx` as the *persist-across-turns* mechanism, so this
  is the sanctioned path — but the interaction with the in-flight `new_message` is exactly the kind of
  thing the `[VM-INTROSPECT]` signature/behavior check in `05-HISTORY-VERIFY.md` must exercise (does
  turn N+1 see the new user message intact after a trim on turn N?). **Action:** add/confirm an
  explicit assertion in the operator runbook that the most-recent user turn survives a trim turn.

**M2 — `len(self.chat_ctx.items)` counts ALL item types, not just rolling user/assistant message
items (`main.py:314`; `history.should_trim`).** `HISTORY_MAX_ITEMS` is documented as "20 message
items (~10 exchanges)," but the guard counts whatever `ChatContext.items` contains — which, depending
on the installed build, may include a leading system/instruction item and/or function-call items.
Combined with `truncate`'s documented behavior ("preserves system instructions; strips leading
orphaned function-call items"), the *retained rolling history* can be fewer than 20 message turns, and
the trip point can be off by the count of non-message items. This does not threaten Criterion 3 (the
prefix is still preserved), but it makes the 20-item budget fuzzier than the comments imply. **Action:**
on the VM, confirm whether `instructions` appear in `.items`; if so, either count only
message-role items or document that `HISTORY_MAX_ITEMS` includes the system item. This also feeds the
already-planned VM tuning of N against the measured flat-TTFT curve.

### Low

**L1 — Each window slide re-prefills the entire history region for one turn (inherent, document it).**
Dropping the oldest items shifts every subsequent history token position, so on a trim turn the whole
post-prefix history re-prefills. The *frozen persona+KB prefix cache still holds* (the keystone), so
this is the correct, cache-safe behavior — but it is a real (small, one-turn) cost each time the
window slides, not a zero-cost operation. Proof B in `05-HISTORY-VERIFY.md` should show bounded
per-turn prompt-eval with the prefix never re-evaluated; this is consistent. No code change needed.

**L2 — `self.chat_ctx.copy()` is O(n) on every over-budget turn (`main.py:315`).** Acceptable: it
only runs when `should_trim` is true (>20 items), n is tiny (~21), and it correctly snapshots before
mutating rather than editing live context. No action.

### Nits

**N1 — The determinism assertion in `_self_check` is a tautology (`history.py:52`).**
`assert should_trim(50) == should_trim(50)` evaluates `True == True` and can never fail regardless of
implementation — it does not actually prove determinism. Harmless, but it gives false confidence.
Consider asserting a concrete expected value instead (e.g. `should_trim(50) is True`).

**N2 — `new_message` (and `turn_ctx`) are unused parameters (`main.py:313`).** Required by the
override signature, so this is correct — noting only that an unused-arg linter may flag it. No action.

---

## Focused answers to the review questions

**history.py — window-cap correctness / off-by-one:** Clean. `should_trim(n) = n > 20`,
`window_target() = 20`. Boundary behavior is exactly right: empty (0) and "shorter than window" → no
trim; exactly at cap (20) → no trim; first over-cap (21) → trim to last 20. The window plateaus at 20.
No off-by-one.

**Can it drop the system/prefix items?** Not from `history.py` — it is a pure integer function with no
reference to `instructions` or any context object, so it is *physically incapable* of touching the
prefix (the design's core claim, verified). The effect side relies on `ChatContext.truncate`
"preserving system instructions"; that guarantee is a documented-but-VM-unconfirmed API contract
(`[VM-INTROSPECT]`). See M2 for the items-count nuance.

**Determinism / byte-stability:** Deterministic pure function; no I/O, no globals mutated, no
volatile data. The `instructions` prefix is never reachable from this path, so byte-stability is
preserved by construction. Good.

**main.py hook — safe mutation / preserves frozen prefix / trims correct end / ordering:** Trims the
correct end (FRONT/oldest via `truncate(max_items=)` which keeps the last N). Snapshots via `copy()`
before mutating (no in-place corruption). Never calls `update_instructions`, so the persona+KB prefix
is untouched. Ordering of the *kept* items is preserved by `truncate`. The only open ordering question
is the interaction with the in-flight `new_message` (M1), which is a VM gate.

**Performance / O(n) per turn / KV cache:** Acceptable. The guard short-circuits below the cap, so the
O(n) `copy()` only fires once the session exceeds 20 items, with n≈21. It does NOT run a mutating
trim on every turn — only when over budget. The KV cache prefix (persona+KB) is never invalidated;
only the volatile history tail re-prefills on a slide turn (L1).

**Phase-6 interaction risk:** Low/none. Phase 6's `compose_instructions` / `handle_mode_update` /
`handle_persona_update` / `ingest_kb` all operate on the **instructions axis** via
`update_instructions`. `HistoryWindowAgent` operates exclusively on the **items axis** via
`update_chat_ctx`. The two axes are orthogonal and compose without clobbering — this is the design
invariant and it holds in the current on-disk state. `handle_mode_update`'s `generate_reply` adds
normal items that get windowed through the same path; no special-casing needed. No shared mutable
state between the windowing hook and the Phase-6 epoch holders (`current_persona/mode/role`).

---

## Recommendations (non-blocking)

1. In `05-HISTORY-VERIFY.md`, add an explicit operator assertion that the most-recent user turn
   survives a trim turn (covers M1's append/persist race).
2. On the VM signature probe, record whether `instructions` is present in `ChatContext.items`; if so,
   either count only message-role items in the guard or update the `HISTORY_MAX_ITEMS` comment to say
   the budget includes the system item (M2).
3. Optionally tighten the tautological determinism assert (N1) to a concrete expected value.

None of these block the phase; all are consistent with the already-deferred `[VM-INTROSPECT]` gates.

---

*Reviewer: automated backfill (code-review capability was disabled during Phase-05 execution).*
*Static review only — live-stack proofs remain operator-gated in `05-HISTORY-VERIFY.md`.*
