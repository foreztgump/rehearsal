# CODE_PRINCIPLES.md — Adept (voice-trainer)

Hard rules and soft guidelines for all code in this project. Loaded into every opencode session *in this project* via the project-root `opencode.json` → `instructions`. The agent MUST follow these on every change; reviewers enforce them. Per-project deviations live in `AGENTS.md` under `## CODE_PRINCIPLES Exceptions`.

## Hard rules (do not violate)

### 1. Single Responsibility (SRP)
Each function does one thing. If its description needs "and", split it.
❌ `parse_and_validate(input)`  ✓ `parse(input)` + `validate(parsed)`

### 2. No magic values
Literals must be named constants. Exempt: `0`, `1`, `True`, `False`, `''`.
❌ `if status == 429: retry(60)`  ✓ `RATE_LIMIT_STATUS = 429; BACKOFF_SECONDS = 60`
(Project-specific: latency budgets like EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms are named constants, never inline numbers.)

### 3. Function size & shape
- ≤40 lines per function. Decompose if longer.
- ≤3 parameters. Group into a config object / dataclass if more.
- ≤3 nesting levels. Use early returns and guard clauses.

### 4. Error handling on every boundary
Every fallible operation has explicit handling.
| Language | Required pattern |
|---|---|
| Python (agent) | no bare `except:`; no `except Exception: pass` without re-raise/handling; use context managers for resources |
| TS/JS (web) | `try/catch` for async + I/O; never silently swallow promises |
Boundaries that always need handling here: mic-permission denial, garbled/empty STT, KB upload/parse failure, Ollama/Kokoro/Whisper sidecar unreachable, LiveKit disconnect.

### 5. Names reveal intent
- No abbreviations (`usr`, `cfg`, `tmp`).
- No generic names in scopes >3 lines (`data`, `info`, `item`, `result`, `temp`).
- Function names are verbs; class/type names are nouns.

### 6. No duplication
Logic blocks of >5 similar lines must be extracted. Small near-duplicates are sometimes fine; large ones are not.

### 7. YAGNI
Only what the task requires. No speculative interfaces, no "while I'm here" generalizations, no abstraction without ≥2 concrete uses today. (Explicitly out of scope per PROJECT.md: vector RAG, multi-user/auth, persistent KB — do not build ahead of the roadmap.)

### 8. Law of Demeter
No method chains through ≥2 objects. Talk to direct collaborators only.
❌ `session.get_room().get_participant().get_track().get_codec()`  ✓ add an intent-revealing accessor.

## Soft guidelines (note, don't block)
- **Deep modules**: simple interface over complex implementation.
- **KISS**: simplest solution that meets requirements wins.
- **Composition over inheritance** when both work.
- **Comments explain WHY, not WHAT**: delete comments that restate the code.
- **Pure functions where practical**: easier to test and reason about.
- **Latency-first**: this project optimizes time-to-first-token and first-sentence streaming over throughput. Prefer streaming/incremental designs; never add a synchronous step into the per-turn hot path without measuring TTFT impact.

## Flag for deeper review
Surface these to the user (or a `plan`/review pass) rather than deciding silently:
- **Deep-module violation** — interface as complex as its implementation (abstraction hides nothing).
- **Hidden coupling** — modules reach into each other's internals.
- **Dependency-direction violation** — high-level modules depend on concretions instead of abstractions.
- **Hot-path regression** — any change that adds blocking work between STT result and first TTS sentence.

## Project-specific exceptions
Document overrides in `AGENTS.md` under `## CODE_PRINCIPLES Exceptions` (e.g. generated code exempt from rules 1–7). The agent reads `AGENTS.md` every session and respects documented exceptions.

## See also
- `AGENTS.md` — project conventions and opencode tool/agent workflow.
- opencode rules & instructions: https://opencode.ai/docs/rules
