# Adept (voice-trainer) — Claude Code Guidelines

Near-real-time, local-first voice persona trainer: LiveKit Agents pipeline (STT→LLM→TTS)
on a single 16GB-VRAM GPU. Headline metric: voice-to-voice **P50 < 1.0s** (the *streaming* STT mode; `buffered`/`hybrid` are accuracy modes at a measured EOU cost — see README "Pick your STT by hardware").
See `.planning/PROJECT.md` for full scope and `README.md` for run/deploy instructions.

@CODE_PRINCIPLES.md

## Repo layout
- `agent/` — Python LiveKit agent (the STT→LLM→TTS pipeline). Managed with **uv**.
- `web/` — Next.js / React voice UI (`livekit-client`). Managed with **npm**.
- `stt/` — Nemotron streaming ASR sidecar (GPU + CPU-ONNX paths).
- `ollama/`, `proxy/`, `certs/`, `scripts/` — model service, reverse proxy, TLS, ops helpers.
- `docker-compose.yml`, `up.sh`, `livekit.yaml` — 6-service GPU stack, boot + LiveKit config.
- `.planning/` — project research, roadmap, requirements, and per-phase artifacts. **Reference docs only** (read for context; this project does NOT use the GSD workflow). `.planning/research/STACK.md` is the verified version baseline.
- `tests/` — test suite (AAA structure).

## Code Quality
Mandatory (full rules in `CODE_PRINCIPLES.md`, imported above and loaded every session):
SRP, no magic values, descriptive names, error handling on boundaries,
≤40 lines / ≤3 params / ≤3 nesting, no duplication, YAGNI, Law of Demeter, AAA tests.
Prefer: KISS, deep modules, composition over inheritance, latency-first streaming designs.
Document any project-specific deviations in the `## CODE_PRINCIPLES Exceptions` section below.

## Behavioral Rules
- Never guess versions, APIs, or config syntax from training knowledge — research first (see Tool Workflow). The stack moves fast (LiveKit 1.5, Ollama, Gemma 4); `.planning/research/STACK.md` is the verified baseline.
- When a task feels too complex or spans many files, stop and ask before proceeding. Over-engineering is the most common failure mode.
- Understand unfamiliar code before changing it (LSP go-to-definition / find-references, or the `Explore` agent). Don't assume from names alone.
- Before adding any abstraction (interface, base class, wrapper, utility), confirm the current task needs it. If not, don't build it. No abstraction without ≥2 concrete uses today.
- When stuck after 2 attempts at the same problem, say so explicitly rather than trying more variations — the codebase may need fixing, not the approach.
- Prefer extending existing patterns over introducing new ones.
- **Local-first is a hard requirement**: no audio, transcript, or KB content leaves the LAN; no cloud inference endpoints (e.g. avoid `inference.TurnDetector` cloud default — use local `MultilingualModel`).
- **Latency is the design driver**: never add blocking work to the per-turn hot path without measuring TTFT. Stream every stage; start TTS on the first completed sentence. Named latency budgets (EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms) are constants, never inline numbers.
- Request a review pass before committing; fix critical issues first. Never push unreviewed code. Commit/push only when the user asks.

## Conventions
- **Commits**: Conventional Commits (`docs:`, `chore:`, `feat:`, `fix:`).
- **Branches**: currently `master`; tags at milestones. Branch before committing if on the default branch.
- **Naming**: Python agent code → `snake_case`; TS/React web → `camelCase` (vars/functions), `PascalCase` (components/types).
- **Stack** (verified in `.planning/research/STACK.md`): Python agent (`livekit-agents~=1.5`) via **uv**; TS/Next.js web (`livekit-client`) via npm; Docker Compose (6 GPU services). Pin image tags — never `:latest`.
- Boundaries that always need error handling here: mic-permission denial, garbled/empty STT, KB upload/parse failure, Ollama/Kokoro/Whisper sidecar unreachable, LiveKit disconnect.

## Tool Workflow (Claude Code)
- **Research** (never guess versions/APIs — research first):
  - **context7** MCP — up-to-date, version-pinned library/framework docs (LiveKit, Next.js, etc.). Prefer over web search for library docs.
  - **Tavily** skills (`tavily-search`, `tavily-extract`, `tavily-crawl`, `tavily-research`) — current docs, library facts, multi-source synthesis.
  - **Microsoft Learn** MCP — official Microsoft/Azure docs when relevant.
  - `WebFetch` for a specific known doc URL; `WebSearch` for general discovery.
- **Navigate / understand code**: LSP (go-to-definition, find-references) and the `Explore` agent — prefer over manual grep for understanding code. Use `Grep`/`Glob` for fast file/content lookup.
- **Browser & web debugging** (the `web/` UI): the `chrome-devtools` MCP plus the `chrome-devtools`, `chrome-devtools-cli`, `a11y-debugging`, `debug-optimize-lcp`, `memory-leak-debugging`, and `troubleshooting` skills. `playwright` MCP is also available for browser automation.
- **Plan vs build**: use the `Plan` agent or plan mode for analysis without edits; implement directly otherwise.
- **Delegate**: the `Agent` tool runs subagents (`Explore`, `Plan`, `general-purpose`) — use for independent units of work in parallel.
- **Skills**: invoke reusable workflows via the `Skill` tool whenever a matching skill exists (research, frontend-design, web-design-guidelines, vercel-react-best-practices, the chrome-devtools debugging skills, etc.).
- **Hard reasoning**: the `sequential-thinking` MCP is available for multi-step problem decomposition.

## Memory (mandatory — two complementary stores)
Use BOTH, for different purposes:
- **agentmemory MCP** (cross-workstation, durable): for lasting, cross-session, cross-project decisions and lessons that should follow you between machines.
  - **At task start**: `memory_smart_search` to load prior decisions, conventions, and gotchas before writing code or re-asking what was settled.
  - **At phase boundaries** (after research, after a design decision, after fixing a non-obvious bug, when the user says "remember this"): `memory_save` with clear `content`, 2–5 `concepts`, a `type` (pattern/preference/architecture/bug/workflow/fact), and relevant `files`.
  - **Before editing an unfamiliar file**: check `memory_file_history` for past pitfalls.
  - **Never** fabricate memory results — present only what the tools return. If the agentmemory MCP is unreachable, tell the user rather than proceeding silently.
- **Claude Code native file memory** (`~/.claude/.../memory/` + `MEMORY.md`): for session-local and Claude-Code-specific context — quick durable facts about this harness setup, user preferences, and pointers. Follow the memory rules in the system prompt.

When in doubt: durable engineering decisions → agentmemory; harness/workflow notes → native memory.

## Session Strategy
- New session for: new features, unrelated bugs, fresh context.
- Use `/compact` (or let auto-compaction run) at natural phase boundaries — after research, planning, or implementation. Summarize state before compaction on long sessions.

## Documentation Updates
After every implementation, check and update: `README.md`, `CHANGELOG.md` (if present), API docs, and this `CLAUDE.md` if conventions changed.

## CODE_PRINCIPLES Exceptions
None yet. Document project-specific deviations here as they arise (e.g. "Reference templates copied verbatim from `.planning/phases/*/01-PATTERNS.md` may exceed the ≤40-line rule").

## Auditable invariants
- **Voice-only isolation (Phase 14, AVTR-12)** replaces the Phase-12 "avatar never touches the server pipeline" frontend-only gate. With Avatar OFF, the captioned TTS requests no word timestamps and publishes no `lk.avatar.*` data channel — voice-only is byte-for-byte the same Kokoro audio with zero avatar traffic. Avatar-ON captioned TTS (the `lk.avatar.lipsync` schedule publish) is the documented, intentional server-pipeline touch, gated live by the `avatar.update` RPC.
