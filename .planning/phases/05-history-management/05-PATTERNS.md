# Phase 5 Patterns: History Management

**Status:** NOT greenfield — every touched seam has a strong in-repo analog. Phases 1–4 built
the full `AgentSession` (`agent/main.py`), three pure-testable livekit-free modules with the
**exact `_self_check()` template** Phase 5 copies (`agent/persona.py`, `agent/metrics.py`,
`agent/kb/parse.py`), the frozen-prefix `render_prompt(persona, brief)` seam carried in the
Agent's `instructions` (`agent/persona.py:116`), the GC-guarded background-task pattern for the
off-hot-path Ollama call (`agent/main.py:311`–`378` `ingest_kb`/`active_tasks`), the off-hot-path
httpx-stream-to-`/api/generate` distill call (`agent/kb/distill.py`), and the per-turn metrics
contract keyed by `speech_id` (`agent/metrics.py`, `llm_ttft_ms`). Phase 5 is **"cap the
conversation history ITEM list so per-turn prefill stops growing (flat TTFT) — without ever
touching the frozen persona+KB prefix in `instructions`."**

Net-new files: ONE small pure module `agent/history.py` (windowing decision logic + `_self_check`).
Everything else MODIFIES a live analog: `agent/main.py` swaps the bare `Agent(...)` for a thin
`HistoryWindowAgent(Agent)` subclass; `agent/metrics.py` is REUSED AS-IS (READ `llm_ttft_ms` over
the time axis — turn-N vs turn-N+20). **There is NO `Agent` subclass and NO history hook today**
(`grep on_user_turn_completed|update_chat_ctx|chat_ctx` → no matches) — Phase 5 introduces the first.

**Source of file list:** `05-RESEARCH.md` §7 (plan-by-plan), §6 (design options + recommendation),
§2 (LiveKit API surface), §0 (three moving parts) — **no CONTEXT.md for this phase** (proceed
without). One roadmap plan: **05-01** (sliding window + optional async summarization behind the
frozen prefix). Clean internal split: **window-first** (pure `history.py` + the subclass wireup =
the SESS-05 verifiable core) then **summarization** (optional second slice, window-only is the floor).

**Core discipline (carried from Phase 1–4, do not break):**
- **History is the ITEM list, NOT the instruction prefix** — the single most important rule. The
  frozen `[persona] + [KB brief]` block lives in the Agent's `instructions` (`render_prompt` output,
  `main.py:262`). Conversation turns are separate `ChatContext` *items* LiveKit appends AFTER the
  instructions. Phase 5 mutates ONLY the item list. **Phase 5 NEVER calls `update_instructions`.**
- **Byte-stability of the frozen prefix is THE keystone constraint** (Pitfall 7). `ChatContext.truncate()`
  "always preserves system instructions" (LiveKit docs) — so windowing the items is *physically
  incapable* of touching the cached persona+KB prefix, PROVIDED windowing never rewrites `instructions`.
  This is why "history sits behind the frozen prefix" (Success Criterion 3) is **structurally true
  already** — Phase 5 caps the item list, it does not re-architect the prompt.
- **Bounded history → flat TTFT** (Pitfall 10 — the thing this phase fixes). Append-only history
  creeps (`llm_ttft_ms` climbs turn-over-turn) and cliffs at `num_ctx` (a session wrapping the window
  evicts the ENTIRE KB/persona prefix). Cap history so `persona(~250) + KB brief(≤1500) + history +
  turn` stays well under `OLLAMA_CONTEXT_LENGTH=8192` (the Modelfile already reserves ~5000 tok for
  history). Tokens-in-context must **plateau, not grow**.
- **Cut from the FRONT, never rewrite the middle** (Pitfall 7 inverted). Trimming the OLDEST items
  is the cache-safe edge — it shifts only the history-region tail (small, bounded re-prefill), not
  the persona+KB block. Do NOT rewrite middle items every turn (maximizes re-prefill). Prefer
  **append + truncate-from-front**.
- **Metrics contract is frozen** (`agent/metrics.py`): per-turn key set
  `{eou_ms,stt_ms,llm_ttft_ms,tts_ttfb_ms,e2e_ms,over_budget}` must NOT change (asserted at
  `metrics.py:284`). 05 READS `llm_ttft_ms` over the time axis as the flat-TTFT-over-time proof — do
  not edit the emitter. Any optional `tokens_in_context` gauge goes on a SEPARATE summary line.
- **No volatile data in any history item** (Anti-Pattern 3). If summarization is added, the summary
  text carries NO timestamps / turn-counters (they churn the history-region cache every turn). Gemma
  thinking is OFF — never carry prior-turn thoughts into history (Pitfall 3); LiveKit stores only
  visible assistant text, so this is satisfied by default.
- **Summarization (if included) runs OFF the hot path** — it is an extra LLM call. Mirror the proven
  GC-guarded `active_tasks` background-task pattern (`main.py:311,373`–`376`). Re-summarize ONLY on
  window overflow (not per turn), keep the summary message stable between events (§3.2 cache churn).
- **Sandbox cannot import livekit / no browser / GPU / Ollama.** Every claim touching the installed
  build is `[VM-INTROSPECT]` (defer like 02/03/04). The PURE pieces — `history.py` windowing decision
  logic + the unchanged `render_prompt` byte-stability golden — ARE sandbox-verifiable and become the
  client-verifiable acceptance criteria; the LiveKit hook round-trip and the flat-TTFT-over-time proof
  are operator/VM gates.

---

## Planned files (extracted from RESEARCH §7 + §6 + the window/summarize split)

| # | File (path) | Role | Data flow | In-repo analog | Plan |
|---|-------------|------|-----------|----------------|------|
| 1 | `agent/history.py` *(new)* | Compute / pure decision logic | `should_trim(item_count) -> bool`, `window_target() -> int`; named `HISTORY_MAX_ITEMS` constant (+ optional token estimate reusing the `len(text)//CHARS_PER_TOKEN` heuristic); operates on COUNTS/items only — no livekit import; `_self_check()` over synthetic counts | **`agent/persona.py`** / **`agent/metrics.py`** / **`agent/kb/parse.py`** (pure module: frozen constants, typed/`@dataclass` returns, `_self_check()` under `if __name__=="__main__"`) | 05-01 |
| 2 | `agent/main.py` | Orchestration / lifecycle | Define `HistoryWindowAgent(Agent)` overriding `on_user_turn_completed`: `self.chat_ctx.copy().truncate(max_items=HISTORY_MAX_ITEMS)` → `await self.update_chat_ctx(...)`; swap the bare `Agent(instructions=...)` at `main.py:262` for the subclass (instructions UNCHANGED). (Optional) async summary fold-in via the existing `active_tasks` GC-guard | **self** — `entrypoint`, `Agent(instructions=render_prompt(...))` (`:262`), the `ingest_kb`/`active_tasks` background-task pattern (`:311,323,373`) | 05-01 |
| 3 | `agent/metrics.py` | Observability | **No code change** — 05-01 READS `llm_ttft_ms` over the time axis (turn-N vs turn-N+20) as the flat-TTFT-over-time proof; optional `tokens_in_context` gauge emitted on a SEPARATE line WITHOUT touching the frozen per-turn key set | **self** — REUSE AS-IS (`llm_ttft_ms`, rolling P50/P95 `SUMMARY_EVERY_TURNS=10`) | (contract only) |
| 4 | `agent/persona.py` | Compute / pure config | **No code change** — confirm `render_prompt` is untouched and the golden `_self_check` byte-stability stays green (Phase 5 must NOT alter the frozen prefix) | **self** — `render_prompt`/`KB_SLOT` golden (`:116,186`) | (regression only) |
| 5 | `agent/kb/distill.py` | Compute (LLM, off hot path) | *(summarization stretch only)* analog for the summarizer's off-hot-path Ollama call shape (httpx stream, `think=false`, accumulate `response`) — OR reuse the LiveKit `summarizer.chat(...).collect()` canonical pattern | **self** — `distill()`/`_generate()` httpx-stream-to-`/api/generate` (`:124`) | 05-01 (stretch) |

> `agent/persona.py` and `agent/metrics.py` are **READ-ONLY analogs** for the window-only MVP floor —
> they do NOT change. History windowing operates on `ChatContext` items, which sit *below* the cached
> `instructions` prefix, so it is orthogonal to persona/KB by construction (§5 — composes, never clobbers).

---

## Role / data-flow classification

**Compute (pure, testable) — #1 `agent/history.py`:** the windowing *decision* (does the item list
exceed budget? how many items to keep?) is a pure function over an integer count (and optionally a
token estimate). Zero livekit import → fully sandbox-verifiable, exactly like `metrics.py` /
`persona.py` / `kb/parse.py`. This carries the client-verifiable acceptance criteria. The function
operates on items/counts ONLY — it never references `instructions` — which is how byte-stability of
the frozen prefix is preserved *by construction*.

**Orchestration / lifecycle — #2 `agent/main.py` (`HistoryWindowAgent`):** the first `Agent` subclass
in the repo. Its `on_user_turn_completed` runs the cheap synchronous window-trim each turn
(`truncate` + `update_chat_ctx` to PERSIST the window across turns) and — for the stretch — fires the
async summary fold-in. The trim is sync/inline (bounds the window immediately, hot-path-cheap); the
summary call, if any, is async (a slow summarizer never delays the next user turn). Swapping
`Agent(...)` for `HistoryWindowAgent(...)` at `main.py:262` leaves `instructions` UNCHANGED.

**Observability — #3 `agent/metrics.py`:** untouched. Where Phase 4 read `llm_ttft_ms` on the
turn-1-vs-turn-2 axis, Phase 5 reads the SAME instrument on the *time* axis (turn-N vs turn-N+20):
without windowing it creeps/cliffs; with windowing it plateaus. An optional `tokens_in_context`
gauge makes the plateau directly observable but MUST NOT alter the frozen per-turn record shape.

**Config (pure, unchanged) — #4 `agent/persona.py`:** the frozen prefix is *not* a Phase-5 concern
except as a regression guard — `render_prompt` and its golden `_self_check` stay byte-identical. The
proof that Phase 5 "did not touch the prefix" is that the persona golden test still passes.

**Compute (LLM, off hot path, stretch) — #5 summarizer:** one Ollama pass when items overflow the
window. Latency is invisible (not on the voice loop), like `distill()`. Re-summarize only on
overflow (not per turn) to bound cache churn; tag the summary item `extra["is_summary"]=True`.

---

## Pattern A — Pure windowing decision logic (file #1 `agent/history.py`) — 05-01

**Analog — `agent/persona.py` / `agent/metrics.py` / `agent/kb/parse.py` are the template for a pure,
testable, livekit-free module:** frozen module-level constants, typed returns, and a `_self_check()`
under `if __name__ == "__main__":` (`python3 agent/history.py`). Mirror exactly. The whole
decision path is testable over synthetic integer counts with NO livekit import — exactly like the
metrics/persona/parse pure cores.

### A1 — Named window constant, coupled to `num_ctx` (no magic numbers, CODE_PRINCIPLES §2)
`HISTORY_MAX_ITEMS` is the lever. Express the window as **max message items** (maps directly to
`ChatContext.truncate(max_items=)`). Document the coupling to `OLLAMA_CONTEXT_LENGTH=8192` and
`BRIEF_TOKEN_BUDGET=1500` — it is the **fourth coupled constant** alongside `num_ctx` /
`KB_MAX_TOKENS` / `BRIEF_TOKEN_BUDGET` (Modelfile reserves ~5000 tok for history). Spoken turns are
short, so a conservative ~16–20 message items (~8–10 exchanges) stays well under 5000 tok.
```python
from __future__ import annotations
import sys

# Sliding-window size in MESSAGE ITEMS. The history budget lever — COUPLED to
# OLLAMA_CONTEXT_LENGTH=8192 and BRIEF_TOKEN_BUDGET=1500 (the Modelfile reserves
# ~5000 tok for the live history window). Spoken turns are short, so ~16-20 items
# (~8-10 exchanges) stays well under 5000 tok. Maps 1:1 to truncate(max_items=).
# [VM-INTROSPECT] tune the exact N against real spoken-turn token sizes + the
# measured flat-TTFT curve; pin to the verified value.
HISTORY_MAX_ITEMS: int = 20

def should_trim(item_count: int) -> bool:
    """True when the live history item list has grown past the window budget."""
    return item_count > HISTORY_MAX_ITEMS

def window_target() -> int:
    """The max_items value to pass to ChatContext.truncate (the last-N kept)."""
    return HISTORY_MAX_ITEMS
```
> **Why item-count, not a hidden global mutating the chat_ctx:** keeping the decision a pure function
> of an integer count preserves byte-stability testability and avoids the hidden-global anti-pattern
> flagged for `KB_SLOT` in 04-RESEARCH §8 / RESEARCH §6.1 option C. The subclass (#2) owns the
> *effect*; this module owns the *decision*.

### A2 — Optional token-budget gate (defensive, reuse the KB char/token heuristic) — refinement
MVP can ship item-count-only. Optionally ALSO gate on an estimated token budget (defensive against an
unusually long single turn) reusing the cheap `len(text)//CHARS_PER_TOKEN` estimate style from
`agent/kb/parse.py:216` — do NOT import a tokenizer.
```python
CHARS_PER_TOKEN: int = 4          # same cheap estimate as kb/parse.py (no tokenizer)
HISTORY_MAX_TOKENS: int = 5000    # the Modelfile history budget; coupled to num_ctx

def estimate_tokens(texts: list[str]) -> int:
    """Cheap token estimate over the live history item texts (chars // CHARS_PER_TOKEN)."""
    return sum(len(t) for t in texts) // CHARS_PER_TOKEN

def should_trim_tokens(texts: list[str]) -> bool:
    return estimate_tokens(texts) > HISTORY_MAX_TOKENS
```

### A3 — `_self_check()` over synthetic counts (mirror `persona.py:186` / `metrics.py:269` / `parse.py:221`)
Pure stdlib, runs in the sandbox. Assert: an over-budget count trips `should_trim`; an under-budget
count does not; `window_target()` returns `HISTORY_MAX_ITEMS` (the last-N kept); the decision is
deterministic (same input → same output); and — the structural invariant — the logic operates on
counts/items only, so **instructions are conceptually preserved** (no path touches the prefix). **No
livekit import.**
```python
def _self_check() -> None:
    """Pure-stdlib check (`python3 agent/history.py`). Mirrors persona/metrics/parse."""
    assert should_trim(HISTORY_MAX_ITEMS + 1) is True, "over-budget must trim"
    assert should_trim(HISTORY_MAX_ITEMS) is False, "at-budget must not trim"
    assert should_trim(0) is False, "empty history must not trim"
    assert window_target() == HISTORY_MAX_ITEMS, "target must keep the last N"
    # Determinism: same input -> identical decision, always.
    assert should_trim(50) == should_trim(50), "should_trim is not deterministic"
    print("history _self_check OK", file=sys.stderr)

if __name__ == "__main__":
    _self_check()
```

---

## Pattern B — Thin `HistoryWindowAgent` subclass: the per-turn hook (file #2 `agent/main.py`) — 05-01

**Analog — `main.py:262` `Agent(instructions=render_prompt(DEFAULT_PERSONA, ""))`** is the bare
construction Phase 5 swaps for a subclass. **Recommended option A** (RESEARCH §6.1): subclass `Agent`,
override the documented per-turn node `on_user_turn_completed`, do the cheap `truncate` synchronously,
`update_chat_ctx` to persist the window. Keep the subclass thin (SRP, ≤40-line methods).

### B1 — Subclass + override (the canonical LiveKit per-turn hook)
`on_user_turn_completed(turn_ctx, new_message)` runs just before the LLM reply. `turn_ctx` edits are
**temporary (this turn only)** unless `update_chat_ctx` is called — so persisting the window REQUIRES
`update_chat_ctx`. `truncate(max_items=N)` reduces to the last N items and **preserves system
instructions by design** (so the persona+KB prefix in `instructions` is untouched — Criterion 3).
```python
import history

class HistoryWindowAgent(Agent):
    """Cap the conversation history ITEM list each turn so per-turn prefill stays
    bounded (flat TTFT, Pitfall 10) WITHOUT touching the frozen persona+KB prefix
    carried in `instructions` (truncate preserves system instructions, Pitfall 7).
    Never calls update_instructions — windowing operates on items only (§2 rule).
    """
    async def on_user_turn_completed(self, turn_ctx, new_message):
        # Cheap synchronous window-trim: keep the last N message items, drop the
        # oldest (cut from the FRONT — the cache-safe edge; never rewrite the middle).
        if history.should_trim(len(self.chat_ctx.items)):
            trimmed = self.chat_ctx.copy().truncate(max_items=history.window_target())
            await self.update_chat_ctx(trimmed)   # PERSIST the window across turns
```
> **Swap at `main.py:262`** (instructions UNCHANGED):
> ```python
> agent = HistoryWindowAgent(instructions=render_prompt(DEFAULT_PERSONA, ""))
> ```
> `[VM-INTROSPECT]` (defer — do NOT mark passed in a plan; sandbox cannot import livekit):
> ```
> python -c "from livekit.agents import Agent; print([m for m in dir(Agent) if 'turn' in m or 'chat_ctx' in m])"
> python -c "import inspect; from livekit.agents import ChatContext; print(inspect.signature(ChatContext.truncate)); print(inspect.signature(ChatContext.copy))"
> python -c "from livekit.agents import ChatContext; c=ChatContext(); print([a for a in dir(c) if 'item' in a or 'message' in a or 'trunc' in a])"
> ```
> Confirm: `on_user_turn_completed` fires per turn; `update_chat_ctx` persists; `truncate(max_items=)`
> + `copy(exclude_instructions=)` signatures on the installed build; the window holds across turns.
> **Fallback** if the subclass is awkward (RESEARCH §6.1 option B): trim on the `conversation_item_added`
> event from `main.py` via `session.current_agent.update_chat_ctx(...)` — but the event fires after
> commit and the ordering vs the next turn is less clear; the subclass is preferred.

### B2 — Never call `update_instructions` from windowing (the §2 design rule)
Persona edit (`handle_persona_update`, `main.py:287`) and KB load (`ingest_kb`, `main.py:362`) are the
ONLY two sanctioned `update_instructions` re-prefills. **Phase 5 adds none.** Windowing mutates the
`ChatContext` item list exclusively. This is what makes "behind the frozen prefix" (Criterion 3)
structurally guaranteed — see §5 (composes, never clobbers).

---

## Pattern C — Async summary fold-in behind the window (file #2 + #5) — 05-01 STRETCH

**Window-only is the MVP floor** (RESEARCH §6.3): the sliding window alone satisfies SESS-05 Criteria
1 ("and/or"), 2, and 3 and is fully deterministic. Ship it first. Summarization is the OPTIONAL
behind-the-window stretch that recovers long-range context the window drops.

### C1 — Off-hot-path discipline (analog: `ingest_kb` / `active_tasks`, `main.py:311,373`)
The summary is an extra LLM call — it MUST run off the voice loop. Do the cheap synchronous `truncate`
inline (B1); fire the summary fold-in asynchronously via the SAME GC-guarded background-task pattern
already proven for KB ingest.
```python
# main.py already has this exact GC guard for ingest_kb (:311) — reuse it:
active_tasks: list[asyncio.Task] = []

def _on_overflow(...):
    task = asyncio.create_task(_maybe_summarize(...))
    active_tasks.append(task)
    task.add_done_callback(active_tasks.remove)
```
> CODE_PRINCIPLES "Latency-first": never add a synchronous step to the hot path without measuring TTFT.
> The trim is sync (bounds the window now); the summarizer call is async (a slow call never delays the
> next user turn).

### C2 — Canonical LiveKit summarizer + re-summarize ONLY on overflow (Pitfall 7 churn)
Reuse the canonical LiveKit `summarize_session` shape (RESEARCH §2): skip non-message items, skip prior
summaries via `item.extra.get("is_summary")`, use a SEPARATE `ChatContext` for the summarizer call.
Place the summary as the **first** history item (after instructions, before live turns). Tag it
`extra["is_summary"]=True`. **Re-summarize only when the window actually overflows** (e.g. batch the
evicted block every K turns) — a running summary that rewrites every turn busts the history-region
cache every turn (§3.2). Keep the summary message stable between events.
```python
async def summarize_session(summarizer, chat_ctx) -> str | None:
    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content="Summarize the conversation ...")
    n = 0
    for item in chat_ctx.items:
        if item.type != "message" or item.role not in ("user", "assistant"):
            continue
        if item.extra.get("is_summary") is True:        # don't summarize summaries
            continue
        text = (item.text_content or "").strip()
        if text:
            summary_ctx.add_message(role="user", content=f"{item.role}: {text}")
            n += 1
    if n == 0:
        return None
    response = await summarizer.chat(chat_ctx=summary_ctx).collect()
    return response.text.strip() if response.text else None
```
> **Anti-Pattern 3 / Pitfall 3:** the summary text lands in a history item — it must carry NO volatile
> data (timestamps, turn counters) or it churns the cache. Summarize VISIBLE turns only
> (`role in ("user","assistant")` message items — the filter above is correct); never carry prior-turn
> thoughts (Gemma thinking is OFF; LiveKit stores only visible text, satisfied by default).
> Use `chat_ctx.copy(exclude_instructions=True)` to build the summarizer input WITHOUT the frozen prefix.

---

## Pattern D — Metrics contract frozen; flat-TTFT-over-time proof (file #3 `agent/metrics.py`) — 05-01

**No code change.** Phase 5 READS the existing instrument on the TIME axis. `agent/metrics.py` emits
per-turn `llm_ttft_ms` keyed by `speech_id` (`metrics.py:69,176`) and a rolling P50/P95 summary every
`SUMMARY_EVERY_TURNS=10` turns (`metrics.py:47`). **The proof for Criterion 2:** run a LONG session
(30–50 turns — enough to overflow the window) and assert `llm_ttft_ms` P50/P95 **does not climb with
turn count**. Without windowing it creeps/cliffs; with windowing it plateaus. Cross-check Ollama logs:
per-turn prompt-eval count stays bounded (a small "new tokens" prefill of the changed history tail),
never a full KB re-prefill mid-session (the `num_ctx`-eviction sign, Pitfall 10).

**Optional `tokens_in_context` gauge (cheap, in-budget):** makes the plateau directly observable
(Pitfall 10: "track tokens-in-context ... it should plateau"). If added, emit it on a SEPARATE summary
line OR extend `emit_turn` carefully WITHOUT breaking the asserted key set (`metrics.py:284`:
`{eou_ms,stt_ms,llm_ttft_ms,tts_ttfb_ms,e2e_ms,over_budget}`). Decide in the plan; **keep the existing
per-turn record shape green** (the Phase-3 contract, also relied on by 04-03).

> `[VM-INTROSPECT]` / operator gate (defer like 04-03): drive 30–50 voice turns; confirm `llm_ttft_ms`
> P50/P95 flat (no upward trend), tokens-in-context plateaus, no mid-session KB re-prefill in Ollama
> logs. This is the Criterion-2 keystone proof — VM-only (needs the live loop).

---

## Pattern E — Compose with persona edit + KB load, never clobber (§5) — 05-01

History lives in a **different place** (items) than the frozen prefix (instructions), so it composes
cleanly with the Phase-3/4 "(persona × KB) epoch" model by construction:
- A persona edit (`handle_persona_update`, `main.py:287`) / KB load (`ingest_kb`, `main.py:362`)
  re-emits **instructions** only; it does NOT touch the history item list. History windowing does NOT
  touch instructions. **Orthogonal — no new clobber risk.**
- **Watch:** when instructions change (persona/KB re-prefill), the history region below re-prefills
  anyway (its prefix moved). That is the EXISTING accepted one-turn cost; windowing does not make it
  worse. No action needed beyond never *adding* per-turn instruction churn (Pattern B2).
- If summarization is added, a summary item is just another history item; a persona edit re-emitting
  instructions leaves the summary item in place (good — grounding + summary both survive the edit).

---

## Anti-patterns for this phase (RESEARCH §6.4) — do NOT do these

- ❌ Don't fold history into `instructions` / `render_prompt` — busts the KB cache every turn
  (Pitfall 7; the whole reason history is a separate item list).
- ❌ Don't rewrite middle history items each turn — maximizes re-prefill (cut from the FRONT only).
- ❌ Don't re-summarize every turn — churns the history-region cache (§3.2); re-summarize only on overflow.
- ❌ Don't run the summarizer LLM call synchronously on the turn path (§3.5; use the `active_tasks` async pattern).
- ❌ Don't put timestamps / turn-counters in any history item (Anti-Pattern 3 / Pitfall 3).
- ❌ Don't change the `metrics.py` per-turn record key set (Phase 3 contract, `metrics.py:284`).
- ❌ Don't call `update_instructions` from windowing — Phase 5 adds NO new re-prefill (§2 rule, Pattern B2).

---

## Requirement → mechanism map (from RESEARCH §7.2)

| Req / Criterion | Mechanism | Files |
|---|---|---|
| SESS-05 / Crit 1 (windowed and/or summarized) | `ChatContext.truncate(max_items=N)` in `on_user_turn_completed` + `update_chat_ctx`; optional async summary fold-in (Pattern C) | #1 → #2 (+#5 stretch) |
| Crit 2 (flat TTFT over a long session) | bounded history → bounded prefill; verified via existing `metrics.py` `llm_ttft_ms` rolling P50/P95 over many turns (turn-N vs turn-N+20) | #1, #2, #3 |
| Crit 3 (behind frozen prefix, no cache bust) | history is `ChatContext` items, NOT `instructions`; `truncate` preserves instructions; Phase 5 never calls `update_instructions` | #2, #4 |

---

## Build order (one plan, internal window-first / summarize-second slice — RESEARCH §7.1)

1. **05-01 window-first (the SESS-05 verifiable core):** new `agent/history.py` (pure
   `should_trim`/`window_target` + `HISTORY_MAX_ITEMS` constant + `_self_check`); `HistoryWindowAgent(Agent)`
   overriding `on_user_turn_completed` (`truncate` + `update_chat_ctx`); swap the bare `Agent(...)` at
   `main.py:262`. Confirm `render_prompt` untouched + persona golden green.
   - **Acceptance (sandbox):** `python3 agent/history.py` `_self_check` passes; `python3 agent/persona.py`
     golden unchanged; the pure module imports cleanly with no livekit.
2. **05-01 summarize-second (OPTIONAL stretch, window-only is the floor):** async summary fold-in via
   the GC-guarded `active_tasks` pattern; re-summarize only on overflow; tag `extra["is_summary"]`;
   place the summary as the first history item.
3. **Operator gates (VM, defer like 04-03):** long session (30–50 turns) → `llm_ttft_ms` P50/P95 flat
   (no upward trend), tokens-in-context plateaus (Crit 2); Ollama logs show bounded per-turn prompt-eval,
   no mid-session KB re-prefill (Crit 3 / Pitfall 7+10); window holds across turns; a KB/persona edit
   mid-session still composes (instructions re-emit, history window intact).

**Phase-5 done = a bounded conversation history** — the item list capped each turn via
`truncate(max_items=HISTORY_MAX_ITEMS)` + `update_chat_ctx` in a thin `HistoryWindowAgent`, sitting
behind the byte-stable persona+KB `instructions` prefix (never touched), with flat `llm_ttft_ms` over
a long session proven (turn-N ≈ turn-N+20, tokens-in-context plateaus) and no mid-session KB re-prefill.
Async summarization is the optional behind-the-window stretch; window-only is the verifiable floor.

---
*Phase 5 patterns — net-new is ONE pure module (`agent/history.py`, mirroring the
`persona.py`/`metrics.py`/`kb/parse.py` `_self_check` template); everything else MODIFIES a live
analog (the `Agent` construction at `main.py:262`, the `ingest_kb`/`active_tasks` background-task
pattern) or REUSES it AS-IS (`metrics.py` `llm_ttft_ms`, `persona.py` golden). Keystone: cap the
history ITEM list, NEVER the `instructions` prefix — so TTFT stays flat (Pitfall 10) without busting
the KB cache (Pitfall 7). Live-build claims tagged `[VM-INTROSPECT]` for the VM.*
