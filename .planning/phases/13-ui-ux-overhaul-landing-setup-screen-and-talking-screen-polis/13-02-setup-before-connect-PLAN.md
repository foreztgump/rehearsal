---
phase: 13
plan: 13-02
slug: setup-before-connect
wave: 2
depends_on: [13-01]
autonomous: true
files_modified:
  - web/app/SetupScreen.tsx
  - web/app/MicPicker.tsx
  - web/app/ApplySetupOnConnect.tsx
  - web/app/VoiceRoom.tsx
  - web/app/PersonaPanel.tsx
  - web/app/ModelPanel.tsx
  - web/app/InterviewPanel.tsx
  - web/app/KbPanel.tsx
requirements: []
---

# Plan 13-02 — Setup-Before-Connect: Landing Screen + Post-Connect Apply

## Goal

Deliver the dedicated landing/setup screen where the user configures EVERYTHING
(persona, knowledge base, response model, interview mode, mic, avatar) in plain
React state BEFORE any LiveKit connection, then on a single-gesture "Start session"
connects the room and a once-only post-connect effect fires the held config as the
existing RPCs (persona → mode → model) + queued KB uploads, gated on agent
readiness. This is the KEY TENSION resolution: only *when* the RPCs fire moves — no
server/RPC/stream contract changes.

VoiceRoom becomes a thin shell holding `sessionConfig` + `token` + phase state and
cross-fading SetupScreen → TalkingScreen via CSS (never unmounting `<LiveKitRoom>`
once connected).

Depends on 13-01 (token module + globals.css). This is the second slice.

## Must-Haves (goal-backward)

### Truths (must remain TRUE)
- The app opens on the SetupScreen; NO LiveKit connection occurs before the user's
  explicit "Start session" click (success criterion 1).
- The "Start session" CTA is a SINGLE user gesture that ends in `setToken(...)` →
  `<LiveKitRoom>` mounts (mic-permission + autoplay-unlock + connect in one gesture).
- D-01: The SetupScreen is a SINGLE elegant panel grouping all config (persona,
  knowledge base, model, mic, avatar) on one organized screen with a prominent
  "Start session" action — NOT a multi-step wizard, NOT a card dashboard.
- The CTA is NEVER disabled by missing choices — sensible defaults pre-fill all
  groups (Cybersecurity Trainer, Fast, Learn, default mic, Avatar OFF) so a
  first-time user can Start immediately (D-02).
- After connect, a once-only effect (`useRef` guard) applies the held config via
  `persona.update` → `mode.update` → `model.update` RPCs then queued KB `sendFile`,
  gated on `useVoiceAssistant().agent.identity` being defined.
- Mic device selection is optional client state plumbed into `<LiveKitRoom>`
  `audioCaptureDefaults.deviceId`; listing-blocked is a non-fatal inline note.
- No console errors during setup → connect → talk (no RPC before agent join; ref
  guard prevents Strict-Mode double-apply).

### Prohibitions (must NOT happen)
- MUST NOT change any file under `agent/`, `stt/`, `tts/`, or `docker-compose.yml`.
- MUST NOT change any RPC method name, payload key, or the `kb.upload` topic — only
  the timing of firing moves.
- MUST NOT add a new runtime dependency (no framework/motion lib).
- MUST NOT unmount `<LiveKitRoom>` for a settings/back visit (only a future
  destructive Leave sets token=null — that affordance is 13-03).
- MUST NOT drop/rename any agent-mirrored constant (carried from 13-01).
- MUST NOT break the `layout.tsx` importmap ordering or the avatar dynamic-import
  (`AvatarStage` stays `dynamic(..., { ssr:false })`, absent from voice-only bundle).

## Tasks

<task id="13-02-1">
<title>Make the config panels controlled so SetupScreen can render them pre-connect</title>
<read_first>
- web/app/PersonaPanel.tsx (after 13-01 refactor — apply() RPC + DEFAULT_PERSONA)
- web/app/ModelPanel.tsx (CHOICES + apply())
- web/app/InterviewPanel.tsx (MODE/ROLES + apply())
- web/app/KbPanel.tsx (sendFile + size check + KbStatus)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§2.1 SessionConfig shape, §2.4 setup-vs-room table)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (Files 10-13 controlled-component refactor)
</read_first>
<action>
Refactor PersonaPanel/ModelPanel/InterviewPanel to accept OPTIONAL controlled
props: a `value` and an `onChange` (e.g. PersonaPanel `value?: Persona`,
`onChange?: (p: Persona) => void`). When `onChange` is provided (setup path), the
panel writes to lifted state and renders WITHOUT the Apply button / RPC (no room
context needed). When omitted (drawer/live path), it keeps its existing internal
useState + Apply + `performRpc` exactly as today. Extract a shared `Persona` type and
the `DEFAULT_PERSONA` constant so SetupScreen and ApplySetupOnConnect import the same
values (keep them agent-mirrored; do not change values). For KbPanel, add a
controlled `files`/`onFilesChange` mode that QUEUES picked files into lifted state
(with the same MAX_UPLOAD_BYTES pre-check) instead of `sendFile`, used by the setup
path; the uncontrolled mode keeps immediate `sendFile`.
Guard against rendering the RPC/`useRoomContext` path when used outside a room.
</action>
<acceptance_criteria>
- Each panel renders correctly in BOTH modes: controlled (lifted value+onChange, no
  RPC) and uncontrolled (internal state + Apply RPC unchanged).
- In controlled mode the panel does not call `useRoomContext`/`performRpc`/`sendFile`
  (so it is safe to render outside `<LiveKitRoom>`).
- Agent-mirrored constants (`VOICE_IDS`, `CHOICES`, `ROLES`, `MODE_*`,
  `DEFAULT_PERSONA`, KB topic/attr/size) byte-identical.
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

<task id="13-02-2">
<title>Create MicPicker (enumerateDevices + optional permission affordance)</title>
<read_first>
- web/app/ModelPanel.tsx (the labeled <select> idiom to clone)
- web/app/ui/tokens.ts (labelStyle/inputStyle)
- web/app/SecureContextProbe.tsx (reference only — navigator.mediaDevices presence pattern)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§6 mic permission flow, §9 mic-deviceId plumbing)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Microphone group copy)
</read_first>
<action>
Create `web/app/MicPicker.tsx`: a controlled component taking `value?: string`
(micDeviceId) + `onChange`. It calls `navigator.mediaDevices.enumerateDevices()` to
list `audioinput` devices into a `<select>` (label `Microphone`). Because labels are
empty before a permission grant, render an "Allow microphone access to choose a
device" button that calls `getUserMedia({audio:true})` once to unlock labels, then
re-enumerates. Selection is OPTIONAL (default mic used otherwise). On enumerate/
permission failure, show an inline muted note (NOT a hard error). Wrap async in
try/catch (boundary handling per CODE_PRINCIPLES). No room, no server call. Use the
UI-SPEC helper copy: "Allow microphone access to choose a device. Optional — we'll
use your default otherwise."
</action>
<acceptance_criteria>
- `web/app/MicPicker.tsx` exists; renders a `<select>` of audioinput devices and a
  permission affordance; selection writes `micDeviceId` via `onChange`.
- No room context / no server RPC is used.
- Enumerate/permission failure yields an inline note, not a thrown/uncaught error
  (verified: no console error when permission denied).
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

<task id="13-02-3">
<title>Create SetupScreen (single elegant landing panel, owns sessionConfig edits)</title>
<read_first>
- web/app/VoiceRoom.tsx (the !token pre-connect branch 49-86 — the seam to expand; the segmented toggle idiom 103-134)
- web/app/PersonaPanel.tsx / ModelPanel.tsx / InterviewPanel.tsx / KbPanel.tsx (controlled mode from 13-02-1)
- web/app/MicPicker.tsx (from 13-02-2)
- web/app/ui/tokens.ts (palette/space/font/panelStyle)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-UI-SPEC.md (Screen A contract, Spacing, Typography, Copywriting table)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 3 section + SessionConfig shape)
</read_first>
<action>
Create `web/app/SetupScreen.tsx`: a single centered card (max-width ~720px, bg
`#0d1117`, radius `12px`, padding lg→2xl) with the "Adept" Display wordmark + tagline
`Set up your session, then start talking.`. It receives `config: SessionConfig` +
`onChange` + `onStart` props (state owned by the VoiceRoom shell in 13-02-4).
Render config groups (Persona, Knowledge base, Response model, Interview mode,
Microphone, Avatar) using the controlled panels + MicPicker + the segmented
Voice-only/Avatar toggle idiom (active segment accent `#58a6ff`). Put advanced
persona/interview fields behind a "Customize" progressive-disclosure
(collapsed by default, summary line shows the current default). Render the moved
headphones tip and the primary `Start session` CTA (green `#3fb950`, 44px target),
NEVER disabled. CTA `onClick` → `onStart()` (single gesture). Show the connect-error
copy from UI-SPEC when present. No `useRoomContext`/`useVoiceAssistant` here.
</action>
<acceptance_criteria>
- `web/app/SetupScreen.tsx` exists; renders the wordmark, all 6 config groups
  pre-filled with defaults, the headphones tip, and an always-enabled `Start session`
  CTA.
- SetupScreen imports NO room hooks (`useRoomContext`/`useVoiceAssistant` absent).
- "Customize" disclosure collapses advanced fields by default.
- Copy matches the UI-SPEC Copywriting table (CTA `Start session`, tagline,
  group labels).
- `npm run build` (web/) succeeds.
</acceptance_criteria>
</task>

<task id="13-02-4">
<title>Refactor VoiceRoom into the shell: lift sessionConfig, phase state, cross-fade</title>
<read_first>
- web/app/VoiceRoom.tsx (full — current state 36-47, AUDIO_CAPTURE_DEFAULTS 24-28, LiveKitRoom 88-95, avatar dynamic import 16)
- web/app/SetupScreen.tsx (from 13-02-3)
- web/app/ui/tokens.ts + web/app/globals.css (cross-fade classes from 13-01-2)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§1.1 connect seam, §2.1 SessionConfig, §3.2 cross-fade)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 8 section)
</read_first>
<action>
Refactor `web/app/VoiceRoom.tsx` into the orchestrator shell. Define the
`SessionConfig` type (persona, mode {mode, role_key}, model "fast"|"better",
micDeviceId?, avatarOn, kbFiles: File[]) seeded with agent-mirrored defaults. Hold
`sessionConfig`, `token`, `error`, and a `phase: "setup"|"connecting"|"talking"`.
Render SetupScreen when `!token` (with exit class) and the in-room subtree when token
is set (with enter class) — both via CSS cross-fade from globals.css; do NOT unmount
`<LiveKitRoom>` once connected. `onStart` fetches `/api/token` and `setToken`
(single gesture; keep the existing try/catch + error copy). Pass
`micDeviceId` into `<LiveKitRoom options>` via `audioCaptureDefaults.deviceId`
(spread onto AUDIO_CAPTURE_DEFAULTS). Keep `personaName` wired to the avatar from
`sessionConfig.persona.display_name`. Keep the avatar dynamic import unchanged.
Render `<ApplySetupOnConnect config={sessionConfig} />` (created in 13-02-5) inside
`<LiveKitRoom>`. Keep `<RoomAudioRenderer/>` + `<StartAudio/>`. (TalkingScreen
extraction + settings drawer is 13-03; for this slice keep the existing in-room
panel layout but the panels here use the live/uncontrolled RPC path.)
</action>
<acceptance_criteria>
- App opens on SetupScreen; no `/api/token` fetch or LiveKit connect fires before
  the `Start session` click (verify: no network/connect call on initial render).
- `setToken` is reached within the single Start click handler; `<LiveKitRoom>` mounts
  and auto-connects.
- `micDeviceId`, when set, is passed into `audioCaptureDefaults.deviceId`.
- `<LiveKitRoom>` is NOT conditionally unmounted except when token returns to null.
- Avatar stays `dynamic(() => import("./AvatarStage"), { ssr:false })`.
- `npm run build` (web/) succeeds; `git diff -- agent/ stt/ tts/ docker-compose.yml`
  empty.
</acceptance_criteria>
</task>

<task id="13-02-5">
<title>Create ApplySetupOnConnect (once-only post-connect apply effect)</title>
<read_first>
- web/app/PersonaPanel.tsx (apply() body 93-118 — the exact agentIdentity resolution + performRpc persona.update to compose)
- web/app/ModelPanel.tsx (model.update payload {choice} + ack === "applied")
- web/app/InterviewPanel.tsx (mode.update payload {mode, role_key})
- web/app/KbPanel.tsx (sendFile loop 110-120 + MAX_UPLOAD_BYTES check; useEffect-on-attribute shape 86-97)
- agent/main.py (RPC registration ordering — persona.update/mode.update/model.update + kb handler registered after session.start(); readiness == agent.identity defined)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-RESEARCH.md (§2.2 apply sequence + ordering rationale, §2.3 error handling, §9 readiness signal)
- .planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md (File 5 section)
</read_first>
<action>
Create `web/app/ApplySetupOnConnect.tsx`, rendered inside `<LiveKitRoom>`. It takes
`config: SessionConfig`. Use `useRoomContext()` + `useVoiceAssistant()` and a
`useEffect` keyed on `agent?.identity`. Guard with a `useRef(applied)` so the apply
runs EXACTLY ONCE (React 19 Strict-Mode double-invoke safe). When `agent.identity`
becomes defined and not-yet-applied, resolve `agentIdentity` exactly as the panels do
(`agent?.identity ?? firstRemoteParticipant?.identity`) and fire in order:
`persona.update` (JSON.stringify(config.persona)) → `mode.update`
(JSON.stringify(config.mode)) → `model.update` (JSON.stringify({choice: config.model}))
→ for each queued `config.kbFiles`: `room.localParticipant.sendFile(file, {topic:
KB_UPLOAD_TOPIC})`. Apply the default-skip optimization: skip a persona/mode/model RPC
when the held value deep-equals the agent default (avoids a needless first-turn
re-prefill); KB fires only if files were queued. Wrap each await in try/catch and
surface non-blocking per-section status (reuse `ApplyState`) + the
"Connecting… → Applying your setup…" status; if `agent` is not yet defined, show the
non-fatal "Still connecting the agent…" note and retry on the next `agent` change —
never hard-fail or block the talking UI. Do NOT change any RPC method/payload key or
the `kb.upload` topic.
</action>
<acceptance_criteria>
- `web/app/ApplySetupOnConnect.tsx` exists and is rendered inside `<LiveKitRoom>`.
- The apply effect is gated on `agent?.identity` and protected by a `useRef` once-guard
  (does not double-fire under Strict Mode).
- RPC order is persona → mode → model, then queued KB `sendFile`; method names and
  payload keys are byte-identical to the existing panels (`persona.update`,
  `mode.update` {mode, role_key}, `model.update` {choice}, topic `kb.upload`).
- When no choices changed from defaults, persona/mode/model RPCs are skipped
  (default-skip) and no KB upload fires (empty kbFiles).
- Agent-not-ready path shows a non-fatal note and retries; no RPC fires before
  `agent.identity` is defined (no console error).
- `npm run build` (web/) succeeds; `git diff -- agent/ stt/ tts/ docker-compose.yml`
  empty.
</acceptance_criteria>
</task>

## Verification

- `cd web && npm run build` succeeds with no new dependency in `package.json`.
- Manual/inspection: initial render shows SetupScreen with no LiveKit connect; the
  Start click is the single gesture that mounts `<LiveKitRoom>`; after the agent
  joins, the held config is applied once via the existing RPCs + queued KB upload.
- `git diff -- agent/ stt/ tts/ docker-compose.yml` is empty.
- All agent-mirrored constants byte-identical; RPC methods/payload keys/topic
  unchanged.
- Avatar dynamic-import + importmap ordering preserved.

## Artifacts this phase produces

- **NEW file** `web/app/SetupScreen.tsx` — the landing/setup panel (no room context).
- **NEW file** `web/app/MicPicker.tsx` — controlled mic device picker + permission
  affordance.
- **NEW file** `web/app/ApplySetupOnConnect.tsx` — in-room once-only post-connect
  apply effect (persona→mode→model→KB), gated on `agent.identity`.
- **NEW type** `SessionConfig` (in VoiceRoom) — held pre-connect config shape.
- **MODIFIED** `web/app/VoiceRoom.tsx` (shell/orchestrator: sessionConfig + phase +
  cross-fade), `PersonaPanel`/`ModelPanel`/`InterviewPanel`/`KbPanel` (optional
  controlled mode for the setup path; live RPC path preserved).
