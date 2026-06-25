---
phase: 04-knowledge-base-layer
plan: 04-02
subsystem: api
tags: [ollama, httpx, distillation, frozen-prefix, kb, persona, livekit]

requires:
  - phase: 04-knowledge-base-layer
    provides: pure parser (agent/kb/parse.py) + in-memory _SessionKb + kb.state publisher + render_persona/KB_SLOT seam
provides:
  - Pure rtc-SDK-free distill surface (agent/kb/distill.py) — build_distill_prompt + off-hot-path distill() + typed DistillError
  - render_prompt(persona, kb_brief="") filling the frozen KB_SLOT; render_persona delegates so the golden stays byte-identical
  - main._ingest_kb extended: distilling → distill() → inject ONCE via update_instructions(render_prompt(...)) → ready → priming turn
  - handle_persona_update composes persona × KB (re-emits the current brief, never clobbers the KB)
  - _SessionKb.brief in-memory field + _concat_docs deterministic join (KB-06 ephemeral)
affects: [04-03-vram-flat-ttft]

tech-stack:
  added: []
  patterns:
    - "Setup-time distill: one off-hot-path Ollama httpx-stream call (think=false, num_predict, no structured-output schema — #15260-safe), latency invisible to the voice loop"
    - "Inject-once frozen prefix: brief lands in KB_SLOT exactly once per session via update_instructions, then FROZEN (no per-turn re-distill/re-inject)"
    - "(persona × KB) epoch compose: persona edit and KB load are both one-time re-prefills that re-emit each other's state, never clobber"

key-files:
  created:
    - agent/kb/distill.py
  modified:
    - agent/kb/__init__.py
    - agent/persona.py
    - agent/main.py

key-decisions:
  - "distill.py reads OLLAMA_GENERATE_URL/OLLAMA_MODEL from os.environ directly (not via `import main`) to avoid a circular import that would also pull in the rtc SDK and break sandbox importability"
  - "render_persona delegates to render_prompt(p, '') so join logic lives in one place; the empty-brief case (`'' or KB_SLOT` == '') keeps the golden byte-identical"
  - "current_persona held as a 1-element list (mutable holder) so both closures (handle_persona_update, ingest_kb) share the same reference for compose"
  - "Plain-text FACTS: delimiter instead of format=json (Ollama #15260) — verbatim fact-anchors for KB-04 grounding"

patterns-established:
  - "Off-hot-path LLM call mirrors _warmup_llm_ttft_ms shape but with a larger num_predict and unbounded timeout (latency invisible)"

requirements-completed: [KB-02, KB-03, KB-04, KB-06]

duration: 10 min
completed: 2026-06-25
status: complete
---

# Phase 4 Plan 04-02: Distill once → inject once into the frozen prefix → KB-grounded trainer Summary

**Setup-time distillation vertical slice: concatenated docs → one off-hot-path Ollama call (`distill()`, think=false, no structured-output schema #15260-safe) → compact prose brief + verbatim `FACTS:` anchors → injected ONCE into the frozen `KB_SLOT` via `render_prompt(persona, brief)` + `update_instructions` → composed with persona edits → priming turn warms the prefill — paid for once at session start, never re-charged per turn.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-25T22:49:24Z
- **Completed:** 2026-06-25T22:57:03Z
- **Tasks:** 4 (3 code commits + 1 verified no-op guard)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `agent/kb/distill.py` (new): pure `build_distill_prompt(text)` (deterministic, sandbox-testable) + `distill(text)` (off-hot-path httpx-stream to `OLLAMA_GENERATE_URL`, `think=False`, `num_predict=2048`, no structured-output schema per #15260) + typed `DistillError`. Model tag resolves from `OLLAMA_MODEL` — no hardcoded tag. rtc-SDK-free (httpx + stdlib).
- `agent/persona.py`: `render_prompt(p, kb_brief="")` fills `KB_SLOT` at the same slot position with `kb_brief or KB_SLOT`; `render_persona` delegates to `render_prompt(p, "")` so the golden is byte-identical. `_self_check` extended with empty-brief equivalence + fixed-brief determinism + brief-in-prefix assertions — all green.
- `agent/main.py`: `_SessionKb.brief` field + `_concat_docs`; `_ingest_kb` now sets `distilling` → `distill()` (try/except `DistillError`) → stores brief → `update_instructions(render_prompt(current_persona, brief))` exactly once → `ready` → priming `generate_reply`. `handle_persona_update` now composes via `render_prompt(p, session_kb.brief)` and updates `current_persona`. KB stays in-memory (KB-06); `agent/metrics.py` untouched.
- `agent/Dockerfile`: verified `COPY kb/ ./kb/` already ships `distill.py` — no change needed.

## Task Commits

1. **Task 04-02-1: pure build_distill_prompt + off-hot-path distill() (#15260-safe)** - `866afe2` (feat)
2. **Task 04-02-2: render_prompt(persona, kb_brief) filling KB_SLOT; golden green** - `4c876db` (feat)
3. **Task 04-02-3: distill, inject once, compose with persona edits, priming turn** - `61e11e1` (feat)
4. **Task 04-02-4: Dockerfile COPY kb/ guard** - verified no-op (no commit; `COPY kb/ ./kb/` already present from 04-01-2)

## Files Created/Modified

- `agent/kb/distill.py` - pure `build_distill_prompt`, off-hot-path `distill()`, `DistillError`, `DISTILL_INSTRUCTION`/`BRIEF_NUM_PREDICT`/`BRIEF_TOKEN_BUDGET`
- `agent/kb/__init__.py` - re-exports `build_distill_prompt`, `distill`, `DistillError`
- `agent/persona.py` - `render_prompt`, `render_persona` delegation, extended `_self_check`
- `agent/main.py` - `_SessionKb.brief`, `_concat_docs`, distill+inject-once+priming in `_ingest_kb`, compose in `handle_persona_update`, `current_persona` holder

## Decisions Made

- **No circular import:** `distill.py` reads `OLLAMA_GENERATE_URL`/`OLLAMA_MODEL` from `os.environ` directly rather than `import main` (which would pull in the rtc SDK and break sandbox importability) — mirrors `main.resolved_llm_tag`.
- **render_persona delegates:** `render_persona(p)` is now `render_prompt(p, "")`; the empty-brief join (`"" or KB_SLOT` == `""`) preserves the golden byte-for-byte.
- **Mutable holder for compose:** `current_persona` is a 1-element list so both `handle_persona_update` and `ingest_kb` share the reference — a persona edit and a KB load each re-emit the other's state (compose, not clobber).
- **Plain-text FACTS anchors over JSON:** avoids Ollama #15260 (`think=false` + structured JSON silently drops the constraint); verbatim `FACTS:` line is parsed out of plain text downstream.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The literal acceptance greps for `format` / `gemma` / `livekit` returning nothing required rewording docstrings in `distill.py` (e.g. "rtc SDK" instead of "livekit", "pinned model family" instead of "gemma-family", "no output-schema key" instead of "format"). Same class of issue as 04-01; no code-behavior change.

## Deferred / Operator Gates (NOT marked passed)

These `[VM-INTROSPECT]` and MANUAL items require the Proxmox VM (installed livekit build, GPU/Ollama, browser + LAN device) and are recorded as **pending operator verification — NOT a blocking checkpoint and NOT marked passed**:

- **`[VM-INTROSPECT]` (distill round-trip):** the live `distill()` output quality on the resident model; whether the brief + `FACTS:` anchors actually ground the trainer (KB-04) end-to-end.
- **`[VM-INTROSPECT]` (update_instructions):** confirm `agent.update_instructions(...)` is a coroutine on the installed build (the inject-once re-prefill).
- **`[VM-INTROSPECT]` (priming turn):** confirm `session.generate_reply(instructions=...)` supports a silent/internal prime (spoken-vs-suppressed decision); goal is the prefill, not a visible utterance.
- **`[VM-INTROSPECT]` (#15260):** whether structured-JSON mode is safe on the pinned Ollama 0.6.8 — only if JSON mode is ever wanted (current path avoids it).
- **MANUAL (VM + LAN device):** upload a doc with a distinctive fact → indicator `parsing → distilling → ready (1 docs)` → ask about that fact by voice and the trainer references the user's material (KB-04); no-KB does NOT invent it; editing the persona after a KB load keeps the KB grounding (compose); the inject turn's elevated `llm_ttft_ms` is the only spike; end session → KB gone (KB-06).

## Next Phase Readiness

- Ready for **04-03** (operator-only flat-TTFT / VRAM proof). The distilled brief now lands in `KB_SLOT`; 04-03 pins `num_ctx` (Modelfile) against `BRIEF_TOKEN_BUDGET` and measures flat per-turn TTFT with the KB resident.
- Operator must run the VM/LAN distill + grounding gates above before relying on the live distill round-trip.

---
*Phase: 04-knowledge-base-layer*
*Completed: 2026-06-25*

## Self-Check: PASSED

- `python3 agent/persona.py` → `persona _self_check OK` (exit 0) — golden + empty-brief equivalence + fixed-brief determinism + brief-in-prefix all pass
- `python3 -m py_compile agent/kb/distill.py agent/persona.py agent/main.py` → exit 0
- `build_distill_prompt('x')==build_distill_prompt('x')` → deterministic
- `distill()` uses `think=False`/`stream=True`/`num_predict`, no `format`, tag from `OLLAMA_MODEL`, typed `DistillError`, no bare except, no rtc-SDK import
- `_ingest_kb` distills + injects once + composes + primes; `agent/metrics.py` unchanged; no disk/db write
- `agent/Dockerfile` `COPY kb/ ./kb/` ships `distill.py`
- All three task commits present (`866afe2`, `4c876db`, `61e11e1`)
- key-files.created exist on disk
