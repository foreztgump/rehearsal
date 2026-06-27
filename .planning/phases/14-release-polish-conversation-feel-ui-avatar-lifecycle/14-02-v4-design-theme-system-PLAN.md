---
phase: 14
plan: 14-02
slug: v4-design-theme-system
depends_on: []
status: ready
kind: verify-and-close-gaps
files_modified:
  - web/app/globals.css        # only if a verified gap requires it
  - web/app/SetupScreen.tsx     # only if a verified gap requires it
requirements: [UI-01, UI-02, UI-03]
---

# Plan 14-02 — v4 Design Language + Theme System (Verify & Close Gaps)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. **This is a verification plan, not a build.**
> The v4 design language and the six-theme switcher are already implemented and in
> `master` (commit `e5f9389`). Your job is to *prove* UI-01/02/03 against the running
> app and fix only genuine, verified gaps — do not rebuild working code.

**Goal:** Sign off UI-01 (v4 design language app-wide), UI-02 (six persisted themes,
reduced-motion respected), and UI-03 (responsive + accessible + no console errors),
and close any real gap surfaced by the checks.

**Architecture (already in tree — do not re-architect):**
- `web/app/ui/tokens.ts` — palette as CSS-variable references (`var(--bg)` …).
- `web/app/globals.css` — six `[data-theme="…"]` palette blocks (35–166); ambient
  drift (189–243); grain (245); frosted topbar (589); `:focus-visible` ring (752);
  `prefers-reduced-motion` kill-switch (832).
- `web/app/ui/themes.ts` — six-theme registry (`THEMES`, `getTheme`, `isThemeId`,
  `DEFAULT_THEME_ID="eclipse-aurora"`, `THEME_STORAGE_KEY="adept.theme"`).
- `web/app/ui/ThemeProvider.tsx` — SSR-safe hydrate from `localStorage`, writes
  `<html data-theme>`.
- `web/app/ThemeDots.tsx` — six-swatch picker (`role="radiogroup"`), rendered in
  `SetupScreen` header **and** `SettingsDrawer`.

**Tech Stack:** Next.js 16, React 19, CSS custom properties. No test runner in `web/`
(`package.json` has only `dev`/`build`/`start`) — verification is `tsc --noEmit` +
`npm run build` + manual browser checks (the `chrome-devtools` MCP is available).

**Current state (vs PRD §2):** PRD §2 says this is "not implemented." **Stale** — it
is implemented. PRD §10's open question ("theme choice also in the drawer?") is
already answered yes (`ThemeDots` is in `SettingsDrawer`). Record this correction.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: CSS-only design layer (no remote font/framework
`@import`, no new runtime dependency); motion animates only transform/opacity;
`prefers-reduced-motion` honored everywhere.

---

## Task 1: Static + build verification

**Files:** none (verification only).

- [ ] **Step 1: Typecheck + production build are green**

Run:
```bash
cd web && npx tsc --noEmit && npm run build
```
Expected: `tsc` prints nothing (success); `next build` completes with no type errors
and no "Module not found".

- [ ] **Step 2: Confirm the six theme palettes + design layers exist**

Run:
```bash
cd web && grep -c '\[data-theme=' app/globals.css        # expect >= 6 (+ the :root alias)
grep -n 'prefers-reduced-motion' app/globals.css          # expect the kill-switch block
grep -n 'backdrop-filter' app/globals.css                 # expect frosted topbar
grep -n 'fractalNoise' app/globals.css                    # expect grain texture
grep -c 'id:' app/ui/themes.ts                            # expect 6 theme ids
```
Expected: all present; the six `ThemeId`s in `themes.ts` match the six
`[data-theme="…"]` blocks in `globals.css` (eclipse-aurora, nebula-bloom, sonar-pulse,
liquid-ember, prism-wave, aurora-veil).

- [ ] **Step 3: Confirm `eclipse-aurora` is the SSR default**

Run:
```bash
cd web && grep -n 'DEFAULT_THEME_ID' app/ui/themes.ts app/layout.tsx
```
Expected: `DEFAULT_THEME_ID = "eclipse-aurora"` and `layout.tsx` seeds
`<html data-theme={DEFAULT_THEME_ID}>` (so SSR markup matches the default palette
block — no hydration flash).

---

## Task 2: Theme switch + persistence + reduced-motion (manual, browser)

**Files:** none unless a gap is found.

- [ ] **Step 1: Start the app**

Run: `cd web && npm run dev` (or use the running stack's web service). Open the setup
screen. (Optionally drive these via the `chrome-devtools` MCP: `new_page` → the local
URL, `take_snapshot`, `click` the theme dots, `list_console_messages`.)

- [ ] **Step 2: Each of the six themes applies instantly**

Click each swatch in the setup-header `ThemeDots`. Expected: background, accent,
ambient blobs, CTA gradient, and the setup-screen orb (`Visualizer`) all recolor
instantly with no reload and no flicker. The active dot shows the accent ring
(`.theme-dot.on`).

- [ ] **Step 3: Choice persists across reload**

Pick `prism-wave`, reload the page. Expected: the app re-renders in `prism-wave`
(read from `localStorage["adept.theme"]`), not the default — with no visible flash of
the default theme before hydration.

- [ ] **Step 4: Theme is switchable in-room too**

Start a session, open Settings. Expected: the drawer's `ThemeDots` switches the theme
live during the conversation (closing PRD §10's open question — record "drawer entry
shipped").

- [ ] **Step 5: Reduced-motion is respected**

In DevTools, emulate `prefers-reduced-motion: reduce` (chrome-devtools `emulate`), then
reload. Expected: ambient drift + grain animation + all transitions are frozen
(globals.css `@media` kill-switch), and the orb renders a **single static frame**
(`Visualizer` reduced-motion branch) instead of animating. The app remains fully
usable and on-theme.

- [ ] **Step 6: If any check fails, fix the specific gap only**

Record the failing check. The likely-and-only candidate edits are `web/app/globals.css`
(a missing transition/variable) or `web/app/SetupScreen.tsx` (a picker not wired).
Make the minimal fix, re-run Task 1 Step 1, and commit:
```bash
cd .. && git add web/app/globals.css web/app/SetupScreen.tsx && \
  git commit -m "fix(14-02): <specific verified theme gap>"
```
If all checks pass, no commit — note "no gap found" in the verification record.

---

## Task 3: Responsive + accessibility + no-console-errors (manual, browser)

**Files:** none unless a gap is found.

- [ ] **Step 1: Responsive setup→talk across breakpoints**

Resize (chrome-devtools `resize_page`) to 375px (mobile), 768px (tablet), 1280px
(desktop). Expected: the setup card's `.grid-2` collapses to one column ≤600px (per
globals.css 269); the talking screen reflows; nothing clips or overflows.

- [ ] **Step 2: Keyboard navigation + focus-visible**

Tab through the setup screen. Expected: every interactive control (theme dots, model
select, mic picker, avatar toggle, Customize disclosure, Start) is reachable in order
and shows the 2px accent `:focus-visible` ring. The theme dots behave as a radiogroup
(`role="radiogroup"`, arrow/Tab to each `role="radio"`).

- [ ] **Step 3: No console errors across the full flow**

With the console open (chrome-devtools `list_console_messages`), run
setup → Start → talk → open Settings → switch theme → Leave. Expected: **zero** errors
(warnings from third-party libs are acceptable; record them).

- [ ] **Step 4: If a gap is found, fix minimally + re-verify**

Same discipline as Task 2 Step 6.

---

## Task 4: Sign-off + PRD correction note

**Files:**
- Modify: `.planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-02-v4-design-theme-system-PLAN.md`
  (append the signed verification record).

- [ ] **Step 1: Record the verification result**

Append a "Verification record" block: each UI-0x requirement → PASS/FAIL + evidence
(build output, the themes you cycled, the persistence/reduced-motion observations,
the console state). For any gap fixed, link the commit.

- [ ] **Step 2: Note the PRD §2/§10 correction**

State plainly: PRD §2 understated this workstream (it is built); PRD §10's drawer
question is resolved (shipped). This keeps the record honest for 14-09's UAT.

- [ ] **Step 3: Commit the record**

```bash
git add .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-02-v4-design-theme-system-PLAN.md
git commit -m "docs(14-02): sign v4 design + theme verification; correct PRD §2/§10"
```

## Verification (summary)
- `cd web && npx tsc --noEmit && npm run build` green.
- Six themes apply instantly + persist across reload; switchable in setup and drawer.
- `prefers-reduced-motion` freezes ambient/grain/transitions and renders the static orb.
- Responsive 375/768/1280; keyboard-navigable with visible focus ring; zero console
  errors across setup→connect→talk.

## Artifacts this plan produces
- A **signed verification record** (in this file) for UI-01/02/03.
- At most **minimal gap fixes** to `web/app/globals.css` / `web/app/SetupScreen.tsx`
  (only if a check fails). Expected: none.
