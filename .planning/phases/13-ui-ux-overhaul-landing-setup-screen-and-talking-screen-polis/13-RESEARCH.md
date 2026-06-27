---
phase: 13
slug: ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
artifact: RESEARCH
created: 2026-06-27
sources:
  - .planning/phases/13-.../13-CONTEXT.md
  - .planning/phases/13-.../13-UI-SPEC.md
  - .planning/ROADMAP.md §Phase 13
  - .planning/STATE.md
  - web/app/* (all components read in full)
  - agent/main.py (RPC registration ordering)
---

# Phase 13 — Research: What you need to PLAN this phase well

> Frontend-only UI/UX overhaul: a setup-before-connect landing screen + a polished
> talking screen with smart auto-scroll. This document grounds the plan in the
> ACTUAL source as it stands today and resolves the highest-risk decision
> (pre-connect config hold → post-connect apply).

---

## 0. TL;DR for the planner

- **The setup/talking split already physically exists** in `VoiceRoom.tsx` as the
  `if (!token) { …Start button… } return <LiveKitRoom>`. The setup screen is the
  pre-token branch; the talking screen is the post-token `<LiveKitRoom>` subtree.
  This is the seam to expand — NOT a rewrite.
- **The RPCs already work BEFORE-connect conceptually**: every panel holds its
  choice in React state and only *applies* on a button click. The change is to
  (a) move that held state UP to the setup screen, and (b) replace the per-panel
  "Apply" buttons with a single **auto-apply-after-connect** effect that fires once
  the agent participant appears.
- **The critical ordering fact (verified in `agent/main.py`):** the agent registers
  its RPC methods (`persona.update`, `mode.update`, `model.update`) and the KB
  byte-stream handler **only after `await ctx.connect()` + `await session.start()`**
  (main.py:381, 404, 496, 538, 569, 692). So the client must **wait for the agent
  participant to join the room** before firing any apply. The existing panels
  already encode this guard: `agent?.identity ?? firstRemoteParticipant?.identity`,
  erroring if absent (PersonaPanel.tsx:98-103). Reuse that signal.
- **Styling recommendation: do NOT add a framework or motion lib.** Extract the
  duplicated inline tokens into `web/app/ui/tokens.ts`, add ONE `globals.css`
  (imported in `layout.tsx`) for `@keyframes`, focus-ring, scrollbar, and the
  `prefers-reduced-motion` block. This is the only approach that satisfies the
  AVTR-01 bundle-isolation gate (zero new runtime deps) — confirmed by the UI-SPEC.
- **Auto-scroll** is a self-contained change to `Transcript.tsx`: wrap the `<ul>`
  in a scroll container, track `atBottom` via a scroll listener, `scrollTop` to
  bottom on new segments only when `atBottom`, show a "Jump to latest" pill when not.
- **Navigation (success criterion 3):** use UI-SPEC pattern (a) — keep the room
  OPEN and surface settings as an overlay/drawer over the talking screen; tweaks
  apply through the same live RPCs. A separate destructive "Leave session" is the
  only thing that disconnects. **Do NOT unmount `<LiveKitRoom>` for settings.**

---

## 1. Current architecture (ground truth, read in full)

### 1.1 The connect seam — `VoiceRoom.tsx`

```
VoiceRoom()
 ├─ state: token | error | avatarOn | personaName
 ├─ if (!token):  ← SETUP SCREEN lives here (outside <LiveKitRoom>, NO room)
 │     <button onClick=fetch('/api/token') → setToken>  Start talking
 │     headphones tip + error line
 └─ return <LiveKitRoom serverUrl token connect audio video=false
              options={{ audioCaptureDefaults }}>  ← TALKING SCREEN
            <RoomAudioRenderer/> <StartAudio/>
            <AgentStatePill/> + Voice-only/Avatar segmented toggle
            {avatarOn && <AvatarStage persona={personaName}/>}
            <PersonaPanel/><InterviewPanel/><ModelPanel/><KbPanel/><Transcript/>
```

Key facts:
- `<LiveKitRoom connect>` auto-connects the moment it mounts (token present).
  The current single user gesture = the Start click that fetches the token; mic
  permission + autoplay unlock happen when `<LiveKitRoom audio>` mounts inside the
  same click-initiated render. **Keep this: the new "Start session" must still be
  one click that ends with token set → room mounts.**
- `AUDIO_CAPTURE_DEFAULTS` (VoiceRoom.tsx:24-28) = `{echoCancellation, noiseSuppression, autoGainControl}`. **Mic device selection** plugs in here as
  `deviceId` (or via `audioCaptureDefaults.deviceId`), passed at connect — net-new
  client state, no server change.
- `personaName` is already lifted to VoiceRoom for the avatar (VoiceRoom.tsx:47).
  This is the template for lifting the rest of the config up.

### 1.2 The config panels — RPC-on-apply pattern (the KEY TENSION)

All three RPC panels are structurally identical:

| Panel | Holds | Applies via | Payload | Ack |
|-------|-------|-------------|---------|-----|
| `PersonaPanel` | `DEFAULT_PERSONA` snapshot | `room.localParticipant.performRpc("persona.update")` | full persona JSON | RPC returns "applied"/throws |
| `ModelPanel` | `choice: "fast"\|"better"` | `performRpc("model.update")` | `{choice}` | returns `"applied"` literal |
| `InterviewPanel` | `{mode, role_key}` | `performRpc("mode.update")` | `{mode, role_key}` | returns `"applied"` literal |
| `KbPanel` | file picker | `room.localParticipant.sendFile(file,{topic:"kb.upload"})` | byte stream | reads back `kb.state` participant attribute |

Each panel independently:
1. `useRoomContext()` + `useVoiceAssistant()` → needs to be **inside `<LiveKitRoom>`**.
2. Resolves the agent identity: `agent?.identity ?? Array.from(room.remoteParticipants.values())[0]?.identity`; **errors if no agent yet** (PersonaPanel.tsx:98-103, ModelPanel.tsx:83-88, InterviewPanel.tsx:85-90).
3. Sets a local `ApplyState: "idle"|"applying"|"applied"|"error"`.

**Why this conflicts with setup-before-connect:** on the setup screen there is no
room, no `useRoomContext`, no agent identity → RPCs cannot fire. KbPanel's
`sendFile` literally rides the open room connection.

**The resolution (verified feasible against agent/main.py):**

> Hold every choice in plain React state on the setup screen (no room needed).
> On "Start session": set token → `<LiveKitRoom connect>` mounts → agent joins →
> `useVoiceAssistant().agent.identity` becomes defined → a **single post-connect
> apply effect** fires the held snapshots as RPCs (persona, then mode, then model),
> and fires any queued KB file upload over the now-open stream. Only *when* the RPCs
> fire moves; the RPC/stream contracts are byte-for-byte unchanged.

### 1.3 Duplication seams that MUST NOT drift (agent-mirrored)

These are copy-pasted in the panels and mirror the Python agent (no get-RPC, so
drift is silent). The UI-SPEC mandates consolidating them into one module while
keeping every key **byte-identical**:

- `PersonaPanel.VOICE_IDS` (13 Kokoro ids) ↔ `agent/persona.py` VOICE_IDS
- `PersonaPanel.DIFFICULTY / VERBOSITY / CORRECTION` ↔ agent/persona.py
- `PersonaPanel.DEFAULT_PERSONA` (display_name "Cybersecurity Trainer", voice
  af_bella, difficulty intermediate, verbosity balanced, correction gentle,
  role_text "") ↔ agent/persona.py DEFAULT_PERSONA
- `ModelPanel.CHOICES = ["fast","better"]` + `CHOICE_LABEL` ↔ agent/main.py
  MODEL_CHOICES (agent validates: unknown choice → "error", main.py:560)
- `InterviewPanel.MODE_LEARN/MODE_INTERVIEW/ROLES` ↔ agent/interview.py
- `KbPanel.KB_UPLOAD_TOPIC="kb.upload" / KB_STATE_ATTRIBUTE="kb.state" /
  MAX_UPLOAD_BYTES=25MB` ↔ agent/main.py

The agent **VALIDATES every RPC payload before mutating** (rejects unknown
knob/voice/mode/role/choice with "error" and a log line) — so a UI bug can't wedge
the agent, but a renamed/dropped key silently breaks the feature. Treat these as a
frozen contract during the refactor.

### 1.4 Talking-screen elements

- `AgentStatePill.tsx`: reads `useVoiceAssistant().state`, colored pill
  (initializing/idle `#8b949e`, listening `#3fb950`, thinking `#d29922`,
  speaking `#58a6ff`). Unchanged colors per UI-SPEC.
- `Transcript.tsx`: renders `useTranscriptions()` as a flat `<ul>`; user right
  `#e6edf3`, agent left `#58a6ff`. **No scroll container today** — this is where
  auto-scroll lands.
- `AvatarStage.tsx` (712 lines): dynamic-imported (`ssr:false`), mounts only when
  `avatarOn`. **Do not touch its internals.** Phase 13 only changes *where/whether*
  it is placed in the layout and how the toggle looks. Preserve: the dynamic
  import in VoiceRoom.tsx:16, the `layout.tsx` importmap-in-`<head>` ordering, and
  the mount-once teardown contract.
- `layout.tsx`: importmap `<script type="importmap">` in `<head>` (MUST stay before
  any avatar module), body inline styles (the flex-center that currently centers
  the whole app — will need adjusting for two full-screen layouts).

### 1.5 Other relevant files

- `page.tsx`: `<main><h1>Adept</h1><VoiceRoom/></main>` — trivial; the wordmark
  moves into the setup screen.
- `api/token/route.ts`: GET mints a `user-<uuid>` identity for room "adept".
  Unchanged. (Transcript relies on the `user-` prefix to attribute sides.)
- `SecureContextProbe.tsx`: a Phase-1 dev probe for `navigator.mediaDevices`
  presence; not wired into the live UI. Useful reference for the mic-permission
  pattern but can be ignored/removed.
- `package.json`: deps are LiveKit + Next 16.2.9 + React 19.2.7 only. No CSS
  framework, no animation lib, **no CSS file exists anywhere** (`web/**/*.css` →
  none). All styling is inline `style={{}}`.

---

## 2. Pre-connect config hold + post-connect apply (the highest-risk mechanism)

### 2.1 Recommended state shape (setup screen owns it)

Lift a single `sessionConfig` object to the top of `VoiceRoom` (or a new
`AppShell`), seeded with the agent-mirrored defaults:

```ts
type SessionConfig = {
  persona: Persona;          // DEFAULT_PERSONA
  mode: { mode: string; role_key: string };  // learn / soc_analyst
  model: "fast" | "better";  // fast
  micDeviceId?: string;      // undefined → default mic
  avatarOn: boolean;         // false
  kbFiles: File[];           // [] (held until connect)
};
```

Setup screen edits this object. **Start session** → `setToken(...)`. Nothing else
changes on the setup screen; no RPCs possible there (no room).

### 2.2 The post-connect apply sequence (inside `<LiveKitRoom>`)

Create one small component rendered inside `<LiveKitRoom>` (so it has room context),
e.g. `<ApplySetupOnConnect config={sessionConfig} />`, that:

1. `const { agent } = useVoiceAssistant();` — `agent` is `undefined` until the
   agent participant joins **and publishes** (this is the readiness signal the
   panels already use). Optionally also watch `RoomEvent.ParticipantConnected`.
2. In a `useEffect` keyed on `agent?.identity`, once defined and not-yet-applied:
   - `await performRpc("persona.update", JSON.stringify(config.persona))`
   - `await performRpc("mode.update", JSON.stringify(config.mode))`
   - `await performRpc("model.update", JSON.stringify({choice: config.model}))`
   - for each queued KB file: `await room.localParticipant.sendFile(file, {topic:"kb.upload"})`
   - guard with a `useRef(applied)` so it runs **exactly once** (React 19 Strict
     Mode double-invokes effects in dev — the ref guard is mandatory).
3. Surface progress as the UI-SPEC "Connecting… → Applying your setup…" transition.

**Ordering rationale:**
- persona → mode → model is the safe order because `compose_instructions()` on the
  agent composes (persona × KB × mode); applying persona first then mode re-emits
  the correct block. Model is independent (only swaps `session.llm._opts.model`).
- KB **last** because the agent's `ingest_kb` runs a distill + an injected priming
  `generate_reply` and re-renders under the *current* persona/mode — so persona/mode
  should be set first so the KB brief composes under the user's chosen persona.
- These are idempotent, last-write-wins snapshots (agent comment main.py:456), so
  exact interleave is forgiving, but the above order avoids an extra re-prefill.

### 2.3 Error handling if the agent isn't ready / RPC fails

- **Defaults case (most common):** if the user changed nothing, every snapshot
  equals the agent's own defaults (`DEFAULT_PERSONA`, learn, fast) — the agent
  *already* started with these (main.py:403,410,417,425). Applying them is a no-op
  re-prefill. **Optimization the planner may take:** skip the persona/mode/model RPC
  when the held value deep-equals the default, avoiding a needless first-turn
  re-prefill bump. (KB only fires if files were queued.)
- **Agent never joins:** the existing panels just show "error". For the auto-apply,
  show a non-fatal inline note ("Still connecting the agent…") and retry on the next
  `agent` change rather than hard-failing — the room is up; the agent worker may be
  a beat behind. Do NOT block the talking UI on this.
- **RPC throws / returns non-"applied":** surface per-section status (reuse the
  `ApplyState` union) in the settings overlay, not as a screen-blocking error. The
  conversation can proceed; the user can re-apply from settings.
- **KB upload fails mid-stream:** KbPanel already handles this (sets error from the
  `sendFile` catch, KbPanel.tsx:114-120). Keep that.

### 2.4 What stays inside `<LiveKitRoom>` vs moves out

| Concern | Setup screen (no room) | Talking screen (in room) |
|---------|------------------------|--------------------------|
| Persona/mode/model/mic/avatar **choice UI** | ✅ here (plain state) | also reachable via Settings overlay for live tweaks |
| `performRpc` / `sendFile` apply | ❌ impossible | ✅ here, after agent joins |
| `useRoomContext` / `useVoiceAssistant` | ❌ not available | ✅ |
| Mic `enumerateDevices` | ✅ here (no room needed) | n/a |

Live tweaks in the Settings overlay keep using the existing per-panel RPC-on-apply
(they have room context) — so the panels' apply logic is **reused, not deleted**.

---

## 3. Styling & animation approach (D-03) — concrete recommendation

**Recommendation: refine the existing inline dark theme into a shared token module +
one global CSS file for keyframes/media-queries. No framework, no motion lib.**

Rationale (matches UI-SPEC §Design System shadcn-gate outcome):
1. **AVTR-01 bundle isolation** forbids shipping new runtime weight into the
   voice-only bundle. Tailwind+Radix or framer-motion all add deps/bundle. A
   `tokens.ts` (tree-shaken constants) + a static `globals.css` add **zero JS**.
2. The stack is bleeding-edge (Next 16.2.9 / React 19.2.7) where shadcn presets are
   unvalidated.
3. An internally-consistent dark palette already exists across 6 components and is
   the de-facto design system.

### 3.1 Concrete structure

- **`web/app/ui/tokens.ts`** — export the palette, spacing scale, typography,
  radii, and the shared `panelStyle/labelStyle/inputStyle/STATUS_LABEL/STATUS_COLOR`
  as typed `React.CSSProperties` objects + helper builders. Every panel imports
  from here instead of redefining. Keep agent-mirrored constants
  (`VOICE_IDS`, `CHOICES`, `ROLES`, `MODE_*`, `DEFAULT_PERSONA`) in their own
  `web/app/ui/agentContract.ts` (or leave in place) — **presentational refactor only**.
- **`web/app/globals.css`** — imported once in `layout.tsx`. Holds:
  - `@keyframes` for screen transitions, jump-pill, status fades.
  - `:focus-visible` ring (`#58a6ff`, 2px) — accessibility criterion 5.
  - custom scrollbar for the transcript container.
  - `@media (prefers-reduced-motion: reduce) { * { animation: none !important;
    transition: none !important; } }` — required by UI-SPEC §Animation.
  - Class-based transition utilities (`.screen-enter`, `.jump-pill`, etc.) used by
    the two screens. CSS classes are fine here; inline styles can't express
    `@keyframes`/`:focus-visible`/media queries.
- **Animation primitives:** CSS `transition`/`@keyframes` on `transform`+`opacity`
  only (GPU-friendly; never animate width/height/top/left). Durations per the
  UI-SPEC Animation Contract table (240ms setup→talking, 200ms reverse, 120ms
  hover, 150-160ms micro-states).

### 3.2 Screen transition pattern (React, no lib)

Keep both screens mountable and cross-fade via a CSS class toggled on a phase state
(`"setup" | "connecting" | "talking"`). Because `<LiveKitRoom>` must NOT unmount
once connected (criterion 3), the transition is a visual overlay/opacity change, not
a conditional unmount of the room. Simplest robust approach: render the talking
screen as soon as token is set, with an entering animation class; render the setup
screen with an exit class; let CSS handle the 240ms fade/slide. Avoid
mount/unmount-based exit animations (they need extra machinery in React 19).

---

## 4. Smart auto-scroll for `Transcript.tsx` (success criterion 4)

Self-contained; no new deps. Pattern (React 19, refs + scroll listener):

```tsx
const containerRef = useRef<HTMLDivElement>(null);
const atBottomRef = useRef(true);          // ref, not state, to avoid re-render churn
const [showJump, setShowJump] = useState(false);
const THRESHOLD = 32;                       // px

// scroll listener: recompute atBottom
function onScroll() {
  const el = containerRef.current!;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= THRESHOLD;
  atBottomRef.current = atBottom;
  setShowJump(!atBottom && hasContent);
}

// after segments change: stick only if atBottom
useEffect(() => {
  const el = containerRef.current;
  if (!el) return;
  if (atBottomRef.current) el.scrollTop = el.scrollHeight;  // 'auto'/instant
}, [segments]);   // useTranscriptions() returns a new array on each token update
```

Key correctness points:
- **Use `scrollTop = scrollHeight` (instant)** for streaming token updates to avoid
  animation thrash; reserve `scrollTo({behavior:"smooth"})` for the explicit
  "Jump to latest ↓" click (UI-SPEC §Transcript).
- **Track `atBottom` in a ref**, recomputed on the `scroll` event — do not derive it
  inside the segments effect, or a programmatic scroll re-reads stale geometry.
- **"Jump to latest ↓" pill** (accent `#58a6ff`, bottom-center) shows when
  `!atBottom`; click → smooth-scroll to bottom + set `atBottomRef = true`.
- **Interim vs final styling:** `useTranscriptions()` segments carry a `streamInfo`;
  finals full-opacity, interim `0.7`/italic per UI-SPEC. (Verify the exact in-progress
  flag on `TextStreamData` from `@livekit/components-react@2.9.21` at implementation
  time — it's on `segment.streamInfo`/attributes; the current code ignores it.)
- **React 19 gotcha:** a programmatic `scrollTop` write fires the `scroll` handler;
  guard against it flipping `atBottom` falsely (it won't if you set scrollTop to the
  exact bottom, but keep the threshold ≥ a few px).
- **Container needs a bounded height** (`flex:1` + `overflow-y:auto` + `min-height:0`
  inside a flex column) for scroll to exist at all — today the `<ul>` is unbounded.

---

## 5. Reversible navigation (success criterion 3)

**Chosen pattern (UI-SPEC recommended (a)):** keep the live room mounted; surface
settings as an overlay/drawer **inside `<LiveKitRoom>`**.

- "Settings" / "Back to setup" opens an overlay drawer containing the same
  Persona/Interview/Model/KB panels — which already apply to the **live** agent via
  their existing RPCs. **No disconnect, no `<LiveKitRoom>` unmount.**
- A separate, clearly-destructive **"Leave session"** (`#f85149`, confirm dialog) is
  the only path that tears down the room (sets `token = null` → `<LiveKitRoom>`
  unmounts → back to setup). Its full clear-all/teardown semantics are **Phase 14**;
  Phase 13 builds the affordance + copy only (UI-SPEC §Copywriting note).
- **Hard rule:** do NOT toggle `<LiveKitRoom>` mounting for a settings visit. If the
  room unmounts, the agent leaves, the transcript clears, and the avatar tears down —
  that is the "broken state" criterion 3 forbids.
- Keyboard: Tab to reach primary actions; Enter/Space activate Start CTA and Jump
  pill; Escape closes the overlay; visible `#58a6ff` 2px focus ring on every control.

---

## 6. Accessibility & responsive (success criterion 5)

- **No size below 14px** (UI-SPEC Typography) — today's `0.85rem`/`0.9rem` muted
  text (13.6px/14.4px) must move to 14px/16px tokens.
- **Focus-visible ring** via `globals.css` (`:focus-visible`), 2px `#58a6ff`.
- **`prefers-reduced-motion`** media block disables all transitions/animations;
  transcript token streaming must never animate regardless.
- **Keyboard nav:** the segmented toggles are `<button>`s already (good). Mic
  `<select>`, persona fields, Start CTA all native/focusable. Ensure the settings
  overlay traps focus and Escape-closes.
- **Mic permission flow:** `navigator.mediaDevices.enumerateDevices()` returns
  device **labels only after a permission grant**. Setup screen: show "Allow
  microphone to list devices" affordance; a one-time `getUserMedia({audio:true})`
  populates labels; selection stays **optional** (default mic used otherwise).
  Listing-blocked is an inline note, not a hard error.
- **No console errors** during setup → connect → talk: the chief risks are
  (1) firing RPCs before the agent joins (guard on `agent.identity`),
  (2) `AudioContext`/autoplay before a user gesture (the Start click covers it; keep
  `<StartAudio>` backstop), (3) Strict-Mode double-effect firing the apply twice
  (ref guard), (4) the avatar importmap order in `<head>` (do not move it).
- **Responsive:** setup panel max-width ~720px centered; talking screen is a flex
  column (top bar / optional avatar / transcript flex-1 / controls). Avatar region
  `360px` unchanged. Verify common viewports (≥360px mobile to desktop).

---

## 7. Isolation invariants this phase MUST preserve

1. **Zero server diff** — `git diff -- agent/ stt/ tts/ docker-compose.yml` empty.
   No RPC/stream/attribute/payload-key changes; only *when* the client fires them.
2. **Voice-only byte-for-byte** — avatar stays dynamic-imported (`ssr:false`), absent
   from the voice-only bundle. **No new runtime dependency** may enter the bundle
   (kills any framework/motion-lib option). `tokens.ts`+`globals.css` add zero JS deps.
3. **`layout.tsx` importmap** emitted in `<head>` before any avatar module — untouched.
4. **Agent-mirrored constants** (`VOICE_IDS`, `CHOICES`, `ROLES`, `MODE_*`,
   `DEFAULT_PERSONA`, `kb.upload`/`kb.state`/25MB) byte-identical after the refactor.
5. **Single user gesture** for entry (mic-permission + autoplay-unlock + connect) —
   the new "Start session" click must still end in `setToken` → room mounts.
6. **Persona prompt unchanged** (sole guardrail). This is server-side; the UI can't
   touch it beyond the existing `role_text` field.

---

## 8. Files to create / modify (for pattern-mapper + planner)

### Create
- `web/app/ui/tokens.ts` — palette, spacing, type scale, radii, shared
  `panelStyle/labelStyle/inputStyle/STATUS_*` (the de-dup target).
- `web/app/globals.css` — keyframes, focus-visible ring, scrollbar, reduced-motion
  block, transition utility classes. Imported in `layout.tsx`.
- `web/app/SetupScreen.tsx` (new) — the single elegant landing panel: wordmark +
  tagline, the config groups (Persona/KB/Model/Interview/Mic/Avatar) with
  progressive-disclosure "Customize", headphones tip, "Start session" CTA. Owns
  `sessionConfig` (or receives it lifted from a parent shell). NO room context.
- `web/app/MicPicker.tsx` (new, optional split) — `enumerateDevices` + permission
  affordance; writes `micDeviceId` into config.
- `web/app/ApplySetupOnConnect.tsx` (new) — rendered inside `<LiveKitRoom>`; the
  once-only post-connect apply effect (persona→mode→model→KB) keyed on agent
  readiness; drives the "Applying your setup…" status.
- `web/app/TalkingScreen.tsx` (new, optional) — extract the in-room layout (top bar,
  avatar stage, transcript, settings drawer) out of VoiceRoom for clarity.
- `web/app/SettingsDrawer.tsx` (new) — overlay hosting the live-tweak panels +
  "Leave session" destructive affordance (copy only; teardown = Phase 14).

### Modify
- `web/app/VoiceRoom.tsx` — becomes the shell/orchestrator: holds `sessionConfig` +
  `token` + phase state; renders SetupScreen (pre-token) and the in-room
  TalkingScreen (post-token) with the cross-fade; passes `micDeviceId` into
  `audioCaptureDefaults`; renders `<ApplySetupOnConnect>`. Keep the single-gesture
  Start. Keep the avatar dynamic import.
- `web/app/Transcript.tsx` — add the scroll container, `atBottom` tracking, stick-to-
  bottom effect, "Jump to latest" pill, interim/final styling, empty-state copy.
- `web/app/PersonaPanel.tsx`, `ModelPanel.tsx`, `InterviewPanel.tsx`,
  `KbPanel.tsx` — import shared tokens from `ui/tokens.ts` (remove the copy-pasted
  style/status blocks); optionally accept lifted value+onChange so the setup screen
  and the settings drawer can both render them (controlled-component refactor).
  Keep their RPC/sendFile apply logic for the live-tweak (drawer) path.
- `web/app/AgentStatePill.tsx` — token import only (colors unchanged).
- `web/app/page.tsx` — drop the inline `<h1>Adept</h1>` (wordmark moves to
  SetupScreen); keep `<main>`/`<VoiceRoom/>` or fold into the shell.
- `web/app/layout.tsx` — `import "./globals.css"`; relax the body flex-center so the
  two full-screen layouts can own their own centering. **Do not move the importmap.**

### Do NOT touch
- `web/app/AvatarStage.tsx` internals, `web/app/avatarConfig.ts`,
  `web/app/api/token/route.ts`, and anything under `agent/`, `stt/`, `tts/`,
  `docker-compose.yml`.

---

## 9. Open questions / verification notes for the planner

- **Interim-segment flag:** confirm the exact field on `useTranscriptions()`
  `TextStreamData` that distinguishes interim vs final in
  `@livekit/components-react@2.9.21` (likely `segment.streamInfo` attributes). The
  current Transcript ignores it; the UI-SPEC requires the visual distinction.
- **Agent-readiness signal:** `useVoiceAssistant().agent` becomes defined when the
  agent participant joins; confirm timing is acceptable for auto-apply (the agent
  registers RPCs right after `session.start()` — main.py:496 — which is after it
  joins, so `agent` defined ⇒ RPC methods registered). If a race is observed, gate
  the apply on a tiny retry/`ParticipantConnected` re-check.
- **Default-skip optimization:** decide whether to skip applying snapshots that equal
  the agent defaults (avoids a first-turn re-prefill bump). Low-risk, recommended.
- **Mic deviceId plumbing:** confirm `audioCaptureDefaults.deviceId` is the right
  field for `<LiveKitRoom options>` in this version (vs `RoomOptions`), or set it on
  the publication. Net-new client state regardless.
- **Two-layout centering:** the current `layout.tsx` body is a global flex-center;
  the talking screen wants a full-height column. Plan the body style change so the
  setup screen still centers and the talking screen fills.

---

## RESEARCH COMPLETE

**Summary:** The setup-vs-talking split already exists physically in `VoiceRoom.tsx`
(the `!token` branch vs `<LiveKitRoom>`). The highest-risk decision resolves cleanly:
**hold all config in plain React state on the setup screen, then on Start set the
token (single gesture) → room mounts → agent joins → a once-only post-connect effect
fires the held persona/mode/model RPCs and queued KB `sendFile` over the now-open
room.** This is verified feasible because the agent registers its RPC handlers right
after `session.start()` and `useVoiceAssistant().agent.identity` is the readiness
signal the existing panels already guard on — only *when* the RPCs fire moves; no
server/RPC/stream contract changes. Styling: extract inline tokens into
`web/app/ui/tokens.ts` + one `globals.css` for keyframes/focus-ring/reduced-motion —
**no framework, no motion lib** (mandatory for the AVTR-01 voice-only bundle gate).
Auto-scroll is a self-contained `Transcript.tsx` change (bounded scroll container +
`atBottom` ref + stick-to-bottom + "Jump to latest" pill). Navigation uses the
keep-room-open settings-overlay pattern (live RPC tweaks) with a separate destructive
"Leave session" — never unmount `<LiveKitRoom>` for settings. Agent-mirrored
constants must stay byte-identical through the de-dup refactor. Section 8 lists every
file to create/modify; Section 9 flags the few items to verify at implementation time.
