---
phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
plan: 13-02
subsystem: ui
tags: [react, nextjs, livekit, rpc, setup-screen, state-lifting]

requires:
  - phase: 13-01-foundation-token-dedup
    provides: ui/tokens.ts design system, ui/apply.ts ApplyState, globals.css cross-fade/transition utilities
provides:
  - web/app/SetupScreen.tsx — single elegant landing panel holding all session config pre-connect (no room hooks)
  - web/app/MicPicker.tsx — controlled audioinput device picker + one-shot permission affordance
  - web/app/ApplySetupOnConnect.tsx — in-room once-only post-connect apply (persona->mode->model->KB), gated on agent.identity
  - SessionConfig type (in VoiceRoom) — held pre-connect config shape
  - controlled mode on PersonaPanel/ModelPanel/InterviewPanel/KbPanel (value+onChange / files+onFilesChange)
affects: [13-03-talking-screen-polish]

tech-stack:
  added: []
  patterns:
    - "Dual-mode component: optional controlled props (setup path, no room) vs internal-state + Apply RPC (live drawer path)"
    - "Once-only post-connect apply effect gated on agent readiness with useRef Strict-Mode guard + default-skip"
    - "Lift-all-config-pre-connect; only WHEN the existing RPCs fire moves (no server/RPC/stream contract change)"

key-files:
  created:
    - web/app/SetupScreen.tsx
    - web/app/MicPicker.tsx
    - web/app/ApplySetupOnConnect.tsx
  modified:
    - web/app/VoiceRoom.tsx
    - web/app/PersonaPanel.tsx
    - web/app/ModelPanel.tsx
    - web/app/InterviewPanel.tsx
    - web/app/KbPanel.tsx

key-decisions:
  - "Split each panel into a presentational *Fields component + a *Live wrapper; default export switches on whether onChange/onFilesChange was passed"
  - "Committed SetupScreen/VoiceRoom/ApplySetupOnConnect together — their SessionConfig types form a circular dependency that only type-checks/builds as a unit"
  - "default-skip via JSON.stringify equality against the agent-mirrored DEFAULT_* (shared key order makes stringify compare sufficient)"

requirements-completed: []

duration: 22 min
completed: 2026-06-27
status: complete
---

# Phase 13 Plan 13-02: Setup-Before-Connect — Landing Screen + Post-Connect Apply Summary

**Moved all session config (persona/KB/model/interview/mic/avatar) into plain React state on a new SetupScreen rendered BEFORE any LiveKit connection; a single "Start session" gesture connects the room and a once-only, agent-readiness-gated effect fires the held config as the existing RPCs (persona→mode→model) + queued KB uploads — only WHEN the RPCs fire moved, zero server/RPC/stream contract change.**

## Performance

- **Duration:** 22 min
- **Tasks:** 5
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments
- **Controlled config panels (13-02-1):** PersonaPanel/ModelPanel/InterviewPanel/KbPanel each split into a presentational `*Fields` component + a `*Live` wrapper. Passing `value`+`onChange` (or `files`+`onFilesChange` for KB) renders the form against lifted state with NO room context / NO RPC (safe outside `<LiveKitRoom>`); omitting props keeps the existing internal-state + Apply `performRpc` / `sendFile` path byte-identical. Extracted shared `Persona`/`ModelChoice`/`InterviewMode` types + `DEFAULT_*` constants and KB topic/size constants.
- **MicPicker (13-02-2):** new controlled `audioinput` device picker; `enumerateDevices()` into a `<select>`, a one-shot "Allow microphone access" button calling `getUserMedia` to unlock empty labels then re-enumerate. Enumerate/permission failures degrade to an inline muted note (never a thrown error). No room, no server call.
- **SetupScreen (13-02-3):** single centered card (max-width 720px) with the "Adept" wordmark + tagline, all six config groups pre-filled with defaults, advanced persona/interview fields behind a collapsed "Customize" disclosure, the moved headphones tip, and an always-enabled green "Start session" CTA. No room hooks.
- **VoiceRoom shell (13-02-4):** defines `SessionConfig` (agent-mirrored defaults), holds `sessionConfig` + `token` + `connecting`/`error`. Renders SetupScreen while `!token`; cross-fades to the in-room subtree on connect (globals.css `screen-enter`) without unmounting `<LiveKitRoom>`. Plumbs `micDeviceId` into `audioCaptureDefaults.deviceId`; avatar stays `dynamic(..., {ssr:false})`.
- **ApplySetupOnConnect (13-02-5):** in-room once-only effect (`useRef` guard, gated on `agent?.identity`) firing `persona.update` → `mode.update` → `model.update` → queued KB `sendFile`, with default-skip and non-blocking per-section status notes ("Connecting…" → "Applying your setup…").

## Task Commits

1. **Task 13-02-1: controlled config panels** - `b4568ca` (refactor)
2. **Task 13-02-2: MicPicker** - `7331e66` (feat)
3. **Tasks 13-02-3/4/5: SetupScreen + VoiceRoom shell + ApplySetupOnConnect** - `0a64d7f` (feat)

## Files Created/Modified
- `web/app/SetupScreen.tsx` (NEW) - Landing panel; all config in lifted state, no room hooks
- `web/app/MicPicker.tsx` (NEW) - Controlled device picker + permission affordance
- `web/app/ApplySetupOnConnect.tsx` (NEW) - Once-only post-connect apply gated on agent readiness
- `web/app/VoiceRoom.tsx` - Orchestrator shell: SessionConfig + token + phase + cross-fade
- `web/app/PersonaPanel.tsx` / `ModelPanel.tsx` / `InterviewPanel.tsx` / `KbPanel.tsx` - Dual-mode (controlled setup path + live RPC path)

## Decisions Made
- **Dual-mode panels via presentational split:** each panel's default export switches on whether a change handler was passed — controlled `*Fields` (setup) vs `*Live` wrapper (drawer). Keeps the live RPC path byte-identical while exposing a room-free form.
- **Combined commit for the shell trio:** SetupScreen imports `SessionConfig` from VoiceRoom which renders ApplySetupOnConnect which imports `SessionConfig` — a circular type dependency that only builds as a unit, so tasks 3/4/5 share one atomic commit.
- **default-skip optimization:** `JSON.stringify(value) === JSON.stringify(DEFAULT_*)` skips a needless first-turn re-prefill; shared key order (both built from panel constants) makes a stringify compare sufficient.

## Deviations from Plan
- Tasks 13-02-3, 13-02-4, 13-02-5 landed in a single commit rather than three, due to the circular `SessionConfig` type dependency between SetupScreen ↔ VoiceRoom ↔ ApplySetupOnConnect (they do not type-check/build independently). All three tasks' acceptance criteria are individually satisfied.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The setup-before-connect surface + post-connect apply are in place; 13-03 (talking-screen polish) can extract the in-room subtree into a TalkingScreen, add transcript auto-scroll, and add the reversible settings drawer (the live/uncontrolled panel path is preserved for that drawer).
- Verification: `npm run build` (web/) clean; `web/package.json` deps unchanged; importmap + avatar dynamic-import intact; all agent-mirrored constants + RPC method names / payload keys / `kb.upload` topic byte-identical; no plan-scoped change under `agent/`/`stt/`/`tts/`/`docker-compose.yml`.

## Self-Check: PASSED
- `web/app/SetupScreen.tsx`, `web/app/MicPicker.tsx`, `web/app/ApplySetupOnConnect.tsx` exist on disk.
- `git log --grep="13-02"` returns 3 task commits.
- `npm run build` (web/) succeeds with zero errors / zero new deps.
- SetupScreen + MicPicker contain no `useRoomContext`/`useVoiceAssistant`; ApplySetupOnConnect rendered inside `<LiveKitRoom>` with a `useRef` once-guard gated on `agent?.identity`.
- RPC order persona→mode→model + queued KB `sendFile`; method names / payload keys / `kb.upload` topic byte-identical; agent-mirrored constants unchanged.
- Avatar stays `dynamic(() => import("./AvatarStage"), { ssr:false })`; `micDeviceId` plumbed into `audioCaptureDefaults.deviceId`.

---
*Phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis*
*Completed: 2026-06-27*
