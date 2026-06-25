# Phase 3 Research: Persona Layer

**Phase:** 03-persona-layer (MVP mode — vertical slices)
**Researched:** 2026-06-25
**Requirements:** PERS-02, PERS-03, PERS-04, PERS-05, PERS-06, PERS-07
**Question answered:** *What do I need to know to PLAN this phase well?*

> **Grounding discipline (carried from Phase 2):** the sandbox CANNOT import
> `livekit` (`ModuleNotFoundError: No module named 'livekit'`) — no Docker, GPU,
> or browser either. Every API claim below is grounded in **published LiveKit
> docs (current 1.5/1.6 line)** + the **source-verified Phase 2 memory** of the
> installed `livekit-agents ~=1.5` surface. Each claim that touches the installed
> build is tagged **[VM-INTROSPECT]** with the exact one-liner to confirm on the
> Proxmox VM. Do NOT mark those passed in a plan; defer them like 02-02/02-03 did.

---

## 0. TL;DR — the shape of this phase

Phase 3 layers a **live-editable persona** over the working voice loop without
restarting `AgentSession`. Five moving parts:

1. **A `Persona` config object** (role/instructions text, display name, three
   enum knobs, voice id) that **deterministically renders** to (a) a byte-stable
   system-prompt string and (b) a Kokoro voice id.
2. **Frozen-prefix prompt layout** `[static persona] + [static KB slot] +
   [rolling history] + [new turn]` — the persona block is the very front of the
   prompt and must be byte-identical turn-to-turn (Phase 4's KB cache depends on
   this; Pitfall 7).
3. **Live hot-swap** via `await agent.update_instructions(...)` (persona text)
   and `session.tts.update_options(voice=...)` (Kokoro voice) — no
   `AgentSession` teardown.
4. **A client→agent control channel** (LiveKit **RPC** preferred) carrying
   persona edits from the Next.js side panel to the Python agent, with an
   **"applying…"/"applied"** ack back.
5. **A side panel UI** (new client component beside `VoiceRoom`) with the role/
   name fields, three knob selectors, and a voice dropdown.

The two-plan split from the ROADMAP holds:
- **03-01** = persona config → system prompt + voice id + frozen-prefix layout (agent-side, pure/testable).
- **03-02** = side panel UI + RPC control channel + live `update_instructions`/voice swap + "applying…" feedback.

The single biggest design constraint is **byte-stability of the persona prefix**
— it dictates that knobs map to **fixed-string lookups**, not interpolated
numbers, and that the prompt is assembled by **concatenating frozen constants**,
never f-strings with volatile data.

---

## 1. livekit-agents live persona/instructions hot-swap

### 1.1 The API: `Agent.update_instructions()` (NOT recreating the session)

The supported, documented way to mutate the system prompt mid-session is the
**coroutine method on the `Agent` object** (not `AgentSession`):

```python
await agent.update_instructions("You are now a SOC-analyst interviewer ...")
```

- Source: LiveKit docs *Tool definition* + *Tool design* pages —
  `await self.update_instructions(self.instructions + " ...")` is shown as the
  canonical runtime-update pattern, and "these changes are automatically tracked
  in the conversation history."
- It is **async** — must be awaited from inside the agent process (an RPC handler
  or task, see §5).
- Companion method `await agent.update_tools([...])` exists (not needed Phase 3).
- `agent.instructions` is readable (the docs concatenate `self.instructions + ...`),
  so you can read-modify-write, but for a **byte-stable** persona we will
  **render the whole block fresh from the `Persona` config** each swap, not append.

**[VM-INTROSPECT]**
```
python -c "import inspect, livekit.agents as a; print(inspect.signature(a.Agent.update_instructions))"
python -c "import inspect, livekit.agents as a; print([m for m in dir(a.Agent) if 'instruction' in m or 'update' in m])"
```
Confirm `update_instructions` exists on the installed `~=1.5` `Agent` and is a
coroutine. (Docs reflect the 1.x line; the exact pin must be confirmed on the VM,
same discipline as 02-02's `generate_reply` gate.)

### 1.2 What it does NOT do / what to avoid

- **Do NOT recreate the `Agent` or restart `AgentSession`** to change persona.
  Success Criterion 3 is "apply within the current session without a restart."
  `update_instructions` is the in-place mutation. Recreating would drop the room,
  history, and warm model state.
- Keep the **single `Agent` instance** held in a reference reachable from the RPC
  handler (e.g. closure over `agent` in `entrypoint`, or store on a small session
  state object). Current `entrypoint` builds `Agent(instructions=PERSONA_INSTRUCTIONS)`
  inline at `session.start(...)` (agent/main.py:237-240) — refactor to a named
  local `agent = Agent(instructions=render_persona(persona))` so the handler can
  reach it.

### 1.3 What triggers the re-prefill ("applying…" moment)

The persona block sits at the **front** of the prompt. Changing it changes the
prefix → on the **next LLM turn** Ollama must re-prefill from the first changed
byte (Pitfall 7). This is the "one-turn re-prefill" the success criterion names.
Mechanics:

- `update_instructions` only swaps the text; it does **not** itself force an LLM
  call. The cost is paid on the **next generated reply**.
- For the persona swap, the new instructions take effect on the next turn the
  model generates (the framework adds session-level instructions to the chat ctx
  at generation time).
- Show **"applying…"** from when the edit is sent until the first token of the
  next reply (or an explicit ack). Because the prefix changed, that next turn's
  TTFT will be a cold-prefix prefill — acceptable, one-time, and exactly why the
  UI masks it. Do **not** edit persona every turn (Pitfall 7, Technical-Debt
  table: "persona timestamp/turn-counter … busts prefix cache every turn").

### 1.4 Surfacing "applying…" state to the client

Two complementary signals:
1. **RPC return value / ack** (§5): the agent's RPC handler returns
   `"applied"` after `await agent.update_instructions(...)` completes — the
   client flips "applying…" → "applied".
2. **`lk.agent.state` participant attribute** already drives `AgentStatePill`
   (`useVoiceAssistant().state`, AgentStatePill.tsx). During the re-prefill turn
   the pill naturally shows `thinking`. The explicit "applying…" should be a
   **separate persona-panel indicator**, not overloaded onto the global pill, so
   it's unambiguous which action is pending.

---

## 2. Kokoro voice selection at runtime

### 2.1 How the voice maps through the plugin

Current wiring (agent/main.py:143-148):
```python
tts=openai.TTS(base_url=KOKORO_BASE_URL, model="tts-1", voice="af_bella", api_key="none")
```
- Kokoro selects the voice via the **`voice` parameter** of the OpenAI-compatible
  `/v1/audio/speech` request — **not** the model. (`model` stays `"tts-1"` for
  the plain audio-stream path; this is already documented in agent/main.py:35-41
  and is correct — confirmed by community reports using `model=kokoro`/`tts-1`
  with `voice=af_bella`.)
- The livekit `openai.TTS` plugin forwards `voice=` straight into that request.

### 2.2 Changing the active voice mid-session

Use **`session.tts.update_options(voice=<id>)`** — the documented runtime TTS
mutation. "Changes take effect on the next utterance."

```python
session.tts.update_options(voice="am_michael")
```

- Source: LiveKit docs (Hume TTS plugin guide + generic *Update Utterance Options*):
  `session.tts.update_options(voice=..., speed=...)`. The method "accepts the same
  parameters as the TTS constructor" and applies on the **next** utterance.
- This is **synchronous** (no `await` shown in docs) — but call it off the hot
  path / not mid-utterance (see Pitfalls §6).
- The `openai.TTS` plugin is the one in use; confirm it exposes `voice` on
  `update_options`. The OpenAI-family plugins take `voice` in the constructor, so
  it is the expected kwarg.

**[VM-INTROSPECT]**
```
python -c "import inspect; from livekit.plugins import openai; print(inspect.signature(openai.TTS.update_options))"
python -c "import inspect; from livekit.plugins import openai; print(inspect.signature(openai.TTS.__init__))"
```
Confirm `update_options(voice=...)` exists on the installed `livekit-plugins-openai`
`TTS`. If `update_options` is absent on this plugin version, **fallback**: keep a
reference to the `TTS` instance and recreate just the TTS plugin, or set the
attribute the plugin reads per request. (Prefer `update_options`; only fall back
if introspection shows it missing.)

### 2.3 Available Kokoro preset voice ids

Kokoro v1.0 ships **54+ voices across 8 languages** (naming: `{lang}{gender}_{name}`,
`a`=American, `b`=British, `f`=female, `m`=male). For the MVP voice dropdown,
expose the **well-tested English subset** (curate, don't dump all 60+):

**American English (recommended default set):**
`af_heart` (A, default-quality), `af_bella` (A-, current default), `af_nicole`
(B-, headphone-mixed), `af_sarah`, `af_kore`, `af_aoede`, `af_nova`,
`am_michael` (B, authoritative), `am_fenrir`, `am_puck`, `am_adam`, `am_onyx`,
`am_echo`, `am_eric`, `am_liam`.

**British English:** `bf_emma` (B-), `bf_alice`, `bf_isabella`, `bf_lily`,
`bm_george`, `bm_fable`, `bm_daniel`, `bm_lewis`.

Highest single-sentence WER scores (cleanest): `af_heart`, `af_bella`,
`am_michael`, `am_fenrir`, `am_puck`, `bf_emma`. **Recommend defaulting the
dropdown to a curated ~8–12 American + British English voices** and keep
`af_bella` as the persona default (matches current code, no behavior change for
PERS-01).

> Caveat: the EXACT voice list depends on the **pinned `kokoro-fastapi` image**.
> **[VM-INTROSPECT]** `curl http://kokoro:8880/v1/audio/voices` (the server
> exposes a voices endpoint) to get the authoritative list for the pinned tag,
> and validate each dropdown id returns audio (a bad id → HTTP 422, seen in
> open-webui reports). Source the dropdown from a **frozen constant list in code**
> (not a live fetch) so the UI is deterministic; reconcile against the server
> list once on the VM.

---

## 3. Byte-stable frozen-prefix prompt layout

### 3.1 The target layout

```
[static persona block]    ← rendered from Persona config; FROZEN within a "persona epoch"
[static KB slot]          ← empty string in Phase 3 (Phase 4 fills it); a fixed placeholder/empty
[rolling history]         ← appended behind the prefix, managed by the framework
[new user turn]           ← the only volatile tail
```

In `livekit-agents` the **persona block = `Agent(instructions=...)`** (the system
message), and `[history] + [new turn]` is the framework-managed `chat_ctx`. The
KB slot is conceptually part of the system/instructions region that Phase 4 will
populate; in Phase 3 it is an **empty (or fixed-placeholder) trailing segment of
the persona block** so that adding KB later appends *after* persona and *before*
history without reordering. Document this seam now.

### 3.2 What keeps the prefix byte-identical (the hard rule)

The prefix must be **byte-for-byte identical** across turns or Ollama's prefix/KV
cache misses and re-prefills the whole thing (Pitfall 7, the entire reason this
phase pre-builds the layout for Phase 4).

**Byte-stability rules for `render_persona(persona) -> str`:**
- **No volatile data anywhere in the block:** no timestamps, turn counters,
  session ids, `datetime.now()`, random ids, UUIDs. (Pitfall 7 / Tech-Debt table.)
- **No f-strings/`.format` interpolating runtime values.** Assemble from frozen
  string constants joined deterministically. (The current `PERSONA_INSTRUCTIONS`
  is already a plain literal — 02-02 established this; extend the discipline to
  the *rendered* output.)
- **Deterministic assembly:** fixed segment order, fixed separators (e.g. a
  single `" "` or `"\n"`), no dict iteration whose order could vary, no JSON
  re-serialization (key order / whitespace drift). If you build from a dict,
  iterate a **fixed tuple of keys**, not `dict.items()`.
- **Stable whitespace:** no trailing-whitespace variance, no conditional newlines
  that depend on optional fields being present/absent in a way that shifts bytes
  unpredictably. Prefer always-present segments.
- **Knob → fixed string (never the number):** see §4. `difficulty=2` must map to
  a constant sentence, and the *same* `difficulty` must always yield the *exact
  same bytes*.

### 3.3 What busts it (catalog)

| Cache-buster | Why | Mitigation |
|---|---|---|
| Timestamp/turn counter in persona | front-of-prompt change every turn | never put volatile data in the prefix; tail only |
| f-string with a runtime value | bytes change when value changes | render from frozen constants; enum→fixed-string |
| Editing persona every turn | rewrites prefix each turn | edit only on explicit user action (Phase 3 IS the edit path — that's fine, it's user-driven and one-shot) |
| History summarization that rewrites earlier turns | invalidates everything after the rewrite | Phase 5 concern — summarize *behind* the frozen prefix only |
| Dict-order / JSON whitespace drift | non-deterministic bytes | fixed key tuple, no JSON in the prefix |
| Reordering segments (KB before vs after persona) | different prefix | freeze the order now: persona → KB → history → turn |

### 3.4 The "persona epoch" mental model

Within a session the persona prefix is frozen **until the user edits it**. Each
edit starts a **new epoch**: the next turn re-prefills (the "applying…" turn),
then the new prefix is frozen again and caches from the turn after. This is the
explicit, user-visible re-prefill the success criterion sanctions — *not* silent
per-turn busting. The plan should state: **persona edits are the only sanctioned
prefix change, they are user-initiated, and each costs exactly one re-prefill.**

### 3.5 How history is appended behind the frozen prefix

- The framework keeps `chat_ctx` (history) as messages **after** the system/
  instructions. `update_instructions` swaps the system text; the framework adds
  it at generation time. History is append-only in Phase 3 (windowing is Phase 5).
- Phase 3 does **not** need to hand-manage history — it must only ensure the
  **persona/system region is the stable front** and nothing volatile leaks in.
- **[VM-INTROSPECT]** Verify, when Ollama receives the assembled prompt, that the
  persona text appears at the very front and is identical turn-to-turn (inspect
  the outgoing `/v1/chat/completions` body or Ollama prompt-eval logs: turn-2
  prompt-eval count should be small/near-zero for the unchanged prefix). This is
  the real Phase-4 gate but the seam is built here.

---

## 4. Behavior knobs → prompt construction

### 4.1 The pattern: enum → fixed-string lookup (NOT interpolated numbers)

Each knob is a **small enum** (e.g. 3 levels). Each level maps to a **fixed,
hand-written prompt fragment constant**. The rendered persona block concatenates
the chosen fragments in a fixed order. This guarantees byte-stability (§3) and
makes knob behavior legible/tunable.

```python
# Illustrative — fixed-string lookups, no number interpolation, byte-stable.
DIFFICULTY = {
    "beginner":     "Pitch explanations at an entry level; define jargon as you go.",
    "intermediate": "Assume working familiarity; use standard practitioner terms without over-explaining.",
    "expert":       "Engage at an expert level; skip basics and probe edge cases.",
}
VERBOSITY = {
    "terse":    "Keep replies to one or two sentences.",
    "balanced": "Keep replies short and spoken-friendly, a few sentences at most.",
    "detailed": "You may elaborate to several sentences when the topic warrants, still spoken-friendly.",
}
CORRECTION = {
    "gentle":      "When the learner uses imprecise terminology, lightly note the precise term once and move on.",
    "moderate":    "When the learner uses sloppy terminology, correct it toward precise practitioner phrasing and briefly say why.",
    "aggressive":  "Actively catch imprecise or wrong terminology every time; restate the precise term and the distinction before continuing.",
}
```

Render:
```python
KNOB_ORDER = ("difficulty", "verbosity", "correction")  # fixed tuple — no dict-order risk
def render_persona(p) -> str:
    return " ".join((
        ROLE_PREAMBLE,                 # frozen base (the Cybersecurity Trainer block, optionally user-edited text)
        DIFFICULTY[p.difficulty],
        VERBOSITY[p.verbosity],
        CORRECTION[p.correction],
        SPOKEN_STYLE_FOOTER,           # frozen "no markdown/bullets" footer
        KB_SLOT,                       # "" in Phase 3 — fixed placeholder seam for Phase 4
    ))
```

### 4.2 Why fixed strings, not numbers

- **Byte-stability:** `difficulty="expert"` always yields the identical bytes; a
  numeric `f"difficulty level {n}/5"` is technically stable too, but enums make
  the **behavior deterministic and legible** and prevent accidental float/format
  drift (`2` vs `2.0`). The model also follows an explicit instruction sentence
  far better than a bare number (Pitfall 11: small model — "structure compensates
  for model size"; give it words, not a dial reading).
- **Tunable:** each fragment is hand-authored prose you can iterate without
  touching code structure.
- **Maps cleanly to the UI:** the side-panel knob is a 3-option selector; the
  value is the enum key; the dropdown labels can be friendlier than the keys.

### 4.3 PERS-07 — correction-aggressiveness specifically

The **correction-aggressiveness knob IS the PERS-07 mechanism**: the default
trainer "gently corrects sloppy terminology toward precise practitioner phrasing,
scaled by the knob." The current `PERSONA_INSTRUCTIONS` already contains a gentle-
correction sentence (agent/main.py:70-72) — Phase 3 **lifts that into the
`CORRECTION` enum**, with `gentle` as the default level (preserving PERS-01
behavior). The three levels scale from a light single note → restating with the
distinction every time.

### 4.4 Difficulty/verbosity vs the latency budget

`verbosity="detailed"` produces longer replies → more TTS → more end-to-end time,
but **not** more TTFT (first token unaffected). Acceptable: the flat-TTFT
invariant is about *first token*, and verbosity changes total speak time, which
the user chose. Note this in the plan so it's not mistaken for a regression.

---

## 5. Client↔agent control channel (persona edits + acks)

### 5.1 Recommended: LiveKit RPC (participant RPC)

The cleanest fit is **LiveKit RPC** — a request/response over the data plane,
purpose-built for "frontend calls the agent" (LiveKit explicitly lists "make
frontend calls with RPC" as the agent control pattern).

**Agent side (Python, in `entrypoint` after `ctx.connect()`):**
```python
ctx.room.local_participant.register_rpc_method("persona.update", handle_persona_update)
```
The handler receives the edit payload (JSON: role text, name, knob enums, voice
id), applies it, and **returns a string ack** (`"applied"`), which the client
receives as the RPC response — this is the built-in "applying…→applied" signal.

```python
async def handle_persona_update(data):  # data.payload is a JSON string
    p = parse_persona(data.payload)
    await agent.update_instructions(render_persona(p))   # §1
    session.tts.update_options(voice=p.voice_id)         # §2
    return "applied"
```

**Client side (browser, livekit-client):**
```ts
const ack = await room.localParticipant.performRpc({
  destinationIdentity: agentIdentity,     // the agent participant identity
  method: "persona.update",
  payload: JSON.stringify(persona),
});
// show "applying…" before await; flip to "applied" when ack resolves
```

- Source: LiveKit RPC docs + node-sdks issue #392 showing
  `registerRpcMethod` / `performRpc` with `destinationIdentity`, `method`,
  `payload`. Python agent registers via `room.local_participant.register_rpc_method`.
- **Gotcha (issue #392):** client→agent RPC requires the agent to have
  **registered the method before the call** and the client to target the correct
  `destinationIdentity`. Register in `entrypoint` right after connect. Get the
  agent identity on the client from the agent participant (the
  `useVoiceAssistant()` / room remote-participants surface exposes the agent).
- **RPC payload limits / timeout:** RPC has a response timeout and payload-size
  considerations; the persona payload (a few hundred chars of text + enums + voice
  id) is well within limits. Set the call to await the ack for the "applying…"
  window.

**[VM-INTROSPECT]**
```
python -c "import inspect; from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'rpc' in m.lower()])"
python -c "import inspect; from livekit import rtc; print(inspect.signature(rtc.LocalParticipant.register_rpc_method))"
```
Confirm `register_rpc_method` (snake_case) on the installed `livekit` (rtc)
Python SDK and the handler signature (`RpcInvocationData` with `.payload`).
On the JS side confirm `performRpc`/`registerRpcMethod` on
`livekit-client@2.20.0` (already pinned, 02-01).

### 5.2 Fallback: participant attributes or data messages

If RPC is unavailable/awkward on the pinned versions:
- **Participant attributes:** the client sets a `persona` attribute (JSON); the
  agent listens for `participant_attributes_changed`. The existing
  `AgentStatePill` already reads the agent's `lk.agent.state` **attribute**, so
  the attribute pattern is proven in this codebase. Downside: no built-in
  request/response ack — you'd ack via a return attribute the client watches
  (more plumbing than RPC's native return value).
- **Data messages** (`publishData` / `registerTextStreamHandler`): lower-level,
  also no native ack. The 02-01 transcript already uses `useTranscriptions`
  (text streams) — data channel is available but RPC is the better fit for a
  command-with-ack.

**Recommendation:** **RPC primary** (native ack = the "applying…/applied" signal),
attributes as the documented fallback. Decide in 03-02 after the VM introspection
confirms `register_rpc_method` on the pin.

### 5.3 Where the persona state lives

- **Source of truth = the agent process** (it renders the prompt and owns the
  `Agent`/`TTS` instances). The client panel holds the editable form state and
  sends full snapshots on apply.
- Seed the panel from the **default persona** (PERS-01 Cybersecurity Trainer)
  so it's populated on load with no round-trip. Optionally expose a
  `persona.get` RPC to fetch current state, but MVP can hardcode the default
  client-side to match the agent default (keep them in sync via a shared constant
  or an env — note the duplication risk in the plan).

---

## 6. Pitfalls (Phase-3-specific)

### 6.1 Prefix-cache busting (the #1 risk — Pitfall 7)
- Persona edits are **the only** sanctioned prefix change; they are user-driven
  and cost exactly one re-prefill (the "applying…" turn). **Never** put volatile
  data in the persona block. **Never** auto-edit persona per turn.
- Knobs → **fixed strings** (§4), assembled deterministically (§3). A subtle
  whitespace/ordering bug here silently halves Phase 4's KB-cache win — so this
  phase should add a **byte-stability unit test**: `render_persona(p)` called
  twice with the same `p` returns identical bytes, and known `p`→known string
  (golden test), runnable with pure stdlib like `metrics.py::_self_check`
  (no livekit import needed — pure function).

### 6.2 Race conditions during hot-swap mid-turn
- A persona edit arriving **while the agent is mid-generation** could apply
  between turns or mid-turn. `update_instructions` affects the **next** generation;
  `update_options(voice=)` affects the **next utterance**. So an in-flight turn
  completes under the old persona/voice — acceptable and predictable.
- Risk: the RPC handler runs on the agent's event loop; ensure the handler
  `await`s `update_instructions` (async) and doesn't block audio. Keep it light.
- If the user spams edits, debounce client-side and/or let the last edit win
  (idempotent full-snapshot apply makes this safe).

### 6.3 Voice changes mid-utterance
- Calling `update_options(voice=)` **during** an utterance: docs say it applies on
  the **next** utterance, so the current sentence finishes in the old voice (no
  mid-word voice flip / glitch). Good. But verify the plugin doesn't reset
  in-flight TTS. **[VM-INTROSPECT]** swap voice while the agent is speaking and
  confirm the current utterance is unbroken and the next one uses the new voice.
- Avoid changing voice on the hot path per-turn; it's a user action only.

### 6.4 Keeping the per-turn metrics contract intact
- `agent/metrics.py` keys turns by `speech_id` and emits a fixed JSON shape
  (`eou_ms/stt_ms/llm_ttft_ms/tts_ttfb_ms/e2e_ms/over_budget`). Phase 3 must
  **not** change those keys or the per-plugin `metrics_collected` wiring
  (`metrics.attach(session)`).
- The "applying…" re-prefill turn will show an **elevated `llm_ttft_ms`** (cold
  prefix) — that's expected and will (correctly) flag `over_budget` for that one
  turn. Don't "fix" it; optionally tag persona-swap turns so latency analysis can
  exclude them, but that's beyond MVP — simplest is to note it.
- Swapping the TTS voice must not detach the metrics handler — `update_options`
  mutates the **existing** `session.tts` instance, so the `metrics_collected`
  subscription (bound to that instance in `attach`) survives. If a fallback
  *recreates* the TTS plugin, the metrics handler would need re-attaching — a
  reason to prefer `update_options`.

### 6.5 Don't break PERS-01 defaults
- The default Cybersecurity Trainer must remain available on load with no setup
  (DEPLOY-03). The persona default = current `PERSONA_INSTRUCTIONS` content,
  refactored into `ROLE_PREAMBLE` + default knob levels (`gentle`/`balanced`/
  `intermediate` or whatever matches today's prose) + `af_bella`. Verify the
  rendered default is behaviorally equivalent to today's static string.

### 6.6 Sandbox limits (carry the Phase-2 discipline)
- Cannot import livekit / no browser / no GPU here. Everything touching the
  installed build is **[VM-INTROSPECT]**. The **pure** pieces — `render_persona`,
  the enum tables, the byte-stability test, the voice-id constant list, the UI
  component compile (`next build`) — ARE verifiable in the sandbox and should be
  the client-verifiable acceptance criteria; the live hot-swap + RPC round-trip +
  voice-mid-utterance are operator gates.

---

## 7. Implementation-ready plan notes

### 7.1 Plan 03-01 (agent-side, mostly pure/testable)
- New module (e.g. `agent/persona.py`): a `Persona` dataclass
  (`role_text`, `display_name`, `difficulty`, `verbosity`, `correction`,
  `voice_id`), the three knob enum→fixed-string tables, the curated voice-id
  list, `render_persona(p) -> str` (frozen-prefix assembly, KB-slot seam,
  fixed key order, no volatile data), and a `DEFAULT_PERSONA` reproducing today's
  Cybersecurity Trainer.
- Refactor `agent/main.py`: `Agent(instructions=render_persona(DEFAULT_PERSONA))`;
  hold a named `agent` reference; `tts` voice from `DEFAULT_PERSONA.voice_id`.
- Add a pure-stdlib `_self_check()` (mirrors `metrics.py`): determinism +
  golden-string + default-equivalence assertions. **Runnable without livekit.**
- Acceptance (sandbox): `py_compile`; `render_persona` deterministic + golden;
  no f-string/volatile data in the rendered prefix; default renders to the
  expected Cybersecurity Trainer text; KB slot is an empty/fixed trailing seam.

### 7.2 Plan 03-02 (UI + control channel + live swap)
- New `web/app/PersonaPanel.tsx` (client component beside `VoiceRoom`): role
  textarea, display-name input, three knob selectors (3 options each), voice
  `<select>` from the frozen voice list, an Apply button, and an "applying…/
  applied/error" status line. Inline-styled, thin — mirror `AgentStatePill`/
  `Transcript` conventions (02-01).
- Wire `performRpc("persona.update", payload)` on Apply; show "applying…" until
  ack; render errors (RPC timeout) gracefully.
- Agent: `register_rpc_method("persona.update", handler)` in `entrypoint` after
  connect; handler parses snapshot, `await agent.update_instructions(...)`,
  `session.tts.update_options(voice=...)`, returns `"applied"`.
- Acceptance (sandbox): `next build` clean; panel renders the fields/knobs/voice
  list; RPC method name + payload shape match agent handler; no secret in client.
- Operator gates (VM): edit role/name/knobs/voice in the panel → next turn
  reflects the change without restart; "applying…" shows then clears; voice
  changes on the next utterance without glitching the current one; metrics line
  still emits the unchanged key shape; correction-aggressiveness visibly scales
  PERS-07 behavior.

### 7.3 Requirement → mechanism map

| Req | Mechanism |
|---|---|
| PERS-02 (edit role/instructions) | `PersonaPanel` role textarea → RPC → `update_instructions(render_persona)` |
| PERS-03 (edit display name) | panel name field; carried in payload; (display-name use = UI label / participant name; minimal prompt impact) |
| PERS-04 (knobs) | three enum selectors → fixed-string fragments in `render_persona` |
| PERS-05 (Kokoro voice) | voice `<select>` (curated ids) → `session.tts.update_options(voice=)` |
| PERS-06 (apply w/o restart) | `update_instructions` + `update_options`, no `AgentSession` restart; RPC ack |
| PERS-07 (scaled gentle correction) | `CORRECTION` enum (gentle/moderate/aggressive); default `gentle` preserves PERS-01 |

### 7.4 Display name (PERS-03) — scope note
The display name is primarily a **UI/label** concern (what the user calls the
persona) and optionally a name the agent uses for itself. For byte-stability,
**either** keep the name OUT of the prompt prefix (pure UI label — safest, zero
cache impact) **or** include it as a fixed segment that only changes on edit
(same epoch rule as the rest). MVP-simplest: **name is a UI label + optionally a
single fixed "You are {name}" segment** rendered as a frozen string (rendered on
edit, not per turn). Decide in 03-01; if included in the prompt, it's just another
frozen segment under the epoch rule.

---

## 8. Consolidated [VM-INTROSPECT] checklist (defer like 02-02/02-03)

```
# Hot-swap instructions
python -c "import inspect, livekit.agents as a; print(inspect.signature(a.Agent.update_instructions))"
# TTS runtime voice swap
python -c "import inspect; from livekit.plugins import openai; print(inspect.signature(openai.TTS.update_options))"
python -c "import inspect; from livekit.plugins import openai; print(inspect.signature(openai.TTS.__init__))"
# RPC control channel (Python rtc SDK)
python -c "from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'rpc' in m.lower()])"
python -c "import inspect; from livekit import rtc; print(inspect.signature(rtc.LocalParticipant.register_rpc_method))"
# Kokoro authoritative voice list for the pinned image
curl http://kokoro:8880/v1/audio/voices
# Frozen-prefix proof (Phase-4 gate, seam built here)
#   inspect outgoing /v1/chat/completions body or Ollama prompt-eval logs:
#   unchanged persona prefix => small/near-zero prompt-eval on turn 2
```
Plus live operator gates: panel edit → next-turn change w/o restart; "applying…"
shows/clears; voice swaps on next utterance cleanly; metrics keys unchanged;
PERS-07 scales audibly.

---

## Sources
- LiveKit docs — Tool definition/design (`await agent.update_instructions(...)`,
  `update_tools`, "changes tracked in conversation history") — HIGH
- LiveKit docs — TTS *Update Utterance Options* / Hume plugin
  (`session.tts.update_options(voice=..., speed=...)`, "next utterance") — HIGH
- LiveKit docs — Agent speech & audio (`session.say`, `generate_reply`
  instructions added as trailing system message) — HIGH
- LiveKit docs/products — Agents RPC ("make frontend calls with RPC") — HIGH
- livekit/node-sdks issue #392 — `registerRpcMethod`/`performRpc`
  (`destinationIdentity`, `method`, `payload`), client→agent gotcha — MEDIUM
- Kokoro: hexgrad/Kokoro-82M VOICES.md (voice ids + grades), remsky/Kokoro-FastAPI
  README, community voice-list dumps (`/v1/audio/voices`, `model=tts-1`,
  `voice=af_bella`) — HIGH (voice ids), MEDIUM (per-image exact list)
- Phase 2 memory `mem_mqtoqxd1` — source-verified `livekit-agents ~=1.5`
  AgentSession/metrics surface (1.5.0/1.5.17/1.6.4) — HIGH
- Repo: agent/main.py, agent/metrics.py, web/app/*.tsx, .planning/research/
  {STACK,PITFALLS}.md, .planning/ROADMAP.md — HIGH

---
*Phase 3 research — Persona Layer. Grounded in installed-version docs + Phase-2
source-verified memory; live-build claims tagged [VM-INTROSPECT] for the VM.*
