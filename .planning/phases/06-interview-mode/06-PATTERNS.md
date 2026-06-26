# Phase 6 Patterns: Interview Mode — File-by-File Analog Map

**Phase goal:** Add a constrained `ask → listen → critique → model-answer → next`
dialogue contract over the *same* STT→LLM→TTS pipeline, toggled from the side panel
with a target-role picker, plus a slow-speech endpointing re-tune.

**Source:** `06-RESEARCH.md` (no CONTEXT.md exists for this phase). The research
recommends **Option B** (single prompt-shaped agent), reusing the persona-hot-swap
machinery rather than multi-agent handoff.

This document maps each file to be created/modified onto its closest existing analog
in the codebase, with concrete code excerpts, so the planner can write `read_first`
lists and concrete actions. Files are grouped by the slice they land in (06-01
wiring/UX, 06-02 quality/tuning).

---

## File inventory (from RESEARCH §8 + §2)

| # | File | Role | Action | Closest analog |
|---|---|---|---|---|
| 1 | `agent/interview.py` | NEW pure module (livekit-free, `_self_check`-guarded) | create | `agent/kb/distill.py` (frozen prompt consts) + `agent/persona.py` (enum→string + `render_*` + golden) + `agent/history.py` (tiny pure decision + self-check) |
| 2 | `agent/main.py` | MODIFY worker wiring | edit | self — clone `handle_persona_update` (308–314) for `mode.update`; mutable holder like `current_persona` (290); `generate_reply` like greeting (401) / KB priming (390) |
| 3 | `web/app/InterviewPanel.tsx` | NEW control panel (client→agent RPC) | create | `web/app/PersonaPanel.tsx` (form state + `performRpc`) + role list seam |
| 4 | `web/app/VoiceRoom.tsx` | MODIFY side-panel row | edit | self — the panel row at lines 83–87 |
| 5 | endpointing re-tune | MODIFY `turn_handling` / per-`Agent` override | edit (06-02) | `agent/main.py:180–188` `build_session` dict [VM-INTROSPECT] |

**Hand-sync seam (accepted, documented):** the role keys in `agent/interview.py`
(`ROLES`) and `web/app/InterviewPanel.tsx` are hand-mirrored exactly like
`PersonaPanel.tsx` mirrors `persona.py` (there is no `mode.get`/`persona.get` RPC).

---

## File 1 — `agent/interview.py` (NEW, pure module)

**Role:** Sandbox-testable core. Holds `ROLES` (enum→fixed-string), the rubric
constants, `render_interview_prompt(role_key)`, and (optionally, Layer 2 only) an
`InterviewState` enum + `next_directive(state)`. Livekit-free; `_self_check()`
guarded by `if __name__ == "__main__":`. The **effect** (`update_instructions`,
`generate_reply`, `turn_ctx` directives) lives in `main.py`, never here — exactly
how `history.py` owns the decision and `HistoryWindowAgent` owns the effect.

**Data flow:** pure function of a `role_key: str` → byte-stable system prompt string.
No network, no rtc-SDK, no volatile data.

### Analog A — `agent/persona.py` (enum→string knobs + `render_*` + golden + self-check)

The byte-stability discipline to copy verbatim. Enum→fixed-string table:

```python
# agent/persona.py:28-32
DIFFICULTY: dict[str, str] = {
    "beginner":     "Pitch explanations at an entry level; define jargon as you go.",
    "intermediate": "Assume working familiarity; use standard practitioner terms without over-explaining.",
    "expert":       "Engage at an expert level; skip the basics and probe edge cases.",
}
```

`ROLES` mirrors this shape exactly — `role_key → fixed role descriptor`, hand-authored
prose, identical bytes per key:

```python
# agent/interview.py (to write) — mirror DIFFICULTY/VERBOSITY/CORRECTION
ROLES: dict[str, str] = {
    "soc_analyst":       "...fixed descriptor of a SOC analyst interview target...",
    "security_engineer": "...fixed descriptor...",
    "grc":               "...fixed descriptor...",
}
```

The `render_prompt` join discipline — FROZEN CONSTANTS in FIXED tuple order, single
separator, opaque inputs, no interpolation on runtime data:

```python
# agent/persona.py:135-142
    return " ".join((
        p.role_text or ROLE_PREAMBLE,
        DIFFICULTY[p.difficulty],
        VERBOSITY[p.verbosity],
        CORRECTION[p.correction],
        SPOKEN_STYLE_FOOTER,
        kb_segment,
    ))
```

`render_interview_prompt(role_key)` assembles the Interview system block the same way:
`[interview framing] [ROLES[role_key]] [one-question rule] [rubric/critique contract]
[SPOKEN_STYLE_FOOTER]` — fixed order, frozen constants.

The golden-string + `_self_check` pattern to replicate (determinism, golden render,
no `{` leak, every enum key renders identical bytes and lands in output):

```python
# agent/persona.py:186-238  (the test shape to mirror)
def _self_check() -> None:
    a = render_persona(DEFAULT_PERSONA)
    b = render_persona(DEFAULT_PERSONA)
    assert a == b, "render_persona is not deterministic"
    assert a == EXPECTED_DEFAULT, "default persona text drifted from golden"
    assert "{" not in a and "}" not in a, "format placeholder leaked into prefix"
    ...
    for field, table in knob_tables:
        for key in table:
            ...
            assert table[key] in r1, f"{field}={key} fragment missing from render"
    print("persona _self_check OK", file=sys.stderr)

if __name__ == "__main__":
    _self_check()
```

`interview._self_check()` should assert: `render_interview_prompt(role)` is
deterministic; for every key in `ROLES` the descriptor lands in the render; no `{`/`}`
leak; a golden render for the default role. **This is the sandbox-verifiable test the
phase's testable logic lives in** (RESEARCH §9 line 9).

### Analog B — `agent/kb/distill.py` (frozen instruction blocks → the rubric)

The 06-02 rubric constants copy `DISTILL_INSTRUCTION`'s frozen-multiline-prose shape
(explicit structure, no markdown/JSON, example-of-shape):

```python
# agent/kb/distill.py:44-59
DISTILL_INSTRUCTION: str = (
    "You are preparing reference material for a spoken coaching session. Read the "
    "source material below and produce TWO sections, plain text only (no markdown, "
    "no JSON, no code fences).\n"
    ...
    "Example output (shape only — use the real source's facts, not these):\n"
    ...
)
```

The interview rubric ("technical accuracy, completeness, precise terminology,
structure → brief critique → strong model answer") is a frozen constant of this exact
form. **Qualitative structure, NO numeric score** (REQUIREMENTS line 107, out of
scope). Structure compensates for the 4B model's depth (Pitfall 11).

### Analog C — `agent/history.py` (minimal pure decision + self-check size)

If Layer 2 (explicit state enum) is needed, mirror `history.py`'s tiny pure-decision +
self-check footprint — small constants, typed returns, `_self_check` guarded:

```python
# agent/history.py:31-38
def should_trim(item_count: int) -> bool:
    return item_count > HISTORY_MAX_ITEMS

def window_target() -> int:
    return HISTORY_MAX_ITEMS
```

`next_directive(state) -> str` would be the analogous pure function returning the
transient per-turn directive string. **Start Layer 1 (prompt-only); only add this if
the §6 quality gate shows drift** (RESEARCH §4, §9 q3 — don't pre-build Layer 2).

### Invariants this module enforces by construction
- Byte-stability: enum→fixed-string, fixed order, no interpolated numbers (RESEARCH §7.2).
- Livekit-free → sandbox-importable (the VM-introspect tax does not apply here).
- No second hardcoded LLM tag *here* (this module renders prompts only; any LLM call
  is in `main.py` and resolves from `OLLAMA_MODEL`).

---

## File 2 — `agent/main.py` (MODIFY — RPC handler + mutable holder + first question)

**Role:** Wire the effects. Add a `mode.update` RPC handler, a mutable mode/role
holder composed into `update_instructions`, and a `generate_reply` to ask the first
question on mode-enter. The `on_user_turn_completed` hook is the listen-complete
boundary for any Layer-2 state machine.

**Data flow:** client RPC (JSON snapshot) → handler → mutable holder write +
`agent.update_instructions(render…)` (async, next-turn) + `generate_reply` (ask Q1).

### Analog A — `handle_persona_update` (the EXACT RPC template to clone) — main.py:308–319

```python
# agent/main.py:308-319
    async def handle_persona_update(data):
        snapshot = json.loads(data.payload)
        p = Persona(**snapshot)
        current_persona[0] = p
        await agent.update_instructions(render_prompt(p, session_kb.brief))
        session.tts.update_options(voice=p.voice_id)
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "persona.update", handle_persona_update
    )
```

`handle_mode_update` clones this exactly: parse JSON `{mode, role_key}`, write the
mutable mode holder, call `update_instructions` with the composed render, return
`"applied"`. The native RPC return value **is** the applying→applied ack (no custom
protocol). Register AFTER `session.start` so the method exists before the client calls.

**Composition decision (RESEARCH §9 q5):** the render must compose mode × persona × KB.
The handler should call a single render that selects the Interview block when
interview mode is active, else the Learn (persona) block — under the current persona
and current `session_kb.brief`. Model the mode/role as a **third mutable axis**
alongside `current_persona`.

### Analog B — the mutable holder pattern — main.py:290

```python
# agent/main.py:290
    current_persona: list[Persona] = [DEFAULT_PERSONA]
```

Add a parallel `current_mode: list[...] = [LEARN]` (or a small mode/role holder) so
all three closures (`handle_persona_update`, `ingest_kb`, `handle_mode_update`)
read/write the same reference and the renders compose (the "(persona × KB × mode)
epoch" model). **MODE-01: default = Learn**, exactly as `DEFAULT_PERSONA` is default-
on-load.

### Analog C — `generate_reply` to ask the first question — main.py:390 & 401

Two existing internal-reply call sites are the template for "ask Q1 on mode-enter":

```python
# agent/main.py:390-392  (KB priming turn — internal reply)
        await session.generate_reply(
            instructions="(internal) acknowledge the loaded material briefly"
        )

# agent/main.py:401  (greeting — agent speaks first)
    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)
```

After `update_instructions` in `handle_mode_update`, fire one
`session.generate_reply(instructions="(internal) ask the first <role> interview
question")` — MODE-04 "one question, then wait" (RESEARCH §3 Option B, §4 *ask*).

### Analog D — `on_user_turn_completed` hook — main.py:246–263 (the listen-complete boundary)

```python
# agent/main.py:260-263
    async def on_user_turn_completed(self, turn_ctx, new_message):
        if history.should_trim(len(self.chat_ctx.items)):
            trimmed = self.chat_ctx.copy().truncate(max_items=history.window_target())
            await self.update_chat_ctx(trimmed)
```

This fires *after the user's answer is transcribed, just before the LLM reply* — the
exact "listen complete → now critique" boundary (RESEARCH §2.1, §4). **INVARIANT
(RESEARCH §7.6):** if a Layer-2 state machine also hooks this method, **compose** with
the existing history-trim — do NOT replace it. Layer-2 per-turn directives go into the
transient `turn_ctx`, **never** `instructions` (RESEARCH §7.1).

### Invariants enforced in main.py
- Flat-TTFT / frozen-prefix: mode toggle is a **one-time re-prefill** (same cost model
  as a persona edit). Never re-render the prefix per turn (RESEARCH §7.1, Pitfall 7).
- No second hardcoded LLM tag: any new LLM call resolves from `OLLAMA_MODEL` via
  `resolved_llm_tag()` (main.py:71) — RESEARCH §7.4.
- Thinking stays OFF: critique runs through the existing
  `with_ollama(reasoning_effort="none")` (main.py:131–135) — RESEARCH §7.5, §6.

---

## File 3 — `web/app/InterviewPanel.tsx` (NEW — clone PersonaPanel)

**Role:** Side-panel control: mode toggle + role `<select>`. Holds local form state,
targets the agent identity, sends a full snapshot over the `mode.update` RPC. The RPC
return is the applying→applied ack.

**Data flow:** local React state → `performRpc({ method: "mode.update", payload })`
→ agent handler.

### Analog — `web/app/PersonaPanel.tsx` (the exact template)

The agent-identity targeting + `performRpc` core to copy verbatim (only `method` and
`payload` keys change):

```tsx
// web/app/PersonaPanel.tsx:93-118
  async function apply() {
    setStatus("applying");
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    if (!agentIdentity) {
      setStatus("error");
      return;
    }
    try {
      await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "persona.update",      // → "mode.update"
        payload: JSON.stringify(persona), // → JSON.stringify({ mode, role_key })
      });
      setStatus("applied");
    } catch {
      setStatus("error");
    }
  }
```

The `ApplyState` union + STATUS_LABEL/STATUS_COLOR + `panelStyle`/`inputStyle`/
`labelStyle` and the `<select>` rendering are all directly reusable:

```tsx
// web/app/PersonaPanel.tsx:20, 143-154  (state union + a select to copy)
type ApplyState = "idle" | "applying" | "applied" | "error";
...
        <select style={inputStyle} value={persona.difficulty}
          onChange={(e) => set("difficulty", e.target.value)}>
          {DIFFICULTY.map((d) => (<option key={d} value={d}>{d}</option>))}
        </select>
```

The role `<select>` maps over a hand-mirrored role list — **the same duplication seam**
PersonaPanel documents (PersonaPanel.tsx:6–18). Keep the role keys byte-identical to
`agent/interview.py` `ROLES` by hand:

```tsx
// web/app/PersonaPanel.tsx:6-18  (the duplication-seam comment to replicate)
// File #6 duplication seam: these arrays ... MUST mirror agent/persona.py ...
// There is no persona.get RPC in the MVP, so drift here is silent — keep in sync
// by hand.
const DIFFICULTY = ["beginner", "intermediate", "expert"] as const;
```

`InterviewPanel.tsx` adds `const ROLES = ["soc_analyst", "security_engineer", "grc"]
as const;` with the same hand-sync warning, plus a mode toggle (checkbox/two-button).

### Optional — agent→UI state push (only if MVP needs visible confirmation)

If the toggle needs a visible "Interview mode — interviewing for SOC analyst" badge or
a question counter, mirror `KbPanel.tsx`'s agent→client attribute-read pattern (RESEARCH
§2.3, §9 q4). **Lean MVP: RPC ack only.** Reserve this if needed:

```tsx
// web/app/KbPanel.tsx:78-91  (agent→client attribute read — the fallback pattern)
  const { attributes } = useParticipantAttributes({ participant: agent });
  useEffect(() => {
    const raw = attributes?.[KB_STATE_ATTRIBUTE];
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as { status?: KbStatus; docs?: number; error?: string };
      if (parsed.status) setStatus(parsed.status);
      ...
    } catch { /* ignore malformed */ }
  }, [attributes]);
```

---

## File 4 — `web/app/VoiceRoom.tsx` (MODIFY — add panel to the row)

**Role:** Slot `<InterviewPanel />` into the existing side-panel row. One import + one
JSX line.

### Analog — the existing panel row (self) — VoiceRoom.tsx:5–8, 83–87

```tsx
// web/app/VoiceRoom.tsx:5-8  (imports)
import AgentStatePill from "./AgentStatePill";
import KbPanel from "./KbPanel";
import PersonaPanel from "./PersonaPanel";
import Transcript from "./Transcript";

// web/app/VoiceRoom.tsx:83-87  (the row)
      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
        <PersonaPanel />
        <KbPanel />
        <Transcript />
      </div>
```

Add `import InterviewPanel from "./InterviewPanel";` and place `<InterviewPanel />` in
the row (RESEARCH §2.3 line 54). Must render inside `<LiveKitRoom>` for room context
(same as the other panels).

---

## File 5 — Endpointing re-tune (MODIFY — 06-02, MODE-05) [VM-INTROSPECT]

**Role:** Slow-speech endpointing profile so deliberate "let me think…" answers aren't
cut mid-thought. Conversational `min_delay 0.3 / max_delay 3.0` → interview
`~0.6–0.8 / ~5.0–6.0`.

### Analog — the single endpointing surface (self) — main.py:180–188

```python
# agent/main.py:180-188  (the ONLY endpointing knob today)
        turn_handling={
            "turn_detection": MultilingualModel(),
            "endpointing": {"mode": "dynamic", "min_delay": 0.3, "max_delay": 3.0},
            "interruption": {
                "min_duration": 0.3,
                "resume_false_interruption": True,
                "false_interruption_timeout": 2.0,
            },
        },
```

### The open design question — how to SWITCH profiles (RESEARCH §5, ordered preference)

1. **Per-`Agent` override (cleanest):** `Agent.__init__` in `~=1.5` may accept
   `min_endpointing_delay` / `max_endpointing_delay` / `turn_detection` /
   `allow_interruptions`. **[VM-INTROSPECT first]** — confirm with
   `inspect.signature(Agent.__init__)` on the installed pin BEFORE relying on it.
2. **Runtime mutation** of session turn options (`session.update_options(...)`) —
   **unconfirmed**; memory note lists no runtime setter. [VM-INTROSPECT.]
3. **Session-level profile chosen at start (MVP-safe fallback):** set the interview-
   friendly profile as the single session profile, or document mode-before-start. The
   lowest-risk ladder fallback if 1/2 don't pan out.

**Plan 06-02 must [VM-INTROSPECT] mechanism 1 first; do NOT assume a runtime
`turn_handling` setter exists.** Keep `MultilingualModel()` as the semantic decider;
VAD `activation_threshold=0.65` (prewarm, main.py:207) stays (orthogonal).

### Metrics interpretation (RESEARCH §2.4, §7.7)

Raising `min_delay` deliberately exceeds `BUDGET_MS["eou"]=300` (metrics.py:30–37), so
interview turns flag `over_budget:["eou"]`. **This is expected and correct, not a
regression** — plan so the metrics line isn't misread.

---

## Cross-cutting invariants (RESEARCH §7 — must not break)

1. **Flat-TTFT / frozen-prefix (keystone, Pitfall 7):** mode toggle/role pick =
   one-time user-initiated re-prefill. NEVER re-render the prefix per turn. Per-turn
   directives → transient `turn_ctx`, not `instructions`. Compose mode × persona × KB
   the way `handle_persona_update` composes today.
2. **Byte-stability:** role descriptors + rubric are enum→fixed-string constants in
   fixed order (mirror `persona.py`). No interpolated numbers/timestamps/dict-order.
3. **Local-first (PERF-03):** interview prompts/roles/critiques all local. No cloud.
4. **No second hardcoded LLM tag:** resolve from `OLLAMA_MODEL`
   (`resolved_llm_tag` / `kb/distill._resolved_llm_tag`).
5. **Thinking stays OFF** on the hot path (`reasoning_effort="none"`); depth from
   prompt structure, not reasoning tokens (§6).
6. **History windowing still applies:** if a state machine also hooks
   `on_user_turn_completed`, compose with the trim — don't replace it.
7. **Metrics:** slow-speech `min_delay` → `over_budget:["eou"]` on interview turns is
   expected.

---

## Suggested slice boundaries (RESEARCH §1)

- **06-01 (wiring/UX):** Files 1 (ROLES + `render_interview_prompt` + self-check,
  Layer 1), 2 (`mode.update` handler + holder + ask-Q1), 3 (InterviewPanel), 4
  (VoiceRoom row). Start prompt-only (Layer 1).
- **06-02 (quality/tuning):** Rubric constants in File 1; File 5 endpointing re-tune
  [VM-INTROSPECT]; the strong-vs-weak critique quality gate (§6); 24GB fallback
  **documented** (not built) — `OLLAMA_MODEL` swap, VRAM math, trigger condition.
