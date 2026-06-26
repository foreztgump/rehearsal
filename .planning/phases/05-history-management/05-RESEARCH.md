# Phase 5 Research: History Management

**Phase:** 05-history-management (MVP mode — single vertical slice)
**Researched:** 2026-06-25
**Requirements:** SESS-05
**Depends on:** Phase 4 (frozen `[persona] + [KB brief] + [history] + [turn]` prefix)
**Question answered:** *What do I need to know to PLAN this phase well?*

> **Grounding discipline (carried from Phases 2–4):** the sandbox CANNOT import
> `livekit` and has no Docker / GPU / browser / Ollama. Every LiveKit/Ollama API
> claim below is grounded in **published docs (current 1.5/1.6 line)** + the
> **source-verified Phase 2–4 memory** and the **working repo code**. Claims that
> touch the installed build or live models are tagged **[VM-INTROSPECT]** with the
> exact check to run on the Proxmox VM — do NOT mark those passed in a plan; defer
> them like 02/03/04 did. The **pure** pieces (windowing/budget logic, byte-stability
> of the prefix) ARE sandbox-verifiable and should be the client-verifiable
> acceptance criteria; the **flat-TTFT-over-time** proof is an operator/VM gate.

---

## 0. TL;DR — the shape of this phase

Phase 5 bounds the **conversation history region** so a long session's per-turn
prefill stops growing — keeping TTFT flat — **without touching the frozen
persona+KB prefix** that Phase 4 cache-warmed. This is the keystone tension
(Pitfall 7 vs Pitfall 10): history must shrink/summarize, but every byte ABOVE the
history (persona + KB brief, carried in the Agent's `instructions`) must stay
byte-identical so Ollama's prefix cache for the heavy KB block keeps hitting.

The good news: **the existing architecture already puts history in the right
place.** The frozen prefix lives in the Agent's `instructions` (set once via
`render_prompt(persona, brief)` and only re-emitted on the two sanctioned
re-prefills — persona edit, KB load). Conversation turns are separate `ChatContext`
*items* that LiveKit appends automatically and assembles AFTER the instructions.
So "history sits behind the frozen prefix" (Success Criterion 3) is **structurally
true already** — Phase 5's job is to *cap that item list*, not to re-architect the
prompt.

Three moving parts:

1. **Where to hook** — subclass `Agent` and override **`on_user_turn_completed`**
   (the per-turn node that runs just before the LLM generates), OR run a windowing
   pass on `conversation_item_added`. The hook trims the persisted `ChatContext`
   items (NOT the instructions).
2. **Sliding window (MVP core)** — keep the last **N** message items verbatim;
   drop the oldest. `ChatContext.truncate(max_items=N)` does exactly this and
   **preserves system instructions** by design (LiveKit docs). This alone
   satisfies Criteria 1 + 2 and is fully deterministic/sandbox-testable.
3. **Async summarization (optional, behind the window)** — when items fall out of
   the window, fold them into a running summary message placed at the FRONT of the
   history region (after instructions, before live turns). Summarize on a
   **background task** (`asyncio.create_task`, GC-guarded like `ingest_kb`) so the
   extra LLM call never touches the hot path. This is the "and/or" in Criterion 1 —
   MVP can ship window-only and treat summarization as a stretch.

The single biggest design constraint is the same as Phase 4: **do not mutate the
frozen prefix.** Trimming history is cache-safe for the persona+KB block (it lives
above the trimmed region); it only re-prefills the *history tail* that changed,
which is small and bounded — that is the whole point.

Roadmap has this as **one plan (05-01)**. A clean split is window-first (pure +
wireup, the SESS-05 core) then summarization (optional second slice) — but MVP can
land both in one plan if window-only is the verified floor.

---

## 1. The concrete seam: how history is assembled today

### 1.1 Current state (repo code)

`agent/main.py:262` constructs the agent as a bare `Agent`:
```python
agent = Agent(instructions=render_prompt(DEFAULT_PERSONA, ""))
await session.start(agent=agent, room=ctx.room)
```
- **`instructions`** = the frozen prefix (`render_prompt` output: persona knobs +
  KB slot). It is the byte-stable block Phase 4 proved cache-warm.
- It is re-emitted ONLY on the two sanctioned re-prefills:
  - `handle_persona_update` → `agent.update_instructions(render_prompt(p, brief))`
  - `ingest_kb` → `agent.update_instructions(render_prompt(persona, brief))`
- **Conversation turns are NOT in `instructions`.** `AgentSession` maintains a
  `ChatContext` of message *items* (user/assistant turns) and appends each turn
  automatically. The LLM prompt each turn = `instructions` + the `ChatContext`
  items + the new user turn. This is exactly the
  `[persona] + [KB] + [history] + [turn]` layout (STATE Phase-3 decision), with
  the history living in the item list, not the instruction string.
- There is **no `Agent` subclass** and **no history hook** today
  (`grep on_user_turn_completed|update_chat_ctx|chat_ctx` → no matches). Phase 5
  introduces the first one.

### 1.2 Why "behind the frozen prefix" is already structurally satisfied

`ChatContext.truncate()` "always preserving system instructions" (LiveKit docs,
chat-context page). The persona+KB block is carried as instructions, so any
window/summarize operation on the item list is **physically incapable of touching
the cached prefix** — provided we operate on the items and never rewrite
`instructions` as part of windowing. This is the cleanest possible realization of
ARCHITECTURE Pattern 5 ("summary block placed *after* the stable KB/persona
prefix") and Pitfall 10's mandate ("summarization happens *behind* the frozen KB
prefix").

**Design rule:** Phase 5 NEVER calls `update_instructions`. It only mutates the
`ChatContext` item list. (If it ever needs to inject a summary, that summary is a
history *item*, not part of the instruction prefix.)

---

## 2. The LiveKit history API surface (grounded, current 1.5/1.6)

| Primitive | What it does | Use in Phase 5 |
|---|---|---|
| `Agent.on_user_turn_completed(turn_ctx, new_message)` | Per-turn node, runs just before the LLM reply. `turn_ctx` edits are **temporary (this turn only)** unless `update_chat_ctx` is called. | The hook to run the window/summary pass each turn. |
| `Agent.update_chat_ctx(chat_ctx)` | **Persists** a modified `ChatContext` beyond the current turn. | Commit the trimmed/summarized context so the window holds across turns. |
| `ChatContext.truncate(max_items=N)` | Reduce to the last N items; **preserves system instructions**; strips leading orphaned function-call items. | The sliding-window mechanism (MVP core). |
| `ChatContext.copy(exclude_instructions=, exclude_function_call=)` | Snapshot a context with filters. | Build the summarizer's input WITHOUT the frozen prefix (`exclude_instructions=True`). |
| `chat_ctx.items` | The ordered item list (messages, etc.); each has `.type`, `.role`, `.text_content`, `.extra`. | Iterate to summarize / tag summary items via `item.extra["is_summary"]`. |
| `conversation_item_added` event | Emitted when an item is committed to history (user+agent); carries a `metrics` field. | Alternative trim trigger; also a token-growth observation point. |
| `session.current_agent` | The active agent instance. | Reach the agent to call `update_chat_ctx` from `main.py` if not subclassing. |

**Canonical LiveKit summarization shape** (docs, agents-handoffs page) — reuse this
exact pattern, it already does the right things (skips non-message items, skips
prior summaries via `item.extra["is_summary"]`, uses a separate `ChatContext` for
the summarizer call):
```python
async def summarize_session(summarizer: llm.LLM, chat_ctx: ChatContext) -> str | None:
    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content="Summarize the conversation ...")
    n = 0
    for item in chat_ctx.items:
        if item.type != "message" or item.role not in ("user", "assistant"):
            continue
        if item.extra.get("is_summary") is True:   # don't summarize summaries
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

**[VM-INTROSPECT]** confirm the installed signatures (sandbox cannot import livekit):
```
python -c "import inspect; from livekit.agents import Agent; print([m for m in dir(Agent) if 'turn' in m or 'chat_ctx' in m])"
python -c "import inspect; from livekit.agents import ChatContext; print(inspect.signature(ChatContext.truncate)); print(inspect.signature(ChatContext.copy))"
python -c "from livekit.agents import ChatContext; c=ChatContext(); print([a for a in dir(c) if 'item' in a or 'message' in a or 'trunc' in a])"
```

---

## 3. Pitfalls that dictate the design

### 3.1 Pitfall 10 — history TTFT creep + `num_ctx` eviction (THE thing this phase fixes)

Append-only history is fine for 5 turns, degrades by ~20–40 (PITFALLS §10). Two
failure modes:
- **Prefill creep:** every turn re-prefills a longer history tail → `llm_ttft_ms`
  climbs turn over turn.
- **Hard cliff at `num_ctx`:** Ollama loses the cache "if context exceeds
  `num_ctx`" — a long session that wraps the window evicts the **entire** KB/persona
  prefix and re-prefills it. On this stack `num_ctx`/`OLLAMA_CONTEXT_LENGTH = 8192`
  (compose env is the single source of truth — Modelfile `num_ctx` does NOT reach
  the hot path; see `ollama/Modelfile` HOT-PATH NOTE). The Modelfile budget already
  reserves **~5000 tok for the history window**; Phase 5 must keep the live history
  *under that budget* so total context never approaches 8192.

**Design rule:** cap history so `persona(~250) + KB brief(≤1500) + history + turn`
stays well under 8192 — the window budget is the lever. Track tokens-in-context as
a metric; it must **plateau, not grow** (PITFALLS §10 warning sign).

### 3.2 Pitfall 7 — prefix-cache invalidation (the constraint, inverted)

Phase 4's keystone: any change to the prefix busts the KB cache. Phase 5's window
operates on the history items, which sit *below* the cached prefix, so trimming the
**front** of the history (oldest items) is the cache-safe edge to cut from —
everything above (instructions) is untouched. **But** note the nuance: trimming the
*oldest* history items shifts what follows, invalidating the cache for the
**history region** from the cut down (not the persona+KB block). That re-prefill is
small and bounded (a few thousand tokens of recent turns), which is the accepted
cost — vs the unbounded growth it prevents. Do NOT rewrite middle items every turn
(that maximizes re-prefill); prefer **append + truncate-from-front**, and when
summarizing, change the summary block **as a discrete, infrequent event**, not
every turn (PITFALLS §7: "if you must summarize, do it as a discrete event ... not
silently every turn").

**Corollary — summary churn is a cache cost.** A running summary that rewrites
every turn busts the history-region cache every turn. Mitigation: only re-summarize
when the window actually overflows (e.g. every K turns, batch the evicted block),
and keep the summary message stable between those events.

### 3.3 Pitfall 3 — don't carry thinking/volatile data into history

Gemma thinking is OFF (`reasoning_effort="none"` / `think=false`). STACK §Gemma-4
caveat: "do **not** carry prior-turn thoughts in history." LiveKit only stores the
visible assistant text in `ChatContext` items, so this is satisfied by default —
but if summarization is added, the summarizer input must be the **visible** turns
only (the canonical pattern filters to `role in ("user","assistant")` message
items, which is correct). Also: the summary text lands in a history item — it must
carry **no volatile data** (timestamps, turn counters) or it churns the cache
(Anti-Pattern 3).

### 3.4 num_ctx coupling — window budget is a VRAM-coupled constant

`num_ctx`, `BRIEF_TOKEN_BUDGET` (1500), `KB_MAX_TOKENS`/`KB_WARN_TOKENS` are
**coupled constants** (Modelfile comment; STATE Phase-04 decision). The history
window budget (~5000 tok in the Modelfile accounting) is the fourth member of that
set. Pick the window size as a **named constant** (CODE_PRINCIPLES §2 — no magic
numbers; "latency budgets ... are named constants") and document it as coupled to
`OLLAMA_CONTEXT_LENGTH`. Recommend expressing the window as **max message items**
(maps directly to `truncate(max_items=)`) and/or a **token budget**; if token-based,
reuse the cheap `len(text)/CHARS_PER_TOKEN` estimate style from the KB size guard
(`agent/kb/parse.py`) rather than importing a tokenizer.

### 3.5 Off-hot-path discipline for summarization

If summarization is included, it is an **extra LLM call** — it MUST run off the
voice loop (ARCHITECTURE Pattern 5: "run async, off the critical path"). Mirror the
proven `ingest_kb` background-task pattern in `main.py`:
```python
active_tasks: list[asyncio.Task] = []   # GC guard (already used for KB)
task = asyncio.create_task(_maybe_summarize(...))
active_tasks.append(task); task.add_done_callback(active_tasks.remove)
```
Do the cheap synchronous `truncate` inline (keeps the window bounded immediately);
fire the summary fold-in asynchronously so a slow summarizer call never delays the
next user turn. CODE_PRINCIPLES "Latency-first": never add a synchronous step to the
hot path without measuring TTFT.

---

## 4. Measuring flat-TTFT-over-time (Success Criterion 2) — the proof

The metrics scaffold already does the heavy lifting — **do not change its key shape**
(Phase 3 contract, asserted in `metrics.py:_self_check`):
- `agent/metrics.py` emits per-turn `llm_ttft_ms` keyed by `speech_id` and a rolling
  P50/P95 summary every `SUMMARY_EVERY_TURNS = 10` turns.
- **The proof for Criterion 2:** run a LONG session (enough turns to overflow the
  window — e.g. 30–50 turns) and assert `llm_ttft_ms` **does not climb with turn
  count**. Without windowing it creeps/cliffs; with windowing it plateaus.
- Cross-check Ollama logs: per-turn prompt-eval count should stay bounded (small
  "new tokens" prefill of the changed history tail), not grow each turn, and never
  show a full KB re-prefill mid-session (the `num_ctx`-eviction sign, Pitfall 10).
- This is the **same instrument** Phase 4 used for turn-1-vs-turn-2; Phase 5 reads
  it over the *time axis* (turn-N vs turn-N+20) instead.

**Optional new metric (cheap, in-budget):** a `tokens_in_context` gauge per turn so
the plateau is directly observable (PITFALLS §10: "track tokens-in-context ... it
should plateau"). If added, extend `emit_turn` carefully WITHOUT breaking the
asserted key set, or emit it on a separate summary line. Decide in the plan; keep
the existing per-turn record shape green.

**[VM-INTROSPECT] / operator gate** (defer like 04-03):
```
# Long-session flat-TTFT: drive 30–50 voice turns; confirm llm_ttft_ms P50/P95 flat
# (no upward trend), tokens-in-context plateaus, no mid-session KB re-prefill in
# ollama logs. This is the Criterion-2 keystone proof — VM-only (needs live loop).
```

---

## 5. Interaction with persona edit + KB load (must compose, not clobber)

Phase 3/4 established that persona edit and KB load are **one-time re-prefills** that
**compose** via `render_prompt(current_persona[0], session_kb.brief)` (STATE Pattern
D3, the "(persona × KB) epoch" model). Phase 5 adds a third concern — history — but
it lives in a **different place** (items, not instructions), so it composes cleanly:
- A persona edit / KB load re-emits **instructions** only; it does NOT touch the
  history item list. History windowing does NOT touch instructions. They are
  orthogonal — no new clobber risk, by construction.
- **Watch:** when instructions change (persona/KB re-prefill), the history region
  below re-prefills anyway (its prefix moved). That is the existing accepted
  one-turn cost; windowing doesn't make it worse. No action needed beyond not
  *adding* per-turn instruction churn (which Phase 5 must never do — §2 rule).
- If summarization is added, a summary item is just another history item; a persona
  edit re-emitting instructions leaves the summary item in place (good — grounding
  + summary both survive the edit).

---

## 6. Design options & recommendation

### 6.1 Window mechanism — recommended: `truncate(max_items=N)` via a subclassed Agent

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Subclass `Agent`, override `on_user_turn_completed`, `truncate` + `update_chat_ctx`** | Canonical LiveKit; per-turn hook is the documented place; preserves instructions automatically; testable | Introduces the first `Agent` subclass (small) | **Recommended** — matches docs, minimal surface |
| B. Trim on `conversation_item_added` event from `main.py` | No subclass | Event fires after commit; ordering vs next turn less clear; still needs `current_agent.update_chat_ctx` | Fallback if subclass is awkward |
| C. Module-level mutation of chat_ctx | — | Hidden global, breaks testability (same anti-pattern flagged for KB_SLOT in 04-RESEARCH §8) | Avoid |

Recommend **A**. Keep the subclass thin (SRP, ≤40-line methods): a single
`HistoryWindowAgent(Agent)` whose `on_user_turn_completed` does the cheap
window-trim synchronously and (optionally) fires the async summary task. The
windowing **decision logic** (does the context exceed budget? how many items to
keep?) should be a **pure function** in a new `agent/history.py` (mirrors
`persona.py` / `parse.py` structure already in `ARCHITECTURE.md`'s suggested layout:
`agent/history.py # sliding-window / summarization`) so it has a `_self_check()`
and is sandbox-verifiable WITHOUT livekit.

### 6.2 Window size — recommended starting point

- **Item-count window** keyed to the ~5000-token history budget. Spoken turns are
  short; a conservative **`HISTORY_MAX_ITEMS`** (e.g. last ~16–20 message items =
  ~8–10 exchanges) keeps well under 5000 tok. Make it a named constant; document
  the coupling to `OLLAMA_CONTEXT_LENGTH=8192` and `BRIEF_TOKEN_BUDGET=1500`.
- Optionally **also** gate on an estimated token budget (defensive against unusually
  long single turns) using the KB-guard char/token heuristic. MVP can ship
  item-count-only; note token-gate as a refinement.
- **[VM-INTROSPECT]** tune the exact N against real spoken-turn token sizes + the
  measured flat-TTFT curve; pin the constant to the verified value.

### 6.3 Summarization — recommended: optional second slice (window-only is the MVP floor)

- **MVP floor:** sliding window alone satisfies SESS-05 Criteria 1 ("and/or") + 2 +
  3 and is fully deterministic. Ship this first; it is the verifiable core.
- **Stretch:** async summary fold-in (canonical pattern §2) when items overflow,
  re-summarizing only on overflow (not per turn) to bound cache churn (§3.2). Tag
  summary items `extra["is_summary"]=True`. Place the summary as the **first**
  history item (after instructions). This recovers long-range context the window
  drops — but is NOT required for SESS-05's "sliding-window **and/or** summarized."

### 6.4 What NOT to do (anti-patterns for this phase)

- ❌ Don't fold history into `instructions` / `render_prompt` — that busts the KB
  cache every turn (Pitfall 7; the whole reason history is a separate item list).
- ❌ Don't rewrite middle history items each turn — maximizes re-prefill.
- ❌ Don't re-summarize every turn — churns the history-region cache (§3.2).
- ❌ Don't run the summarizer LLM call synchronously on the turn path (§3.5).
- ❌ Don't put timestamps/turn-counters in any history item (Anti-Pattern 3).
- ❌ Don't change the `metrics.py` per-turn record key set (Phase 3 contract).

---

## 7. Plan-by-plan notes (vertical slice)

### 7.1 Plan 05-01 — sliding window (+ optional async summarization) behind the frozen prefix

**Pure / sandbox-testable core (the client-verifiable acceptance):**
- New `agent/history.py` with pure decision logic: `should_trim(item_count|tokens) ->
  bool`, `window_target() -> int`, named `HISTORY_MAX_ITEMS` constant (+ optional
  token estimate reusing the KB char/token heuristic). A `_self_check()` mirroring
  `persona.py`/`metrics.py`: assert that for an over-budget item list the target
  keeps the last N, that instructions are conceptually preserved (logic operates on
  items only), and that the function is deterministic. No livekit import.
- Confirm `render_prompt` is untouched and the golden byte-stability test stays
  green (Phase 5 must not alter the frozen prefix — `persona.py:_self_check`).

**Wireup (VM):**
- `HistoryWindowAgent(Agent)` overriding `on_user_turn_completed`: cheap
  `self.chat_ctx.copy().truncate(max_items=HISTORY_MAX_ITEMS)` →
  `await self.update_chat_ctx(...)` to persist the window. Swap the bare
  `Agent(instructions=...)` in `main.py:262` for the subclass (instructions
  unchanged).
- (Optional) async summary fold-in via the GC-guarded `active_tasks` pattern already
  in `main.py`; re-summarize only on overflow; tag `extra["is_summary"]`.

**Acceptance (sandbox):** `history.py` `_self_check` passes; `persona.py` golden
unchanged; `agent` imports cleanly for the pure module.

**Operator gates (VM, defer like 04-03):**
- Long session (30–50 turns) → `llm_ttft_ms` P50/P95 flat (no upward trend),
  tokens-in-context plateaus (Criterion 2).
- Ollama logs show bounded per-turn prompt-eval, no mid-session KB re-prefill
  (Criterion 3 / Pitfall 7+10).
- Confirm window holds across turns and a KB/persona edit mid-session still composes
  (instructions re-emit; history window intact).

### 7.2 Requirement → mechanism map

| Req / Criterion | Mechanism |
|---|---|
| SESS-05 / Crit 1 (windowed and/or summarized) | `ChatContext.truncate(max_items=N)` in `on_user_turn_completed` + `update_chat_ctx`; optional async summary fold-in (§2, §6) |
| Crit 2 (flat TTFT over a long session) | Bounded history → bounded prefill; verified via existing `metrics.py` `llm_ttft_ms` rolling P50/P95 over many turns (§4) |
| Crit 3 (behind frozen prefix, no cache bust) | History is `ChatContext` items, not `instructions`; `truncate` preserves instructions; Phase 5 never calls `update_instructions` (§1.2, §2 rule) |

---

## 8. Sandbox limits & [VM-INTROSPECT] checklist (defer like 02/03/04)

```
# History API signatures on the installed build
python -c "import inspect; from livekit.agents import Agent; print([m for m in dir(Agent) if 'turn' in m or 'chat_ctx' in m])"
python -c "import inspect; from livekit.agents import ChatContext; print(inspect.signature(ChatContext.truncate)); print(inspect.signature(ChatContext.copy))"
python -c "from livekit.agents import ChatContext; c=ChatContext(); print([a for a in dir(c) if 'item' in a or 'message' in a])"
# on_user_turn_completed override fires per turn; update_chat_ctx persists the window
# Flat-TTFT-over-time: 30–50-turn session; llm_ttft_ms P50/P95 flat; tokens plateau;
#   ollama prompt-eval bounded, no mid-session KB re-prefill (the Crit-2/3 proof)
# Tune HISTORY_MAX_ITEMS against real spoken-turn token sizes vs the measured curve
# (optional) summarizer call runs off-hot-path; re-summarize only on window overflow
```
**Pure, sandbox-verifiable now:** the windowing decision logic in `agent/history.py`
(`_self_check`) and the unchanged `render_prompt` byte-stability golden. Make these
the client-verifiable acceptance criteria; the LiveKit hook round-trip,
window-holds-across-turns, summarization quality, and the flat-TTFT-over-time proof
are operator/VM gates.

---

## Sources
- Repo: `agent/main.py` (Agent construction, `update_instructions` re-prefills,
  `ingest_kb` GC-guarded background-task pattern), `agent/persona.py`
  (`render_prompt`/`KB_SLOT` frozen prefix, golden `_self_check`), `agent/metrics.py`
  (per-turn `llm_ttft_ms` keyed by `speech_id` + rolling P50/P95; asserted key
  shape), `ollama/Modelfile` + `docker-compose.yml` (`OLLAMA_CONTEXT_LENGTH=8192`,
  `OLLAMA_NUM_PARALLEL=1`, ~5000-tok history budget, coupled constants) — HIGH
- `.planning/research/ARCHITECTURE.md` Pattern 5 (sliding-window/summarized history
  *after* the stable prefix), Anti-Patterns 3 + 6, `agent/history.py` in the
  suggested layout — HIGH
- `.planning/research/PITFALLS.md` Pitfalls 7 (prefix-cache byte-identity), 10
  (history TTFT creep + `num_ctx` eviction), 3 (no prior thoughts in history) — HIGH
- `.planning/research/STACK.md` (Gemma-4 thinking off + sliding-window history;
  `OLLAMA_KV_CACHE_TYPE=q8_0`/flash-attn) — HIGH
- `.planning/STATE.md` (frozen-prefix layout decision; Pattern D3 persona×KB epoch
  composition; `num_ctx` coupled-constants decision) — HIGH
- LiveKit Agents docs (current 1.5/1.6) — *Chat context* (`truncate(max_items=)`
  preserves system instructions; `copy(exclude_instructions=...)`),
  *Nodes / on_user_turn_completed* (per-turn hook; temporary vs `update_chat_ctx`
  persist), *Agents handoffs* (canonical `summarize_session` pattern, `is_summary`
  tagging), *Events* (`conversation_item_added`) — HIGH (shape), MEDIUM (exact
  pinned signatures → [VM-INTROSPECT])
- Phase 4 `04-RESEARCH.md` (byte-stability discipline, GC-guarded background task,
  pure-module `_self_check` convention) — HIGH

---
*Phase 5 research — History Management. Grounded in repo code + installed-version
docs + Phase 2–4 source-verified state. Keystone: bound the history ITEM list
(not the instruction prefix) so TTFT stays flat without busting the KB cache
(Pitfalls 7 + 10). Window-only is the verifiable MVP floor; async summarization is
the optional behind-the-window stretch.*
