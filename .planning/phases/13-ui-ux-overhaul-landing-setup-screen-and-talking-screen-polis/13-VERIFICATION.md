---
phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
mode: ui
status: passed
verified_at: 2026-06-27
verdict: PASS
build: clean (npm run build — compiled + TypeScript OK)
---

# Phase 13 Verification — UI/UX Overhaul (Landing Setup Screen + Talking Screen Polish)

## Verdict: PASS

All five success criteria are satisfied in the actual codebase (`web/app/*`). The web
app builds clean (`next build` — "Compiled successfully", "Finished TypeScript"). All
three plan SUMMARYs (13-01, 13-02, 13-03) accurately reflect the shipped code. No new
runtime dependency was added; the agent-mirrored constants and RPC/stream contracts are
byte-identical.

---

## Success Criteria

### 1. App opens on dedicated setup screen; only connects after explicit "Connect/Start" — PASS

- `VoiceRoom.tsx:87-97` renders `<SetupScreen>` while `!token`. No `<LiveKitRoom>`,
  no `/api/token` fetch, no room hooks execute on initial render.
- `start()` (`VoiceRoom.tsx:71-85`) is the only path that sets `token`; it is invoked
  exclusively by the `Start session` CTA (`SetupScreen.tsx:186` → `onStart`). Single
  user gesture: fetch token → `setToken` → `<LiveKitRoom connect>` mounts
  (`VoiceRoom.tsx:99-113`).
- `SetupScreen.tsx` imports NO `useRoomContext`/`useVoiceAssistant` (confirmed) — it is
  pure pre-connect React state.
- Held config applied only AFTER connect + agent readiness via `ApplySetupOnConnect.tsx`
  (gated on `agent?.identity`, `useRef` once-guard, default-skip). RPC order
  persona→mode→model→KB; method names/payload keys (`persona.update`, `mode.update`
  `{mode, role_key}`, `model.update` `{choice}`, topic `kb.upload`) byte-identical to
  the live panels. No RPC fires before the agent joins.

### 2. Clean, organized, consistently styled with tasteful performant animations — PASS

- Single shared design-system source `ui/tokens.ts` (locked palette, 4px space scale,
  radius, 4 sizes/2 weights) consumed by every panel/screen. Locked hex values present
  and unchanged.
- All four config panels + AgentStatePill de-duped onto the token module; `ui/apply.ts`
  holds the shared `ApplyState`/`STATUS_*` maps (byte-identical: idle/applying…/applied/
  "error — could not apply" with `#8b949e`/`#d29922`/`#3fb950`/`#f85149`).
- `globals.css` animates ONLY `transform`/`opacity` (GPU-friendly): `screen-enter`
  240ms ease-out, `screen-exit` 200ms ease-in, jump-pill 150ms, status/segment/hover/
  disclosure utilities — durations match the UI-SPEC Animation Contract table.
- No remote `@import` in globals.css. SetupScreen is a single elegant card
  (max-width 720px, panel bg, 12px radius), NOT a wizard/grid (D-01). Defaults pre-fill
  all six groups; advanced fields behind a collapsed "Customize" disclosure (D-02).
- Minor note: `AvatarStage.tsx:703,706` retains two `0.9rem` muted "loading avatar…"
  lines (~14.4px, still ≥14px). AvatarStage was explicitly out-of-scope for the
  refactor (prohibition: do not touch avatar internals); the four refactored config
  panels carry no sub-14px text. Non-blocking.

### 3. Navigation between setup and talking is intuitive and reversible — PASS

- `SettingsDrawer.tsx` is an overlay rendered INSIDE `<LiveKitRoom>` (UI-SPEC pattern
  (a)). Opening/closing it (`TalkingScreen.tsx:116-120`, `open` boolean) never unmounts
  the room — transcript, agent, and avatar persist.
- Drawer hosts Persona/Interview/Model/KB in UNCONTROLLED live-RPC mode (no props →
  `*Live` wrappers), so tweaks apply to the running agent via the unchanged
  `performRpc`/`sendFile` paths.
- Destructive "Leave session" shows the exact UI-SPEC confirm copy
  ("End this conversation and return to setup? Your transcript will clear.") and only on
  confirm calls `onLeave` → `setToken(null)` (`VoiceRoom.tsx:125`) — the single
  disconnect path back to setup. No premature teardown (Phase 14 owns clear-all).
- Avatar dynamic-import `dynamic(() => import("./AvatarStage"), { ssr:false })` preserved
  (`VoiceRoom.tsx:16`); importmap in `layout.tsx` `<head>` untouched.

### 4. Live transcript auto-scrolls to newest while at bottom; no yank when scrolled up — PASS

- `Transcript.tsx` wraps the `<ul>` in a bounded `overflow-y:auto`, `flex:1`,
  `min-height:0` container (`transcript-scroll`). `atBottomRef` (ref, not state) is
  recomputed on `scroll` against named `THRESHOLD = 32`.
- `useEffect([segments])` writes `el.scrollTop = el.scrollHeight` (instant) ONLY when
  `atBottomRef.current`; when scrolled up it does not move the viewport — it only flips
  the jump pill on (no yank).
- "Jump to latest ↓" pill (accent `#58a6ff`, bottom-center) shows only when scrolled up
  with content; click → `scrollTo({behavior:"smooth"})` + re-engages stick.
- Interim vs final styling: `lk.transcription_final === "true"` ⇒ final (opacity 1);
  else interim (opacity 0.7 / italic). User-right `#e6edf3` / agent-left `#58a6ff` split
  + `user-` attribution preserved. Empty-state copy ("Start talking" / "Say hello…")
  renders at zero segments. Token streaming renders instantly (no animation).

### 5. Responsive + accessible — keyboard-navigable, no console errors — PASS

- `:focus-visible { outline: 2px solid #58a6ff; outline-offset: 2px }` global ring;
  `@media (prefers-reduced-motion: reduce)` disables all animation/transition.
- SettingsDrawer: Escape closes (capture-phase keydown), Tab focus-trapped to the
  panel's focusables, focus moved into the drawer on open; `role="dialog"`
  `aria-modal="true"`. Segmented toggles use `role="group"` + `aria-label`; Customize
  uses `aria-expanded`.
- Layouts are responsive flex columns (`100vh`, `flex:1`/`min-height:0` transcript hero;
  setup card `width:100%`, `maxWidth:720px`). Primary actions are native `<button>`s
  (Enter/Space) with 44px CTA target.
- No-console-error paths verified by construction: no RPC before `agent.identity`
  (ApplySetupOnConnect gate); MicPicker degrades enumerate/permission failures to an
  inline muted note (never throws — `MicPicker.tsx:36-48,56-72`); build emits zero type
  errors.

---

## Plan SUMMARY cross-reference (claimed vs actual)

| Plan | Claimed artifacts | Actual on disk | Status |
|------|-------------------|----------------|--------|
| 13-01 | `ui/tokens.ts`, `ui/apply.ts`, `globals.css`; panels de-duped; wordmark dropped from page.tsx; body relaxed | All present; tokens locked-palette + 4px scale + 4/2 typography; apply maps byte-identical; globals.css has focus-ring + reduced-motion + no remote @import; `page.tsx` has no inline `<h1>`; `layout.tsx` body de-centered, importmap intact | MATCH |
| 13-02 | `SetupScreen.tsx`, `MicPicker.tsx`, `ApplySetupOnConnect.tsx`; `SessionConfig`; dual-mode panels | All present; SetupScreen has no room hooks, 6 groups defaulted, always-enabled CTA, Customize disclosure; MicPicker controlled + permission affordance; ApplySetupOnConnect once-guard + agent gate + default-skip + RPC order; VoiceRoom shell plumbs `micDeviceId`→`audioCaptureDefaults.deviceId` | MATCH (3-task combined commit `0a64d7f` noted as deviation — justified by circular `SessionConfig` type) |
| 13-03 | `TalkingScreen.tsx`, `SettingsDrawer.tsx`; Transcript auto-scroll/jump/interim/empty | All present; TalkingScreen flex column top-bar/avatar/hero-transcript/drawer; SettingsDrawer reversible overlay + focus trap + Leave confirm; Transcript THRESHOLD=32, ref-based stick, jump pill, interim 0.7/italic, empty state | MATCH |

Commits present: `0ec525c`/`42d3c2f` (13-01), `b4568ca`/`7331e66`/`0a64d7f` (13-02),
`14c206b`/`7337d15`/`23be36b`/`28234a8` (13-03).

---

## Prohibitions / invariants

- `git diff -- agent/ stt/ tts/ docker-compose.yml`: changes present BUT they are the
  pre-existing **out-of-scope Path-B captioned-lipsync** work (`agent/main.py`,
  `agent/Dockerfile`, `stt/*`, untracked `agent/captioned_tts.py`) — explicitly flagged
  as NOT part of phase 13 and correctly excluded by all three plans. No phase-13-scoped
  file touched them.
- Uncommitted `web/app/AvatarStage.tsx` + `avatarConfig.ts` changes are the SAME
  out-of-scope lip-sync feature (adds `LIPSYNC_TOPIC`, word→viseme timeline). These are
  NOT phase-13 changes and do not affect any phase-13 success criterion; the avatar
  dynamic-import/ssr:false contract and importmap ordering remain intact.
- No new runtime dependency in `web/package.json` (CSS-only animations, native HTML).
- Agent-mirrored constants byte-identical: `DEFAULT_PERSONA` (Cybersecurity Trainer,
  `af_bella`, gentle) mirrors `agent/persona.py`; `VOICE_IDS`/`CHOICES`/`ROLES`/`MODE_*`/
  `KB_UPLOAD_TOPIC`/`KB_STATE_ATTRIBUTE`/`MAX_UPLOAD_BYTES` unchanged; AgentStatePill
  `STATE_COLORS` byte-identical.

---

## Build

```
cd web && npm run build
✓ Compiled successfully in ~1.7s
  Finished TypeScript (no errors)
✓ Generating static pages (3/3)
Route (app): / (Static), /api/token (Dynamic)
```

## Notes / non-blocking observations

1. `AvatarStage.tsx` still has two `0.9rem` (~14.4px, ≥14px) muted loading lines —
   inside the explicitly out-of-scope avatar component; the four refactored config
   panels are clean. Cosmetic, optional follow-up.
2. The setup→talking cross-fade is implemented via the `screen-enter` ENTER keyframe on
   both screens; the `screen-exit` reverse class exists in globals.css but is not wired
   to an explicit exit animation (React unmounts the setup tree immediately on `setToken`).
   Acceptable: the enter cross-fade is present, reduced-motion-aware, and non-janky;
   meets criterion 2. Optional polish for a future slice.
