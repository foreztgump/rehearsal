---
phase: 13
plan: 13-01
slug: foundation-token-dedup
wave: 1
depends_on: []
autonomous: true
files_modified:
  - web/app/ui/tokens.ts
  - web/app/ui/apply.ts
  - web/app/globals.css
  - web/app/layout.tsx
  - web/app/page.tsx
  - web/app/PersonaPanel.tsx
  - web/app/ModelPanel.tsx
  - web/app/InterviewPanel.tsx
  - web/app/KbPanel.tsx
  - web/app/AgentStatePill.tsx
requirements: []
---

# Plan 13-01 — Foundation: Shared Token Module + De-dup Refactor

## Goal

Establish the design-system foundation for the Phase 13 overhaul WITHOUT changing
behavior: extract the copy-pasted inline-style blocks (`panelStyle`/`labelStyle`/
`inputStyle`/`STATUS_LABEL`/`STATUS_COLOR`/`ApplyState`) into one shared
`web/app/ui/tokens.ts` (+ `ui/apply.ts`) consumed by every panel, add one
`web/app/globals.css` (keyframes, focus-visible ring, scrollbar, reduced-motion
block, transition utility classes) imported in `layout.tsx`, and normalize
typography/spacing onto the UI-SPEC px scale (no size below 14px). This is a
**presentational-only** refactor: every agent-mirrored constant stays byte-identical
and no server file changes.

This is the first of three slices (foundation → setup-before-connect → talking
polish). It is autonomous and unblocks 13-02 and 13-03 by giving them the token
module + global CSS to build against.

## Must-Haves (goal-backward)

### Truths (must remain TRUE)
- The web app builds clean (`npm run build` in `web/`) with zero new runtime deps.
- Visual appearance is preserved or improved per UI-SPEC; the dark palette values
  (`#0b0f14` bg, `#0d1117` panel, `#161b22` input, `#30363d` border, `#58a6ff`
  accent, `#3fb950` action, `#d29922` warning, `#f85149` destructive, text
  `#e6edf3`/`#c9d1d9`/`#8b949e`) are unchanged.
- `globals.css` exists, is imported once in `layout.tsx`, and contains a
  `@media (prefers-reduced-motion: reduce)` block disabling transitions/animations
  and a `:focus-visible` 2px `#58a6ff` ring (accessibility, success criterion 5).
- D-03: The shared token module + `globals.css` keyframes/transition utilities
  (transform/opacity only, tasteful and performant, reduced-motion-aware)
  establish the clean, animated, well-organized visual foundation the rest of
  the phase builds on.
- No text size below 14px remains in the refactored panels (success criterion 5).

### Prohibitions (must NOT happen)
- MUST NOT change any file under `agent/`, `stt/`, `tts/`, or `docker-compose.yml`
  (`git diff -- agent/ stt/ tts/ docker-compose.yml` empty).
- MUST NOT add any new runtime dependency to `web/package.json` (no CSS framework,
  no motion library, no icon package) — preserves the AVTR-01 voice-only bundle gate.
- MUST NOT drop, rename, or change the value of ANY agent-mirrored constant:
  PersonaPanel `VOICE_IDS`/`DIFFICULTY`/`VERBOSITY`/`CORRECTION`/`DEFAULT_PERSONA`,
  ModelPanel `CHOICES`/`CHOICE_LABEL`, InterviewPanel `MODE_LEARN`/`MODE_INTERVIEW`/
  `ROLES`/`ROLE_LABEL`, KbPanel `KB_UPLOAD_TOPIC`/`KB_STATE_ATTRIBUTE`/
  `MAX_UPLOAD_BYTES`. These stay in their panels (or a non-presentational module),
  NOT mixed into `tokens.ts`.
- MUST NOT move or alter the `layout.tsx` importmap `<script type="importmap">` in
  `<head>` (avatar specifier-resolution ordering).
- MUST NOT change AgentStatePill per-state color VALUES (only the source of shared
  tokens moves; the `STATE_COLORS` map stays byte-identical).
- MUST NOT change any RPC method, payload key, or behavior in the panels (apply
  logic untouched in this slice).

## Tasks

<task id="13-01-1">
<title>Create the shared token module and ApplyState module</title>
<read_first>
- web/app/PersonaPanel.tsx (source of the de-dup blocks: panelStyle:47-74,
  labelStyle, inputStyle, STATUS_LABEL:33-45, STATUS_COLOR, ApplyState:20)
- web/app/ModelPanel.tsx (byte-identical style blocks 35-62, STATUS_* 21-33)
- web/app/InterviewPanel.tsx (byte-identical style blocks 36-63, STATUS_* 22-34)
- web/app/avatarConfig.ts (the dependency-free pure-constants module SHAPE to mirror — no React import, tree-shakes)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Spacing Scale, Typography, Color tables — the normalization target)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 1 section — token module contract)
</read_first>
<action>
Create `web/app/ui/tokens.ts` as a pure-constants module (no React import; same
discipline as avatarConfig.ts). Export:
- A `palette` object holding the locked color values (bg `#0b0f14`, panel
  `#0d1117`, inputBg `#161b22`, border `#30363d`, accent `#58a6ff`, action
  `#3fb950`, warning `#d29922`, destructive `#f85149`, text `#e6edf3`, textBody
  `#c9d1d9`, textMuted `#8b949e`).
- A `space` object mapping xs/sm/md/lg/xl/xxl/xxxl to "4px".."64px" per UI-SPEC.
- A `radius` object (control "8px", card "12px", pill "999px").
- A `font` object with the 4 sizes (body 16px, label 14px, heading 20px, display
  28px) and 2 weights (400, 600) and line-heights (1.5 body, 1.2 heading).
- Typed `React.CSSProperties` objects `panelStyle`, `labelStyle`, `inputStyle`
  rebuilt from the palette/space/radius/font tokens (replacing the rem ad-hoc
  values; bump `0.9rem`/`0.85rem` text to >=14px). Keep panel `background`
  `#0d1117`, border `#30363d`, input `background` `#161b22` exactly.
Create `web/app/ui/apply.ts` exporting `type ApplyState = "idle"|"applying"|
"applied"|"error"` plus `STATUS_LABEL` and `STATUS_COLOR` maps with the
byte-identical current values (idle "" `#8b949e`, applying "applying…" `#d29922`,
applied "applied" `#3fb950`, error "error — could not apply" `#f85149`).
Do NOT put any agent-mirrored constant into either module.
</action>
<acceptance_criteria>
- `web/app/ui/tokens.ts` and `web/app/ui/apply.ts` exist; neither imports React
  (type-only `React.CSSProperties` annotation is allowed) nor has side effects.
- `STATUS_LABEL`/`STATUS_COLOR` values in `ui/apply.ts` are byte-identical to the
  current PersonaPanel values (grep-diff: same 4 labels, same 4 colors).
- `tokens.ts` palette values match the locked palette exactly (assert each hex).
- No agent-mirrored key (`VOICE_IDS`, `CHOICES`, `ROLES`, `MODE_*`,
  `DEFAULT_PERSONA`, `KB_UPLOAD_TOPIC`, etc.) appears in either new module.
- `web/package.json` dependencies unchanged.
</acceptance_criteria>
</task>

<task id="13-01-2">
<title>Create globals.css and wire it in layout.tsx</title>
<read_first>
- web/app/layout.tsx (importmap in <head> lines 14-30 MUST NOT MOVE; body flex-center 31-42)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Animation Contract table; §Navigation/§Accessibility focus ring; reduced-motion requirement)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 2 + File 16 sections)
</read_first>
<action>
Create `web/app/globals.css` containing ONLY CSS (no `@import` of remote
font/framework): `@keyframes` for setup↔talking cross-fade, jump-pill in/out, and
status fades; a `:focus-visible { outline: 2px solid #58a6ff; outline-offset: 2px; }`
rule; a custom scrollbar rule scoped to a transcript container class; transition
utility classes (`.screen-enter`, `.screen-exit`, `.jump-pill`, etc.) using the
UI-SPEC durations (240ms setup→talking ease-out, 200ms reverse ease-in, 120ms
hover, 160ms segmented-slide, 150ms status/pill) animating ONLY `transform`/
`opacity`; and a `@media (prefers-reduced-motion: reduce) { *, *::before, *::after
{ animation: none !important; transition: none !important; } }` block.
In `web/app/layout.tsx`: add `import "./globals.css";` at the top, and relax the
`<body>` flex-center so the two full-screen layouts can own their centering (body
becomes a plain full-height block: keep `fontFamily: system-ui`, `margin: 0`,
`minHeight: 100vh`, `background: #0b0f14`, `color: #e6edf3`; remove the
`display:flex/alignItems/justifyContent` centering). DO NOT touch the importmap.
</action>
<acceptance_criteria>
- `web/app/globals.css` exists and is imported exactly once via `layout.tsx`.
- The `@media (prefers-reduced-motion: reduce)` block disables `animation` and
  `transition` globally; the `:focus-visible` rule yields a 2px `#58a6ff` outline.
- No `@import url(...)` of any remote resource exists in globals.css.
- `layout.tsx` importmap `<script type="importmap">` is unchanged and still in
  `<head>` before `<body>` (assert byte-identical AVATAR_IMPORTMAP block).
- `npm run build` (in web/) compiles globals.css without error.
</acceptance_criteria>
</task>

<task id="13-01-3">
<title>Refactor the four config panels + AgentStatePill to import shared tokens</title>
<read_first>
- web/app/PersonaPanel.tsx (full — remove its local style/STATUS/ApplyState blocks, keep VOICE_IDS/DIFFICULTY/VERBOSITY/CORRECTION/DEFAULT_PERSONA + apply() RPC untouched)
- web/app/ModelPanel.tsx (full — keep CHOICES/CHOICE_LABEL + apply() RPC untouched)
- web/app/InterviewPanel.tsx (full — keep MODE_LEARN/MODE_INTERVIEW/ROLES/ROLE_LABEL + apply() RPC untouched)
- web/app/KbPanel.tsx (full — keep KB_UPLOAD_TOPIC/KB_STATE_ATTRIBUTE/MAX_UPLOAD_BYTES + KbStatus union + sendFile untouched; KbStatus is a DIFFERENT union from ApplyState — do NOT merge)
- web/app/AgentStatePill.tsx (full — STATE_COLORS values stay byte-identical)
- web/app/ui/tokens.ts + web/app/ui/apply.ts (created in 13-01-1)
- agent/persona.py (verify VOICE_IDS / DEFAULT_PERSONA values stay mirrored)
- agent/main.py (verify MODEL_CHOICES + KB_UPLOAD_TOPIC/KB_STATE_ATTRIBUTE mirrored)
- agent/interview.py (verify MODE/ROLES mirrored)
</read_first>
<action>
In PersonaPanel, ModelPanel, InterviewPanel: delete the local `panelStyle`/
`labelStyle`/`inputStyle`/`STATUS_LABEL`/`STATUS_COLOR`/`ApplyState` definitions and
replace with `import { panelStyle, labelStyle, inputStyle } from "./ui/tokens";` and
`import { ApplyState, STATUS_LABEL, STATUS_COLOR } from "./ui/apply";`. Leave the
agent-mirrored constants and the entire `apply()`/`performRpc` body untouched.
In KbPanel: import `panelStyle`/`inputStyle` from `./ui/tokens`; KEEP its own
`KbStatus` union and its `STATUS_LABEL`/`STATUS_COLOR` maps (different union — do not
merge with `ApplyState`). Keep `sendFile`, size check, and attribute-read effect.
In AgentStatePill: optionally source the pill background `#0b0f14`/radius/font from
tokens; keep the `STATE_COLORS` map byte-identical. Normalize any sub-14px font on
all five files to the token sizes.
</action>
<acceptance_criteria>
- PersonaPanel/ModelPanel/InterviewPanel no longer define local style or STATUS
  blocks; they import from `./ui/tokens` and `./ui/apply`.
- `git diff` shows ZERO change to: PersonaPanel `VOICE_IDS`/`DIFFICULTY`/`VERBOSITY`/
  `CORRECTION`/`DEFAULT_PERSONA`, ModelPanel `CHOICES`/`CHOICE_LABEL`, InterviewPanel
  `MODE_LEARN`/`MODE_INTERVIEW`/`ROLES`/`ROLE_LABEL`, KbPanel
  `KB_UPLOAD_TOPIC`/`KB_STATE_ATTRIBUTE`/`MAX_UPLOAD_BYTES` (grep each value).
- Each panel's `apply()`/`upload()` RPC/sendFile body is behaviorally unchanged
  (same method names `persona.update`/`model.update`/`mode.update`, same payload
  keys, same `kb.upload` topic).
- AgentStatePill `STATE_COLORS` values byte-identical.
- `npm run build` (web/) succeeds with no type errors.
- `git diff -- agent/ stt/ tts/ docker-compose.yml` is empty.
</acceptance_criteria>
</task>

<task id="13-01-4">
<title>Drop the inline wordmark from page.tsx (defer wordmark to SetupScreen)</title>
<read_first>
- web/app/page.tsx (full — the inline <h1>Adept</h1> at line 6)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 15 section)
</read_first>
<action>
In `web/app/page.tsx`, remove the inline `<h1 style=...>Adept</h1>` (the wordmark
relocates to SetupScreen in 13-02). Keep `<main>` and `<VoiceRoom/>`; relax the
`textAlign:"center"` on `<main>` if it conflicts with the talking screen filling the
viewport (coordinate with the relaxed body in 13-01-2). Do not otherwise change the
VoiceRoom mount.
</action>
<acceptance_criteria>
- `page.tsx` no longer renders an inline `<h1>Adept</h1>`.
- `<VoiceRoom/>` is still mounted.
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

## Verification

- `cd web && npm run build` completes with zero errors and zero new dependencies in
  `package.json`.
- `git diff -- agent/ stt/ tts/ docker-compose.yml` is empty.
- Grep confirms every frozen agent-mirrored constant value is byte-identical to its
  pre-refactor value and still mirrors its `agent/*.py` source.
- `web/app/globals.css` contains the reduced-motion block and the `:focus-visible`
  ring; it is imported once in `layout.tsx`; the importmap is untouched.
- No font-size below 14px remains in the refactored panels.

## Artifacts this phase produces

- **NEW file** `web/app/ui/tokens.ts` — exports `palette`, `space`, `radius`, `font`,
  `panelStyle`, `labelStyle`, `inputStyle` (pure constants, zero deps).
- **NEW file** `web/app/ui/apply.ts` — exports `ApplyState` type, `STATUS_LABEL`,
  `STATUS_COLOR`.
- **NEW file** `web/app/globals.css` — keyframes, `:focus-visible` ring, transcript
  scrollbar, `prefers-reduced-motion` block, transition utility classes.
- **MODIFIED** `web/app/layout.tsx` (globals.css import + relaxed body), `page.tsx`
  (wordmark removed), `PersonaPanel.tsx`/`ModelPanel.tsx`/`InterviewPanel.tsx`/
  `KbPanel.tsx`/`AgentStatePill.tsx` (token imports; behavior unchanged).
