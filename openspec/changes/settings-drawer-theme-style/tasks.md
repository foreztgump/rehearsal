# Tasks — settings-drawer-theme-style

TDD order: red test first (T1), make it green with the surgical component + CSS fix (T2),
then verify the whole web suite + typecheck stay clean (T3). Standard tier, width-1: each
task depends on the previous, so `assign-waves.py` will schedule three sequential 1-wide waves.

Shared hard rules (CODE_PRINCIPLES.md) for every task: **no magic values** (use `tokens.ts`
`palette`/`space`/`radius`/`font` or CSS variables — never raw hex/rgba in TSX), **SRP**,
**≤40 lines / ≤3 params / ≤3 nesting**, **no duplication** (reuse the shared class, don't
re-implement it), **YAGNI** (only the one new scrim class + one `.danger` modifier).

---

## T1 — Red: assert the drawer uses shared theme classes

- **Create**: `web/app/settingsDrawerTheme.test.mjs`
- **Test**: this file IS the test (mirrors `talkingScreenEnd.test.mjs` / `kbDropzone.test.mjs`
  — `node --test`, `node:assert/strict`, read source as text, assert on class names/patterns).

Acceptance criteria (each an assertion; the suite must FAIL red against today's
`SettingsDrawer.tsx` + `globals.css`, proving it guards the real fix):

- [ ] Scrim is themed, not hardcoded: `assert.doesNotMatch(drawerSrc, /rgba\(0\s*,\s*0\s*,\s*0\s*,\s*0\.55\)/)`
      AND `assert.match(drawerSrc, /className="drawer-scrim"/)`.
- [ ] `globals.css` defines the scrim theme-aware: a `.drawer-scrim` block that contains
      `backdrop-filter` AND a `var(--…)`-based background (assert both substrings within the
      block — reuse the `.topbar` `color-mix`/`var(--bg)` pattern; no literal `rgba(0,0,0,`).
- [ ] Drawer panel uses `.surface`: `assert.match(drawerSrc, /className="[^"]*\bsurface\b[^"]*"/)`
      AND no inline `background: palette.panel` remains on the panel
      (`assert.doesNotMatch(drawerSrc, /background:\s*palette\.panel/)`).
- [ ] Close button uses `.btn-ghost` and drops its inline reimplementation
      (`assert.match` a `btn-ghost` Close button; `assert.doesNotMatch` a `borderRadius:\s*radius\.control`
      paired with the Close `aria-label="Close settings"` region — simplest: assert the file no
      longer contains `aria-label="Close settings"` within ~200 chars of an inline `border:` — or,
      pragmatically, assert the Close button line carries `className="btn-ghost"`).
- [ ] End armed outline uses `.btn-ghost danger`: `assert.match(drawerSrc, /className="btn-ghost danger"/)`
      (parity with TalkingScreen).
- [ ] End confirm destructive fill uses `.btn-apply danger`:
      `assert.match(drawerSrc, /className="btn-apply danger"/)`, AND its label color is NOT
      `palette.bg` (`assert.doesNotMatch(drawerSrc, /color:\s*palette\.bg/)`), AND `globals.css`
      has a `.btn-apply.danger` rule setting `background: var(--destructive)`.
- [ ] Confirm-step Cancel uses `.btn-ghost` (`assert.match` a `btn-ghost` Cancel button).
- [ ] Back-compat: `assert.match(drawerSrc, /export const END_CONFIRM/)` still holds
      (keeps `talkingScreenEnd.test.mjs` green).
- [ ] No newly-introduced raw hex in the TSX: assert `SettingsDrawer.tsx` contains no `#`-hex
      color literal (there are none today; the fix must not add any).

- **Error-handling strategy**: none — pure static assertions, no runtime/boundary. If a path
  URL is wrong the test throws (visible red), which is the intended TDD signal.
- **Hard rules**: AAA structure per assertion; descriptive test names; no magic values beyond
  the class-name string literals under assertion.

---

## T2 — Green: reskin the four inline blocks onto shared classes

- **Modify**: `web/app/SettingsDrawer.tsx`, `web/app/globals.css`
- **Depends on**: T1

Acceptance criteria:

- [ ] `globals.css`: add a `.drawer-scrim` rule — `position: fixed; inset: 0;` background via
      `color-mix(in srgb, var(--bg) 60%, transparent)` (reusing the `.topbar` translucency
      recipe) + `backdrop-filter: blur(4px)` + `-webkit-backdrop-filter: blur(4px)`. No new
      z-index/layout coupling beyond what the inline scrim already set (the TSX keeps `zIndex`,
      `display:flex`, `justifyContent`, `inset` — or move them all into the class; either is
      fine, but the scrim COLOR must come from the class, not inline).
- [ ] `globals.css`: add `.btn-apply.danger { background: var(--destructive); box-shadow: none; }`
      (recolor-only modifier; inherits `color: var(--ink)`, padding, radius, hover from `.btn-apply`).
- [ ] `SettingsDrawer.tsx` scrim `<div>`: remove `background: "rgba(0,0,0,0.55)"`; add
      `className="drawer-scrim"` (keep the `onClick={onClose}` close-on-scrim behavior).
- [ ] `SettingsDrawer.tsx` panel `<div>`: change `className="screen-enter"` →
      `className="screen-enter surface"`; remove the inline `background: palette.panel` and the
      now-redundant inline `borderLeft` (the `.surface` gradient + `--shadow` replace them; keep
      `width`, `height`, `overflowY`, `padding`, layout flex props inline via tokens).
- [ ] Close button: delete the inline `border`/`borderRadius`/`background`/`padding`/`color`
      style object; render `className="btn-ghost"` (keep `type`, `onClick`, `aria-label`).
- [ ] End armed-outline button: replace the inline destructive-outline style with
      `className="btn-ghost danger"` (keep `onClick={() => setConfirmLeave(true)}` and the
      `alignSelf: "flex-start"` if still wanted via a token/style — but no inline color/border).
- [ ] End confirm fill button: `className="btn-apply danger"`; delete the inline style object
      **including** the wrong `color: palette.bg`; keep `flex: 1` layout via a minimal inline
      style if needed (`{ flex: 1 }` is layout, not theme — acceptable) and `onClick={onEnd}`.
- [ ] Confirm Cancel button: `className="btn-ghost"` (+ optional `{ flex: 1 }`), drop inline
      border/background/color; keep `onClick={() => setConfirmLeave(false)}`.
- [ ] Two-step confirm structure (`confirmLeave` state, `END_CONFIRM` copy paragraph) is
      **unchanged** — only the button styling swaps. `END_CONFIRM` stays exported.
- [ ] Import hygiene (owned here, since T2 owns every `SettingsDrawer.tsx` edit): after the
      inline styles are removed, if any of `font`/`palette`/`radius`/`space` is now unused, drop
      it from `import { font, palette, radius, space } from "./ui/tokens"` so no dead import
      lingers (`space`/`font`/`palette` almost certainly still used; `radius` may become unused).
- [ ] a11y floor intact: `role="dialog"`, `aria-modal`, `aria-label="Session settings"`, the
      focus trap (`FOCUSABLE`), Escape handler, and open-focus effect are untouched; the shared
      classes inherit the global `:focus-visible` ring.
- [ ] T1 now passes green.

- **Error-handling strategy**: presentational only — no new boundaries. The existing mic/RPC/
      LiveKit boundaries in this file (`resetSession`, `newSession`) are NOT in scope and stay
      byte-for-byte unchanged.
- **Hard rules**: no duplication (reuse classes), no magic values (tokens/vars only), keep the
      `return`-JSX render function within nesting/length limits — swapping inline styles for
      classes reduces its size, so this improves compliance.

---

## T3 — Verify: web suite + typecheck stay clean

- **Test / verify only** (no source edits): `web/app/*.test.mjs`, `npx tsc --noEmit`
- **Depends on**: T2

Acceptance criteria:

- [ ] `cd web && node --test app/*.test.mjs` — the prior 52 pass, PLUS the new
      `settingsDrawerTheme.test.mjs` assertions, all green; `talkingScreenEnd.test.mjs` and
      `kbDropzone.test.mjs` unaffected.
- [ ] `cd web && npx tsc --noEmit` — introduces **no new** errors. The 2 pre-existing
      `.next`-generated `validator.ts` errors (stale `stt-debug/route.js`) are out of scope and
      may remain; assert the count/identity is unchanged, not zero.
- [ ] `CHANGELOG.md`: add a `[Unreleased] › Changed` entry referencing `web`, e.g.
      "SettingsDrawer scrim/panel/close/End controls now use the shared theme classes
      (`.drawer-scrim`, `.surface`, `.btn-ghost[.danger]`, `.btn-apply.danger`) instead of
      hardcoded inline styles." (AGENTS.md: CHANGELOG mandatory on every change.)

- **Error-handling strategy**: this is the verification gate — any red test or new tsc error
      blocks completion (do not mark done on partial/failing state, per the completion rules).
- **Hard rules**: documentation update (CHANGELOG) is part of "done"; YAGNI (no extra tests
      beyond the guard).
