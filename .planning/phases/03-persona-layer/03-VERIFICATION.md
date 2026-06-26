---
status: passed
phase: 03-persona-layer
verified: 2026-06-25
requirement_ids: [PERS-02, PERS-03, PERS-04, PERS-05, PERS-06, PERS-07]
live_verification: 03-UAT.md (all 5 tests pass, driven via Chrome DevTools Protocol)
---

# Phase 03 — Persona Layer — VERIFICATION

**Verified:** 2026-06-25
**Phase goal:** Layer a live-editable expert persona over the working loop — role/instructions,
display name, behavior knobs (difficulty, verbosity, correction-aggressiveness), and Kokoro voice
selection — establishing the byte-stable frozen-prefix prompt layout that KB caching will depend on,
with in-session hot-swap and "applying…" feedback.

**Plans:** 03-01 (persona config module + frozen-prefix render + named agent ref),
03-02 (persona side panel + RPC control channel + live hot-swap).
Both plans are `autonomous: false` — verified via VM + LAN operator gates for live behavior.

---

## Verdict

**ACHIEVED — sandbox substrate verified AND live behavior confirmed via CDP (2026-06-25).**

All sandbox-verifiable substrate (module structure, render order, byte-stability self-check, RPC
method/payload contract, client/server mirror, py_compile, tsc, metrics.py unchanged) is verified
against the actual codebase and PASSES. The previously-deferred live-behavior success criteria
(runtime editing, knob/voice effect, in-session hot-swap, scaled correction) were subsequently
driven against the running Docker stack over the Chrome DevTools Protocol (headless Chromium + fake
mic) and ALL PASS — recorded in `03-UAT.md` (5/5). Only two acoustic sub-claims (audible voice swap,
audible correction firmness) remain human-ear-only; their full code paths are verified end-to-end.

**Finding during live verification:** the stack was running stale pre-phase images; rebuilding
exposed a real defect — `agent/Dockerfile` omitted `persona.py` from its COPY, crash-looping the
agent. Fixed in commit `dd17ffa`. See `03-UAT.md` Gaps.

---

## Requirement ID Cross-Reference (PERS-02..07 vs REQUIREMENTS.md)

Every phase requirement ID is accounted for. REQUIREMENTS.md marks all `[x]` and Traceability table
shows Phase 3 / Complete for each.

| Req ID | Requirement | Plan / Mechanism | Substrate status |
|--------|-------------|------------------|------------------|
| PERS-02 | Edit role + system instructions in side panel | 03-02 — role `<textarea>` → payload `role_text` → `update_instructions(render_persona(p))` | Verified (structural) |
| PERS-03 | Edit display name | 03-02 — name `<input>` → payload `display_name` (UI label; out of prompt prefix, MVP) | Verified (structural) |
| PERS-04 | Difficulty / verbosity / correction knobs | 03-02 — three `<select>`s → enum keys → fixed-string fragments server-side | Verified (structural) |
| PERS-05 | Select Kokoro preset voice | 03-02 — voice `<select>` from frozen `VOICE_IDS` → `session.tts.update_options(voice=)` | Verified (structural) |
| PERS-06 | Persona changes apply within session without restart | 03-02 — in-place `update_instructions` + `update_options`, no AgentSession/Agent/TTS teardown | Verified (structural) |
| PERS-07 | Default trainer gently corrects, scaled by knob | 03-01 — `CORRECTION` enum (`gentle\|moderate\|aggressive`); default `gentle` preserves PERS-01 | Verified (structural) |

Note: 03-01 frontmatter declares `requirements: [PERS-07]`; 03-02 declares
`requirements: [PERS-02, PERS-03, PERS-04, PERS-05, PERS-06]`. Union = PERS-02..07 = phase requirement
set. **No unaccounted IDs; no extra IDs claimed.**

---

## Success Criteria Classification

### Automated (structural / contract) — VERIFIED in sandbox

**SC-5 — Frozen-prefix layout `[static persona] + [static KB slot] + [rolling history] + [new turn]`**
- `agent/persona.py:111-118` — `render_persona` joins a FIXED tuple:
  `(role_text|ROLE_PREAMBLE, DIFFICULTY, VERBOSITY, CORRECTION, SPOKEN_STYLE_FOOTER, KB_SLOT)`.
- `KB_SLOT: str = ""` (`persona.py:78`) is the LAST segment (`persona.py:117`) — the Phase-4 seam,
  empty and not reordered/filled. History + new turn are appended by AgentSession after the prefix.
- **PASS.**

**Byte-stability self-check**
- `python3 agent/persona.py` → exits 0, prints `persona _self_check OK`.
- Asserts: determinism (same persona → identical bytes), golden `EXPECTED_DEFAULT` match,
  no format-placeholder leak (`{`/`}`), and knob-permutation byte-stability across all three tables.
- **PASS.**

**No interpolation / volatile data in the rendered prefix**
- `render_persona` body (`persona.py:111-118`) uses `" ".join(...)` over frozen constants — no
  f-string / `.format` / `dict.items()` on runtime data (all grep matches land in
  comments/docstrings/`_self_check` assert messages, none inside the render path).
- No `datetime|time.|uuid|random|now()` anywhere in the module.
- **PASS.**

**RPC method / payload contract (client ↔ server mirror)**
- Client (`PersonaPanel.tsx:109-113`): `performRpc({ destinationIdentity, method: "persona.update",
  payload: JSON.stringify(persona) })`; payload keys `role_text, display_name, difficulty, verbosity,
  correction, voice_id`.
- Server (`main.py:241-251`): `handle_persona_update` → `json.loads(data.payload)` → `Persona(**snapshot)`
  → `register_rpc_method("persona.update", ...)`. Method name + payload keys match `Persona` fields exactly.
- **PASS.**

**Client/server constant mirror (file-#6 duplication seam)**
- `VOICE_IDS` (13 ids, incl. `af_bella`), `DIFFICULTY`, `VERBOSITY`, `CORRECTION` arrays in
  `PersonaPanel.tsx:11-18` mirror `agent/persona.py` keys exactly; seed persona mirrors `DEFAULT_PERSONA`.
- **PASS.**

**In-place hot-swap, no recreation in handler**
- `main.py` build sites: `AgentSession(` (:109), `openai.TTS(` (:130), `Agent(` (:226) — all OUTSIDE
  the handler. Handler (`:241-246`) calls only `update_instructions` + `update_options(voice=)`,
  returns `"applied"`. No session/agent/TTS recreation.
- **PASS.**

**metrics.py unchanged**
- `git diff --stat agent/metrics.py` → empty. Per-turn JSON key contract frozen.
- **PASS.**

**No secret in client payload**
- `grep -niE "token|secret|api[_-]?key" PersonaPanel.tsx` → no matches. Payload is persona text/enums/voice id only.
- **PASS.**

**Compile / typecheck**
- `python3 -m py_compile agent/main.py agent/persona.py` → exits 0.
- `cd web && npx tsc --noEmit` → TSC OK.
- **PASS.**

**Mount inside LiveKitRoom**
- `VoiceRoom.tsx:83` renders `<PersonaPanel />` as a sibling INSIDE `<LiveKitRoom>` (shares room
  context for `useRoomContext`/`performRpc`); `RoomAudioRenderer`/`StartAudio`/`AgentStatePill`/`Transcript` intact.
- **PASS.**

### Human Verification (live runtime behavior) — CONFIRMED via CDP 2026-06-25 (03-UAT.md)

Driven against the running Docker stack over the Chrome DevTools Protocol (headless Chromium + fake
mic), after rebuilding the stale `web`/`agent` images. Pinned builds: `livekit-client@2.20.0`,
`@livekit/components-react@2.9.21`, Kokoro server.

**SC-1 — User can edit role/instructions + display name in a side panel**
- After join, DOM contained the role `<textarea>` + display-name `<input>`; both editable and carried
  in the Apply payload. **PASS** (UAT Test 1).

**SC-2 — User can adjust difficulty/verbosity/correction knobs + select a Kokoro voice**
- All 4 `<select>`s present; Voice select lists all 13 frozen `VOICE_IDS` in order;
  `curl http://kokoro:8880/v1/audio/voices` serves every id. **PASS** (UAT Tests 1, 5).

**SC-3 — Persona changes apply within the current session without restart ("applying…" feedback)**
- Edited fields + Apply → status settled on `applied` (the native `persona.update` RPC ack), no
  error; agent kept emitting the unchanged per-turn metrics key set. Signatures reconciled on the
  installed build: `Agent.update_instructions` is a coroutine, `openai.TTS.update_options(voice=)`
  accepts voice, `register_rpc_method` (snake_case) exists, `RpcInvocationData.__init__` has
  `payload`. **PASS** (UAT Tests 2, 4). Audible next-turn voice swap is the one human-ear sub-claim.

**SC-4 — Default trainer gently corrects sloppy terminology, scaled by correction-aggressiveness knob**
- `python /app/persona.py` self-check green (default = golden Phase-2-equivalent); the 3 correction
  tiers render distinct escalating prompts, applied live via the verified Apply path. **PASS** (UAT
  Test 3). Audible firmness scaling is the one human-ear sub-claim.

**Operator gate (PERS-01 / DEPLOY-03 regression)**
- On browser join the agent greeted as the Cybersecurity Trainer with the default persona — unchanged
  from Phase 2. **PASS** (UAT Test 3).

---

## must_haves — checked against actual codebase

03-01:
- [x] PERS-07 correction is an enum; `gentle` is the default and preserves PERS-01 (`persona.py:41-55,127`).
- [x] Rendered prefix byte-stable; asserted across repeats + knob permutations (`persona.py:154-191`, self-check green).
- [x] Frozen order `role → difficulty → verbosity → correction → footer → KB_SLOT(empty)` (`persona.py:111-118`).
- [x] `render_persona(DEFAULT_PERSONA)` behaviorally equivalent to old `PERSONA_INSTRUCTIONS`; PERS-01/DEPLOY-03 default-on-load preserved.
- [x] `main.py` holds a single NAMED `agent` ref reachable by the RPC handler (`main.py:226`).
- [x] Prohibitions: no interpolated numbers/f-strings/`.items()` in prefix; no volatile data; metrics.py byte-identical; no AgentSession re-plumbing beyond voice source; LLM tag still from `OLLAMA_MODEL`; KB slot empty + last.

03-02:
- [x] PERS-02 role textarea → payload → `update_instructions(render_persona(p))`.
- [x] PERS-03 display-name input editable + carried in payload (UI label).
- [x] PERS-04 three knob selects → enum keys → server fixed-string fragments.
- [x] PERS-05 voice selectable from curated list → `update_options(voice=)`.
- [x] PERS-06 in-session apply, no restart; RPC return value is the ack.
- [x] Panel mounted inside `<LiveKitRoom>`.
- [x] Prohibitions: no teardown/recreation; metrics.py unchanged; no secret in payload; no per-turn auto-edit; no live voice-list fetch; `[VM-INTROSPECT]` items not marked passed.

---

## Deferred / VM-Introspect Items — RESOLVED 2026-06-25 (see 03-UAT.md)

1. **OPERATOR GATE — RESOLVED (UAT T2):** edit role/name/knobs/voice → Apply → `applied`; RPC ack
   returned; metrics key set unchanged. (Audible voice swap = human-ear sub-claim.)
2. **OPERATOR GATE (regression) — RESOLVED (UAT T3):** default-trainer greeting unchanged on join.
3. **`[VM-INTROSPECT]` agent — RESOLVED (UAT T4):** `update_instructions` coroutine ✓;
   `openai.TTS.update_options(voice=)` ✓; `register_rpc_method` snake_case ✓; `RpcInvocationData`
   has `payload` ✓.
4. **`[VM-INTROSPECT]` client — RESOLVED (UAT T4):** `performRpc`/`registerRpcMethod` proven by the
   Test 2 round-trip on `livekit-client@2.20.0`; `useVoiceAssistant().agent.identity` is the
   destination.
5. **`[VM-INTROSPECT]` Kokoro — RESOLVED (UAT T5):** `/v1/audio/voices` serves every `VOICE_IDS` entry.

**Remaining (non-blocking):** two acoustic sub-claims (audible voice swap, audible correction
firmness) are human-ear-only; their code paths are verified end-to-end. Optional quick listen on VM.

---

## Summary

| Check | Result |
|-------|--------|
| `python3 agent/persona.py` self-check | PASS (green) |
| `python3 -m py_compile agent/main.py agent/persona.py` | PASS |
| `cd web && npx tsc --noEmit` | PASS |
| Frozen-prefix layout + KB_SLOT last | PASS |
| Byte-stability (no interpolation/volatile data) | PASS |
| RPC method/payload contract (client ↔ `Persona(**snapshot)`) | PASS |
| Client/server constant mirror | PASS |
| No recreation in handler / in-place hot-swap | PASS |
| metrics.py unchanged | PASS |
| No secret in client payload | PASS |
| PersonaPanel mounted inside LiveKitRoom | PASS |
| Requirement IDs PERS-02..07 accounted for | PASS |
| SC-1..4 live behaviors (CDP, 03-UAT.md 5/5) | PASS |

**Sandbox substrate: fully verified. Live behavior: confirmed via CDP against the running stack
(03-UAT.md, 5/5 pass). Phase goal achieved. Only two acoustic sub-claims remain human-ear-only.**
