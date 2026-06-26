---
plan: 08-01
title: LLM Speed Selector vertical slice — Fast/Better resolver + current_model holder + model.update RPC + in-place _opts.model swap + num_predict cap + ModelPanel.tsx + VoiceRoom mount
phase: 8
wave: 1
depends_on: []
autonomous: false
requirements: [LLM-01, LLM-02, LLM-03, LLM-04]
files_modified:
  - agent/main.py
  - web/app/ModelPanel.tsx
  - web/app/VoiceRoom.tsx
  - .env.example
  - agent/requirements.txt
---

# Plan 08-01: The working end-to-end LLM picker — pick Fast/Better in the UI, the agent retargets the selected Ollama tag IN PLACE on the next turn, no session teardown, no TTS interrupt

## User Story

**As a** learner holding a live spoken conversation, **I want to** pick a "Fast (snappier)" or
"Better (more thoughtful)" response model from a side panel, **so that** the agent switches which
Ollama model answers me starting on my next turn — without tearing down the session, interrupting
the reply currently being spoken, or ever exposing me to raw model tags.

## Context

This is the **vertical slice** of Phase 8 — the complete demonstrable picker→swap loop end-to-end
(panel select → `model.update` RPC → validate → in-place `_opts.model` mutation → next turn serves
the new tag), not a horizontal layer. After this plan a real user can flip Fast↔Better mid-session
and the agent re-targets the model. Plan **08-02** (Wave 2) then pulls/pins both tags, adds the
per-build verification gate, and authors the operator runbook.

**Swap mechanism is SOLVED (RESEARCH §1).** The installed `livekit-plugins-openai==1.6.4`
`openai.LLM` (built by `with_ollama`) has **NO** `update_options()`, and `LLM.model` is a read-only
`@property`. But `_opts` is a **non-frozen** dataclass and `chat()` re-reads `self._opts.model`
**fresh every turn** — so the swap is one line: `session.llm._opts.model = tag`. Same `LLM`
instance ⇒ the `metrics_collected` subscription from `metrics.attach()` (agent/metrics.py:332)
survives, identical to the proven `session.tts.update_options(voice=...)` in-place swap
(main.py:431). `reasoning_effort="none"` lives in the same `_opts`, re-read per `chat()`, so
thinking-off carries across the swap automatically — no re-pass.

**Clone `handle_mode_update` but SIMPLER (RESEARCH §7.1, PATTERNS File 1).** `handle_mode_update`
(main.py:448-478) is the exact validate-before-commit RPC template. `handle_model_update` clones its
validate-before-mutate discipline (the Phase-6 fix) but drops BOTH `update_instructions` (a model
swap does not re-render the persona/KB/mode prefix) AND `generate_reply` (a model switch must NOT
inject an agent turn — it lands on the user's next real turn, LLM-02). Payload is a plain choice key
`{"choice":"fast"|"better"}` — NEVER a raw tag from the client (LLM-01).

**No hardcoded tag (CONTEXT §decisions, the v1.0 invariant).** `resolved_llm_tag()` (main.py:127)
generalizes to a Fast/Better resolver reading `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`, same
`SystemExit`-if-unset posture. `build_session()` constructs at the **Fast** default tag (LLM-02
configurable-default Fast). The two env vars are documented in `.env.example`; the actual pull/pin
that writes them is Wave 2 — this plan only consumes them.

**LLM-04 num_predict gap (RESEARCH §1.5, §8.1).** `with_ollama` does NOT accept
`max_completion_tokens`, so the live hot-path LLM currently caps NOTHING (only warmup/distill cap
`num_predict` off the hot path). LLM-04 explicitly lists "a capped num_predict" — close it here with
a one-line `session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP` after construction, which
maps OpenAI `max_completion_tokens` → Ollama `num_predict` and applies equally to both models. The
OpenAI→Ollama mapping is verified on the VM (runbook, Wave 2).

**Pin the plugin (RESEARCH §1.1, §8.2).** `livekit-plugins-openai` is currently unpinned; pin it to
`==1.6.4` (this research's grounding) for a deterministic build, and confirm the swap surface with
the `[VM-INTROSPECT]` probe against the rebuilt image (runbook, Wave 2). If a future version DOES
expose `update_options(model=...)`, prefer it — but the shipped path is `_opts.model` mutation.

**Sandbox vs VM split (carried from Phases 1–6).** The sandbox CANNOT import livekit / has no
Docker/GPU/Ollama/browser. `py_compile agent/main.py` + the web typecheck ARE sandbox-verifiable;
the live RPC round-trip, the in-place swap proof, and the `[VM-INTROSPECT]` probe are operator/VM
gates authored in Wave 2's `08-LLM-VERIFY.md`. Marked `autonomous: false` for that reason.

**Scope discipline (YAGNI).** Do NOT warm the newly-selected model out-of-band (cold-switch cost is
accepted single-resident behavior, deferred to Phase 10 — RESEARCH §2.2). Do NOT raise
`OLLAMA_MAX_LOADED_MODELS`. Do NOT add a `model.get` RPC (the choice-key seam is hand-mirrored, like
InterviewPanel). Do NOT touch the STT/TTS pipeline, `agent/metrics.py`, or the persona prompt.

## Tasks

<task id="08-01-1">
  <title>Pin livekit-plugins-openai==1.6.4 in agent/requirements.txt (deterministic swap surface)</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§1.1 installed version; §8.2 unpinned-plugin risk)
    - agent/requirements.txt (the current `livekit-agents~=1.5` + unpinned `livekit-plugins-openai` lines)
  </read_first>
  <action>
    Pin the openai plugin to the version this phase's swap mechanism is grounded on. In
    `agent/requirements.txt`, change the unpinned `livekit-plugins-openai` line to
    `livekit-plugins-openai==1.6.4`. Leave `livekit-agents~=1.5` and every other pin UNCHANGED
    (1.6.4 is what `~=1.5` already resolves to, per RESEARCH §1.1 — this just freezes it). Add a
    one-line comment noting the pin grounds the `_opts.model` in-place swap (RESEARCH §1.2-1.3) and
    that the `[VM-INTROSPECT]` probe (08-LLM-VERIFY Gate 1) confirms the surface on the rebuilt image.
    Do NOT change any other dependency. Do NOT upgrade livekit-agents.
  </action>
  <acceptance_criteria>
    - `agent/requirements.txt` pins the openai plugin exactly (`grep -n "livekit-plugins-openai==1.6.4" agent/requirements.txt`)
    - No other pin changed (`git diff agent/requirements.txt` shows only the openai line + its comment)
  </acceptance_criteria>
</task>

<task id="08-01-2">
  <title>Generalize the tag resolver + add current_model holder + model.update RPC + in-place _opts.model swap + num_predict cap in agent/main.py</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 1 — Analog A handle_mode_update :448-478; Analog B in-place TTS swap :431; Analog C current_mode holder :363; Analog D resolved_llm_tag :127; Analog E build_session :187-191; the main.py invariants block)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§1.2-1.5 the _opts.model swap + num_predict cap; §7.1 clone-mode.update-but-simpler; §9 req→mechanism map)
    - .planning/phases/08-llm-speed-selector-part-a/08-CONTEXT.md (§decisions Agent-Side Model Switch Mechanism; §Established Patterns validate-before-mutate)
    - agent/main.py (resolved_llm_tag :127-132; build_session llm= :187-191; current_mode/current_role holders :363-364; handle_mode_update :448-478; register_rpc_method :476-478; entrypoint session/agent wiring :342-350)
    - agent/metrics.py (attach / the metrics_collected subscription that must survive the in-place swap — around line 332)
  </read_first>
  <action>
    Wire the agent EFFECTS, cloning the mode-hot-swap machinery but SIMPLER (no update_instructions,
    no generate_reply). Concrete steps:
    - Add module-level choice constants near `resolved_llm_tag` (main.py:127): `MODEL_CHOICES =
      ("fast", "better")`, `DEFAULT_MODEL_CHOICE = "fast"` (LLM-02 default Fast), and the choice→env
      map `_MODEL_ENV = {"fast": "OLLAMA_MODEL_FAST", "better": "OLLAMA_MODEL_BETTER"}`.
    - Add `def resolved_model_tag(choice: str) -> str:` mirroring `resolved_llm_tag`'s SystemExit-if-
      unset posture: read `os.environ.get(_MODEL_ENV[choice], "").strip()`; raise
      `SystemExit(f"{_MODEL_ENV[choice]} is not set — run ollama/pull-and-pin.sh first")` when empty.
      NO hardcoded gemma tag anywhere (continues the v1.0 invariant). Keep `resolved_llm_tag()` in
      place (warmup/prewarm still call it; it reads OLLAMA_MODEL which Wave 2 keeps as the Fast alias).
    - Add a named live num_predict cap constant (no magic value, AGENTS.md), e.g.
      `LIVE_NUM_PREDICT_CAP: int = <a few hundred>` with a comment sizing it to the SPOKEN_STYLE_FOOTER
      "sentence or two" budget (RESEARCH §1.5) — it bounds runaway generation uniformly on both models.
    - In `build_session()` (main.py:187-191): construct the LLM at the Fast default tag —
      `model=resolved_model_tag(DEFAULT_MODEL_CHOICE)` (was `resolved_llm_tag()`), `base_url` and
      `reasoning_effort="none"` UNCHANGED. build_session returns the AgentSession inline as today (it
      does `return AgentSession(...)` at main.py:171 — there is no handle to reach `session.llm._opts`
      before the return without a restructure, so do NOT cap here). The cap is pinned to a single site
      in `entrypoint` (next bullet).
    - In `entrypoint()` AFTER `metrics.attach(session)` (main.py:344) — the SINGLE cap site, where
      `session.llm` is reachable — set `session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP`
      (LLM-04 — chat() forwards max_completion_tokens → Ollama num_predict when given, RESEARCH §1.5).
      Add a comment that this closes the pre-existing live num_predict gap, applies to BOTH models, and
      is the one and only place the cap is set (applied exactly once at startup).
    - Add the fourth mutable holder beside current_mode/current_role (main.py:363-364):
      `current_model: list[str] = [DEFAULT_MODEL_CHOICE]` with a comment that — unlike
      current_persona/current_mode/current_role — it does NOT feed compose_instructions(); it ONLY
      drives `session.llm._opts.model` (LLM-02 per-session persistence; the simpler axis).
    - Add `async def handle_model_update(data):` cloning `handle_mode_update`'s validate-before-mutate
      discipline but SHORTER: parse `json.loads(data.payload)`; read `choice = snapshot.get("choice")`;
      if `choice not in MODEL_CHOICES` → `logger.warning("model.update rejected: unknown choice %r",
      choice)` and `return "error"` (NEVER accept a raw tag — LLM-01; validate BEFORE mutating, the
      Phase-6 fix); on success set `current_model[0] = choice` then
      `session.llm._opts.model = resolved_model_tag(choice)` (in-place; next chat() uses it —
      RESEARCH §1.3) and `return "applied"`. Do NOT call `update_instructions` and do NOT call
      `generate_reply` (RESEARCH §7.1 — a model swap touches ONLY the LLM tag, lands next turn, must
      not inject an agent turn). Wrap the private-attr reach behind a one-line comment so it is
      explicit and one-place (mirrors the TTS-swap comment at main.py:431).
    - Register it AFTER `session.start` beside the mode.update registration (main.py:476-478):
      `ctx.room.local_participant.register_rpc_method("model.update", handle_model_update)`.
    INVARIANTS (PATTERNS File 1): no second hardcoded LLM tag; in-place swap only (same LLM instance ⇒
    metrics_collected survives, no teardown, next-turn effective, current TTS uninterrupted); thinking
    stays OFF (reasoning_effort="none" in the shared _opts carries automatically); validate-before-
    mutate (reject unknown choice before touching _opts.model). Do NOT modify
    HistoryWindowAgent.on_user_turn_completed, agent/metrics.py, the persona prompt, or the STT/TTS
    construction. The live RPC round-trip + swap proof are operator/VM gates (Wave 2 runbook); editing
    is sandbox-safe (py_compile).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile agent/main.py` exits 0 (syntax valid without importing livekit)
    - The Fast/Better resolver + choice constants exist (`grep -n "MODEL_CHOICES\|DEFAULT_MODEL_CHOICE\|_MODEL_ENV\|def resolved_model_tag" agent/main.py`)
    - `resolved_model_tag` raises SystemExit when the env var is unset, mirroring `resolved_llm_tag` (`grep -n "is not set — run ollama/pull-and-pin.sh" agent/main.py` shows both)
    - build_session constructs at the Fast default tag (`grep -n "resolved_model_tag(DEFAULT_MODEL_CHOICE)\|model=resolved_model_tag" agent/main.py`)
    - A live num_predict cap is applied to `session.llm._opts.max_completion_tokens` exactly once at startup (`grep -n "max_completion_tokens\|LIVE_NUM_PREDICT_CAP" agent/main.py`)
    - A `current_model` holder defaults to Fast (`grep -n "current_model.*DEFAULT_MODEL_CHOICE\|current_model: list" agent/main.py`)
    - `handle_model_update` is defined and registered on the `model.update` RPC (`grep -n "def handle_model_update\|\"model.update\"" agent/main.py`)
    - The handler validates the choice before mutating and performs the in-place `_opts.model` swap (`grep -n "choice not in MODEL_CHOICES\|session.llm._opts.model = resolved_model_tag" agent/main.py`)
    - The handler does NOT call update_instructions or generate_reply (inspect `handle_model_update`'s body — neither appears inside it; it is strictly shorter than handle_mode_update)
    - No new hardcoded gemma tag and no second `with_ollama`/`openai.LLM` construction (`grep -n "with_ollama\|gemma" agent/main.py` shows only the single existing build_session LLM)
    - `python3 agent/persona.py` still prints `persona _self_check OK` and `python3 agent/interview.py` prints `interview _self_check OK` (pure cores intact)
    - OPERATOR-VERIFICATION (VM, deferred — 08-LLM-VERIFY Gate C): the `model.update` RPC applies; toggling Fast↔Better mid-session lands the new tag on the NEXT turn, current TTS is not interrupted, no agent turn is injected, and `docker compose logs agent` shows the new tag serving; the num_predict cap truncates a "count to 500" probe
  </acceptance_criteria>
</task>

<task id="08-01-3">
  <title>Create web/app/ModelPanel.tsx (clone InterviewPanel) — two-option picker, OUTCOME labels only, model.update RPC; mount it in VoiceRoom</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 2 — InterviewPanel clone: performRpc core, ApplyState union, styles, the fast/better duplication seam + OUTCOME-label invariant; File 3 — VoiceRoom row :84-89)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§7.2 UI clone; §9 LLM-01/LLM-02 rows)
    - .planning/phases/08-llm-speed-selector-part-a/08-CONTEXT.md (§decisions LLM Picker UI; §specifics outcome-labels-only, exactly two options)
    - web/app/InterviewPanel.tsx (the EXACT full-file template — useRoomContext + useVoiceAssistant agent-identity targeting, performRpc with destinationIdentity, JSON.stringify payload, ApplyState union + STATUS_LABEL/STATUS_COLOR, panelStyle/labelStyle/inputStyle, the `<select>` rendering, the duplication-seam comment :6-11)
    - web/app/VoiceRoom.tsx (imports :6-9; the side-panel row :84-89 where the panel slots in; must render inside <LiveKitRoom>)
    - agent/main.py (MODEL_CHOICES "fast"/"better" — the validation set the web choice keys must mirror by hand)
  </read_first>
  <action>
    Create `web/app/ModelPanel.tsx` by cloning `web/app/InterviewPanel.tsx` and reusing its styles +
    RPC core. Concrete contents:
    - A hand-mirrored choice-key array with a duplication-seam warning comment (mirrors
      InterviewPanel.tsx:6-11): `const CHOICES = ["fast", "better"] as const;` — comment that these MUST
      mirror agent/main.py `MODEL_CHOICES`, there is no `model.get` RPC in the MVP so drift is silent,
      keep in sync by hand, and NEVER surface the raw Ollama tag here.
    - OUTCOME labels ONLY (LLM-01, REQUIREMENTS:98 — no tags, no latency numbers):
      `const CHOICE_LABEL: Record<(typeof CHOICES)[number], string> = { fast: "Fast (snappier)",
      better: "Better (more thoughtful)" };`.
    - Copy the `ApplyState` union + `STATUS_LABEL`/`STATUS_COLOR` + `panelStyle`/`labelStyle`/
      `inputStyle` verbatim from InterviewPanel.
    - Local React state: `const [choice, setChoice] = useState<(typeof CHOICES)[number]>("fast");`
      (LLM-02 default Fast; per-session persistence by construction — the panel holds the choice for
      the session) + the `status` ApplyState.
    - `apply()` cloning InterviewPanel's: target the agent identity
      (`agent?.identity ?? fallback?.identity`, guard if none → error), then
      `room.localParticipant.performRpc({ destinationIdentity, method: "model.update",
      payload: JSON.stringify({ choice }) })`; `setStatus(ack === "applied" ? "applied" : "error")`
      (the native RPC return IS the ack). Payload key MUST match the agent's parse: `choice`.
    - Render a panel titled e.g. "Response model" with a single `<select>` over `CHOICES` showing
      `CHOICE_LABEL[c]`, plus the Apply button + status span (mirror InterviewPanel's layout). Two
      options only — no model zoo (REQUIREMENTS:96).
    Then edit `web/app/VoiceRoom.tsx`: add `import ModelPanel from "./ModelPanel";` to the import block
    (:6-9) and place `<ModelPanel />` in the side-panel row (:84-89) alongside `<PersonaPanel />`,
    `<InterviewPanel />`, `<KbPanel />`, `<Transcript />`. It must render inside `<LiveKitRoom>` for
    room context. Do NOT add an agent→UI attribute-read state push (RPC ack only, MVP). Do NOT render
    any raw tag or latency number anywhere.
  </action>
  <acceptance_criteria>
    - `web/app/ModelPanel.tsx` exists and default-exports a `ModelPanel` component (`grep -n "export default function ModelPanel" web/app/ModelPanel.tsx`)
    - It sends the `model.update` RPC with a `{ choice }` payload (`grep -n "model.update\|performRpc\|JSON.stringify({ choice })" web/app/ModelPanel.tsx`)
    - It declares the hand-mirrored CHOICES keys with a duplication-seam sync warning (`grep -n "fast\|better\|mirror agent/main" web/app/ModelPanel.tsx`)
    - Labels are OUTCOME-only — no raw tag, no latency number (`grep -n "Fast (snappier)\|Better (more thoughtful)" web/app/ModelPanel.tsx`; `grep -ni "evalengine\|defyma85\|gemma\|ms\|latency\|tokens/s" web/app/ModelPanel.tsx` returns nothing)
    - It defaults the picker to Fast (LLM-02) (`grep -n 'useState<.*>("fast")\|useState("fast")' web/app/ModelPanel.tsx`)
    - It reuses the ApplyState applying→applied/error ack pattern (`grep -n "applying\|applied\|ApplyState\|error" web/app/ModelPanel.tsx`)
    - It does NOT push agent→UI state via participant attributes (`grep -n "useParticipantAttributes" web/app/ModelPanel.tsx` returns nothing)
    - `web/app/VoiceRoom.tsx` imports and renders `<ModelPanel />` inside the panel row (`grep -n "ModelPanel" web/app/VoiceRoom.tsx` shows both the import and the JSX usage)
    - The web typecheck passes with the new panel (`npx tsc --noEmit` in `web/`, or the project's typecheck script)
    - OPERATOR-VERIFICATION (VM, deferred — 08-LLM-VERIFY Gate C): picking Fast/Better shows applying→applied; the choice persists for the session and takes effect on the next turn
  </acceptance_criteria>
</task>

<task id="08-01-4">
  <title>Document OLLAMA_MODEL_FAST / OLLAMA_MODEL_BETTER in .env.example (keep OLLAMA_MODEL as the Fast back-compat alias)</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 6 — the two-var addition + OLLAMA_MODEL Fast-alias back-compat note)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§7.3 keep OLLAMA_MODEL pointing at Fast so warmup/vram/distill/Modelfile keep working)
    - .env.example (the existing OLLAMA_MODEL line :31 + the Ollama VRAM-budget block :26-31)
  </read_first>
  <action>
    Edit `.env.example` to document the two picker tags the agent resolves through. Below the existing
    `OLLAMA_MODEL=` line (:31) add:
    - A comment: the two user-selectable tags are resolved by `ollama/pull-and-pin.sh` (Phase 8,
      LLM-03); Fast is the default (LLM-02); NO hardcoded gemma tag in code — the agent reads these.
    - `OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest`
    - `OLLAMA_MODEL_BETTER=defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest`
    - Repoint the existing `OLLAMA_MODEL` to the Fast/default tag with a back-compat comment: existing
      scripts (warmup.py / vram-validate.sh / kb/distill.py / Modelfile) read `OLLAMA_MODEL`, so point
      it at the Fast tag so they keep working unchanged (RESEARCH §7.3). i.e.
      `OLLAMA_MODEL=evalengine/unbound-e2b:latest`.
    Leave the server-level latency env (`OLLAMA_FLASH_ATTENTION`/`OLLAMA_KV_CACHE_TYPE`/
    `OLLAMA_KEEP_ALIVE`) UNCHANGED — it applies to BOTH tags by construction (LLM-04). This is the
    EXAMPLE template only; the live `.env` is written by Wave 2's pull-and-pin.sh.
  </action>
  <acceptance_criteria>
    - `.env.example` documents both picker vars (`grep -n "OLLAMA_MODEL_FAST=\|OLLAMA_MODEL_BETTER=" .env.example`)
    - `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` carry the two community tags from REQUIREMENTS LLM-03 (`grep -n "evalengine/unbound-e2b\|defyma85/gemma-4-E4B-it-ultra-uncensored-heretic" .env.example`)
    - `OLLAMA_MODEL` is repointed to the Fast tag as a back-compat alias with an explaining comment (`grep -n "OLLAMA_MODEL=evalengine/unbound-e2b\|back-compat\|Fast" .env.example`)
    - The server-level latency env block is unchanged (`grep -n "OLLAMA_FLASH_ATTENTION=1\|OLLAMA_KV_CACHE_TYPE=q8_0\|OLLAMA_KEEP_ALIVE=-1" .env.example`)
  </acceptance_criteria>
</task>

## Verification

- `python3 -m py_compile agent/main.py` exits 0; `agent/main.py` defines `MODEL_CHOICES`/
  `DEFAULT_MODEL_CHOICE`/`_MODEL_ENV`/`resolved_model_tag` (SystemExit-if-unset), constructs
  build_session at the Fast tag, sets a live `_opts.max_completion_tokens` cap, holds `current_model`
  defaulting to Fast, and defines+registers `handle_model_update` on the `model.update` RPC doing a
  validate-before-mutate in-place `_opts.model` swap — with NO `update_instructions`/`generate_reply`
  inside it, NO second hardcoded tag, NO new `with_ollama` construction.
- `python3 agent/persona.py` prints `persona _self_check OK` and `python3 agent/interview.py` prints
  `interview _self_check OK` (pure cores unbroken).
- `agent/requirements.txt` pins `livekit-plugins-openai==1.6.4` (and nothing else changed).
- `web/app/ModelPanel.tsx` exists, sends `model.update {choice}`, mirrors the two `fast`/`better`
  keys, renders OUTCOME labels only (no tag/latency), defaults to Fast, reuses the ApplyState ack, and
  has no attribute-read state push; `web/app/VoiceRoom.tsx` renders it in the panel row; the web
  typecheck passes.
- `.env.example` documents `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` and keeps `OLLAMA_MODEL` as the
  Fast back-compat alias.
- BUILD-FIRST (VM, before any live gate — baked-image invariant, CONTEXT §Established Patterns):
  `docker compose build web agent && docker compose up -d && docker compose ps` (all services Up).
- OPERATOR GATE (VM — deferred; authored in Wave 2's `08-LLM-VERIFY.md`):
  - **[VM-INTROSPECT] (Gate 1):** the probe confirms `has update_options: False`, `_opts` includes
    `model`/`reasoning_effort`/`max_completion_tokens`, frozen `False`, plugin version `1.6.4` — so
    the shipped `_opts.model` swap path is correct (LLM-03).
  - **Live swap (Gate C):** toggling Fast↔Better mid-session applies (applying→applied), lands on the
    NEXT turn, does NOT interrupt current TTS, injects NO agent turn, and `docker compose logs agent`
    shows the new tag serving; the one-time cold-switch latency on the first post-switch turn is
    EXPECTED (single-resident eviction, RESEARCH §2.2), not a regression (LLM-02, LLM-03).
  - **num_predict cap:** a "count to 500" probe truncates at the cap on BOTH models (LLM-04).
- DEFER (do NOT mark passed in this plan): all VM/operator items above; the sandbox cannot run
  Docker/GPU/Ollama/browser or import livekit.

## must_haves

truths:
- LLM-01: the user selects the response model via a two-option picker with plain-language OUTCOME
  labels ("Fast (snappier)" / "Better (more thoughtful)") that NEVER surface a raw Ollama tag —
  `web/app/ModelPanel.tsx` renders `CHOICE_LABEL` and sends only the plain key `{choice}`; the agent
  rejects anything not in `MODEL_CHOICES` (CONTEXT §decisions LLM Picker UI).
- LLM-02: the selected model is configurable-default Fast (E2B), persists for the session, and a
  switch takes effect on the NEXT turn without tearing down the session or interrupting current TTS —
  `current_model[0]` defaults to `DEFAULT_MODEL_CHOICE="fast"`, the panel defaults to `"fast"`, and
  `handle_model_update` mutates `session.llm._opts.model` in place (re-read by the next `chat()`),
  with NO `generate_reply`/`update_instructions`/teardown (CONTEXT §decisions Agent-Side Switch).
- LLM-03: both models are served via Ollama and the agent's LLM plugin targets the selected tag —
  `resolved_model_tag(choice)` resolves `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` and the in-place
  `_opts.model` mutation re-targets the SAME `openai.LLM.with_ollama` instance (the pull/pin that
  makes the tags resident is Wave 2).
- LLM-04: the live hot path preserves thinking-OFF (`reasoning_effort="none"` carried in the shared
  `_opts` across the swap), token streaming (unchanged), and a CAPPED num_predict via
  `session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP` applied to BOTH models; the
  server-level flash-attn/keep-alive/ctx env is untouched and applies to both by construction.
- The swap is IN PLACE on the same `LLM` instance, so the `metrics_collected` subscription from
  `metrics.attach()` survives — identical safety property to the proven TTS voice swap (RESEARCH §1.3).
- The choice flows as a plain validated key over the `model.update` RPC, validate-before-mutate (the
  Phase-6 fix): an unknown choice returns `"error"` and never reaches `_opts.model`.

must_haves.prohibitions:
- NEVER surface a raw Ollama tag or any latency/token-speed number in the UI — outcome labels only
  (LLM-01; REQUIREMENTS:98 out-of-scope).
- NO hardcoded model tag in code — every tag resolves from `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`
  with SystemExit-if-unset (the v1.0 invariant, generalized).
- NO AgentSession/Agent teardown, NO LLM reassignment/recreation, NO TTS recreation — in-place
  `_opts.model` mutation only (CONTEXT §decisions: "In-place mutation only").
- NO `generate_reply` and NO `update_instructions` inside `handle_model_update` — a model swap must
  not inject an agent turn or re-render the persona/KB/mode prefix; it lands on the user's next turn.
- NO turning thinking back on (`reasoning_effort` ≠ `"none"`), NO second `with_ollama`/`openai.LLM`
  construction, NO change to `agent/metrics.py`, the persona prompt, or the STT/TTS construction.
- NO raising `OLLAMA_MAX_LOADED_MODELS` and NO out-of-band model warming on switch (single-resident;
  co-residency is Phase 10).
- NO `model.get` RPC / agent→UI state push — the fast/better seam is hand-mirrored (RPC ack only, MVP).
- NO marking any OPERATOR-VERIFICATION / `[VM-INTROSPECT]` step passed in this plan.

## Artifacts this plan produces

- `agent/requirements.txt` (modified): `livekit-plugins-openai` pinned to `==1.6.4`.
- `agent/main.py` (modified): `MODEL_CHOICES`/`DEFAULT_MODEL_CHOICE`/`_MODEL_ENV`/`LIVE_NUM_PREDICT_CAP`
  constants; `resolved_model_tag(choice)` resolver; build_session constructs at the Fast tag; a live
  `session.llm._opts.max_completion_tokens` cap; `current_model: list[str] = [DEFAULT_MODEL_CHOICE]`
  holder; `handle_model_update(data)` (validate-before-mutate, in-place `_opts.model` swap, returns
  `"applied"`/`"error"`, no generate_reply/update_instructions) registered on the `model.update` RPC.
- `web/app/ModelPanel.tsx` (new): React component default-exporting `ModelPanel` — two-option
  `<select>` over hand-mirrored `CHOICES` with OUTCOME labels, defaults Fast, sends `model.update
  {choice}`, reuses the `ApplyState` applying→applied/error ack.
- `web/app/VoiceRoom.tsx` (modified): `import ModelPanel` + `<ModelPanel />` in the side-panel row
  inside `<LiveKitRoom>`.
- `.env.example` (modified): `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` documented; `OLLAMA_MODEL`
  repointed to the Fast tag as a back-compat alias.
- RPC method introduced: `model.update`. Constants introduced: `MODEL_CHOICES`, `DEFAULT_MODEL_CHOICE`,
  `LIVE_NUM_PREDICT_CAP`, `resolved_model_tag`. (The pull/pin, per-build verify gate, and operator
  runbook are produced by 08-02.)
