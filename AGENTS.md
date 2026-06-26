# Adept (voice-trainer) — Project Guidelines

Near-real-time, local-first voice persona trainer: LiveKit Agents pipeline (STT→LLM→TTS) on a single 16GB-VRAM GPU. Headline metric: voice-to-voice **P50 < 1.0s**. See `.planning/PROJECT.md` for full scope.

## Code Quality
Mandatory: SRP, no magic values, descriptive names, error handling on boundaries,
≤40 lines / ≤3 params / ≤3 nesting, no duplication, YAGNI, Law of Demeter, AAA tests.
Prefer: KISS, deep modules, composition over inheritance, latency-first streaming designs.
Full rules: `CODE_PRINCIPLES.md` (loaded every session in this project via the project-root `opencode.json` → `instructions`).

## Behavioral Rules
- Never guess versions, APIs, or config syntax from training knowledge — research first (see Tool Workflow). The stack moves fast (LiveKit 1.5, Ollama, Gemma 4); `.planning/research/STACK.md` is the verified baseline.
- When a task feels too complex or spans many files, stop and ask before proceeding. Over-engineering is the most common failure mode.
- Use `lsp` (goToDefinition, findReferences) to understand unfamiliar code before changing it. Don't assume from names alone.
- Before adding any abstraction (interface, base class, wrapper, utility), confirm the current task needs it. If not, don't build it.
- When stuck after 2 attempts at the same problem, say so explicitly rather than trying more variations — the codebase may need fixing, not the approach.
- Prefer extending existing patterns over introducing new ones.
- Local-first is a hard requirement: no audio, transcript, or KB content leaves the LAN; no cloud inference endpoints (e.g. avoid `inference.TurnDetector` cloud default — use local `MultilingualModel`).
- Latency is the design driver: never add blocking work to the per-turn hot path without measuring TTFT. Stream every stage; start TTS on the first completed sentence.
- Request a review pass before committing; fix critical issues first. Never push unreviewed code.

## Existing Conventions
- **State**: greenfield — no source code committed yet (only `.planning/`). Establish conventions as code lands; update this section when tooling configs (linter/formatter) appear.
- **Commits**: Conventional Commits (`docs:`, `chore:`, `feat:`, `fix:`).
- **Branches**: `master` only; GSD branching strategy is `none` (work on `master`, tags at milestones).
- **Naming**: Python agent code → `snake_case`; TS/React web → `camelCase` (vars/functions), `PascalCase` (components/types).
- **Planned stack** (from `.planning/research/STACK.md`): Python agent (`livekit-agents~=1.5`) via **uv**; TS/Next.js web (`livekit-client`) via npm; Docker Compose (6 GPU services). Pin image tags — never `:latest`.

## Tool Workflow (opencode)
- **Research** (never guess versions/APIs — research first):
  - **Tavily** is the primary web-research tool, used CLI/skill-first: the `tavily-search`, `tavily-extract`, `tavily-crawl`, and `tavily-research` skills wrap the Tavily CLI. Reach for these for current docs, library facts, and multi-source synthesis.
  - **context7** (wired MCP server) for up-to-date, version-pinned library/framework docs (LiveKit, Next.js, etc.).
  - `webfetch` for a specific known doc URL; `websearch` for opencode's built-in discovery; `@scout` for cloning a dependency and reading its source.
- **Navigate**: `lsp` (goToDefinition, findReferences, documentSymbol) and `@explore` — prefer over manual grep for understanding code.
- **Search**: `grep`, `glob`, `list` for fast file/content lookup.
- **Plan vs build**: switch to the `plan` agent (Tab) for analysis without edits; `build` for implementation.
- **Delegate**: the `task` tool runs subagents (`explore`, `scout`, `general`) — use for independent units of work in parallel.
- **Skills**: load reusable workflows via the `skill` tool when a matching skill exists (e.g. the `tavily-*` research skills).
- **Memory**: agentmemory is mandatory — `memory_smart_search` before starting, `memory_save` at phase boundaries (see Agent Memory below).

## Agent Memory (mandatory)
This project uses agentmemory for persistent cross-session memory, wired as the `agentmemory` MCP server. Memory use is REQUIRED, not optional:
- **At task start**: call `memory_smart_search` (or `/recall <topic>`) to load prior decisions, conventions, and gotchas before writing code or asking the user what was already settled.
- **At phase boundaries** (after research, after a design decision, after fixing a non-obvious bug, when the user says "remember this"): call `memory_save` (or `/remember <insight>`) with a clear `content`, 2–5 `concepts`, and a `type` (pattern/preference/architecture/bug/workflow/fact). Include relevant `files`.
- **Before editing an unfamiliar file**: check `memory_file_history` for past pitfalls.
- **Never** fabricate memory results — present only what the tools return.
The store is shared across workstations, so memories saved on one machine are available on another. If the `agentmemory` MCP tools are unavailable, tell the user the memory server isn't reachable rather than proceeding silently.

## Agents
- `build` (primary) — full tool access; default for implementation.
- `plan` (primary) — edits/bash `ask`; analysis and planning.
- `explore` (subagent, read-only) — fast codebase search.
- `scout` (subagent, read-only) — external docs / dependency source.
- `general` (subagent) — multi-step research, parallel work.
Tab to switch primaries; `@<name>` or `task` to invoke subagents.

## Workflow (GSD-core)
This project uses the GSD-core phase loop: **Discuss → Plan → Execute → Verify → Ship**, driven by `/gsd-*` commands. Workflow state lives in `.planning/` — `STATE.md` (where the project sits in the loop), `ROADMAP.md` (7 phases), `REQUIREMENTS.md` (42 v1 requirements), `PROJECT.md` (scope/decisions), and per-phase artifacts under `.planning/phases/`. Read `STATE.md` first to orient. `.planning/` is GSD-owned: let the `/gsd-*` commands manage it rather than hand-editing.
- **`.planning/` vs agentmemory** — complementary, not redundant: `.planning/` holds *this project's* current workflow state (the artifacts of the active loop); agentmemory holds *durable, cross-session, cross-project* decisions and lessons. Save lasting insights to agentmemory; let GSD own the phase artifacts.

## Session Strategy
- New session for: new features, unrelated bugs, fresh context.
- Run `/compact` at natural phase boundaries (after research, planning, implementation). opencode also auto-compacts when context fills.
- For long sessions, summarize state before compaction so context survives.

## Documentation Updates
After every implementation, check and update: README.md, CHANGELOG.md, API docs, and this `AGENTS.md` if conventions changed (especially the Existing Conventions section once linter/formatter configs land).

## CODE_PRINCIPLES Exceptions
None yet. Document project-specific deviations here as they arise (e.g. "Reference templates copied verbatim from `.planning/phases/*/01-PATTERNS.md` may exceed the ≤40-line rule").
