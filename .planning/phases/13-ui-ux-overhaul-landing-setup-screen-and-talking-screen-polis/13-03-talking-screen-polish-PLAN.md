---
phase: 13
plan: 13-03
slug: talking-screen-polish
wave: 3
depends_on: [13-02]
autonomous: true
files_modified:
  - web/app/TalkingScreen.tsx
  - web/app/SettingsDrawer.tsx
  - web/app/Transcript.tsx
  - web/app/VoiceRoom.tsx
requirements: []
---

# Plan 13-03 — Talking Screen Polish: Layout, Settings Drawer, Smart Auto-Scroll

## Goal

Polish the in-room talking screen: extract the in-room layout into a clean
`TalkingScreen` (top bar with state pill + Voice-only/Avatar toggle + Settings/Back
affordance, optional avatar stage, transcript as the hero column, config panels moved
into a reversible `SettingsDrawer` overlay), and give `Transcript.tsx` smart
stick-to-bottom auto-scroll with a "Jump to latest" pill and interim/final styling.
Navigation between talking and setup-tweaks is reversible WITHOUT unmounting
`<LiveKitRoom>` (settings is an overlay; only a destructive "Leave session"
affordance — copy only, teardown is Phase 14 — sets token=null).

Depends on 13-02 (shell + controlled panels). This is the third and final slice.

## Must-Haves (goal-backward)

### Truths (must remain TRUE)
- D-04: The live transcript auto-scrolls to keep the newest line in view WHILE the user is
  at the bottom, and does NOT yank the view when the user has scrolled up to read
  history (success criterion 4).
- A "Jump to latest ↓" pill (accent `#58a6ff`, bottom-center) appears when the user
  is scrolled up and new content arrives; clicking it smooth-scrolls to bottom and
  re-engages stick.
- Interim (in-progress) transcript segments are styled distinctly from finals; the
  two-sided split is preserved (user right `#e6edf3`, agent left `#58a6ff`).
- Navigation talking↔settings is reversible without breaking the live room: the
  Settings overlay/drawer keeps `<LiveKitRoom>` mounted and tweaks apply via the
  existing live RPCs (success criterion 3).
- The talking screen is responsive (flex column: top bar / optional avatar / hero
  transcript / controls) and keyboard-navigable (Tab to primary actions, Enter/Space
  activate Start + Jump pill, Escape closes the drawer; visible `#58a6ff` focus ring).
- No console errors during the setup → connect → talk flow.

### Prohibitions (must NOT happen)
- MUST NOT change any file under `agent/`, `stt/`, `tts/`, or `docker-compose.yml`.
- MUST NOT unmount `<LiveKitRoom>` for a settings/back visit — only a confirmed
  destructive Leave sets token=null (its full teardown semantics are Phase 14; this
  slice builds the affordance + copy only).
- MUST NOT animate transcript token streaming (instant render) regardless of motion
  prefs; respect `prefers-reduced-motion` for all other transitions.
- MUST NOT add a new runtime dependency (no framework/motion lib).
- MUST NOT touch `AvatarStage.tsx` internals; keep the avatar dynamic-import
  (`ssr:false`), the `360px` region, and the importmap ordering.
- MUST NOT change RPC methods/payload keys/`kb.upload` topic or any agent-mirrored
  constant.

## Tasks

<task id="13-03-1">
<title>Add smart auto-scroll + jump pill + interim styling + empty state to Transcript</title>
<read_first>
- web/app/Transcript.tsx (full — the flat <ul> 15-38, USER_IDENTITY_PREFIX, useTranscriptions)
- web/app/KbPanel.tsx (useEffect-on-data shape 86-97 — effect discipline analog)
- web/app/ui/tokens.ts + web/app/globals.css (jump-pill class + scrollbar from 13-01)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§4 auto-scroll pattern + React 19 gotchas, §9 interim-segment flag note)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Transcript auto-scroll contract, Empty state copy)
</read_first>
<action>
Modify `web/app/Transcript.tsx`: wrap the `<ul>` in a bounded scroll container
(`overflow-y:auto`, `flex:1`, `min-height:0` in a flex column) using the
globals.css scrollbar class. Add `containerRef`, an `atBottomRef` (ref, not state, to
avoid churn), `const THRESHOLD = 32` named constant, and a `showJump` state. On the
container `scroll` event recompute `atBottom = scrollHeight - scrollTop -
clientHeight <= THRESHOLD` and set `showJump = !atBottom && segments.length > 0`. In a
`useEffect` keyed on `[segments]`, if `atBottomRef.current` set `el.scrollTop =
el.scrollHeight` (instant — no thrash). Render a "Jump to latest ↓" pill (accent
`#58a6ff`, bottom-center, globals.css `.jump-pill`) when `showJump`; click →
`scrollTo({behavior:"smooth"})` to bottom + `atBottomRef.current = true`. Style interim
vs final segments distinctly (finals full-opacity; interim `0.7` opacity / italic) by
reading the in-progress flag on the `TextStreamData` segment (verify the exact field —
`segment.streamInfo`/attributes — against `@livekit/components-react@2.9.21` at
implementation). Preserve the user-right `#e6edf3` / agent-left `#58a6ff` split and
the `USER_IDENTITY_PREFIX` attribution. Add the empty state (heading `Start talking` +
body `Say hello, ask a question, or describe what you want to practice.`, muted,
centered) when `segments.length === 0`.
</action>
<acceptance_criteria>
- The transcript container scrolls (bounded height) and sticks to bottom only when
  `atBottom`; when scrolled up, new segments do NOT move the viewport.
- The "Jump to latest ↓" pill shows only when scrolled up with content; click
  smooth-scrolls to bottom and re-engages stick.
- Interim segments render visually distinct from finals; user/agent sides + colors
  unchanged.
- Empty state copy renders when there are no segments.
- `THRESHOLD` is a named constant (no magic value); the programmatic scrollTop write
  does not falsely flip `atBottom`.
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

<task id="13-03-2">
<title>Create SettingsDrawer (in-room reversible overlay hosting live-tweak panels)</title>
<read_first>
- web/app/VoiceRoom.tsx (after 13-02 shell — the in-room panel row + token state)
- web/app/PersonaPanel.tsx / ModelPanel.tsx / InterviewPanel.tsx / KbPanel.tsx (uncontrolled live RPC mode — reused, not deleted)
- web/app/ui/tokens.ts + web/app/globals.css (focus ring, overlay transition)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§5 reversible navigation hard rules)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Navigation Contract, Copywriting: Settings/Leave session)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 7 section)
</read_first>
<action>
Create `web/app/SettingsDrawer.tsx`: an overlay/drawer rendered INSIDE
`<LiveKitRoom>`, opened/closed by an `open` boolean + `onClose` prop. It hosts the
existing PersonaPanel/InterviewPanel/ModelPanel/KbPanel in their UNCHANGED
uncontrolled live-RPC mode (they have room context; tweaks apply to the running
agent). Add a clearly-destructive "Leave session" affordance (`#f85149`) with a
confirm dialog using the UI-SPEC copy: "End this conversation and return to setup?
Your transcript will clear." On confirm it calls an `onLeave` prop that sets
token=null in the shell (the ONLY disconnect path; full clear-all teardown is Phase
14 — build affordance + copy only). Keyboard: focus-trap the overlay, Escape closes
(`onClose`), visible `#58a6ff` 2px focus ring on every control. Do NOT toggle
`<LiveKitRoom>` mounting to open/close the drawer.
</action>
<acceptance_criteria>
- `web/app/SettingsDrawer.tsx` exists; opening/closing it does NOT unmount
  `<LiveKitRoom>` (room, transcript, avatar persist).
- The hosted panels keep their live `performRpc`/`sendFile` apply logic unchanged.
- "Leave session" shows the confirm copy and only on confirm calls `onLeave`
  (token=null); no teardown logic beyond setting the token.
- Escape closes the drawer; focus is trapped while open; focus ring visible.
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

<task id="13-03-3">
<title>Create TalkingScreen and wire it into the VoiceRoom shell</title>
<read_first>
- web/app/VoiceRoom.tsx (after 13-02 — the in-room subtree + avatar toggle 99-147; ApplySetupOnConnect mount)
- web/app/TalkingScreen.tsx target analog (the in-room subtree to extract)
- web/app/SettingsDrawer.tsx (from 13-03-2)
- web/app/Transcript.tsx (from 13-03-1)
- web/app/AgentStatePill.tsx
- web/app/ui/tokens.ts + web/app/globals.css
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Screen B layout regions, Animation Contract)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 6 section)
</read_first>
<action>
Create `web/app/TalkingScreen.tsx` rendering INSIDE `<LiveKitRoom>` as a full-height
flex column: a top bar (`AgentStatePill` + the Voice-only/Avatar segmented toggle +
a `Settings` button that opens the SettingsDrawer), an optional avatar stage
(only when `avatarOn`; `360px` region; the avatar dynamic-import contract stays in
the shell — pass the mounted `<AvatarStage>` or `avatarOn`/`personaName` props as
appropriate), the `Transcript` as the hero flex-1 column, and the SettingsDrawer
(closed by default). Props: `avatarOn`, `onToggleAvatar`, `personaName`,
`onLeave`, plus the avatar element/flag. Keep `<RoomAudioRenderer/>` + `<StartAudio/>`
in the shell (autoplay backstop). Update `web/app/VoiceRoom.tsx` to render
`<TalkingScreen .../>` (replacing the inline in-room panel row) alongside
`<ApplySetupOnConnect/>`, keeping `<LiveKitRoom>` mounted for the whole session and
the avatar dynamic-import unchanged. Move the config panels OUT of the always-visible
talking layout and into the drawer so the transcript is the hero. Apply the
240ms/200ms cross-fade classes for the setup↔talking transition (from globals.css).
</action>
<acceptance_criteria>
- `web/app/TalkingScreen.tsx` exists; the talking screen is a responsive flex column
  (top bar / optional avatar / hero transcript / drawer) — config panels live in the
  drawer, not crowding the transcript.
- Opening Settings overlays the drawer without unmounting `<LiveKitRoom>`; the
  transcript and (if on) avatar persist.
- `<RoomAudioRenderer/>` + `<StartAudio/>` still render; the avatar stays
  `dynamic(..., { ssr:false })` and the importmap ordering is untouched.
- Setup→talking transition uses the CSS cross-fade (transform/opacity only),
  disabled under `prefers-reduced-motion`.
- No console errors across setup → connect → talk.
- `npm run build` (web/) succeeds; `git diff -- agent/ stt/ tts/ docker-compose.yml`
  empty.
</acceptance_criteria>
</task>

## Verification

- `cd web && npm run build` succeeds with no new dependency in `package.json`.
- Transcript sticks to bottom when at bottom, does not yank when scrolled up, and
  shows the Jump pill + interim styling + empty state.
- Settings overlay is reversible without unmounting `<LiveKitRoom>`; only a confirmed
  Leave returns to setup (token=null).
- Keyboard: Tab/Enter/Space/Escape work for primary actions and the drawer; focus
  ring visible.
- `git diff -- agent/ stt/ tts/ docker-compose.yml` is empty; avatar dynamic-import +
  importmap preserved; no console errors in the full flow.

## Artifacts this phase produces

- **NEW file** `web/app/TalkingScreen.tsx` — in-room layout (top bar, optional avatar
  stage, hero transcript, settings drawer).
- **NEW file** `web/app/SettingsDrawer.tsx` — reversible in-room settings overlay
  hosting the live-tweak panels + destructive "Leave session" affordance (copy only).
- **MODIFIED** `web/app/Transcript.tsx` — smart stick-to-bottom auto-scroll,
  "Jump to latest ↓" pill, interim/final styling, empty state.
- **MODIFIED** `web/app/VoiceRoom.tsx` — renders TalkingScreen + ApplySetupOnConnect
  inside the persistent `<LiveKitRoom>`; setup↔talking cross-fade.
