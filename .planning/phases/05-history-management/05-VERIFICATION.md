---
phase: 05-history-management
status: passed
verified: 2026-06-26
verifier: gsd-verifier
sandbox_layer: passed
operator_gates: deferred
requirement_ids: [SESS-05]
plans_verified: [05-01]
---

# Phase 05 — History Management: VERIFICATION

**Phase goal:** Keep long sessions fast by managing conversation history — sliding-window
plus async summarization placed *behind* the frozen KB/persona prefix — so growing history
never inflates per-turn TTFT and never busts the KB prefix cache.

**Verdict: PASS.** The sandbox-verifiable core is fully present and green. The keystone
live-stack proofs (flat-TTFT-over-time, Ollama cache-hold, installed-livekit signatures)
are legitimately DEFERRED operator/VM gates captured in `05-HISTORY-VERIFY.md` — the same
`[VM-INTROSPECT]` pattern used in Phases 1–4. They are NOT marked failed.

---

## Requirement traceability (PLAN frontmatter ↔ REQUIREMENTS.md)

| Req ID | PLAN declares | REQUIREMENTS.md | Phase mapping | Status |
|--------|---------------|-----------------|---------------|--------|
| SESS-05 | `requirements: [SESS-05]` (05-01) | line 56 `[x]`, line 149 Phase 5 Complete | Phase 5 | ✅ accounted for |

Every requirement ID in the PLAN frontmatter (`[SESS-05]`) is accounted for in
REQUIREMENTS.md and maps back to Phase 5. No orphan IDs. Single-plan phase; no other
plan frontmatter to reconcile.

---

## must_haves — checked against the actual codebase

### Truths

| # | Truth | Evidence | Verdict |
|---|-------|----------|---------|
| 1 | SESS-05: history sliding-windowed each turn via `truncate(max_items=HISTORY_MAX_ITEMS)` + `update_chat_ctx` in `HistoryWindowAgent(Agent)` overriding `on_user_turn_completed` | `agent/main.py:246` class, `:260` hook, `:261-263` should_trim→copy().truncate→update_chat_ctx | ✅ PASS |
| 2 | Criterion 2 (flat TTFT): bounded history → bounded prefill; proven by `llm_ttft_ms` on the TIME axis over 30–50 turns | Wiring present (bounded window); the live proof is Proof A in `05-HISTORY-VERIFY.md` | ✅ wired / ⏸ operator |
| 3 | Criterion 3 (behind frozen prefix): history is `ChatContext` items not `instructions`; subclass NEVER calls `update_instructions` | hook body `:261-263` mutates items only; `grep update_instructions` shows only `:312`+`:383` (sanctioned), none in subclass | ✅ PASS |
| 4 | Windowing DECISION is a pure, livekit-free, `_self_check`-tested fn in `agent/history.py`; subclass owns the EFFECT | `python3 agent/history.py` → `history _self_check OK` (exit 0); no livekit import | ✅ PASS |
| 5 | Composes with Phase-3/4 persona-edit + KB-load re-prefills (items vs instructions orthogonal) | `handle_persona_update:312` + `ingest_kb:383` untouched; subclass touches items only | ✅ PASS (structural) |

### Prohibitions

| # | Prohibition | Evidence | Verdict |
|---|-------------|----------|---------|
| 1 | No `update_instructions` from the windowing path | subclass `:260-263` has none; only `:312` (handle_persona_update) + `:383` (ingest_kb) | ✅ HELD |
| 2 | No folding of history into `instructions`/`render_prompt` | hook operates on `self.chat_ctx.items` only; `render_prompt` arg byte-identical at `:283` | ✅ HELD |
| 3 | No rewriting middle items — trim from FRONT only | `truncate(max_items=...)` keeps last N (drops oldest) | ✅ HELD |
| 4 | No change to `agent/metrics.py` / `agent/persona.py` render_prompt+golden | `git diff --stat agent/persona.py agent/metrics.py` → empty | ✅ HELD |
| 5 | No async summarization, no token-budget gate, no timestamps/turn-counters | `grep summariz\|estimate_tokens\|should_trim_tokens agent/history.py` → empty | ✅ HELD |
| 6 | No OPERATOR/`[VM-INTROSPECT]` step marked passed in-plan | `05-HISTORY-VERIFY.md` status `pending-operator`; results tables blank | ✅ HELD |

---

## Sandbox executable checks (re-run during verification)

| Command | Expected | Observed |
|---------|----------|----------|
| `python3 agent/history.py` | exit 0, `history _self_check OK` | ✅ exit 0, printed |
| `python3 -m py_compile agent/main.py` | exit 0 | ✅ exit 0 |
| `python3 agent/persona.py` | exit 0, `persona _self_check OK` | ✅ exit 0, printed |
| `grep -n "^import history" agent/main.py` | present | ✅ `:28` |
| `grep class HistoryWindowAgent / on_user_turn_completed` | both present | ✅ `:246`, `:260` |
| `grep HistoryWindowAgent(instructions=render_prompt` | present (byte-identical arg) | ✅ `:283` |
| `grep -ni "import livekit\|from livekit" agent/history.py` | empty | ✅ empty |
| `git diff --stat agent/persona.py agent/metrics.py` | empty | ✅ empty |

`history.py` defines all four required symbols: `HISTORY_MAX_ITEMS=20` (`:28`),
`should_trim` (`:31`), `window_target` (`:36`), `_self_check` (`:41`), with the
coupled-constant comment documenting `8192` / `BRIEF_TOKEN_BUDGET` / `~5000`-tok budget
(`:22-27`).

---

## Deferred operator gates (legitimate — NOT failures)

`05-HISTORY-VERIFY.md` exists (`status: pending-operator`) with:
- **§0** build/deploy-before-verify reminder (`docker compose build` / `up -d`).
- **§1 [VM-INTROSPECT]** three history-API signature-check commands + fallback option B.
- **Proof A** flat-TTFT-over-time (30–50 turns, turn-5/20/35/50 checkpoints, no-upward-trend assertion, rolling P50/P95 table).
- **Proof B** Ollama bounded-prompt-eval / no-mid-session-KB-re-prefill cache-hold + cache-bust failure signature.
- **Proof C** window-persists-across-turns + composes with persona/KB edits.
- `metrics.py`-read-only + summarization-out-of-MVP-scope notes.

These need Docker/GPU/Ollama/browser/livekit which the sandbox lacks. Deferral is
consistent with the Phase 1 VRAM gate and Phase 2/3/4 `[VM-INTROSPECT]` precedent.

---

## Scope note (goal vs MVP slice)

The phase goal text mentions "plus async summarization." The PLAN deliberately scopes
summarization OUT as a documented future refinement: SESS-05's "sliding window /
summarization" is an **and/or** requirement (REQUIREMENTS.md:56), satisfied by the
deterministic item-count window alone (YAGNI / CODE_PRINCIPLES §7). This is an explicit,
recorded decision (PLAN §Context, SUMMARY key-decisions), not a gap. Window-only is the
verified MVP floor; tuning `HISTORY_MAX_ITEMS` + summarization are noted VM/future follow-ups.

---

## Conclusion

- **SESS-05 sandbox core: PASS.** All must_have truths wired, all prohibitions held,
  all sandbox commands green, read-only analogs byte-identical.
- **Operator gates: DEFERRED (legitimate).** Captured in `05-HISTORY-VERIFY.md`, correctly
  unmarked. The keystone flat-TTFT-over-time + cache-hold proofs await the VM.
- **Requirement traceability: COMPLETE.** SESS-05 fully accounted for; no orphan IDs.

**Phase 05 goal achievement: VERIFIED for the sandbox-verifiable scope; the live-stack
keystone proof is a properly documented deferred operator gate.**
