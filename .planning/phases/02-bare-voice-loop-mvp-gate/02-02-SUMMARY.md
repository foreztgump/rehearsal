---
phase: 02-bare-voice-loop-mvp-gate
plan: 02-02
subsystem: agent
tags: [livekit, livekit-agents, agentsession, ollama, with_ollama, reasoning_effort, persona, tts, voice]

requires:
  - phase: 01-foundation-infrastructure
    provides: AgentSession built in agent/main.py (Silero VAD + faster-whisper STT + Ollama LLM via with_ollama + Kokoro TTS + local MultilingualModel turn detector), session.start called, metrics scaffold
  - phase: 02-bare-voice-loop-mvp-gate
    provides: 02-01 browser room-join SPA (LiveKitRoom + RoomAudioRenderer + StartAudio), agent-state pill, two-sided transcript — the browser now joins so the agent's first utterance is audible
provides:
  - Default Cybersecurity Trainer persona as a static top-block system prompt (Phase 3 frozen-prefix-compatible)
  - Greeting on connect — agent speaks first via session.generate_reply after session.start (PERS-01)
  - Thinking-OFF on live LLM turns plumbed over Ollama OpenAI-compat /v1 via with_ollama(reasoning_effort="none")
  - Per-turn reply loop relies on AgentSession's automatic turn (no manual orchestration)
affects: [02-03, persona, kb-injection, metrics]

tech-stack:
  added: []
  patterns:
    - "Persona is a static string constant consumed by Agent(instructions=...) — no interpolation, no volatile data (Phase 3 frozen prefix slots a KB beneath it unchanged)"
    - "Greeting drives the full LLM->TTS path via generate_reply(instructions=...) after session.start — no second hardcoded greeting string"
    - "Thinking-OFF over /v1 = reasoning_effort='none' on with_ollama (Ollama maps it to internal Think=false); /v1 ignores the native think field. No Modelfile change, no model repoint — tag still resolves from OLLAMA_MODEL"
    - "Unverified-in-sandbox kwargs (preemptive_generation) are conservatively NOT passed; introspection deferred to the VM"

key-files:
  created: []
  modified:
    - agent/main.py

key-decisions:
  - "Thinking-OFF path (a) chosen over path (b): pass reasoning_effort='none' to with_ollama (forwards think-off over the OpenAI-compat /v1 path) instead of adding a template-level <think> strip to the adept-gemma Modelfile and repointing. Path (a) needs no Modelfile change and keeps the LLM tag resolving from OLLAMA_MODEL (prohibition: no second hardcoded LLM tag). Grounded: Ollama /v1 ignores `think` but honors `reasoning_effort` ('none' -> Think=false); with_ollama exposes `reasoning_effort` directly (livekit-plugins-openai reference)."
  - "preemptive_generation NOT added: AgentSession.__init__ signature is not introspectable in this sandbox (livekit-agents not importable). Per sandbox guidance, the conservative path is to not pass an unverified kwarg. Deferred to the VM."
  - "Greeting uses the canonical LiveKit pattern (generate_reply after session.start) from the official voice-AI quickstart; the exact fire-once trigger semantics on the installed ~=1.5 are an operator gate on the VM."

patterns-established:
  - "Static persona top-block (frozen-prefix-ready) — no f-string/.format/runtime data in the system prompt"
  - "Sandbox-conservative kwarg discipline: pass only documented/verified params; defer unintrospectable kwargs to the VM and record them"

requirements-completed: [VOICE-01, VOICE-02, PERS-01]

duration: 9min
completed: 2026-06-25
status: complete
---

# Phase 2 Plan 02-02: Make it converse — greeting + per-turn loop + Cybersecurity Trainer persona Summary

**Default Cybersecurity Trainer persona (static frozen-prefix-ready prompt) + greet-on-connect via `session.generate_reply` + live thinking-OFF over Ollama's `/v1` via `with_ollama(reasoning_effort="none")` — the bare voice loop is now wired to speak.**

## Performance

- **Duration:** ~9 min
- **Tasks:** 3
- **Files modified:** 1 (agent/main.py)

## Accomplishments

- Replaced the generic placeholder persona with a concrete **Cybersecurity Trainer** system prompt: security-domain coach that holds a spoken conversation, pulls the learner into articulating the subject, and gently corrects sloppy terminology toward precise practitioner phrasing. Written as a static top block with **no volatile/runtime data** so the Phase 3 frozen prefix (`[persona]+[KB]+[history]+[turn]`) can slot a KB beneath it without a rewrite.
- Added the **greeting on connect**: after `session.start(...)`, `await session.generate_reply(instructions=...)` makes the agent speak first (PERS-01 "talking within seconds"), exercising the full LLM->TTS path — no second hardcoded greeting string.
- Enforced **thinking-OFF on live turns** by passing `reasoning_effort="none"` to `with_ollama(...)`. Ollama's OpenAI-compat `/v1` ignores the native `think` field but maps `reasoning_effort="none"` to its internal `Think=false`. This forwards think-off over `/v1` **without** a Modelfile change or repointing the model — the tag still resolves from `OLLAMA_MODEL` via `resolved_llm_tag()`.
- Left the **per-turn reply loop** to AgentSession's automatic turn (no manual orchestration) and the **first-sentence TTS streaming** to the framework (verified-not-built — no hand-rolled sentence splitter).

## Task Commits

Each task was committed atomically:

1. **Task 02-02-1: default Cybersecurity Trainer persona** - `d25bcd2` (feat)
2. **Task 02-02-2: greet on connect via generate_reply** - `1d4fae8` (feat)
3. **Task 02-02-3: thinking-OFF via reasoning_effort=none; per-turn + first-sentence TTS verify** - `35f7f3f` (feat)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `agent/main.py` (modified):
  - `PERSONA_INSTRUCTIONS` — replaced placeholder with the static Cybersecurity Trainer prompt
  - `GREETING_INSTRUCTIONS` + `entrypoint()` — `session.generate_reply(...)` greeting after `session.start(...)`
  - `build_session()` — `with_ollama(..., reasoning_effort="none")` for live thinking-OFF over `/v1`
  - stale Phase 1 "no generate_reply / no agent speech" docstring updated to describe the live loop

## Decisions Made

- **Thinking-OFF path (a), not (b).** The plan offered two mechanisms: (a) confirm `with_ollama` forwards think-off over `/v1`, or (b) add a template-level `<think>` strip to the `adept-gemma` Modelfile and repoint the LLM. Chose **(a)**: `reasoning_effort="none"` is a documented `with_ollama` parameter and Ollama maps it to `Think=false` over `/v1`. This avoids any Modelfile edit and keeps the LLM tag resolving from `OLLAMA_MODEL` (honoring the "no second hardcoded LLM tag" prohibition). `ollama/Modelfile` is unchanged. This is also belt-and-suspenders: Gemma 4 thinking is request-driven / off-by-default, so the explicit forward hardens an already-likely-off path.
- **`preemptive_generation` not added.** It is an *optional* latency win gated on the kwarg existing on the installed `~=1.5`. Introspection is impossible in this sandbox (livekit-agents not importable), so per the conservative-path guidance it was **not** passed. Deferred to the VM (see Operator Gates).
- **Greeting trigger.** Used the official quickstart pattern (`generate_reply` after `session.start`). Whether this fires exactly once on browser join on the installed version is an operator gate.

## Deviations from Plan

None - plan executed exactly as written. (Path (a) for thinking-OFF is one of the two plan-sanctioned mechanisms, not a deviation; the conservative omission of `preemptive_generation` follows the plan's "only if verified present" instruction.)

## Issues Encountered

None.

## Operator Gates (deferred — VM + LAN device)

This sandbox has **no Docker daemon, no GPU, no browser, and `livekit-agents` is not importable** (`ModuleNotFoundError: No module named 'livekit'`). The following are NOT executed here and are **NOT marked passed** — they must be verified on the Proxmox VM with the stack up, `LIVEKIT_NODE_IP` set, UDP 7882 / TCP 7881 open, and a real CA-trusted LAN device:

### Deferred introspection (could not run — livekit not installed)
- **`AgentSession.generate_reply` signature** (`python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.generate_reply))"`) — confirm the `instructions=` kwarg and the fire-once-on-join trigger semantics on the installed `~=1.5`. The canonical documented pattern was used in the meantime.
- **`AgentSession.__init__` signature** — confirm whether `preemptive_generation` exists on the installed `~=1.5`; if present and desired, add `preemptive_generation=True` in `build_session()`'s `AgentSession(...)`. Currently NOT passed (conservative).
- **`with_ollama` request introspection** — confirm `reasoning_effort="none"` actually rides the `/v1` chat-completions request (and that the installed plugin version exposes the `reasoning_effort` param). Grounded on the published `livekit-plugins-openai` reference + Ollama OpenAI-compat docs, but not executed here.

### Deferred MANUAL operator gates (audible / live)
- **[02-02-2] Greeting (PERS-01):** on browser join the agent audibly greets exactly once as the Cybersecurity Trainer.
- **[02-02-3] First-sentence TTS (VOICE-02):** a multi-sentence reply begins audible playout on its first completed sentence, before the full text is generated (first audio ts precedes full-text ts).
- **[02-02-3] No `<think>` preamble (VOICE-01):** no `<think>` text appears in the live transcript and TTFT is not inflated by a reasoning preamble.
- **[02-02-3] Per-turn loop (VOICE-01):** speak → hear a relevant spoken reply via the full streamed mic->STT->LLM->TTS loop, with no manual per-turn glue.
- **Plan VERIFICATION operator gate:** join → audible greeting → speak → relevant spoken reply that starts on its first sentence; full streamed loop; no `<think>` preamble.

> If the VM introspection reveals `with_ollama` does NOT carry `reasoning_effort` on the installed version, OR a `<think>` preamble still leaks in live output, the fallback is plan path (b): add a template-level `<think>` strip to the `adept-gemma` Modelfile and repoint the LLM at the rebuilt model.

## Client-Verifiable Criteria (executed here — all PASS)

- `python3 -m py_compile agent/main.py` exits 0 — PASS.
- `PERSONA_INSTRUCTIONS` describes a Cybersecurity Trainer (security domain) and references gently correcting terminology — PASS (`grep -i "cybersecurity"` + `grep -i "gently correct"`).
- `PERSONA_INSTRUCTIONS` is a plain string-literal assignment (no f-string / `.format` / interpolation) — PASS.
- `Agent(instructions=PERSONA_INSTRUCTIONS)` still consumes it (no rename break) — PASS.
- `entrypoint()` calls `session.generate_reply(...)` with a greeting instruction after `session.start(...)` — PASS.
- `grep -c generate_reply agent/main.py` = 1 (only the greeting call; no manual per-turn orchestration) — PASS.
- Thinking-OFF mechanism present in `agent/main.py`: `reasoning_effort="none"` on `with_ollama(...)` — PASS.
- `preemptive_generation` is NOT passed (unverified kwarg, deferred) — PASS.
- No hand-rolled sentence splitter — PASS.
- Model still resolves from `OLLAMA_MODEL` via `resolved_llm_tag()`; no second hardcoded gemma tag — PASS.
- `ollama/Modelfile` unchanged (path (a) taken) — PASS.

## Next Phase Readiness

- The bare voice loop is now wired to converse: persona active on load, greeting on connect, thinking-OFF forwarded over `/v1`, per-turn + first-sentence TTS left to the framework. Ready for **02-03** (endpointing tuning ~250–350ms, barge-in gate, client AEC, real per-turn + `e2e_ms` + P50/P95 metrics).
- The operator gates above must be cleared on the VM to close the Phase-2 hard MVP gate (audible loop). 02-03's endpointing-API-surface introspection is also a VM task (same sandbox limit).

## Self-Check: PASSED

- Modified file exists on disk: `agent/main.py` — confirmed.
- `git log --oneline --grep="02-02"` returns 3 task commits — confirmed.
- All client-verifiable `<acceptance_criteria>` re-run and PASS; `python3 -m py_compile agent/main.py` exits 0 from committed state.
- Deferred operator gates + deferred introspection documented above; none fabricated or marked passed.

---
*Phase: 02-bare-voice-loop-mvp-gate*
*Completed: 2026-06-25*
