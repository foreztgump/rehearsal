---
phase: 06-interview-mode
verified: 2026-06-26
verifier: phase-verification
phase_goal: >
  Add a constrained dialogue state machine over the same pipeline — user toggles
  Interview Mode and picks a target role, the agent asks one realistic role-relevant
  question at a time, waits for the spoken answer, then critiques it and demonstrates
  a strong model answer — with a re-tuned slow-speech endpointing profile.
requirement_ids: [MODE-01, MODE-02, MODE-03, MODE-04, MODE-05]
plans: [06-01, 06-02]
status: passed
---

# Phase 06 — Interview Mode: Goal Verification

**Verdict: PASS (sandbox-verified core complete; live behavior legitimately deferred to operator/VM gates).**

Both plans (06-01, 06-02) are `autonomous: false` and intentionally defer their live
voice-loop behavior to `06-INTERVIEW-VERIFY.md`, matching the Phase 1–5 `[VM-INTROSPECT]`
precedent. The sandbox cannot import livekit / run Docker / GPU / Ollama / a browser, so
the live `mode.update` round-trip, ask-Q1 over real STT→LLM→TTS, slow-speech no-cut-in,
and the strong-vs-weak Gate A are **not** marked passed here. Every sandbox-verifiable
core IS verified green below.

---

## 1. Requirement ID cross-reference (PLAN frontmatter ⇄ REQUIREMENTS.md)

Every phase requirement ID is accounted for. No orphans, no unplanned IDs.

| Req ID  | REQUIREMENTS.md | Covered by plan(s) | Sandbox evidence | Live gate |
|---------|-----------------|--------------------|------------------|-----------|
| MODE-01 | Learn/Converse is the default | 06-01 | `current_mode=[interview.MODE_LEARN]` (main.py:347); `MODE_LEARN` default in InterviewPanel (`useState(MODE_LEARN)`, :76); `interview.py` `MODE_LEARN="learn"` | Gate C (Learn toggle restores converse) |
| MODE-02 | Toggle into Interview from side panel | 06-01 | InterviewPanel mode `<select>` → `mode.update` RPC `{mode, role_key}` (:93-97); `handle_mode_update` registered (main.py:418) | Gate C / RPC ack applying→applied |
| MODE-03 | Pick target role | 06-01 | role `<select>` over `ROLES` (3 keys), carried in payload; `render_interview_prompt(current_role[0])` (main.py:360) | Gate C per-role |
| MODE-04 | One role-relevant question, then wait | 06-01 (loop), 06-02 (endpointing/verify) | `ONE_QUESTION_RULE` constant; ask-Q1 `generate_reply` on Interview-enter (main.py:409-415) | Gate A/B/C |
| MODE-05 | Critique + strong model answer | 06-01 (basic), 06-02 (rubric depth + endpointing) | rubric `CRITIQUE_CONTRACT` (4 qualitative dims → critique → model answer → next); interview endpointing profile | Gate A (discrimination), Gate B (slow-speech) |

PLAN frontmatter requirement coverage:
- 06-01 `requirements: [MODE-01, MODE-02, MODE-03, MODE-04, MODE-05]` ✓
- 06-02 `requirements: [MODE-04, MODE-05]` ✓ (depth/endpointing deepening)

Phase requirement set `{MODE-01..05}` fully covered. REQUIREMENTS.md traceability table
already marks all five **Complete** under Phase 6 (lines 140-144). No requirement ID is
unaccounted for; no plan claims an ID outside the phase set.

---

## 2. Sandbox-verifiable acceptance criteria — all PASS

| Check | Command | Result |
|-------|---------|--------|
| Interview core self-check | `python3 agent/interview.py` | `interview _self_check OK`, exit 0 ✓ |
| Persona golden unbroken | `python3 agent/persona.py` | `persona _self_check OK`, exit 0 ✓ |
| Agent compiles w/o livekit | `python3 -m py_compile agent/main.py` | exit 0 ✓ |
| Web typecheck | `npx tsc --noEmit` (web) | exit 0 ✓ |
| metrics.py read-only | `git diff --stat agent/metrics.py` | empty ✓ |

### interview.py (pure core)
- Defines `MODE_LEARN`, `MODE_INTERVIEW`, `ROLES`, `DEFAULT_ROLE`, `render_interview_prompt`, `_self_check` ✓ (lines 34,35,42,67,117,170)
- `ROLES` has exactly the three keys `soc_analyst`, `security_engineer`, `grc` ✓
- No livekit import ✓ (grep empty); reuses `persona.SPOKEN_STYLE_FOOTER` ✓ (:30)
- No `InterviewState` / `next_directive` (Layer 2 not built) ✓ (grep empty)
- Rubric names all four qualitative dimensions: technical accuracy, completeness, precise practitioner terminology, structure/clarity ✓ (:100-103)
- Critique → model answer → next ordering asserted by index in `_self_check` ✓ (:193-196)
- No numeric-score token in rendered prompt/golden — `score`/`rating`/`/10`/`points`/`grade` appear ONLY in code comments and the `_self_check` assertion tuple, never in the spoken text ✓ (verified by passing run + grep)
- `render_interview_prompt` join order unchanged from 06-01 (framing, ROLES, one-question rule, rubric, footer) ✓ (:125-131)

### main.py (effect wiring)
- `import interview` ✓ (:29)
- `current_mode=[interview.MODE_LEARN]` (default Learn, MODE-01) + `current_role=[interview.DEFAULT_ROLE]` ✓ (:347-348)
- `compose_instructions()` selects `render_interview_prompt` in Interview mode else `render_prompt`, both composed with `session_kb.brief` ✓ (:350-362)
- `handle_mode_update` parses `mode`/`role_key`, returns `"applied"`, registered on `mode.update` ✓ (:404-420)
- Ask-Q1 `generate_reply` fires ONLY on Interview-enter (MODE-04 boundary) ✓ (:409-415)
- `handle_persona_update`/`ingest_kb` routed through `compose_instructions` (compose, not clobber) ✓ (:386, :486)
- No new `with_ollama`/LLM construction; single session LLM `reasoning_effort="none"` (thinking OFF) ✓ (:171-175)
- Named endpointing constants `INTERVIEW_ENDPOINTING_MIN_DELAY=0.7` ∈ [0.6,0.8], `INTERVIEW_ENDPOINTING_MAX_DELAY=5.0` ∈ [5.0,6.0] ✓ (:76-77)
- `[VM-INTROSPECT]` block enumerates three ordered switch mechanisms, states no runtime `turn_handling` setter assumed; ships mechanism 3 (single session profile) ✓ (:83-102)
- `over_budget:["eou"]`-is-expected comment present ✓ (:78-81, :201-204)
- `MultilingualModel()` semantic decider + VAD `activation_threshold=0.65` unchanged ✓ (:227, :257)

### InterviewPanel.tsx / VoiceRoom.tsx (UI)
- Default-exports `InterviewPanel`; sends `mode.update {mode, role_key}` via `performRpc` ✓ (:73, :93-97)
- Hand-mirrored `ROLES` array (3 agent keys) + duplication-seam sync warning ✓ (:6-11)
- Defaults to Learn (MODE-01) ✓ (:76); reuses `ApplyState` applying→applied/error ack ✓ (:20-34, 80-101)
- No `useParticipantAttributes` agent→UI push (RPC ack only for MVP) ✓ (grep empty)
- VoiceRoom imports + renders `<InterviewPanel />` in the panel row inside `<LiveKitRoom>` ✓ (:6, :86)

---

## 3. must_haves — prohibitions honored

- No per-turn re-render: `compose_instructions` is only called from RPC/ingest closures, never per turn ✓
- No second hardcoded LLM tag / no new LLM construction; thinking stays OFF ✓
- No interpolation/volatile data in `ROLES`/framing (byte-stable golden passes) ✓
- No multi-agent handoff, no `turn_detection="manual"` (Option B single agent) ✓
- No `InterviewState`/`next_directive`, no numeric scoring (REQUIREMENTS line 107) ✓
- No agent→UI attribute state-push ✓
- `agent/metrics.py` unchanged; `over_budget:["eou"]` treated as expected ✓
- VAD `activation_threshold=0.65` and `MultilingualModel()` unchanged ✓
- Endpointing switch mechanism flagged `[VM-INTROSPECT]`, not silently resolved ✓
- 24GB fallback DOCUMENTED only (no code path) ✓

---

## 4. 06-INTERVIEW-VERIFY.md operator runbook — present and complete

- Gates A (scripted strong-vs-weak discrimination + FAIL→24GB), B (slow-speech no-cut-in + `over_budget:["eou"]` caveat), C (per-role loop) each as numbered operator steps with results tables ✓
- `[VM-INTROSPECT]` `inspect.signature(Agent.__init__)` / `AgentSession` endpointing-setter probes + three-mechanism decision rule ✓
- 24GB fallback section: `OLLAMA_MODEL` swap, VRAM math (gemma4:26b ~18GB / Qwen3 8B / 16GB floor), model-by-mode v2 idea, Gate-A trigger ✓
- Build/deploy stale-deploy reminder; metrics-read-only + thinking-OFF notes ✓
- Status `pending-operator`; no gate marked passed by executor ✓

---

## 5. Deferred operator / VM gates (NOT marked passed — by design)

Per the explicit sandbox/VM split, these require the Proxmox VM (Docker + RTX 5090 +
Ollama + browser + LAN device) and are legitimately deferred to `06-INTERVIEW-VERIFY.md`:

- **Gate 1 [VM-INTROSPECT]:** which endpointing switch mechanism the installed pin supports; shipped code uses mechanism 3.
- **Gate A:** strong-vs-weak critique discrimination (the E4B-depth blocker, STATE.md line 101) — discharge or trigger the 24GB fallback.
- **Gate B:** deliberate pause-heavy answer not cut mid-thought; `over_budget:["eou"]` confirmed expected.
- **Gate C:** one-question-at-a-time per role → critique → model answer → next; Learn toggle restores conversational contract.
- Live `mode.update` RPC round-trip + ask-Q1 over real STT→LLM→TTS.

These are classified as **legitimately deferred operator gates**, consistent with the
Phase 1–5 precedent — NOT as failures.

---

## Conclusion

**Phase 06 goal is ACHIEVED at the sandbox-verifiable level and correctly structured for
operator sign-off.** The constrained dialogue contract (toggle → role pick → ask ONE
question → wait → rubric critique → strong model answer → next) is implemented over the
existing single-agent pipeline via the proven persona-hot-swap pattern (Option B,
Layer 1 prompt-only), composed with persona × KB through one re-prefill helper, with a
re-tuned slow-speech endpointing profile (min 0.7 / max 5.0) and the profile-switch
mechanism honestly flagged `[VM-INTROSPECT]`. All five requirement IDs (MODE-01..05) are
accounted for and covered. All sandbox acceptance criteria pass; all prohibitions are
honored; metrics.py is untouched. Live voice-loop verification is deferred to the
operator runbook per the established VM-introspect precedent.
