---
phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
plan: 13-01
subsystem: ui
tags: [react, nextjs, css, design-tokens, refactor, accessibility]

requires:
  - phase: 12-optional-3d-avatar-part-d
    provides: voice-only bundle isolation gate (AVTR-01), avatar importmap in layout.tsx head
provides:
  - web/app/ui/tokens.ts — palette/space/radius/font + shared panelStyle/labelStyle/inputStyle (pure constants, zero deps)
  - web/app/ui/apply.ts — ApplyState type + STATUS_LABEL/STATUS_COLOR maps
  - web/app/globals.css — keyframes, :focus-visible ring, transcript scrollbar, prefers-reduced-motion block, transition utility classes
  - de-duplicated config panels importing the shared token module
affects: [13-02-setup-before-connect, 13-03-talking-screen-polish]

tech-stack:
  added: []
  patterns:
    - "Shared pure-constants token module (no React import) mirroring avatarConfig.ts discipline for bundle isolation"
    - "Global CSS stylesheet for keyframes/focus-ring/reduced-motion; inline styles consume token objects"

key-files:
  created:
    - web/app/ui/tokens.ts
    - web/app/ui/apply.ts
    - web/app/globals.css
  modified:
    - web/app/layout.tsx
    - web/app/page.tsx
    - web/app/PersonaPanel.tsx
    - web/app/ModelPanel.tsx
    - web/app/InterviewPanel.tsx
    - web/app/KbPanel.tsx
    - web/app/AgentStatePill.tsx

key-decisions:
  - "Split ApplyState/STATUS maps into ui/apply.ts (not tokens.ts) so KbPanel's distinct KbStatus union stays uncoupled"
  - "Presentational-only refactor: every agent-mirrored constant left byte-identical in its panel"

patterns-established:
  - "ui/tokens.ts: palette (locked hex), space (4px scale), radius, font (4 sizes/2 weights) — the single design-system source"
  - "globals.css transition utility classes (.transition-hover/.transition-status/.transition-pill) animate transform/opacity only"

requirements-completed: []

duration: 14 min
completed: 2026-06-27
status: complete
---

# Phase 13 Plan 13-01: Foundation — Shared Token Module + De-dup Refactor Summary

**Extracted the copy-pasted inline-style blocks across 4 config panels into one pure-constants `ui/tokens.ts` (+ `ui/apply.ts`) and added a `globals.css` (keyframes, focus-visible ring, prefers-reduced-motion block) — presentational-only, zero new deps, every agent-mirrored constant byte-identical.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-06-27T07:39:00Z
- **Completed:** 2026-06-27T07:53:10Z
- **Tasks:** 4
- **Files modified:** 7 (3 created, 7 modified)

## Accomplishments
- New `web/app/ui/tokens.ts` — locked `palette`, `space` (4px scale), `radius`, `font` (4 sizes/2 weights), plus rebuilt `panelStyle`/`labelStyle`/`inputStyle`; pure constants, no React import.
- New `web/app/ui/apply.ts` — shared `ApplyState` union + byte-identical `STATUS_LABEL`/`STATUS_COLOR`.
- New `web/app/globals.css` — cross-fade/jump-pill/status keyframes, `:focus-visible` 2px `#58a6ff` ring, transcript scrollbar, transition utility classes, and a `prefers-reduced-motion` block disabling all animation/transition. Imported once in `layout.tsx`.
- Refactored PersonaPanel/ModelPanel/InterviewPanel/KbPanel/AgentStatePill to import shared tokens; normalized all sub-14px text to the token scale; behavior (RPCs, sendFile, STATE_COLORS) unchanged.
- Dropped the inline `<h1>Adept</h1>` from `page.tsx` (wordmark relocates to SetupScreen in 13-02); relaxed `layout.tsx` body flex-centering so the two full-screen layouts own their centering. Importmap untouched.

## Task Commits

1. **Task 13-01-1: shared token + apply modules** - `7c4bb3d` (feat)
2. **Task 13-01-2: globals.css + layout wiring** - `35e34db` (feat)
3. **Task 13-01-3: panel + AgentStatePill token refactor** - `cfb497c` (refactor)
4. **Task 13-01-4: drop inline wordmark** - `0ec525c` (feat)

## Files Created/Modified
- `web/app/ui/tokens.ts` - Design-system source of truth (palette/space/radius/font + shared styles)
- `web/app/ui/apply.ts` - ApplyState + STATUS_LABEL/STATUS_COLOR
- `web/app/globals.css` - Keyframes, focus ring, scrollbar, reduced-motion, transition utilities
- `web/app/layout.tsx` - Import globals.css; relaxed body centering (importmap untouched)
- `web/app/page.tsx` - Removed inline wordmark; full-height main
- `web/app/PersonaPanel.tsx` / `ModelPanel.tsx` / `InterviewPanel.tsx` - Import tokens + apply maps; removed local style/STATUS/ApplyState blocks
- `web/app/KbPanel.tsx` - Import panelStyle/inputStyle from tokens; kept own KbStatus maps
- `web/app/AgentStatePill.tsx` - Sourced non-state values from tokens; STATE_COLORS byte-identical

## Decisions Made
- Put `ApplyState`/`STATUS_*` in a separate `ui/apply.ts` rather than `tokens.ts`, keeping the presentational palette and the agent-apply contract cleanly separated and leaving KbPanel's distinct `KbStatus` union uncoupled.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Token module + global CSS foundation is in place; 13-02 (setup-before-connect) and 13-03 (talking polish) can build against `ui/tokens.ts`, `ui/apply.ts`, and the `globals.css` transition utilities.
- Verification: `npm run build` (web/) clean; `web/package.json` deps unchanged; importmap intact; all agent-mirrored constants byte-identical; no plan-scoped change under `agent/`/`stt/`/`tts/`/`docker-compose.yml` (pre-existing out-of-scope edits there were left untouched).

## Self-Check: PASSED
- `web/app/ui/tokens.ts`, `web/app/ui/apply.ts`, `web/app/globals.css` exist on disk.
- `git log --grep="13-01"` returns 4 task commits.
- `npm run build` (web/) succeeds with zero errors / zero new deps.
- Agent-mirrored constants (VOICE_IDS, DEFAULT_PERSONA, CHOICES/CHOICE_LABEL, MODE_*/ROLES, KB_UPLOAD_TOPIC/KB_STATE_ATTRIBUTE/MAX_UPLOAD_BYTES) and AgentStatePill STATE_COLORS verified byte-identical.
- globals.css imported once; `:focus-visible` ring + `prefers-reduced-motion` block present; no remote `@import`; importmap unchanged.

---
*Phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis*
*Completed: 2026-06-27*
