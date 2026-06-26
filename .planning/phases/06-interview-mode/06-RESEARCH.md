# Phase 6 Research: Interview Mode

**Phase goal:** Add a constrained dialogue state machine over the *same* pipeline. The user toggles Interview Mode and picks a target role; the agent asks one realistic role-relevant question at a time, waits for the spoken answer, then critiques it and demonstrates a strong model answer — with a re-tuned slow-speech endpointing profile.

**Requirements:** MODE-01, MODE-02, MODE-03, MODE-04, MODE-05
**Depends on:** Phase 5 (History Management) — complete.
**Mode:** mvp (vertical slice). No CONTEXT.md exists; planning proceeds from this research.

**Verification note (carried from every prior phase):** the execution sandbox has **no Docker / GPU / Ollama / browser and cannot `import livekit`**. Every claim about a *live* LiveKit API surface is tagged **[VM-INTROSPECT]** and must be confirmed on the Proxmox VM with an `inspect.signature(...)` probe before it is trusted — exactly the Phase 2/3/4/5 precedent. Pure modules (a `mode.py`/`interview.py` config + render + `_self_check()`) ARE sandbox-verifiable and should carry the testable logic.

---

## 1. What this phase actually is

It is **not** a new pipeline. It is a *second conversational contract* layered over the working STT→LLM→TTS loop:

- **Learn/Converse (default, MODE-01):** today's open Cybersecurity Trainer behavior — already shipped (Phases 2–5). Nothing to build except making it the explicit "default mode".
- **Interview (MODE-02..05):** a constrained turn structure — `ask → listen → critique → model-answer → next` — driven by prompt shaping (and optionally a per-turn state machine), plus a slower endpointing profile so deliberate "let me think…" answers don't get cut off.

The roadmap pre-seeds two plans, and they map cleanly to a **wiring/UX slice** then a **quality/tuning slice**:

- **06-01:** Mode toggle + role picker + Interview state machine (the loop).
- **06-02:** Rubric-structured critique prompts + slow-speech endpointing re-tune + 24GB fallback documented.

---

## 2. How the existing pipeline is wired (concrete)

Read these files before planning; the integration seams are precise.

### 2.1 Agent worker — `agent/main.py`
- **`build_session(vad)`** constructs the single `AgentSession` with STT (faster-whisper), LLM (`openai.LLM.with_ollama(reasoning_effort="none")`), TTS (Kokoro), and the **session-level** `turn_handling` dict (lines 180–188):
  ```python
  turn_handling={
      "turn_detection": MultilingualModel(),
      "endpointing": {"mode": "dynamic", "min_delay": 0.3, "max_delay": 3.0},
      "interruption": {"min_duration": 0.3, "resume_false_interruption": True,
                       "false_interruption_timeout": 2.0},
  }
  ```
  **This is the single endpointing surface today — the slow-speech re-tune lives here (see §5).**
- **`HistoryWindowAgent(Agent)`** (lines 246–263) is the live Agent subclass. It overrides `on_user_turn_completed(turn_ctx, new_message)` to window-trim history. **This is the natural hook for an Interview state machine** — `on_user_turn_completed` fires *after the user's spoken answer is transcribed, just before the LLM reply* — i.e. exactly the "listen complete → now critique" boundary.
- **`entrypoint(ctx)`** (lines 266–401): `ctx.connect()` → `build_session` → `metrics.attach` → builds the agent with `render_prompt(DEFAULT_PERSONA, "")` → `session.start(agent, room)` → registers the `persona.update` RPC → registers the `kb.upload` byte-stream handler → fires the greeting via `session.generate_reply(...)`.
- **Persona hot-swap (the template to copy):** `handle_persona_update(data)` (lines 308–314) is the proven **client→agent control channel**: a JSON snapshot over the `persona.update` RPC → `agent.update_instructions(render_prompt(p, brief))` (async, next-turn) + `session.tts.update_options(voice=...)` (sync). **Mode toggle + role pick should reuse this exact RPC pattern** (a `mode.update` RPC), not invent a new transport.
- **`current_persona: list[Persona]`** (line 290) is the mutable holder so persona × KB compose. Interview mode is a third axis — model it the same way (a mutable mode/role holder, composed into `update_instructions`).

### 2.2 Prompt assembly — `agent/persona.py`
- **`render_prompt(p: Persona, kb_brief="")`** (lines 116–142) joins FROZEN CONSTANTS in fixed order:
  `[role_text] [DIFFICULTY] [VERBOSITY] [CORRECTION] [SPOKEN_STYLE_FOOTER] [kb_segment]`.
- Knobs are **enum → fixed-string** lookup tables (`DIFFICULTY`, `VERBOSITY`, `CORRECTION`), never interpolated numbers — the byte-stability rule that protects the KB prefix cache (Pitfall 7).
- **The frozen prefix is `[persona] + [KB] + [history] + [turn]`.** Interview mode changes the *system instruction block* (which role to interview for, how to critique). **Changing the system block is a sanctioned one-turn re-prefill** (same cost model as a persona edit): the toggle/role-pick is user-initiated and infrequent, so the one elevated-TTFT turn is acceptable. It MUST NOT be re-rendered per turn (that would bust the cache every turn — Pitfall 7 / §7 below).

### 2.3 Web UI — `web/app/`
- **`VoiceRoom.tsx`** is the room shell. The side panel row (lines 83–87) renders `<PersonaPanel /> <KbPanel /> <Transcript />`. **An `<InterviewPanel />` (mode toggle + role picker) slots in here**, same row.
- **`PersonaPanel.tsx`** is the exact template for a new control panel: it holds local form state, targets the agent participant identity (`useVoiceAssistant().agent?.identity`), and calls `room.localParticipant.performRpc({ destinationIdentity, method: "persona.update", payload })`. The RPC return value *is* the applying→applied ack. **Copy this for `mode.update`.**
- **`KbPanel.tsx`** shows the *other* direction: agent→client status via a participant **attribute** (`kb.state`) read with `useParticipantAttributes`. Use this pattern if the agent needs to push interview state (e.g., current question number) back to the UI — though for MVP the toggle/role RPC ack may be enough.
- **Duplication seam (documented, accepted):** `PersonaPanel.tsx` hand-mirrors the agent's enum lists (there is no `persona.get` RPC). An Interview role list will have the **same hand-sync seam** — keep the role keys identical in `agent/` and `web/` by hand, and document it like the persona one.

### 2.4 Metrics — `agent/metrics.py`
Per-stage metrics are attached per-plugin (`metrics.attach(session)`). The slow-speech re-tune (§5) will visibly raise `eou_ms` (end-of-utterance delay) — that is **expected and correct**, not a regression. Note the budget constant `BUDGET_MS["eou"]=300`; a slow-speech `min_delay` deliberately exceeds the conversational budget, so interview turns will flag `over_budget:["eou"]`. Plan for this (either accept the flag in interview mode or scope the budget) so the metrics line isn't misread as a bug.

---

## 3. LiveKit API surface for the state machine (the key technical decision)

There are **three viable ways** to implement the `ask → listen → critique → model-answer → next` loop. Recommendation: **Option B (prompt-shaped single agent)** for the MVP, with Option A noted as the idiomatic-but-heavier alternative.

### Option A — Multi-Agent handoff (idiomatic LiveKit)
LiveKit's documented pattern is **agent handoff**: distinct `Agent` subclasses, each with its own `instructions` and its own `on_enter()` that calls `self.session.generate_reply(...)`. A `@function_tool` returns `NewAgent(chat_ctx=self.chat_ctx)` to hand off. [VM-INTROSPECT: confirm `Agent.on_enter`, tuple-return handoff signature on the installed `~=1.5` pin.]
- **Fit:** Could model `LearnAgent` ⇄ `InterviewAgent`. `on_enter` makes the agent *ask the first question on entry* cleanly.
- **Cost / risk:** Handoff via `@function_tool` lets the **LLM** decide when to switch — but our toggle is **user-driven via UI**, not LLM-driven. You'd be swapping the agent object imperatively from the RPC handler, not via a tool. Also a new `InterviewAgent` instance means re-establishing `chat_ctx` and re-rendering instructions = a re-prefill. Heavier than needed for a 4B model on a tight latency budget.
- **Verdict:** Over-engineered for MVP (CODE_PRINCIPLES §7 YAGNI). Keep in back pocket if prompt-shaping proves insufficient.

### Option B — Single agent, prompt-shaped contract (RECOMMENDED)
Keep one `HistoryWindowAgent`. Mode + role live in a mutable holder (like `current_persona`). `update_instructions` swaps the system block between a **Learn prompt** and an **Interview prompt** when the user toggles. The Interview system prompt itself encodes the contract: *"Ask ONE role-relevant question. After the user answers, give a short critique, then demonstrate a strong model answer, then ask the next question."*
- **Why this fits the codebase:** It is the **persona hot-swap pattern already proven end-to-end** (§2.1). One re-prefill on toggle; per-turn behavior is steered by the static instruction block (byte-stable, cache-safe).
- **Asking the first question on entry:** the `mode.update` RPC handler, after `update_instructions`, fires one `session.generate_reply(instructions="(internal) ask the first <role> interview question")` — mirroring the existing greeting and KB-priming-turn calls.
- **The state machine is mostly the LLM following the instruction.** If you want *hard* structure (guarantee exactly one question, prevent the model from critiquing before the answer), add a lightweight explicit state enum (§4) checked in `on_user_turn_completed` and inject a per-turn *directive* into `turn_ctx` (the transient, non-frozen edit) — NOT into `instructions`.

### Option C — Fully code-driven turn control (manual)
Use `turn_detection="manual"` + explicit `generate_reply` calls to fully control timing. Overkill and fights the semantic-endpointing design. Reject.

**Recommendation:** **Option B.** It reuses the persona-swap machinery, keeps the frozen-prefix invariant, and concentrates the work in (1) a pure prompt-render module and (2) one RPC handler + one UI panel. Reserve Option A's per-`Agent` structure only if 06-02's quality gate shows the single-prompt approach can't keep the model on-contract.

---

## 4. The Interview state machine (`ask → listen → critique → model-answer → next`)

Two layers — pick the lightest that passes the quality gate:

**Layer 1 (prompt-only):** The Interview system prompt describes the full loop; the LLM produces "critique + model answer + next question" as one streamed reply after each user answer. Simplest; works because the structure is regular. Risk: the small model may merge/skip steps or critique before hearing the answer.

**Layer 2 (explicit enum, if needed):** Mirror the existing pure-module convention (`history.py`, `persona.py`):
- A new pure module `agent/interview.py` (livekit-free, `_self_check()`-guarded) holding:
  - `ROLES: dict[str, str]` — role key → a fixed-string role descriptor (e.g. `soc_analyst`, `security_engineer`, `grc`), enum→string like the persona knobs (byte-stable).
  - `render_interview_prompt(role_key) -> str` — assembles the Interview system block from frozen constants (rubric, one-question rule, critique-then-model-answer contract). Deterministic; sandbox-testable.
  - Optionally an `InterviewState` enum + a pure `next_directive(state) -> str` returning the transient per-turn directive.
- The **effect** (calling `update_instructions` / injecting `turn_ctx` directives / `generate_reply`) lives in `main.py`'s Agent subclass — never in the pure module (mirrors how `history.py` owns the decision and `HistoryWindowAgent` owns the effect).

**State boundary mapping (concrete):**
- *ask* → `session.generate_reply(...)` on mode-enter and after each model-answer.
- *listen* → the normal VAD→turn-detect→STT path; completion fires `on_user_turn_completed`.
- *critique + model-answer + next* → the LLM reply driven by the Interview system block (Layer 1) or a `turn_ctx` directive (Layer 2).

**Keep it small.** For MVP, start at Layer 1. Only add the enum if the quality gate (§6) shows the model drifting off-contract.

---

## 5. Endpointing re-tune for deliberate interview speech (MODE-05)

This is a real, named pitfall (PITFALLS.md Pitfall 6 + the "looks-done-but-isn't" slow-speech checklist item). Interview answers are slow and pause-heavy ("let me think… the answer is…"); the conversational profile (`min_delay 0.3, max_delay 3.0`) will **cut in mid-thought**.

### What to change
The endpointing knob lives in the **session-level `turn_handling` dict** (`agent/main.py:182`). The slow-speech profile raises the floor so a thoughtful pause isn't read as turn-end:
- `endpointing.min_delay` ↑ (conversational 0.3s → interview ~**0.6–0.8s**) — wait longer before committing a turn.
- `endpointing.max_delay` ↑ (3.0s → ~**5.0–6.0s**) — allow a longer final pause before forcing turn-end (the AssemblyAI/Speechmatics examples use `max_turn_silence` of 1000–1280ms in their own units; LiveKit `max_delay` up to ~5s is reasonable for deliberate answers).
- Keep `MultilingualModel()` as the semantic decider (it already guards against premature cutoff; raising delays makes it *safer still* for slow speech).
- VAD `activation_threshold` (0.65, set in `prewarm`) can stay; it's an open-mic/echo defense, orthogonal to slow-speech endpointing.

### How to switch profiles — the open design question [VM-INTROSPECT]
There is **no proven runtime setter for `turn_handling` in this codebase yet.** Three candidate mechanisms, in order of preference for MVP:

1. **Per-`Agent` override (cleanest if supported):** the `Agent` constructor in recent `~=1.5` accepts `min_endpointing_delay` / `max_endpointing_delay` / `turn_detection` / `allow_interruptions` that override the session defaults for that agent. If confirmed, an `InterviewAgent` (Option A) carries the slow profile by construction. **[VM-INTROSPECT: `inspect.signature(Agent.__init__)` — confirm these kwargs exist on the installed pin.]**
2. **Runtime mutation of the session's turn options:** check for a `session.update_options(...)` or a settable `turn_handling`. The agentmemory note on the endpointing API does **not** list a runtime setter, only constructor surfaces — so treat this as **unconfirmed**. **[VM-INTROSPECT.]**
3. **Session-level profile chosen at start (MVP-safe fallback):** if neither runtime path is clean, the pragmatic MVP move is to set the **interview-friendly endpointing as the single session profile** and accept slightly slower Learn-mode turns, OR document that mode is chosen before `session.start`. This is the lowest-risk path if 1/2 don't pan out, and matches the "ladder/fallback" discipline the project uses elsewhere.

**Recommendation:** Plan 06-02 should **first [VM-INTROSPECT] the `Agent.__init__` signature** and prefer mechanism 1 (per-agent override). If absent, fall back to a documented session-profile decision. Do not assume a runtime `turn_handling` setter exists.

### Verification (MODE-05)
Operator gate on the VM (sandbox can't run voice): speak a deliberate, pause-heavy answer; confirm the agent does **not** cut in on the mid-thought pause and **does** respond promptly after a clear finish. This is the slow-speech checklist item in PITFALLS.md line 388.

---

## 6. Critique quality — the E4B depth risk (06-02, Pitfall 11)

**This is the single biggest content risk in the phase**, and it's already logged as a STATE.md blocker:
> [Phase 6]: E4B critique depth unproven — gate on a strong-vs-weak answer check; keep 24GB larger-model swap behind LiveKit's interface.

A 4B-class model gives shallow/generic critique, may praise weak answers, and may produce bland "model answers". Mitigations (from PITFALLS.md Pitfall 11):

- **Rubric-structured critique prompt (the 06-02 deliverable).** Don't say "give feedback". Give the model an explicit structure: what to assess (e.g., technical accuracy, completeness, use of precise terminology, structure of the answer), then a fixed template — *brief critique → strong model answer*. **Structure compensates for model size.** Build this as frozen constants in `interview.py` (byte-stable, like `DISTILL_INSTRUCTION` in `kb/distill.py`).
- **No numeric scoring rubric.** Explicitly OUT OF SCOPE (REQUIREMENTS.md line 107: "Numeric interview scoring rubric — encourages gaming a number; qualitative critique + model answer is more instructive"). The rubric is a *qualitative structure*, not a score.
- **Quality gate (acceptance criterion for the phase):** craft one strong and one weak answer to a default-role question; verify the agent's critique **distinguishes** them (praises the strong, identifies the gaps in the weak). This is the gate the STATE.md blocker demands. If E4B fails it → trigger the 24GB fallback.
- **Reuse the no-think hot-path config.** Critique still runs through `with_ollama(reasoning_effort="none")`; do NOT turn thinking back on (it breaks first-sentence TTS and TTFT). Depth comes from prompt structure, not reasoning tokens.

### 24GB fallback (must be *documented*, not built — 06-02)
- The LLM is already behind LiveKit's interface (`openai.LLM.with_ollama(model=resolved_llm_tag())`, tag from `OLLAMA_MODEL`). **Swapping models is a config change, not a code change** — exactly as designed.
- Documented larger options (verified real in STACK.md): `gemma4:26b` (MoE, 18GB) or a Qwen3 8B — both need a **24GB** card; they do **not** fit the 16GB floor with the other two models resident.
- **Model-by-mode idea (document as an option, don't build for MVP):** E4B for fast Converse, a larger model only for Interview critique turns where a ~1.5s reply is acceptable (a slow critique is fine; a slow conversational reply isn't). This is a v2/24GB enhancement, not an MVP requirement.
- **Deliverable for 06-02:** a short doc/section stating the swap mechanism (`OLLAMA_MODEL` + pull the larger tag on a 24GB host), the VRAM math, and the trigger condition (failed quality gate). No 24GB code path ships in v1.

---

## 7. Invariants this phase must not break

1. **Flat-TTFT / frozen-prefix (the project keystone, Pitfall 7).** Mode toggle and role pick re-render the **system instruction block** → a **one-time, user-initiated re-prefill** (same cost model as a persona edit). NEVER re-render the prompt prefix per turn. Per-turn interview directives (if any) go in the transient `turn_ctx`, not `instructions`. Compose with persona × KB the way `handle_persona_update` already composes (`render` under the current persona + current brief + current mode).
2. **Byte-stability.** Role descriptors and the rubric must be **enum→fixed-string** constants in fixed order (mirror `persona.py`). No interpolated numbers, no timestamps, no dict-order drift.
3. **Local-first (PERF-03).** Nothing new leaves the LAN. Interview prompts, roles, and critiques are all local. No cloud anything.
4. **No second hardcoded LLM tag.** Any new LLM call resolves the tag from `OLLAMA_MODEL` (mirror `resolved_llm_tag` / `kb/distill._resolved_llm_tag`).
5. **Thinking stays OFF** on the hot path (`reasoning_effort="none"`).
6. **History windowing still applies** in interview mode (`HistoryWindowAgent.on_user_turn_completed` must keep working — if a state machine also hooks this method, compose the two behaviors, don't replace one).
7. **Metrics interpretation.** Slow-speech `min_delay` will raise `eou_ms` above the 300ms budget → `over_budget:["eou"]` on interview turns. This is expected; plan so it isn't misread.

---

## 8. Concrete file-level plan map

| Requirement | Where it lands | Pattern to copy |
|---|---|---|
| MODE-01 (Learn default) | `agent/main.py` default mode = Learn; `interview.py` mode enum | existing `DEFAULT_PERSONA` default-on-load |
| MODE-02 (toggle from side panel) | new `web/app/InterviewPanel.tsx` + `mode.update` RPC in `main.py` | `PersonaPanel.tsx` + `handle_persona_update` |
| MODE-03 (role picker) | role `<select>` in `InterviewPanel.tsx`; `ROLES` in `interview.py` (+ hand-mirrored in web) | `PersonaPanel` voice/knob `<select>` + duplication seam |
| MODE-04 (one Q at a time, wait for answer) | Interview system prompt + `generate_reply` on enter; `on_user_turn_completed` boundary | greeting + KB-priming `generate_reply`; `HistoryWindowAgent` hook |
| MODE-05 (slow-speech endpointing) | `turn_handling` profile / per-`Agent` override | `build_session` turn_handling dict [VM-INTROSPECT §5] |
| Critique rubric (06-02) | frozen rubric constants in `interview.py` | `DISTILL_INSTRUCTION` in `kb/distill.py` |
| 24GB fallback (06-02) | doc section; `OLLAMA_MODEL` swap | already behind LiveKit interface |

**Suggested module:** `agent/interview.py` — pure, livekit-free, `_self_check()`-guarded, holding `ROLES`, `render_interview_prompt(role)`, the rubric constants, and (optionally) the state enum + `next_directive`. This is the sandbox-testable core; `main.py` wires the effects. Mirrors `history.py`/`persona.py`/`kb/distill.py` exactly.

---

## 9. Open questions to resolve at plan time (flag for the planner)

1. **[VM-INTROSPECT] Per-`Agent` endpointing override:** does the installed `~=1.5` `Agent.__init__` accept `min_endpointing_delay`/`max_endpointing_delay`/`turn_detection`? If yes → cleanest slow-speech path (per-agent profile). If no → session-profile fallback (§5).
2. **[VM-INTROSPECT] Runtime `turn_handling` mutation:** is there a `session.update_options(...)` or settable turn options to switch profiles mid-session without a restart? Memory note suggests *no* runtime setter — verify.
3. **State machine depth:** start prompt-only (Layer 1). Does the quality gate (§6) pass without an explicit enum? Decide empirically; don't pre-build Layer 2.
4. **Agent→UI interview state:** does the UI need the current question number / state pushed back (via a `mode.state` attribute like `kb.state`), or is the RPC ack enough for MVP? Lean MVP: ack only, unless the toggle needs visible confirmation of "Interview mode — interviewing for SOC analyst".
5. **Mode × persona × KB composition:** confirm the render call composes all three (mode block + persona knobs + KB brief). The Interview *role* may override or augment the persona `role_text` — decide whether interview mode replaces the Cybersecurity Trainer framing or wraps it.

---

## 10. Sources

- **Codebase (read directly):** `agent/main.py`, `agent/persona.py`, `agent/history.py`, `agent/metrics.py`, `agent/kb/distill.py`, `web/app/VoiceRoom.tsx`, `web/app/PersonaPanel.tsx`, `web/app/KbPanel.tsx`, `web/app/AgentStatePill.tsx`, `web/app/Transcript.tsx`.
- **Planning:** `.planning/REQUIREMENTS.md` (MODE-01..05, out-of-scope numeric rubric), `.planning/STATE.md` (E4B-depth blocker, decisions log), `.planning/ROADMAP.md` (Phase 6 plans 06-01/06-02), `.planning/research/PITFALLS.md` (Pitfall 6 endpointing, Pitfall 11 E4B depth, slow-speech checklist), `.planning/research/STACK.md` (24GB model options, VRAM math), `.planning/research/SUMMARY.md`.
- **agentmemory:** `mem_mqtoqxd1` (livekit-agents ~=1.5 endpointing/interruption API, source-verified — `turn_handling` dict surface, EndpointingOptions keys); `mem_mqtwzstn` (Phase 3 persona hot-swap API — `update_instructions`, `tts.update_options`, the `register_rpc_method`/`performRpc` control channel, frozen-prefix + byte-stability rules).
- **context7 `/websites/livekit_io_agents` + `/livekit/agents`:** agent-handoff pattern (`Agent` subclass + `on_enter` + tuple-return handoff), `EndpointingOptions`/`TurnDetectionMode` TypedDefs, per-session `min_endpointing_delay`/`max_endpointing_delay` surfaces. All live-API specifics tagged [VM-INTROSPECT] for VM confirmation against the installed pin.
</content>
</invoke>
