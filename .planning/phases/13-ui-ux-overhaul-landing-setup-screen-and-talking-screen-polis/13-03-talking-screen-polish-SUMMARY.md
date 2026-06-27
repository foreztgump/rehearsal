---
phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
plan: 13-03
subsystem: ui
tags: [react, nextjs, livekit, transcript, auto-scroll, settings-drawer, talking-screen]

requires:
  - phase: 13-02-setup-before-connect
    provides: VoiceRoom thin-shell orchestrator (SessionConfig + token + phase), controlled config panels with preserved live-RPC uncontrolled path, ApplySetupOnConnect, globals.css cross-fade/jump-pill utilities, ui/tokens.ts
provides:
  - web/app/TalkingScreen.tsx — in-room Screen B layout (top bar + optional avatar stage + hero transcript + settings drawer)
  - web/app/SettingsDrawer.tsx — reversible in-room overlay hosting live-tweak panels + destructive Leave-session affordance (copy only)
  - Transcript smart stick-to-bottom auto-scroll + "Jump to latest ↓" pill + interim/final styling + empty state
affects: [14-session-lifecycle]

tech-stack:
  added: []
  patterns:
    - "Stick-to-bottom auto-scroll: atBottom tracked in a ref (no render churn), instant scrollTop write on segment change only when atBottom, smooth scroll reserved for explicit Jump click"
    - "Interim vs final transcript styling via streamInfo.attributes['lk.transcription_final'] === 'true' (0.7 opacity/italic for interims)"
    - "Reversible navigation: settings as an overlay INSIDE <LiveKitRoom> (never unmount); only a confirmed Leave sets token=null"
    - "Avatar element mounted in the shell (preserves dynamic-import ssr:false contract) and passed as a prop into TalkingScreen's 360px region"

key-files:
  created:
    - web/app/TalkingScreen.tsx
    - web/app/SettingsDrawer.tsx
  modified:
    - web/app/Transcript.tsx
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Interim flag resolved to streamInfo.attributes['lk.transcription_final'] (livekit-client ParticipantAgentAttributes.TranscriptionFinal) verified against @livekit/components-react@2.9.21 setupTextStream source"
  - "Avatar <AvatarStage> stays mounted in VoiceRoom (shell) and is passed into TalkingScreen as an `avatar` ReactNode prop, so the dynamic-import ssr:false contract + importmap ordering never move"
  - "SettingsDrawer hosts the panels in UNCONTROLLED mode (no value/onChange) so their existing performRpc/sendFile live-apply logic is reused byte-identical"
  - "Focus trap implemented with a capture-phase keydown listener (Escape closes, Tab cycles visible focusables) — no new dependency"

requirements-completed: []

duration: 4 min
completed: 2026-06-27
status: complete
---

# Phase 13 Plan 13-03: Talking Screen Polish — Layout, Settings Drawer, Smart Auto-Scroll Summary

**Extracted the in-room subtree into a clean TalkingScreen (top bar with state pill + Voice-only/Avatar toggle + Settings, optional 360px avatar stage, hero Transcript), moved the config panels into a reversible SettingsDrawer overlay that never unmounts `<LiveKitRoom>`, and gave Transcript ref-based stick-to-bottom auto-scroll with a "Jump to latest ↓" pill, interim/final styling, and an empty state.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-27T08:08:38Z
- **Completed:** 2026-06-27T08:12:01Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- **Transcript smart auto-scroll (13-03-1):** wrapped the `<ul>` in a bounded `overflow-y:auto` flex-column container using the globals.css `.transcript-scroll` class. `atBottomRef` (ref, not state) recomputed on the container `scroll` event against a named `THRESHOLD = 32`; a `useEffect` keyed on `[segments]` writes `scrollTop = scrollHeight` (instant) only when at bottom and never yanks when scrolled up. The "Jump to latest ↓" pill (accent `#58a6ff`, bottom-center, `.jump-pill`) shows only when scrolled up with content; click → `scrollTo({behavior:"smooth"})` + re-engage stick. Interims (`lk.transcription_final !== "true"`) render at `0.7` opacity / italic vs full-opacity finals; user-right `#e6edf3` / agent-left `#58a6ff` split + `user-` attribution preserved. Empty-state heading/body renders when there are no segments.
- **SettingsDrawer (13-03-2):** new right-side overlay rendered inside `<LiveKitRoom>` (open/onClose/onLeave props). Hosts Persona/Interview/Model/KB in their unchanged uncontrolled live-RPC mode. Escape closes, Tab is focus-trapped (capture-phase keydown), focus moves into the drawer on open, every control gets the globals.css `#58a6ff` focus ring. Destructive "Leave session" (`#f85149`) reveals the UI-SPEC confirm copy and only on confirm calls `onLeave`; no teardown logic beyond the token reset (Phase 14 owns clear-all).
- **TalkingScreen + shell wiring (13-03-3):** new full-height flex column (top bar / optional avatar / hero transcript / drawer). VoiceRoom now renders `<TalkingScreen>` (replacing the inline 5-panel row) alongside `<ApplySetupOnConnect>`, keeps `<RoomAudioRenderer/>` + `<StartAudio/>` in the shell, mounts `<AvatarStage>` in the shell and passes it as the `avatar` prop, and routes `onLeave` to `setToken(null)` (the only disconnect path). 240ms cross-fade via `.screen-enter`.

## Task Commits

1. **Task 13-03-1: Transcript smart auto-scroll + jump pill + interim styling + empty state** - `14c206b` (feat)
2. **Task 13-03-2: SettingsDrawer reversible in-room overlay** - `7337d15` (feat)
3. **Task 13-03-3: TalkingScreen + VoiceRoom shell wiring** - `23be36b` (feat)

## Files Created/Modified
- `web/app/TalkingScreen.tsx` (NEW) - In-room Screen B layout; top bar + optional avatar + hero Transcript + SettingsDrawer
- `web/app/SettingsDrawer.tsx` (NEW) - Reversible overlay hosting live panels + Leave-session affordance (copy only)
- `web/app/Transcript.tsx` - Stick-to-bottom auto-scroll, jump pill, interim/final styling, empty state
- `web/app/VoiceRoom.tsx` - Renders TalkingScreen inside the persistent `<LiveKitRoom>`; avatar mounted in shell

## Decisions Made
- **Interim flag source:** verified against the `@livekit/components-react@2.9.21` / `@livekit/components-core` `setupTextStream` source that transcription finality rides `streamInfo.attributes["lk.transcription_final"]` (livekit-client `ParticipantAgentAttributes.TranscriptionFinal`). `=== "true"` ⇒ final.
- **Avatar mount stays in the shell:** `<AvatarStage>` is instantiated in VoiceRoom (keeping `dynamic(..., {ssr:false})` + importmap ordering untouched) and handed to TalkingScreen as an `avatar` ReactNode rendered only in the 360px region when `avatarOn`.
- **Drawer reuses live panels uncontrolled:** hosting Persona/Interview/Model/KB with no props keeps their `performRpc`/`sendFile` apply path byte-identical, satisfying reversible live-tweak navigation.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The two-screen flow is complete: setup-before-connect (13-02) → cross-fade → polished TalkingScreen (13-03) with reversible settings and smart transcript. Phase 14 (session lifecycle) can implement the full Leave/clear-all/export/new-session teardown behind the affordance + copy slots this slice provides.
- Verification: `npm run build` (web/) clean; `web/package.json` deps unchanged (zero new runtime dep); avatar dynamic-import (`ssr:false`) + importmap preserved; `<RoomAudioRenderer/>` + `<StartAudio/>` intact; `<LiveKitRoom>` never unmounts for a settings visit (only confirmed Leave sets token=null); no plan-scoped change under `agent/`/`stt/`/`tts/`/`docker-compose.yml` (the pre-existing agent/stt diffs are out-of-scope uncommitted changes from before this plan, untouched).

## Self-Check: PASSED
- `web/app/TalkingScreen.tsx` and `web/app/SettingsDrawer.tsx` exist on disk.
- `git log --grep="13-03"` returns 3 task commits (14c206b, 7337d15, 23be36b).
- `npm run build` (web/) succeeds with zero errors / zero new deps.
- Transcript: `THRESHOLD = 32` named constant; instant scrollTop stick; smooth-scroll reserved for the Jump pill; interim opacity 0.7/italic; empty-state copy present; user/agent colors unchanged.
- SettingsDrawer hosts uncontrolled live panels; Escape + Tab focus trap; Leave-session confirm copy gates `onLeave`.
- VoiceRoom keeps avatar `dynamic(() => import("./AvatarStage"), { ssr:false })`, `<RoomAudioRenderer/>` + `<StartAudio/>`, and routes onLeave → setToken(null).

---
*Phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis*
*Completed: 2026-06-27*
