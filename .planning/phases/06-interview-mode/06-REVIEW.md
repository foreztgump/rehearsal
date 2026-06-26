# Phase 06 (Interview Mode) — Code Review

**Scope:** commits `097d93d..HEAD` (479 insertions across 4 source files)
**Reviewed files:** `agent/interview.py` (NEW), `agent/main.py` (MODIFIED), `web/app/InterviewPanel.tsx` (NEW), `web/app/VoiceRoom.tsx` (MODIFIED)
**Method:** static review only (sandbox cannot import livekit / run the stack). Build gates already green: `py_compile`, `interview _self_check OK`, `tsc --noEmit`.

**Resolution:** H1 + M1 + M2 all FIXED in commit `13f3416` (`fix(06): validate mode.update before committing holders; route interview KB brief through cite-nudge`). L1–L3 left as documented low-severity notes. Re-verified: `interview/persona/history _self_check OK`, `py_compile agent/main.py`, web `tsc --noEmit` all green; `agent/metrics.py` untouched.

---

## Summary by severity

| Severity | Count | Findings | Status |
|----------|-------|----------|--------|
| Critical | 0 | — | — |
| High     | 1 | H1 — `handle_mode_update` mutates shared holders before a fallible render → unknown `role_key` poisons state and cascades into persona/KB handlers | ✓ Fixed (`13f3416`) |
| Medium   | 2 | M1 — KB cite-nudge bypassed in Interview-mode composition (grounding asymmetry vs Learn); M2 — unknown `mode` silently treated as Learn while the holder keeps the bogus value (no validation/log) | ✓ Fixed (`13f3416`) |
| Low      | 3 | L1 — dead `CONVERSATIONAL_ENDPOINTING_*` constants; L2 — Learn mode now runs at the interview endpointing floor (accepted tradeoff, undocumented UX cost); L3 — RPC handlers raise without logging, malformed payloads surface only as an opaque client-side error |

No secrets, no hardcoded second model tag, no new `openai.LLM`/`with_ollama` construction, no thinking-on regression. `generate_reply` correctly reuses the single session LLM. Byte-stability discipline in `interview.py` is clean. `compose_instructions` is confirmed **not** called per turn (only in the three RPC/ingest closures), so the flat-TTFT invariant holds.

---

## High

### H1 — Holders mutated before a fallible render; unknown `role_key` corrupts shared state and cascades (`agent/main.py:404-414`)

```python
async def handle_mode_update(data):
    snapshot = json.loads(data.payload)
    current_mode[0] = snapshot["mode"]        # committed BEFORE render
    current_role[0] = snapshot["role_key"]    # committed BEFORE render
    await agent.update_instructions(compose_instructions())  # can raise
    ...
```

`compose_instructions()` → `interview.render_interview_prompt(current_role[0])` → `ROLES[role_key]`, which raises **`KeyError`** for any `role_key` not in the three known keys. Because `current_mode[0]`/`current_role[0]` are **written before** the render is attempted, a failing call leaves the shared holders in a poisoned state: `current_mode[0] == "interview"` with an invalid `current_role[0]`.

The damage is not local to this RPC. `handle_persona_update` (`main.py:386`) and `ingest_kb` (`main.py:486`) both route through the **same** `compose_instructions()`. After the holders are poisoned, every subsequent persona edit or KB load also throws `KeyError` for the rest of the session — a silent, session-long regression of two unrelated features triggered by one malformed mode RPC.

`mode.update` is an untrusted network boundary (any room participant can call `performRpc` with an arbitrary payload); the shipped `InterviewPanel` only offers the three valid roles, so this is not reachable from the official UI, but the review brief explicitly calls out the `KeyError on ROLES[role_key]` case and the RPC is the trust boundary.

**Recommendation:** validate then commit — render first into a local, and only assign the holders after a successful render. E.g.:

```python
async def handle_mode_update(data):
    snapshot = json.loads(data.payload)
    mode = snapshot["mode"]
    role_key = snapshot["role_key"]
    if role_key not in interview.ROLES:
        return "error"                      # or raise a typed RpcError
    instructions = (
        f"{interview.render_interview_prompt(role_key)} {session_kb.brief}".rstrip()
        if mode == interview.MODE_INTERVIEW
        else render_prompt(current_persona[0], session_kb.brief)
    )
    current_mode[0], current_role[0] = mode, role_key   # commit only on success
    await agent.update_instructions(instructions)
    ...
```

Note the same "mutate-before-fallible-call" shape exists in `handle_persona_update` (`Persona(**snapshot)` is built before assignment, so a bad snapshot raises *before* mutation — that one is fine). The mode handler differs precisely because it assigns first and renders second.

---

## Medium

### M1 — KB cite-nudge bypassed in Interview-mode composition (`agent/main.py:358-362`)

```python
if current_mode[0] == interview.MODE_INTERVIEW:
    interview_block = interview.render_interview_prompt(current_role[0])
    return f"{interview_block} {session_kb.brief}" if session_kb.brief else interview_block
return render_prompt(current_persona[0], session_kb.brief)
```

The Learn path (`render_prompt`, `persona.py:134`) prepends the frozen `KB_CITE_NUDGE` before the brief — added in 04-04 (GAP-2b) specifically because the Socratic persona *deflected* instead of citing supplied facts. The Interview path appends `session_kb.brief` **raw**, with no cite-nudge. If a learner loads KB material and then interviews, the agent gets the brief without the instruction to cite exact terms/identifiers from it — the exact failure mode the nudge was introduced to fix, now silently reintroduced for Interview mode.

This may be intentional (interview questions are role-driven, not KB-driven), but it is an undocumented asymmetry between the two composition paths. **Recommendation:** either reuse `persona.KB_CITE_NUDGE` in the interview branch for consistency, or add a one-line comment stating the nudge is deliberately omitted in Interview mode and why.

### M2 — Unknown `mode` silently degrades to Learn while the holder keeps the bogus value (`agent/main.py:358`, `406`)

`compose_instructions` only tests `current_mode[0] == interview.MODE_INTERVIEW`; any other string (including a typo or a malicious value) falls through to the Learn branch. That is a safe *render* outcome, but `current_mode[0]` still stores the bogus value, and the handler returns `"applied"` as if the mode were honored. There is no validation against `{MODE_LEARN, MODE_INTERVIEW}` and no log line. A client sending `{"mode": "Interview"}` (capitalized) gets a green "applied" ack but the agent stays in Learn — a confusing silent no-op. **Recommendation:** validate `mode` against the two known constants and return `"error"` (or normalize) on anything else.

---

## Low

### L1 — Dead `CONVERSATIONAL_ENDPOINTING_*` constants (`agent/main.py:72-73`)

`CONVERSATIONAL_ENDPOINTING_MIN_DELAY` / `_MAX_DELAY` are defined but never referenced — `build_session` uses `ENDPOINTING_MIN_DELAY/MAX_DELAY`, which alias the **interview** floor. They serve only as documentation of the old values. This is fine as intent-capture but is genuinely unused code; consider a comment marking them as reference-only, or remove them to avoid implying a runtime switch that does not exist.

### L2 — Learn mode now runs at the interview endpointing floor (`agent/main.py:96-97`, `228-231`)

Mechanism-3 fallback ships the single interview profile (`min_delay 0.7 / max_delay 5.0`) for **all** turns, including Learn/Converse, which previously ran at `0.3 / 3.0`. This is per the 06-02 plan and is well-commented, but the user-visible cost — slower conversational turn commit in Learn mode — is not surfaced in the `[VM-INTROSPECT]` block as a UX tradeoff (only as a metrics caveat). Worth a one-line note so the operator knows Learn responsiveness regressed by design until the VM probe selects mechanism 1/2.

### L3 — RPC handlers raise without logging on malformed payloads (`agent/main.py:380-388`, `404-414`)

`json.loads(data.payload)` and the `snapshot[...]` key reads can raise `JSONDecodeError`/`KeyError`. The livekit RPC layer converts a raising handler into a client-side rejection, which `InterviewPanel.apply()`'s `catch` turns into the generic `"error — could not apply"` label — so a malformed payload is observable to the user but produces no agent-side log for diagnosis. This mirrors the existing `handle_persona_update` style (consistent), but combined with H1 the lack of a log makes the cascading-corruption case hard to diagnose. Consider wrapping the parse in a `try/except` that logs and returns `"error"`.

---

## Verified-correct (no action)

- **No per-turn re-render:** `compose_instructions` is invoked only in `handle_persona_update`, `handle_mode_update`, and `ingest_kb` — never in `on_user_turn_completed`. Flat-TTFT keystone intact (`main.py:350`, `386`, `408`, `486`).
- **No second model tag / no new LLM:** `generate_reply` and `update_instructions` run through the existing session LLM; no `with_ollama`/`openai.LLM` added; `THINKING_ENABLED=False` untouched.
- **Byte-stability in `interview.py`:** enum→fixed-string `ROLES`, fixed-tuple-order join, no interpolation of runtime data into frozen constants; golden `EXPECTED_DEFAULT_INTERVIEW` + `_self_check` guard drift. The brief appended in `compose_instructions` is the session-frozen opaque string (same treatment as the persona path), safe for the prefix cache.
- **`InterviewPanel.tsx`:** null-agent guard present (`agentIdentity` fallback + early error return, `:85-90`); `performRpc` wrapped in `try/catch` (`:91-101`); payload keys `{mode, role_key}` match the agent parser exactly; no `useParticipantAttributes` state-push (RPC-ack-only honored); role `<select>` correctly disabled outside Interview mode.
- **`VoiceRoom.tsx`:** `<InterviewPanel />` rendered inside `<LiveKitRoom>` alongside the other panels — room context available.
- **`metrics.py`:** unchanged (read-only honored).
- **Scope discipline:** no `InterviewState`/`next_directive` Layer-2, no numeric scoring, no multi-agent handoff, no `turn_detection="manual"`, VAD `activation_threshold=0.65` and `MultilingualModel()` unchanged.

---

## Top recommendation

Fix **H1** before the VM gate: reorder `handle_mode_update` to validate `role_key`/`mode` and render *before* committing the holders, so an unexpected payload cannot poison the shared `current_mode`/`current_role` state and silently break the persona and KB hot-swap paths for the rest of the session. M1/M2 are quick consistency fixes worth folding into the same change.

**Report written to:** `.planning/phases/06-interview-mode/06-REVIEW.md`
