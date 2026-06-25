# Phase 3 Patterns: Persona Layer

**Status:** NOT greenfield — every touched area has a strong in-repo analog. Phase 1/2
built the full `AgentSession` (`agent/main.py`) with `PERSONA_INSTRUCTIONS` as a static
top block, the per-plugin metrics scaffold (`agent/metrics.py`) with a pure-stdlib
`_self_check()`, and the thin `@livekit/components-react` UI components (`VoiceRoom`,
`AgentStatePill`, `Transcript`). Phase 3 is **"lift the static persona into a rendered
config + add a side-panel editor + an RPC control channel + live hot-swap."** Two net-new
files (`agent/persona.py`, `web/app/PersonaPanel.tsx`); everything else MODIFIES a live
analog.

**Source of file list:** `03-RESEARCH.md` §7.1/§7.2 + the provisional plan split (no
CONTEXT.md — user chose to continue without it). Plans referenced: **03-01** (persona
config → system prompt + voice id + frozen-prefix layout, agent-side pure/testable),
**03-02** (side panel UI + RPC channel + live `update_instructions`/voice swap +
"applying…" feedback).

**Core discipline (carried from Phase 1/2, do not break):**
- **Byte-stability of the persona prefix is the #1 constraint** (Pitfall 7). Knobs map to
  **fixed-string lookups**, never interpolated numbers; the prompt is assembled by joining
  **frozen constants** in a **fixed key order** — no f-strings on runtime data, no
  timestamps / turn counters / UUIDs / `datetime.now()`, no `dict.items()` ordering risk,
  no JSON-in-prefix whitespace drift.
- **Metrics contract is frozen:** per-plugin `metrics_collected` only; the per-turn JSON
  keys (`eou_ms/stt_ms/llm_ttft_ms/tts_ttfb_ms/e2e_ms/over_budget`) must NOT change. Prefer
  `session.tts.update_options(...)` (mutates the existing instance → metrics subscription
  survives) over recreating the TTS plugin (would detach the handler).
- **No `AgentSession` teardown to change persona** (PERS-06). `await agent.update_instructions(...)`
  + `session.tts.update_options(voice=...)` are the in-place mutations.
- Local-first / no egress (PERF-03): voice list is a **frozen constant in code**, not a live
  fetch; reconcile against `curl http://kokoro:8880/v1/audio/voices` once on the VM.
- `OLLAMA_MODEL` is the single LLM-tag source; pin exact npm versions (no float).
- **Sandbox cannot import livekit / no browser / no GPU.** Every claim touching the installed
  build is `[VM-INTROSPECT]` (defer like 02-02/02-03 did). Pure pieces (`render_persona`,
  enum tables, byte-stability test, voice-id list, `next build`) ARE sandbox-verifiable.

---

## Planned files (extracted from RESEARCH.md + plan split)

| # | File (path) | Role | Data flow | In-repo analog | Plan |
|---|-------------|------|-----------|----------------|------|
| 1 | `agent/persona.py` *(new)* | Compute / pure config | `Persona` dataclass + enum→fixed-string knob tables + curated voice-id list + `render_persona(p)→str` + `DEFAULT_PERSONA` + `_self_check()` | **`agent/metrics.py`** (pure module: dataclass, frozen constants, `_self_check()` guarded by `if __name__=="__main__"`) | 03-01 |
| 2 | `agent/main.py` | Orchestration / compute | Lift `PERSONA_INSTRUCTIONS` → `render_persona(DEFAULT_PERSONA)`; named `agent` ref; `KOKORO_VOICE`→`DEFAULT_PERSONA.voice_id`; register RPC handler in `entrypoint`; handler calls `update_instructions` + `update_options` | **self** — `build_session()` / `entrypoint()` / `PERSONA_INSTRUCTIONS` | 03-01 / 03-02 |
| 3 | `agent/metrics.py` | Observability | **No code change** — keep keys/`attach()` intact; persona-swap turn shows elevated `llm_ttft_ms` (expected, don't "fix") | **self** — REUSE AS-IS | (contract only) |
| 4 | `web/app/PersonaPanel.tsx` *(new)* | Frontend / control UI | Role textarea + name input + 3 knob `<select>`s + voice `<select>` + Apply → `performRpc("persona.update", JSON)`; "applying…/applied/error" status line | **`AgentStatePill.tsx`** (thin `"use client"`, inline-styled, reads room context) + `VoiceRoom.tsx` (form/fetch+error state) | 03-02 |
| 5 | `web/app/VoiceRoom.tsx` | Frontend / room shell | Mount `<PersonaPanel />` beside the transcript inside `<LiveKitRoom>` (so it shares the room context for `performRpc`) | **self** — already composes `<AgentStatePill/>`+`<Transcript/>` | 03-02 |
| 6 | (shared voice-id / default constant) | Config seam | Client dropdown list + default persona must match the agent's `DEFAULT_PERSONA` (duplication risk — note in plan) | n/a — cross-language constant | 03-01 / 03-02 |

> **`web/app/AgentStatePill.tsx` and `web/app/Transcript.tsx` are READ-ONLY analogs** for
> the new panel (client-component shape + `@livekit/components-react` hook usage) — they do
> **not** change. The "applying…" indicator is a **separate panel-local state**, NOT
> overloaded onto the global agent-state pill (RESEARCH §1.4).

---

## Role / data-flow classification

**Config (pure, testable) — #1 `agent/persona.py`:** the `Persona` dataclass renders
deterministically to (a) a byte-stable system-prompt string and (b) a Kokoro voice id.
Zero livekit import → fully sandbox-verifiable, exactly like `metrics.py`.

**Control-in (panel → agent) — #4 → RPC → #2:** the browser side panel holds editable form
state and sends a **full persona snapshot** JSON on Apply via
`room.localParticipant.performRpc({ method: "persona.update", payload })`. The agent's
registered handler parses it, applies the swap, and **returns `"applied"`** — the native
RPC return value IS the "applying…→applied" ack (no custom protocol).

**Compute (hot-swap) — #2 `agent/main.py`:** the RPC handler `await`s
`agent.update_instructions(render_persona(p))` (persona text; effective next turn) and calls
`session.tts.update_options(voice=p.voice_id)` (voice; effective next utterance). No session
restart. Source of truth for persona state = the agent process.

**UI-state — #4 panel-local:** an `"idle" | "applying" | "applied" | "error"` union drives
the status line; flips to `applying` before the `await performRpc`, to `applied`/`error`
when it resolves/throws. Independent of `useVoiceAssistant().state`.

**Observability — #3 `agent/metrics.py`:** untouched. The one re-prefill turn after an edit
legitimately flags `over_budget: ["llm_ttft"]` — sanctioned, not a regression.

---

## Pattern A — Pure persona config module (file #1 `agent/persona.py`) — 03-01

**Analog — `agent/metrics.py` is the template for a pure, testable, livekit-free module:**
frozen module-level constants, a `@dataclass`, and a `_self_check()` run under
`if __name__ == "__main__":` (`python3 agent/persona.py`). Mirror its shape exactly.

### A1 — The `Persona` dataclass + frozen knob tables
Lift the three behavioral concerns out of the current `PERSONA_INSTRUCTIONS` literal
(`agent/main.py:62-75`) into enum→fixed-string tables. **Fixed strings, never numbers**
(RESEARCH §4.2): `difficulty="expert"` always yields identical bytes, and a small model
follows an instruction sentence far better than a bare dial reading.
```python
from __future__ import annotations
from dataclasses import dataclass

# Enum → fixed prompt fragment. Hand-authored prose; iterate the WORDS, not a number.
DIFFICULTY: dict[str, str] = {
    "beginner":     "Pitch explanations at an entry level; define jargon as you go.",
    "intermediate": "Assume working familiarity; use standard practitioner terms without over-explaining.",
    "expert":       "Engage at an expert level; skip basics and probe edge cases.",
}
VERBOSITY: dict[str, str] = {
    "terse":    "Keep replies to one or two sentences.",
    "balanced": "Keep replies short and spoken-friendly, a few sentences at most.",
    "detailed": "You may elaborate to several sentences when the topic warrants, still spoken-friendly.",
}
# PERS-07 mechanism — lifts the gentle-correction sentence at main.py:70-72 into a knob.
CORRECTION: dict[str, str] = {
    "gentle":     "When the learner uses imprecise terminology, lightly note the precise term once and move on.",
    "moderate":   "When the learner uses sloppy terminology, correct it toward precise practitioner phrasing and briefly say why.",
    "aggressive": "Actively catch imprecise or wrong terminology every time; restate the precise term and the distinction before continuing.",
}

@dataclass
class Persona:
    role_text: str       # the editable base block (PERS-02)
    display_name: str    # PERS-03 — UI label; see A4 for prompt scope
    difficulty: str      # key into DIFFICULTY
    verbosity: str       # key into VERBOSITY
    correction: str      # key into CORRECTION
    voice_id: str        # Kokoro voice id (PERS-05)
```

### A2 — `render_persona()` — frozen-prefix assembly (the hard rule, RESEARCH §3/§4.1)
Concatenate **frozen constants in a fixed tuple order** with a fixed separator. The KB slot
is an **empty trailing segment** — the Phase-4 seam (persona → KB → history → turn order
frozen NOW). **No volatile data, no f-strings on runtime values, no `dict.items()`.**
```python
ROLE_PREAMBLE = "..."        # the frozen Cybersecurity Trainer role block (from main.py:62-69)
SPOKEN_STYLE_FOOTER = (      # frozen "no markdown/bullets" footer (from main.py:73-74)
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document."
)
KB_SLOT = ""                 # Phase 3: empty fixed seam; Phase 4 fills it (appended AFTER persona)

def render_persona(p: Persona) -> str:
    """Deterministic, byte-stable system prompt. Same p → identical bytes, always."""
    return " ".join((
        p.role_text or ROLE_PREAMBLE,   # editable base; default falls back to frozen preamble
        DIFFICULTY[p.difficulty],
        VERBOSITY[p.verbosity],
        CORRECTION[p.correction],
        SPOKEN_STYLE_FOOTER,
        KB_SLOT,                         # "" in Phase 3 — seam, do not reorder
    ))
```
> **Why join a fixed tuple, not iterate a dict:** dict iteration order is an avoidable
> byte-stability risk. If you ever build from a mapping, iterate a `KNOB_ORDER` tuple
> (RESEARCH §4.1), never `.items()`.

### A3 — `DEFAULT_PERSONA` must reproduce today's behavior (PERS-01 / DEPLOY-03, Pitfall 6.5)
The default = current `PERSONA_INSTRUCTIONS` content, decomposed so `render_persona(DEFAULT_PERSONA)`
is **behaviorally equivalent** to today's static string, with `gentle` correction preserving
PERS-01 and `af_bella` matching `main.py:41`.
```python
DEFAULT_PERSONA = Persona(
    role_text=ROLE_PREAMBLE,
    display_name="Cybersecurity Trainer",
    difficulty="intermediate",
    verbosity="balanced",
    correction="gentle",          # preserves PERS-01 gentle-correction behavior
    voice_id="af_bella",          # matches current main.py KOKORO_VOICE
)
```

### A4 — Display name (PERS-03) scope decision
**MVP-simplest (RESEARCH §7.4): keep `display_name` OUT of the prompt prefix** (pure UI
label → zero cache impact). If a "You are {name}" line is wanted in-prompt, render it as a
**single frozen segment** under the same epoch rule (changes only on edit) — decide in 03-01.
Default: UI label only.

### A5 — Curated voice-id list (PERS-05, RESEARCH §2.3)
A **frozen constant list** (not a live fetch — PERF-03 determinism). Curate ~8–12
English voices; keep `af_bella` default. Reconcile against the server once on the VM.
```python
VOICE_IDS: tuple[str, ...] = (
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_kore",
    "am_michael", "am_fenrir", "am_puck", "am_adam",
    "bf_emma", "bf_alice", "bm_george", "bm_daniel",
)
```
> `[VM-INTROSPECT]` `curl http://kokoro:8880/v1/audio/voices` → validate each id returns
> audio (a bad id → HTTP 422). The **client dropdown must mirror this list** (file #6
> duplication — note in plan; keep in sync via a shared constant or hardcode-to-match).

### A6 — `_self_check()` byte-stability test (Pitfall 6.1) — mirror `metrics.py:269`
Pure stdlib, runnable in the sandbox. Three assertions: **determinism** (same `p` twice →
identical bytes), **golden string** (known `p` → known output), **default-equivalence**
(`render_persona(DEFAULT_PERSONA)` matches the expected Cybersecurity Trainer text). Plus a
**no-volatile-data** smoke check (no digits-that-look-like-timestamps / no `{`-style format
leftovers). Guard with `if __name__ == "__main__":` like `metrics.py:290`.
```python
def _self_check() -> None:
    a = render_persona(DEFAULT_PERSONA)
    b = render_persona(DEFAULT_PERSONA)
    assert a == b, "render_persona is not deterministic"          # byte-stability
    assert a == EXPECTED_DEFAULT, "default persona text drifted"  # golden
    assert "{" not in a and "}" not in a, "format placeholder leaked into prefix"
    print("persona _self_check OK", file=sys.stderr)
```

---

## Pattern B — Agent-side refactor + hot-swap (file #2 `agent/main.py`) — 03-01 / 03-02

### B1 — Lift `PERSONA_INSTRUCTIONS` into the rendered default (03-01)
**Analog — current static literal + inline `Agent(...)`:**
```python
# main.py:62  PERSONA_INSTRUCTIONS = ( "You are a Cybersecurity Trainer: ..." )
# main.py:41  KOKORO_VOICE = "af_bella"
# main.py:237 await session.start(agent=Agent(instructions=PERSONA_INSTRUCTIONS), room=ctx.room)
```
**Phase 3:** import from the new module; render the default; **hold a named `agent` ref** so
the RPC handler can reach it (RESEARCH §1.2). Source `tts` voice from the persona too.
```python
from persona import DEFAULT_PERSONA, render_persona     # new module

# build_session(): tts=openai.TTS(..., voice=DEFAULT_PERSONA.voice_id, ...)  # replaces KOKORO_VOICE

async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = build_session(ctx.proc.userdata["vad"])
    metrics.attach(session)
    agent = Agent(instructions=render_persona(DEFAULT_PERSONA))   # NAMED ref (was inline)
    await session.start(agent=agent, room=ctx.room)
    # ... B2 registers the RPC handler here ...
    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)
```

### B2 — RPC control channel + hot-swap handler (03-02, RESEARCH §5.1)
Register **after `ctx.connect()`** (Gotcha: method must exist before the client calls it).
The handler closes over `agent` and `session`. `update_instructions` is **async (await)**;
`update_options` is **sync** (RESEARCH §1.1/§2.2). Keep the handler light (runs on the agent
event loop — don't block audio).
```python
import json
from persona import Persona, render_persona

async def entrypoint(ctx: JobContext) -> None:
    # ... after session.start(...) ...
    async def handle_persona_update(data):           # data.payload is a JSON string
        snapshot = json.loads(data.payload)
        p = Persona(**snapshot)                       # full-snapshot, idempotent (last-edit-wins)
        await agent.update_instructions(render_persona(p))   # §1 — effective NEXT turn
        session.tts.update_options(voice=p.voice_id)         # §2 — effective NEXT utterance
        return "applied"                              # native RPC ack = "applying…→applied"
    ctx.room.local_participant.register_rpc_method("persona.update", handle_persona_update)
```
> `[VM-INTROSPECT]` (defer — do NOT mark passed in a plan):
> ```
> python -c "import inspect, livekit.agents as a; print(inspect.signature(a.Agent.update_instructions))"
> python -c "import inspect; from livekit.plugins import openai; print(inspect.signature(openai.TTS.update_options))"
> python -c "from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'rpc' in m.lower()])"
> python -c "import inspect; from livekit import rtc; print(inspect.signature(rtc.LocalParticipant.register_rpc_method))"
> ```
> Confirm: `update_instructions` is a coroutine on the `~=1.5` `Agent`; `update_options`
> accepts `voice=`; `register_rpc_method` (snake_case) exists and the handler arg is
> `RpcInvocationData` with `.payload`. **Fallbacks** (RESEARCH §2.2/§5.2): if
> `update_options` is missing → keep a `TTS` ref and recreate just the plugin (then
> **re-attach metrics** — `metrics.attach` binds to the instance); if RPC is missing →
> participant-attributes path (the `AgentStatePill` `lk.agent.state` attribute proves the
> pattern in-repo) with a return-attribute ack.

### B3 — Race / mid-turn safety (Pitfall 6.2/6.3) — already correct by design
An edit arriving mid-generation applies to the **next** turn/utterance; the in-flight turn
finishes under the old persona/voice (no mid-word voice flip). Full-snapshot apply is
idempotent → spam-safe (debounce client-side, last-edit-wins). Nothing extra to build —
just don't auto-edit persona per turn (that would bust the prefix every turn, Pitfall 7).

---

## Pattern C — Persona side panel (file #4 `web/app/PersonaPanel.tsx`) — 03-02

**Analog — `AgentStatePill.tsx` (thin `"use client"`, inline-styled, reads room context via
a `@livekit/components-react` hook) + `VoiceRoom.tsx` (the fetch+`try/catch`+error-state
form pattern at lines 27-64).** Compose these; do not hand-roll `livekit-client` plumbing.

### C1 — Component shape (mirror the repo conventions)
Top-of-file `"use client"`, a small typed status union, inline `style` objects (no CSS
framework — `layout.tsx`/`page.tsx` style), seeded from the default persona so it's
populated on load with no round-trip (RESEARCH §5.3).
```tsx
"use client";
import { useRoomContext } from "@livekit/components-react";
import { useState } from "react";

type ApplyState = "idle" | "applying" | "applied" | "error";

// Mirror agent/persona.py DEFAULT_PERSONA + VOICE_IDS (file #6 — keep in sync).
const VOICE_IDS = ["af_heart", "af_bella", "am_michael", "bf_emma", /* ... */] as const;
const DIFFICULTY = ["beginner", "intermediate", "expert"] as const;
const VERBOSITY  = ["terse", "balanced", "detailed"] as const;
const CORRECTION = ["gentle", "moderate", "aggressive"] as const;

export default function PersonaPanel() {
  const room = useRoomContext();
  const [persona, setPersona] = useState({
    role_text: "", display_name: "Cybersecurity Trainer",
    difficulty: "intermediate", verbosity: "balanced",
    correction: "gentle", voice_id: "af_bella",
  });
  const [status, setStatus] = useState<ApplyState>("idle");
  // ... role textarea, name input, 3 knob <select>s, voice <select>, Apply button ...
}
```

### C2 — Apply → `performRpc` with the "applying…" window (RESEARCH §5.1)
Flip to `applying` before the await; to `applied`/`error` when it resolves/throws. Target
the **agent participant identity** (get it from the room's remote participants / the
`useVoiceAssistant().agent` surface — RESEARCH §5.1 Gotcha).
```tsx
async function apply() {
  setStatus("applying");
  try {
    const agentIdentity = /* agent remote participant identity */;
    await room.localParticipant.performRpc({
      destinationIdentity: agentIdentity,
      method: "persona.update",
      payload: JSON.stringify(persona),    // shape MUST match agent Persona(**snapshot)
    });
    setStatus("applied");
  } catch {
    setStatus("error");                    // RPC timeout / no agent → graceful
  }
}
```
> `[VM-INTROSPECT]` confirm `performRpc`/`registerRpcMethod` on the pinned
> `livekit-client@2.20.0` (already pinned). Payload (a few hundred chars) is well within RPC
> limits. **No secret in the client** — the panel only sends persona text/enums/voice id.

### C3 — Knob/voice controls = simple `<select>`s
Three 3-option selectors (difficulty/verbosity/correction) + one voice dropdown from the
frozen `VOICE_IDS`. The value is the enum **key** (matches the agent's table keys); labels
may be friendlier than keys (RESEARCH §4.3). Role = `<textarea>` (PERS-02), name = `<input>`
(PERS-03).

---

## Pattern D — Mount the panel in the room shell (file #5 `web/app/VoiceRoom.tsx`) — 03-02

**Analog — current composition inside `<LiveKitRoom>` (`VoiceRoom.tsx:69-82`):**
```tsx
    <LiveKitRoom serverUrl={SERVER_URL} token={token} connect audio video={false} ...>
      <RoomAudioRenderer />
      <StartAudio label="Click to enable audio" />
      <AgentStatePill />
      <Transcript />
    </LiveKitRoom>
```
**Phase 3:** add `<PersonaPanel />` as a sibling **inside** `<LiveKitRoom>` so it shares the
room context (`useRoomContext`/`performRpc` need it). Lay it out as a side panel beside the
transcript (inline-styled fl/`display:flex`, matching the repo's no-framework style).
```tsx
      <AgentStatePill />
      <PersonaPanel />     {/* new — must be INSIDE LiveKitRoom for room context */}
      <Transcript />
```

---

## Pattern E — Metrics contract is frozen (file #3 `agent/metrics.py`) — verify, do NOT edit

No code change. The persona-swap turn shows an **elevated `llm_ttft_ms`** (cold-prefix
re-prefill) and correctly flags `over_budget: ["llm_ttft"]` for that one turn — **expected,
do not "fix"** (RESEARCH §6.4). Because `update_options` mutates the **existing**
`session.tts` instance, the `metrics_collected` subscription bound in `attach()`
(`metrics.py:250-266`) **survives** the voice swap — a concrete reason to prefer
`update_options` over recreating the plugin. The per-turn key set
(`{"eou_ms","stt_ms","llm_ttft_ms","tts_ttfb_ms","e2e_ms","over_budget"}`, asserted in
`_self_check` at `metrics.py:284`) must stay byte-for-byte identical.

---

## The "persona epoch" model (carry into both plans) — RESEARCH §3.4

Within a session the persona prefix is **frozen until the user edits it**. Each edit starts a
**new epoch**: the next turn re-prefills (the "applying…" turn), then the prefix is frozen
again and caches from the turn after. **Persona edits are the ONLY sanctioned prefix change,
they are user-initiated, and each costs exactly one re-prefill** — never silent per-turn
busting. This is what the byte-stability test (A6) and the frozen-prefix assembly (A2)
protect, and it is the seam Phase 4's KB cache depends on.

---

## Notes for the planner

- **Reuse, don't re-plumb.** Token route, `build_session()` transport wiring, the metrics
  `attach()` surface, the `<LiveKitRoom>` shell, and `AgentStatePill`/`Transcript` are DONE —
  extend only. Two net-new files (`agent/persona.py`, `PersonaPanel.tsx`).
- **03-01 is almost entirely sandbox-verifiable** (pure module): `py_compile` /
  `python3 agent/persona.py` self-check (determinism + golden + default-equivalence),
  no f-string/volatile data in the rendered prefix, KB slot is an empty trailing seam.
  Treat live `update_instructions`/voice swap/RPC round-trip as **operator gates** on the VM.
- **03-02 sandbox acceptance:** `next build` clean; panel renders fields/knobs/voice list;
  RPC method name (`persona.update`) + payload shape match the agent handler
  (`Persona(**snapshot)`); no secret in the client. **Operator gates:** edit
  role/name/knobs/voice → next turn reflects it without restart; "applying…" shows then
  clears; voice changes on the next utterance without glitching the current one; metrics
  line keys unchanged; PERS-07 correction scales audibly.
- **File #6 duplication risk:** the client `VOICE_IDS`/default persona must mirror
  `agent/persona.py`. MVP-acceptable to hardcode-to-match; note the drift risk (optionally a
  `persona.get` RPC later, but not MVP).
- **Defer every `[VM-INTROSPECT]` (do not mark passed in a plan)** — same discipline as
  02-02's `generate_reply` / 02-03's endpointing gates. Consolidated checklist in
  RESEARCH §8.

## Requirement → mechanism map (from RESEARCH §7.3)

| Req | Mechanism | Files |
|---|---|---|
| PERS-02 (edit role/instructions) | role textarea → RPC → `update_instructions(render_persona)` | #4 → #2 → #1 |
| PERS-03 (edit display name) | panel name field in payload; UI label (out of prefix, MVP) | #4 (#1 if in-prompt) |
| PERS-04 (knobs) | 3 enum `<select>`s → fixed-string fragments | #4 → #1 |
| PERS-05 (Kokoro voice) | voice `<select>` (curated ids) → `session.tts.update_options(voice=)` | #4 → #2 |
| PERS-06 (apply w/o restart) | `update_instructions` + `update_options`, no session restart; RPC ack | #2 |
| PERS-07 (scaled gentle correction) | `CORRECTION` enum (gentle default preserves PERS-01) | #1 |

## Build order (vertical slices, from RESEARCH §7)
1. **03-01** — `agent/persona.py` (dataclass + knob tables + `render_persona` + voice list +
   `DEFAULT_PERSONA` + `_self_check`); refactor `main.py` to render the default + named
   `agent` ref + voice from persona. Pure/testable in the sandbox.
2. **03-02** — `PersonaPanel.tsx` (role/name/knobs/voice + Apply + status line); mount in
   `VoiceRoom`; `performRpc("persona.update")` → agent `register_rpc_method` handler doing
   `update_instructions` + `update_options` → `"applied"` ack.

**Phase-3 done = a live-editable persona** (role/name/knobs/voice) applied within the current
session without restart, with an "applying…/applied" signal, byte-stable prefix preserved,
the metrics contract untouched, and PERS-01 defaults unchanged on load.

---
*Phase 3 patterns — mostly MODIFY against live Phase-1/2 analogs; two thin net-new files.
Mapped against `agent/main.py`, `agent/metrics.py`, `web/app/*.tsx`. Live-build claims tagged
`[VM-INTROSPECT]` for the VM.*
