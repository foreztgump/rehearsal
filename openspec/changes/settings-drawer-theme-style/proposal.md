# Settings drawer — theme & style alignment

## Why

The in-room **SettingsDrawer** (`web/app/SettingsDrawer.tsx`) hosts theme-correct panels
(Persona/Interview/Model/KB/ThemeDots) but owns four inline-styled blocks that bypass the
shared v4 theme system, so they don't re-skin with the active `[data-theme]` and don't
match the rest of the app. This is a presentational fix: reuse the existing shared classes,
add the one genuinely-missing scrim class.

## What Changes

- **Scrim** — replace the hardcoded `background: "rgba(0,0,0,0.55)"` (not theme-aware, no
  blur) with a new `.drawer-scrim` class that is theme-driven + blurred, reusing the exact
  `.topbar` translucency pattern (`color-mix(in srgb, var(--bg) …, transparent)` +
  `backdrop-filter: blur()`). This is the ONE new class — no `.scrim`/`.drawer-scrim`
  exists today.
- **Drawer panel** — drop the flat inline `background: palette.panel` (+ redundant inline
  `borderLeft`) and apply the existing `.surface` class (gradient `--panel-2 → --panel` +
  `box-shadow: var(--shadow)`), matching SetupScreen's `className="screen-enter surface"`.
- **Close button** — replace the inline-reimplemented button with the shared `.btn-ghost`.
- **End session** — the armed outline button → `.btn-ghost danger` (matches TalkingScreen's
  identical End action); the confirm-step destructive fill → `.btn-apply danger` (a new
  `.danger` recolor modifier mirroring the existing `.btn-ghost.danger` convention), whose
  label color comes from `var(--ink)` — fixing the current wrong `color: palette.bg`; the
  confirm-step Cancel → `.btn-ghost`.

BREAKING: none. `END_CONFIRM` stays exported; the F33 two-step confirm is preserved.

## Capabilities

None new. This is a presentational alignment of an existing capability
(in-room session settings) onto already-established shared classes; no SHALL/MUST behavior
changes, so no `specs/` capability spec is warranted (PONYTAIL — don't add files the change
doesn't need). `design.md` is likewise skipped: the only design decision is recorded below.

## The one design decision

**Destructive confirm fill: reuse `.btn-apply` + a new `.btn-apply.danger` modifier**
(NOT a standalone `.btn-danger` class, NOT an inline recolor of base `.btn-apply`).
Justification: it reuses `.btn-apply`'s entire fill shape (padding, radius, weight,
`color: var(--ink)`, hover transform) and overrides only `background → var(--destructive)`
(dropping the accent glow), which is the smallest on-pattern change and directly mirrors the
already-present `.btn-ghost.danger` recolor-modifier convention.

## Impact

- `web/app/SettingsDrawer.tsx` — swap four inline-styled blocks to shared classes; remove the
  hardcoded scrim rgba and the `color: palette.bg` label.
- `web/app/globals.css` — add `.drawer-scrim` and the `.btn-apply.danger` modifier.
- `web/app/settingsDrawerTheme.test.mjs` — new TDD guard (text-assertion, `node --test`).
- `CHANGELOG.md` — `[Unreleased] › Changed` entry (`web`).
- No hot-path, RPC, dep, or latency impact (pure CSS/JSX). a11y floor unchanged.
