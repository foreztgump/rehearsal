# Phase 03 (Persona Layer) — Code Review (backfill)

**Scope:** Phase-03 source introduced/changed in `622e35a^..e3c8659` (451 insertions across 4 files), reviewed at current HEAD `fb4182c` (files since extended by Phases 4/6 — findings scoped to the Phase-03 persona logic).
**Reviewed files:** `agent/persona.py` (NEW, 242 lines now), `agent/main.py` (persona render + `handle_persona_update` hot-swap), `web/app/PersonaPanel.tsx` (NEW), `web/app/VoiceRoom.tsx` (mount).
**Method:** static review only (sandbox cannot import livekit / run Docker/GPU). Build gates green: `python3 agent/persona.py` → `persona _self_check OK`; `py_compile`; web `tsc --noEmit` (per SUMMARYs). The poisoning hypothesis below was reproduced directly against `agent/persona.py` in-sandbox.
**Context:** this is the backfill review the config disabled during execution. The brief flags the `persona.update` RPC as the SAME untrusted-boundary pattern that produced the Phase-06 High (holders mutated before a fallible render). That class of bug **is present** in `handle_persona_update` and was **not** caught by the Phase-06 fix — see H1.

**Resolution (backfill fixes):** H1 FIXED (folding in M1 + L1) in `agent/main.py` `handle_persona_update`: the handler now validates the knob VALUES (`difficulty`/`verbosity`/`correction` against the persona tables) and `voice_id` (against `VOICE_IDS`), wraps the parse in `try/except (JSONDecodeError, TypeError)` with a `logger.warning`, and commits `current_persona[0]` only AFTER validation — so a malformed `persona.update` returns `"error"` instead of poisoning the shared persona/KB/mode holder. This is the persona-handler twin of the Phase-06 `mode.update` fix; the live-reproduced `KeyError('Expert')` poisoning path is now closed. L2/L3 (client-side) left as documented findings.

---

## Summary by severity

| Severity | Count | Findings |
|----------|-------|----------|
| Critical | 0 | — |
| High     | 1 | H1 — `handle_persona_update` commits `current_persona[0] = p` BEFORE the fallible render; an unknown `difficulty`/`verbosity`/`correction` VALUE (valid keys) poisons the shared persona holder → every later persona edit / KB load / mode toggle that routes through `compose_instructions` raises `KeyError` for the rest of the session. The Phase-06 review explicitly judged this handler "fine" — that conclusion only covered bad KEYS, not bad VALUES. |
| Medium   | 1 | M1 — no `voice_id` validation in the agent: an arbitrary RPC `voice_id` is passed straight to `session.tts.update_options(voice=...)`. |
| Low      | 3 | L1 — RPC handler raises with no agent-side log on malformed payload (`JSONDecodeError`/`TypeError`); L2 — silent client/agent constant duplication seam (no `persona.get` RPC, drift undetectable); L3 — `PersonaPanel` `catch {}` swallows the RPC error with no detail, and status never returns to `idle`. |

No secrets, no hardcoded model tags, no second `openai.LLM`/`with_ollama`, no thinking-on regression (`THINKING_ENABLED=False` untouched). `persona.py` byte-stability discipline is clean: enum→fixed-string tables, fixed-tuple-order join, no interpolation of runtime data into frozen constants, no volatile data; `display_name` correctly kept OUT of the prefix; `render_persona(p) == render_prompt(p, "")` preserves the golden. `_self_check` golden + knob-permutation byte-stability is sound.

---

## High

### H1 — `current_persona[0]` poisoned before the render succeeds; unknown knob VALUE cascades into persona/KB/mode handlers (`agent/main.py:389-397`)

```python
async def handle_persona_update(data):
    snapshot = json.loads(data.payload)                     # 390
    p = Persona(**snapshot)                                 # 391  keys validated, VALUES are not
    current_persona[0] = p                                  # 392  COMMITTED before render
    await agent.update_instructions(compose_instructions()) # 395  fallible: DIFFICULTY[p.difficulty] -> KeyError
    session.tts.update_options(voice=p.voice_id)            # 396
    return "applied"
```

`Persona(**snapshot)` is a plain `@dataclass` — it raises `TypeError` for **missing or extra keys**, but performs **no value validation**. A payload with the correct six keys but an unknown knob value (e.g. `difficulty="Expert"` capitalized, or any typo) constructs a `Persona` without complaint, then `current_persona[0] = p` (line 392) commits it to the shared holder **before** anything renders. The render at line 395 routes `compose_instructions()` → `render_prompt(current_persona[0], …)` → `DIFFICULTY[p.difficulty]` (`persona.py:137-139`), which raises **`KeyError`** on the bad value.

Reproduced in-sandbox against `agent/persona.py`:

```
Persona constructed OK with difficulty=Expert (no value validation): Expert
render_persona raised KeyError: 'Expert'
```

The damage is not local. `current_persona[0]` is the shared `(persona × KB × mode)` holder read by **three** closures — `handle_persona_update`, `handle_mode_update`, and `ingest_kb` — all of which call `compose_instructions()` → `render_prompt(current_persona[0], …)`. Once poisoned with an invalid knob value, **every** subsequent persona edit, KB upload, and mode toggle throws `KeyError` for the rest of the session: a one-shot malformed RPC silently wedges three unrelated features.

This is the exact analog of Phase-06 H1 (`handle_mode_update`). Notably the Phase-06 review (`06-REVIEW.md:62`) explicitly cleared this handler — *"`Persona(**snapshot)` is built before assignment, so a bad snapshot raises before mutation — that one is fine."* That is only true for bad **keys** (TypeError at line 391, before the line-392 mutation). It is **false** for bad **values**: the dataclass accepts them, the mutation lands, and the `KeyError` fires later in the render. The poisoning window the Phase-06 fix closed for `mode.update` remains open here.

`persona.update` is an untrusted network boundary — any room participant can `performRpc` an arbitrary payload. The shipped `PersonaPanel` constrains every knob to valid enum values via `<select>`, so this is not reachable from the official UI, but the brief explicitly calls out the `KeyError on DIFFICULTY[p.difficulty]` case and the RPC trust boundary, and the cascading-corruption blast radius makes it High by the same standard applied to Phase-06 H1.

**Recommendation:** validate-then-commit — render into a local first, assign the holder only on success. Mirror the Phase-06 fix shape:

```python
async def handle_persona_update(data):
    snapshot = json.loads(data.payload)
    p = Persona(**snapshot)
    if (p.difficulty not in DIFFICULTY or p.verbosity not in VERBOSITY
            or p.correction not in CORRECTION):
        logger.warning("persona.update rejected: unknown knob value %r", snapshot)
        return "error"
    instructions = render_prompt(p, session_kb.brief)   # render BEFORE mutating
    current_persona[0] = p                               # commit only on success
    await agent.update_instructions(instructions)
    session.tts.update_options(voice=p.voice_id)
    return "applied"
```

(Routing through `compose_instructions()` is also acceptable as long as the holder is assigned only after a successful render.)

---

## Medium

### M1 — No `voice_id` validation before `session.tts.update_options(voice=…)` (`agent/main.py:396`)

`p.voice_id` is forwarded verbatim from the untrusted RPC into the live TTS plugin with no check against `persona.VOICE_IDS`. The official panel constrains the value via a `<select>` over the mirrored list, but a hand-crafted RPC can pass any string. Best case Kokoro rejects/ignores the next utterance; worst case it desyncs the voice from what the panel believes is applied. Cheap fix: `if p.voice_id not in VOICE_IDS: return "error"` (or clamp to `DEFAULT_PERSONA.voice_id`). Folding this into the H1 validation block covers the whole untrusted payload in one place.

---

## Low

### L1 — RPC handler raises with no agent-side log on a malformed payload (`agent/main.py:389-391`)

`json.loads(data.payload)` (`JSONDecodeError`) and `Persona(**snapshot)` (`TypeError` on missing/extra keys) both raise inside the handler. The livekit RPC layer converts a raising handler into a client-side rejection — observable to the user as the generic `"error"` label — but produces **no** agent-side log line for diagnosis. This mirrors the original Phase-06 style (and the same gap was noted as 06-L3), but combined with H1 the absence of a log makes the cascading-corruption case hard to trace. Wrap the parse in `try/except (JSONDecodeError, TypeError)` that logs and returns `"error"`.

### L2 — Silent client/agent duplication seam (`web/app/PersonaPanel.tsx:11-31` vs `agent/persona.py:28-99,154-161`)

`VOICE_IDS`, `DIFFICULTY`/`VERBOSITY`/`CORRECTION`, and the seed `DEFAULT_PERSONA` are hand-duplicated in the panel to mirror `agent/persona.py`. There is no `persona.get` RPC in the MVP, so any future drift (a renamed voice id, a new knob value, a changed default) is silent — the panel offers a value the agent's tables don't have, and per H1 a drifted knob value would currently poison the session. The duplication is documented (`PersonaPanel.tsx:6-10`) and accepted for the MVP; flagged so it's tracked. Fixing H1's value-validation also converts a silent poison into a clean `"error"`, materially de-risking the drift.

### L3 — `catch {}` swallows the RPC error; status never resets to idle (`web/app/PersonaPanel.tsx:104-118`)

The `apply()` `catch {}` discards the thrown error with no `console`/telemetry, so an RPC timeout, a rejected (raising) handler, and "no agent joined" are indistinguishable to the user — all surface as the same `"error — could not apply"`. Minor: `status` stays `"applied"`/`"error"` indefinitely (never returns to `idle`), so the label lingers across subsequent unrelated interactions until the next Apply. UX-only; consider capturing the error for logging and/or a timed reset to `idle`.

---

## Verified-correct (no action)

- **`persona.py` byte-stability:** `render_persona`/`render_prompt` join a FIXED tuple of frozen constants with a single space (`persona.py:135-142`); knobs are enum→fixed-string lookups, never interpolated numbers; no `f"`/`.format`/`.items()` on runtime data, no volatile data (timestamp/turn-counter/uuid/random). `KB_SLOT=""` stays last (Phase-4 seam). `role_text` is user free-text but is set once per Apply (a sanctioned re-prefill), not interpolated per turn — cache-safe.
- **Golden + self-check:** `EXPECTED_DEFAULT` locks the default render; `_self_check` asserts determinism, golden, no `{}`-placeholder leak, empty-KB == golden, and per-knob byte-stability. `render_persona(p) == render_prompt(p, "")` keeps one join path. Green in-sandbox.
- **`display_name` scope:** carried in the dataclass/payload but deliberately absent from the rendered prefix (`persona.py:109`) — zero cache impact, correct per PERS-03 MVP.
- **Hot-swap mechanism:** in-place `agent.update_instructions(...)` (async) + `session.tts.update_options(voice=…)` (sync, mutates the existing `session.tts`) — no `AgentSession`/`Agent`/TTS-plugin recreation in the handler, so the `metrics_collected` subscription survives (PERS-06 / Pattern E honored).
- **`PersonaPanel.tsx`:** null-agent guard present (`agentIdentity` via `useVoiceAssistant().agent?.identity` with a first-remote-participant fallback, early `error` return, `:98-103`); `performRpc` wrapped in `try/catch` (`:104-117`); payload keys `{role_text, display_name, difficulty, verbosity, correction, voice_id}` match `Persona(**snapshot)` exactly; no token/secret in the payload; `applying` set before the await and the button disabled during it.
- **`VoiceRoom.tsx`:** `<PersonaPanel />` mounted INSIDE `<LiveKitRoom>` (room context available for `useRoomContext`/`performRpc`); existing siblings unchanged.
- **No regressions:** no secrets, no hardcoded model tag (LLM still resolves via `OLLAMA_MODEL`/`resolved_llm_tag()`), `THINKING_ENABLED=False` untouched, `agent/metrics.py` not touched by this phase.

---

## Top recommendation

Fix **H1**: reorder `handle_persona_update` to validate the knob values (and `voice_id`, M1) and render BEFORE assigning `current_persona[0]`, so a malformed `persona.update` cannot poison the shared persona/KB/mode epoch state and silently break every later hot-swap for the session. This is the persona-handler twin of the Phase-06 `mode.update` fix and was missed because the Phase-06 review checked only for bad keys, not bad values. Fold M1 into the same validation block; L1/L3 (logging) are quick adjacent hardening.

**Report written to:** `.planning/phases/03-persona-layer/03-REVIEW.md`
