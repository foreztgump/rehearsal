---
status: pending-operator
phase: 05-history-management
plan: 05-01
requirement_ids: [SESS-05]
verifies: [SESS-05, "Criterion 2 (flat TTFT over a long session)", "Criterion 3 (behind the frozen prefix)"]
harness_note: All proofs below need the live voice loop (Docker + RTX 5090 + Ollama + browser + LAN device). The execution sandbox has no Docker/GPU/Ollama/browser and cannot import livekit, so these are deferred operator/VM gates, mirroring the Phase-1 VRAM gate and the Phase-2/3/4 [VM-INTROSPECT] deferrals. NONE are marked passed by the executor.
---

# Phase 05 — History Management: OPERATOR VERIFICATION (the keystone flat-TTFT-over-time proof)

**Status:** PENDING OPERATOR — run on the Proxmox VM (Docker daemon + RTX 5090 +
Ollama + browser + LAN device). The sandbox has **no** Docker/GPU/Ollama/browser and
**cannot import livekit**, so every proof below is a deferred operator gate. **None are
marked passed by the executor** — the operator fills the results tables with measured
numbers.

**Owns:** **SESS-05** (conversation history is sliding-windowed as the session grows),
**Criterion 2** (per-turn TTFT stays flat over a long session — never climbs with turn
count), and **Criterion 3** (history sits behind the frozen persona+KB prefix and does
not invalidate the prefix cache).

**What ships sandbox-verified (already green, not in this doc):**
- `python3 agent/history.py` → `history _self_check OK` (the pure windowing decision).
- `python3 agent/persona.py` → `persona _self_check OK` (the frozen-prefix golden is
  unbroken — `render_prompt` untouched).
- `python3 -m py_compile agent/main.py` → exit 0 (the `HistoryWindowAgent` wireup is
  syntactically valid without importing livekit).

---

## `agent/metrics.py` is READ-ONLY for these proofs

The per-turn JSON line shape is the **frozen Phase-3 contract** — keys
`eou_ms / stt_ms / llm_ttft_ms / tts_ttfb_ms / e2e_ms / over_budget` (see
`agent/metrics.py` `emit_turn`, asserted at `metrics.py:284`). Phase 5 only **READS**
that emitted line — specifically `llm_ttft_ms` on the **TIME axis** (turn-N vs
turn-N+20) — to prove the flat-TTFT-over-time invariant. It does **not** modify the
emitter. `git diff --stat agent/metrics.py` must show **no change**.

**Out of MVP scope (window-only is the verified floor):** async summarization /
condensation is NOT built in this slice. SESS-05's "sliding-window **and/or**
summarized" is satisfied by the deterministic item-count window alone. Tuning
`HISTORY_MAX_ITEMS` against the measured TTFT curve (below) is the VM follow-up.

---

## 0. Build / deploy BEFORE verifying (stale-deploy guard)

The stack runs from **baked images** — a code edit is NOT live until the image is
rebuilt. This bit the Phase-3 UAT (stale deploy) and is a standing STATE.md decision.
Always rebuild + restart before live verification:

```bash
# from the repo root on the VM
set -a && . ./.env && set +a
docker compose build agent web
docker compose up -d
docker compose ps          # all services Up
```

---

## 1. [VM-INTROSPECT] — history-API signature checks (does the installed build match the wired code?)

Confirm the LiveKit build installed in the agent image exposes the exact members
`HistoryWindowAgent` relies on (`on_user_turn_completed`, `ChatContext.truncate`,
`ChatContext.copy`, `Agent.update_chat_ctx`, `chat_ctx.items`). Run inside the agent
container so the introspection targets the SAME installed version the worker runs:

```bash
# 1a — Agent turn / chat_ctx members (expect on_user_turn_completed + chat_ctx + update_chat_ctx)
docker compose exec agent python -c "from livekit.agents import Agent; print([m for m in dir(Agent) if 'turn' in m or 'chat_ctx' in m])"

# 1b — ChatContext.truncate + ChatContext.copy signatures (expect truncate(max_items=...), copy(...))
docker compose exec agent python -c "import inspect; from livekit.agents import ChatContext; print(inspect.signature(ChatContext.truncate)); print(inspect.signature(ChatContext.copy))"

# 1c — ChatContext item/message/trunc attributes (expect an `items` collection)
docker compose exec agent python -c "from livekit.agents import ChatContext; c=ChatContext(); print([a for a in dir(c) if 'item' in a or 'message' in a or 'trunc' in a])"
```

**Confirm:** `on_user_turn_completed` is an overridable per-turn node; `truncate`
accepts `max_items=`; `copy` exists (optionally `copy(exclude_instructions=...)`);
`chat_ctx.items` is the live item list; `update_chat_ctx` persists a replacement ctx.

**If a signature differs (fallback — RESEARCH §6.1 option B):** instead of the
subclass hook, trim on the `conversation_item_added` event from `main.py` via
`session.current_agent.update_chat_ctx(session.current_agent.chat_ctx.copy().truncate(max_items=history.window_target()))`.
Note the event fires AFTER commit, so the trim lands one turn later than the
`on_user_turn_completed` path — the subclass is preferred when its signature matches.

**Results capture:**

| Check | Command | Expected | Observed |
|-------|---------|----------|----------|
| 1a Agent members | `dir(Agent)` turn/chat_ctx | `on_user_turn_completed`, `chat_ctx`, `update_chat_ctx` present | ___ |
| 1b truncate/copy sigs | `inspect.signature` | `truncate(max_items=...)`, `copy(...)` | ___ |
| 1c ChatContext items | `dir(ChatContext())` | `items` present | ___ |
| Signatures match wired code? | — | yes | ___ |

---

## Proof A — flat-TTFT-over-time (SESS-05 / Criterion 2)

**Goal:** as the session grows long enough to overflow `HISTORY_MAX_ITEMS=20`, per-turn
`llm_ttft_ms` does **NOT climb with turn count** — it plateaus. Without windowing,
append-only history makes TTFT creep turn-over-turn and then CLIFF when the context
wraps `num_ctx` (the whole KB/persona prefix evicts and re-prefills). With windowing it
stays flat.

**Steps:**

1. **Start a session.** Open `https://<vm-lan-ip>/` on a LAN device and start a session.
   *Optionally* upload a KB doc first (to ALSO exercise Criterion 3 — see Proof B);
   wait for the indicator to reach `ready (1 docs)`.
2. **Drive a LONG session — 30–50 voice turns.** Speak 30–50 short turns, enough to push
   the history item list well past `HISTORY_MAX_ITEMS=20` (the window trims from turn ~20
   onward). Keep turns short and conversational (representative spoken length).
3. **Capture the per-turn metric lines** from the agent (the frozen JSON record):

   ```bash
   docker compose logs agent | grep llm_ttft_ms
   ```

   Also capture the rolling P50/P95 summary lines (emitted every
   `SUMMARY_EVERY_TURNS=10` turns by `metrics.py`):

   ```bash
   docker compose logs agent | grep rolling_summary
   ```

4. **Record `llm_ttft_ms` at turn checkpoints** — turn-5, turn-20, turn-35, turn-50 — in
   the table below.
5. **ASSERT (Criterion 2):** `llm_ttft_ms` does NOT trend upward with turn count —
   **turn-50 ≈ turn-20** (and turn-35 ≈ turn-20), no creep, no cliff. The rolling P50/P95
   over the last window is flat (later windows ≈ earlier windows). A clear upward trend or
   a sudden cliff = FAIL (investigate whether the window is actually trimming — re-check
   Proof C and the `should_trim`/`update_chat_ctx` path).

**Results capture:**

| Turn checkpoint | `llm_ttft_ms` | `over_budget` |
|-----------------|---------------|---------------|
| turn-5 (pre-window)   | ___ | ___ |
| turn-20 (at window)   | ___ | ___ |
| turn-35 (post-trim)   | ___ | ___ |
| turn-50 (post-trim)   | ___ | ___ |

| Rolling summary | window | `llm_ttft` p50 | `llm_ttft` p95 |
|-----------------|--------|----------------|----------------|
| turns 1–10  | 100 | ___ | ___ |
| turns 21–30 | 100 | ___ | ___ |
| turns 41–50 | 100 | ___ | ___ |

- turn-50 ≈ turn-20 (no upward trend with turn count)? **[ ] yes**
- rolling P50/P95 flat across early vs late windows? **[ ] yes**
- **Criterion 2 verdict:** ___

---

## Proof B — prefix-cache holds, no mid-session KB re-prefill (Criterion 3 / Pitfall 7+10)

**Goal:** windowing the item list never busts the cached persona+KB prefix. Per-turn
Ollama prompt-eval ("new tokens") stays **BOUNDED** (only the changed history tail is
evaluated); there is **NO full KB re-prefill mid-session** (a full re-eval of the brief =
the `num_ctx`-eviction / cache-bust signature = FAIL).

**Steps:**

1. Run Proof A **with a KB loaded** (step 1, upload option).
2. Inspect Ollama prompt-eval counts across the long session:

   ```bash
   docker compose logs ollama | grep -iE 'prompt eval|prompt_eval|n_past|cache'
   ```

3. **Read the prompt-eval token count per request** as the session grows past turn-20:
   - Each post-window turn evaluates only a **SMALL** bounded count (the new turn + the
     shifted history tail) — the persona+KB prefix is reused from cache.
4. **Cache-BUST signature (FAIL):** if any mid-session turn's prompt-eval count jumps to
   ≈ the brief size again (a full re-eval of the persona+KB prefix), the frozen prefix was
   invalidated. Investigate: the windowing path must NEVER call `update_instructions`
   (verify `grep -n update_instructions agent/main.py` shows only `handle_persona_update`
   and `ingest_kb`, none inside `HistoryWindowAgent`); `truncate` must preserve system
   instructions on the installed build (Proof 1 / [VM-INTROSPECT]).

**Results capture:**

| Turn | prompt-eval (new tokens) | bounded? | full KB re-prefill? |
|------|--------------------------|----------|---------------------|
| turn-20 | ___ | ___ | ___ |
| turn-35 | ___ | ___ | ___ |
| turn-50 | ___ | ___ | ___ |

- per-turn prompt-eval stays bounded across the long session? **[ ] yes**
- NO full KB re-prefill mid-session (no cache-bust)? **[ ] yes**
- **Criterion 3 verdict:** ___

---

## Proof C — window holds across turns + composes with persona/KB edits (Pattern E)

**Goal:** the trimmed window PERSISTS across turns (item count plateaus at
~`HISTORY_MAX_ITEMS`, it does not grow unbounded), and a persona edit + a KB load
MID-session still apply with the window intact (history items vs the `instructions`
prefix are orthogonal — neither clobbers the other).

**Steps:**

1. **Window persists.** During the Proof-A long session, observe the live item count
   (e.g. add a one-off debug log of `len(self.chat_ctx.items)`, or infer from the bounded
   prompt-eval in Proof B). Confirm it **plateaus at ~`HISTORY_MAX_ITEMS=20`** from
   turn ~20 onward rather than climbing — proving `update_chat_ctx` persisted the trim
   across turns (a temporary `turn_ctx` edit would NOT persist; the count would keep
   growing).
2. **Persona edit mid-session.** Around turn-25, change the persona from the browser side
   panel (`persona.update` RPC). Confirm the new persona instructions re-emit (the one
   sanctioned re-prefill turn shows elevated `llm_ttft_ms` / `over_budget:["llm_ttft"]`),
   and the history window is still ~20 items afterward.
3. **KB load mid-session.** Around turn-35, upload a KB doc. Confirm the brief injects
   (`ready (n docs)`), the grounding applies on the next turn, and the window is still
   intact and plateaued.

**Results capture:**

| Observation | Expected | Observed |
|-------------|----------|----------|
| peak history item count | plateaus ~20 (not unbounded) | ___ |
| window persists across turns? | yes (count flat, not growing) | ___ |
| persona edit @ ~turn-25 applies, window intact? | yes | ___ |
| KB load @ ~turn-35 grounds, window intact? | yes | ___ |

- window holds across turns (count plateaus at ~`HISTORY_MAX_ITEMS`)? **[ ] yes**
- persona edit + KB load mid-session compose with the window? **[ ] yes**
- **Proof C verdict:** ___

---

## Overall SESS-05 sign-off

| Proof | What it proves | Verdict |
|-------|----------------|---------|
| 1 ([VM-INTROSPECT]) | installed history-API signatures match the wired `HistoryWindowAgent` code | ___ |
| A | flat-TTFT-over-time — `llm_ttft_ms` does not climb with turn count (turn-50 ≈ turn-20) — **Criterion 2** | ___ |
| B | prefix-cache holds — bounded per-turn prompt-eval, no mid-session KB re-prefill — **Criterion 3** | ___ |
| C | window persists across turns + composes with persona/KB edits — **SESS-05 / Pattern E** | ___ |

**Operator:** ___  **Date:** ___  **VM/GPU:** Proxmox + RTX 5090

**Residual notes:** async summarization is OUT of this MVP slice (window-only is the
verified floor). The VM follow-up is tuning `HISTORY_MAX_ITEMS` against the measured
spoken-turn token sizes + the flat-TTFT curve from Proof A, then pinning the value.
