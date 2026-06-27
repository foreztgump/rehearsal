# Phase 13 Patterns: UI/UX Overhaul — File-by-File Analog Map

**Phase goal:** A frontend-only two-screen experience — a **setup-before-connect
landing screen** (hold all config in client state, apply after connect) and a
**polished talking screen** with smart auto-scroll — restyled simple/elegant/
animated, with **zero server diff** and **zero new runtime deps** (AVTR-01 bundle
isolation gate).

**Sources:** `13-CONTEXT.md` (D-01..D-04 + KEY TENSION), `13-RESEARCH.md`
(§8 file list, §2 apply mechanism, §3 styling, §4 auto-scroll, §5 navigation,
§7 isolation invariants), `13-UI-SPEC.md` (design contract: tokens, color,
typography, spacing, animation, copywriting).

This document maps each file to be created/modified onto its closest existing
analog in `web/app/`, with concrete code excerpts, so the planner can write
`read_first` lists and concrete actions. Every excerpt below is from the actual
source as it stands today.

---

## File inventory (from RESEARCH §8)

| # | File | Role | Action | Closest analog |
|---|---|---|---|---|
| 1 | `web/app/ui/tokens.ts` | NEW pure constants module (de-dup target) | create | the copy-pasted `panelStyle`/`labelStyle`/`inputStyle`/`STATUS_LABEL`/`STATUS_COLOR` blocks in PersonaPanel/ModelPanel/InterviewPanel/KbPanel + `avatarConfig.ts` (dependency-free, tree-shakes) |
| 2 | `web/app/globals.css` | NEW global stylesheet (keyframes/focus/reduced-motion) | create | none in repo (`web/**/*.css` → none today); imported in `layout.tsx` |
| 3 | `web/app/SetupScreen.tsx` | NEW landing panel (no room context) | create | `VoiceRoom.tsx:49-86` (the `!token` pre-connect branch) + the panels' form-state idiom |
| 4 | `web/app/MicPicker.tsx` | NEW (optional split) device picker | create | `KbPanel.tsx` file-input + a `<select>` like ModelPanel; permission via `getUserMedia`/`enumerateDevices` |
| 5 | `web/app/ApplySetupOnConnect.tsx` | NEW in-room once-only apply effect | create | the three panels' `apply()` body (`PersonaPanel.tsx:93-118`, ModelPanel/InterviewPanel) + KbPanel `sendFile` |
| 6 | `web/app/TalkingScreen.tsx` | NEW (optional) in-room layout extract | create | `VoiceRoom.tsx:88-148` (the `<LiveKitRoom>` subtree) |
| 7 | `web/app/SettingsDrawer.tsx` | NEW overlay hosting live-tweak panels | create | `VoiceRoom.tsx:99-147` panel row + the avatar toggle idiom (`VoiceRoom.tsx:103-134`) |
| 8 | `web/app/VoiceRoom.tsx` | MODIFY → shell/orchestrator | edit | self (it already holds the `!token` vs `<LiveKitRoom>` seam) |
| 9 | `web/app/Transcript.tsx` | MODIFY → scroll container + stick-to-bottom + jump pill | edit | self (the flat `<ul>` at lines 19-37) + KbPanel `useEffect`-on-attribute pattern |
| 10 | `web/app/PersonaPanel.tsx` | MODIFY → import tokens; optional controlled refactor | edit | self + tokens module |
| 11 | `web/app/ModelPanel.tsx` | MODIFY → import tokens; optional controlled refactor | edit | self + tokens module |
| 12 | `web/app/InterviewPanel.tsx` | MODIFY → import tokens; optional controlled refactor | edit | self + tokens module |
| 13 | `web/app/KbPanel.tsx` | MODIFY → import tokens; queue-file path for setup | edit | self + tokens module |
| 14 | `web/app/AgentStatePill.tsx` | MODIFY → token import only (colors unchanged) | edit | self |
| 15 | `web/app/page.tsx` | MODIFY → drop inline `<h1>`; wordmark moves to SetupScreen | edit | self (`page.tsx:1-10`) |
| 16 | `web/app/layout.tsx` | MODIFY → `import "./globals.css"`; relax body flex-center | edit | self (`layout.tsx:31-42`) |

**Do NOT touch (RESEARCH §8):** `web/app/AvatarStage.tsx` internals,
`web/app/avatarConfig.ts`, `web/app/api/token/route.ts`, anything under `agent/`,
`stt/`, `tts/`, `docker-compose.yml`.

**Frozen duplication seams (must stay byte-identical through the de-dup refactor —
RESEARCH §1.3, §7.4):** `PersonaPanel.VOICE_IDS / DIFFICULTY / VERBOSITY /
CORRECTION / DEFAULT_PERSONA`, `ModelPanel.CHOICES / CHOICE_LABEL`,
`InterviewPanel.MODE_LEARN / MODE_INTERVIEW / ROLES / ROLE_LABEL`,
`KbPanel.KB_UPLOAD_TOPIC / KB_STATE_ATTRIBUTE / MAX_UPLOAD_BYTES`. These mirror the
Python agent with **no get-RPC**, so drift is silent. The tokens refactor is
**presentational only** — move styles, never agent-mirrored keys.

---

## File 1 — `web/app/ui/tokens.ts` (NEW, pure constants)

**Role:** Single source of truth for the dark-theme design system. Exports the
palette, spacing scale, typography, radii, and the shared
`panelStyle`/`labelStyle`/`inputStyle`/`STATUS_LABEL`/`STATUS_COLOR` as typed
`React.CSSProperties`. Every panel imports from here instead of redefining.

**Data flow:** pure constants, no React state, no network. Dependency-free so it
tree-shakes and never pulls weight into the voice-only bundle.

### Analog A — the copy-pasted style blocks (the de-dup target)

These four blocks are **byte-identical** across PersonaPanel, ModelPanel,
InterviewPanel, and (partially) KbPanel — this is exactly what moves into tokens:

```tsx
// web/app/PersonaPanel.tsx:47-74 (identical in ModelPanel:35-62, InterviewPanel:36-63)
const panelStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: "0.6rem", width: "20rem",
  padding: "1rem", border: "1px solid #30363d", borderRadius: "0.5rem",
  background: "#0d1117", color: "#c9d1d9", fontSize: "0.9rem",
};
const labelStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: "0.25rem", fontWeight: 600,
};
const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.5rem", borderRadius: "0.35rem", border: "1px solid #30363d",
  background: "#161b22", color: "#c9d1d9", fontWeight: 400,
};
```

```tsx
// web/app/PersonaPanel.tsx:33-45 (identical in ModelPanel:21-33, InterviewPanel:22-34)
const STATUS_LABEL: Record<ApplyState, string> = {
  idle: "", applying: "applying…", applied: "applied", error: "error — could not apply",
};
const STATUS_COLOR: Record<ApplyState, string> = {
  idle: "#8b949e", applying: "#d29922", applied: "#3fb950", error: "#f85149",
};
```

The `ApplyState` union is also duplicated verbatim (`PersonaPanel.tsx:20`,
ModelPanel:19, InterviewPanel:20): `type ApplyState = "idle"|"applying"|"applied"|"error"`.
Move it to tokens (or a small `ui/apply.ts`).

**UI-SPEC normalization to apply during the move:** the SPEC declares a px spacing
scale (4/8/16/24/32/48/64) and exactly 4 type sizes / 2 weights, **no size below
14px**. Today's `0.9rem`/`0.85rem` (14.4px/13.6px) and ad-hoc `0.6rem`/`0.4rem`
spacing collapse onto the SPEC tokens. The palette is unchanged (it IS the locked
design system): `#0b0f14` bg, `#0d1117` panel, `#161b22` nested input, `#30363d`
border, `#58a6ff` accent, `#3fb950` action, `#d29922` warning, `#f85149`
destructive, text `#e6edf3`/`#c9d1d9`/`#8b949e`.

### Analog B — `avatarConfig.ts` (the dependency-free module shape to mirror)

```ts
// web/app/avatarConfig.ts:1-3
// Pure client constants ... Dependency-free (no React) so it tree-shakes cleanly
// and never pulls the avatar libraries into the voice-only bundle.
```

`tokens.ts` follows this exact discipline: pure constants/typed objects, no React
import, no side effects. This is the bundle-isolation contract (RESEARCH §3.1, §7.2).

### Invariants enforced
- Zero new runtime deps (RESEARCH §7.2) — constants only, no framework, no motion lib.
- Agent-mirrored constants stay in their panels (or a separate `agentContract.ts`),
  **not** mixed into presentational tokens; refactor is presentational only.

---

## File 2 — `web/app/globals.css` (NEW, global stylesheet)

**Role:** The one place CSS lives. Holds what inline styles cannot express:
`@keyframes`, `:focus-visible` ring, custom transcript scrollbar, the
`prefers-reduced-motion` block, and class-based transition utilities for the
two-screen cross-fade and the jump pill.

**Data flow:** static stylesheet, imported once in `layout.tsx`. Zero JS.

### Analog — none exists (net-new); the layout import is the wiring

There is **no CSS file anywhere in `web/`** today (RESEARCH §1.5) — all styling is
inline `style={{}}`. So this file has no code analog; its analog is the *gap*. The
wiring point is a single `import "./globals.css";` at the top of `layout.tsx`.

### Required contents (UI-SPEC Animation Contract + §6 accessibility)

- `@keyframes` for: setup↔talking cross-fade, jump-pill in/out, status fades.
- `:focus-visible { outline: 2px solid #58a6ff; }` — accessibility criterion 5.
- Custom scrollbar for the transcript container.
- `@media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation:none!important; transition:none!important; } }` — required.
- Transition utilities: durations from the SPEC table (240ms setup→talking ease-out,
  200ms reverse ease-in, 120ms hover, 160ms segmented-slide, 150ms status/pill).
- Motion only on `transform`/`opacity` (GPU-friendly); never `width/height/top/left`.

### Invariants
- CSS-only, no `@import` of a remote font/framework (bundle isolation, RESEARCH §7.2).
- Transcript token streaming MUST NOT animate regardless of motion prefs (UI-SPEC §Animation).

---

## File 3 — `web/app/SetupScreen.tsx` (NEW, landing panel — no room)

**Role:** The single elegant landing panel (D-01). Wordmark + tagline, config
groups (Persona/KB/Model/Interview/Mic/Avatar) all pre-filled with defaults (D-02),
progressive-disclosure "Customize", headphones tip, and the prominent "Start
session" CTA. Owns (or receives lifted) `sessionConfig`. **No room context** —
plain React state only.

**Data flow:** local/ lifted `sessionConfig` state ← form edits; "Start session"
click → parent `setToken(...)` (single user gesture). No RPCs possible here.

### Analog A — the existing pre-connect branch (the seam to expand) — VoiceRoom.tsx:49-86

```tsx
// web/app/VoiceRoom.tsx:49-86 (the SETUP SCREEN lives here today)
if (!token) {
  return (
    <div>
      <button style={{ /* green #3fb950 CTA */ }}
        onClick={async () => {
          setError(null);
          try {
            const res = await fetch("/api/token");
            if (!res.ok) throw new Error(`token fetch failed (${res.status})`);
            const data = await res.json();
            setToken(data.token);
          } catch (err) {
            setError(err instanceof Error ? err.message : "could not start");
          }
        }}>
        Start talking
      </button>
      <p style={{ color: "#8b949e", ... }}>Tip: use headphones ...</p>
      {error && <p style={{ color: "#f85149", ... }}>{error}</p>}
    </div>
  );
}
```

SetupScreen is this branch, expanded into the SPEC's single 720px card. **Keep the
single-gesture Start** — the click must still end in `setToken` → `<LiveKitRoom>`
mounts (RESEARCH §7.5). Copy updates per UI-SPEC: button → `Start session`,
tagline → `Set up your session, then start talking.`, headphones tip text unchanged.

### Analog B — the form-field idiom (per group) — PersonaPanel.tsx:124-193

The labeled `<label>`+`<select>`/`<input>` rows are the building block for each
config group; the SetupScreen renders the same controls but writes to held state
instead of firing an RPC:

```tsx
// web/app/PersonaPanel.tsx:143-154 (a select row to reuse)
<label style={labelStyle}>
  Difficulty
  <select style={inputStyle} value={persona.difficulty}
    onChange={(e) => set("difficulty", e.target.value)}>
    {DIFFICULTY.map((d) => (<option key={d} value={d}>{d}</option>))}
  </select>
</label>
```

The progressive-disclosure "Customize" wrapper holds the advanced fields
(role_text, voice, difficulty/verbosity/correction, interview role) collapsed by
default; the collapsed summary shows the current default (UI-SPEC §Screen A).

### Analog C — the segmented toggle (for Avatar Voice-only/Avatar) — VoiceRoom.tsx:103-134

```tsx
// web/app/VoiceRoom.tsx:103-134 (the reusable segmented-control idiom)
<div role="group" aria-label="Voice only / Avatar"
  style={{ display:"inline-flex", borderRadius:"999px", overflow:"hidden",
           border:"1px solid #30363d", fontSize:"0.85rem" }}>
  {([["Voice only", false], ["Avatar", true]] as const).map(([label, on]) => (
    <button key={label} type="button" onClick={() => setAvatarOn(on)}
      style={{ ..., background: avatarOn === on ? "#58a6ff" : "transparent",
               color: avatarOn === on ? "#0b0f14" : "#8b949e" }}>
      {label}
    </button>
  ))}
</div>
```

This same idiom serves the Avatar group on the setup screen AND the Learn/Interview
mode toggle. Active segment uses accent `#58a6ff` (UI-SPEC reserved-accent rule).

### Recommended held-state shape (RESEARCH §2.1)

```ts
type SessionConfig = {
  persona: Persona;                            // DEFAULT_PERSONA
  mode: { mode: string; role_key: string };    // learn / soc_analyst
  model: "fast" | "better";                    // fast
  micDeviceId?: string;                        // undefined → default mic
  avatarOn: boolean;                           // false
  kbFiles: File[];                             // [] held until connect
};
```

### Invariants
- **No room context here** — `useRoomContext`/`useVoiceAssistant` are unavailable
  (RESEARCH §1.2, §2.4). Pure state only.
- Start CTA is NEVER disabled by missing choices (D-02 / UI-SPEC §Screen A).
- Defaults are the agent-mirrored constants (seed from `DEFAULT_PERSONA`, learn, fast).

---

## File 4 — `web/app/MicPicker.tsx` (NEW, optional split)

**Role:** `enumerateDevices` + permission affordance; writes `micDeviceId` into
config. Selection is optional (default mic used otherwise).

**Data flow:** `getUserMedia({audio:true})` (one-time, to unlock labels) →
`navigator.mediaDevices.enumerateDevices()` → `<select>` → `onChange` writes
`micDeviceId` to `sessionConfig`. No room, no server.

### Analog — the `<select>` + label idiom (ModelPanel) + KbPanel's device-style note

```tsx
// web/app/ModelPanel.tsx:108-119 (the labeled select to clone)
<label style={labelStyle}>
  Model
  <select style={inputStyle} value={choice}
    onChange={(e) => setChoice(e.target.value as ...)}>
    {CHOICES.map((c) => (<option key={c} value={c}>{CHOICE_LABEL[c]}</option>))}
  </select>
</label>
```

There is no existing `enumerateDevices` call in the live UI (RESEARCH §1.5 notes
`SecureContextProbe.tsx` is an unwired dev probe referencing `navigator.mediaDevices`
— useful reference only). UI-SPEC copy: label `Microphone`, helper "Allow microphone
access to choose a device. Optional — we'll use your default otherwise." Listing
blocked = inline note, **not** a hard error (RESEARCH §6).

### Plumbing target (RESEARCH §9 mic-deviceId note)

The chosen `micDeviceId` flows into `<LiveKitRoom options>` via
`audioCaptureDefaults.deviceId` at connect (see File 8). Confirm the exact field on
`@livekit/components-react@2.9.21` at implementation time.

### Invariants
- Permission/labels gate is informational, never blocking (selection optional).
- No server change — net-new client state only (RESEARCH §1.1).

---

## File 5 — `web/app/ApplySetupOnConnect.tsx` (NEW, in-room once-only apply)

**Role:** THE highest-risk mechanism. Rendered **inside `<LiveKitRoom>`**, it waits
for the agent participant to join, then fires the held `sessionConfig` as the
existing RPCs (persona → mode → model) and uploads any queued KB files — **exactly
once**. Drives the "Applying your setup…" status.

**Data flow:** `sessionConfig` (prop) + `useVoiceAssistant().agent` readiness →
`useEffect` keyed on `agent?.identity` → sequential `performRpc` + `sendFile` →
status callback. Renders nothing (or a status line).

### Analog A — the panel `apply()` body (the EXACT RPC core to compose) — PersonaPanel.tsx:93-118

```tsx
// web/app/PersonaPanel.tsx:93-118 (identical agent-targeting in ModelPanel/InterviewPanel)
async function apply() {
  setStatus("applying");
  const fallback = Array.from(room.remoteParticipants.values())[0];
  const agentIdentity = agent?.identity ?? fallback?.identity;
  if (!agentIdentity) { setStatus("error"); return; }   // ← readiness guard to reuse
  try {
    await room.localParticipant.performRpc({
      destinationIdentity: agentIdentity,
      method: "persona.update",
      payload: JSON.stringify(persona),
    });
    setStatus("applied");
  } catch { setStatus("error"); }
}
```

`ApplySetupOnConnect` calls these three in order (persona → mode → model — RESEARCH
§2.2 ordering rationale), reusing the `agentIdentity` resolution verbatim:

```tsx
// model + mode payload shapes (from ModelPanel.tsx:93-98 / InterviewPanel.tsx:95-99)
await performRpc({ method: "model.update", payload: JSON.stringify({ choice }) });   // ack === "applied"
await performRpc({ method: "mode.update", payload: JSON.stringify({ mode, role_key }) });
```

### Analog B — the KB queued-upload (last) — KbPanel.tsx:99-121

```tsx
// web/app/KbPanel.tsx:110-120 (the sendFile loop to fire for queued files)
try {
  for (const file of Array.from(files)) {
    await room.localParticipant.sendFile(file, { topic: KB_UPLOAD_TOPIC });
  }
} catch (err) {
  setStatus("error");
  setError(err instanceof Error ? `Upload failed: ${err.message}` : "Upload failed");
}
```

KB fires **last** (after persona/mode set) so the brief composes under the chosen
persona/mode (RESEARCH §2.2). KbPanel already handles mid-stream failure — keep it.

### Analog C — the once-guard + effect-on-readiness (KbPanel's attribute effect shape) — KbPanel.tsx:86-97

```tsx
// web/app/KbPanel.tsx:86-97 (the useEffect-keyed-on-agent-signal shape to mirror)
useEffect(() => {
  const raw = attributes?.[KB_STATE_ATTRIBUTE];
  if (!raw) return;
  ...
}, [attributes]);
```

`ApplySetupOnConnect` keys its effect on `agent?.identity`; **guard with a
`useRef(applied)` so it runs exactly once** — React 19 Strict Mode double-invokes
effects in dev, so the ref guard is mandatory (RESEARCH §2.2 step 2, §6 risk 3).

### Error / ordering rules (RESEARCH §2.2-§2.3)
- **Agent not joined yet:** non-fatal inline note ("Still connecting the agent…"),
  retry on next `agent` change — do NOT hard-fail or block the talking UI.
- **Default-skip optimization (recommended):** skip the persona/mode/model RPC when
  the held value deep-equals the agent default (avoids a needless first-turn
  re-prefill). KB only fires if files were queued.
- **RPC throws / non-"applied":** surface per-section status (reuse `ApplyState`),
  non-blocking; user can re-apply from the settings drawer.

### Invariants (RESEARCH §7)
- **Zero server diff** — same RPC methods/payload keys/stream topic; only *when*
  they fire moves. No `persona.update`/`mode.update`/`model.update`/`kb.upload` change.
- Single-gesture entry preserved (the Start click set the token; this just applies after).

---

## File 6 — `web/app/TalkingScreen.tsx` (NEW, optional in-room layout extract)

**Role:** Extract the in-room layout (top bar, optional avatar stage, transcript as
the hero column, settings affordance) out of VoiceRoom for clarity. Must render
inside `<LiveKitRoom>`.

**Data flow:** consumes room context (via hooks in children); receives
`avatarOn`/`personaName`/`onOpenSettings` props from the shell.

### Analog — the existing in-room subtree (self) — VoiceRoom.tsx:88-148

```tsx
// web/app/VoiceRoom.tsx:88-148 (the TALKING SCREEN content today — flat row of 5 panels)
return (
  <LiveKitRoom serverUrl={SERVER_URL} token={token} connect audio video={false}
    options={{ audioCaptureDefaults: AUDIO_CAPTURE_DEFAULTS }}>
    <RoomAudioRenderer />
    <StartAudio label="Click to enable audio" />
    <div style={{ display:"flex", gap:"0.75rem", alignItems:"center" }}>
      <AgentStatePill />
      {/* Voice only / Avatar toggle */}
    </div>
    {avatarOn && <div style={{ width:"100%", height:"360px", marginTop:"1rem" }}>
      <AvatarStage persona={personaName} /></div>}
    <div style={{ display:"flex", gap:"1rem", alignItems:"flex-start", marginTop:"1rem" }}>
      <PersonaPanel /><InterviewPanel /><ModelPanel /><KbPanel /><Transcript />
    </div>
  </LiveKitRoom>
);
```

UI-SPEC §Screen B reshapes this from a flat 5-panel row into: **top bar**
(state pill + avatar toggle + Settings/Back affordance), **optional avatar stage**
(`360px`, mount contract unchanged), **transcript as the focal column** (flex-1),
and the config panels moved into the SettingsDrawer (File 7) so they don't crowd the
transcript. **Keep `<RoomAudioRenderer/>` + `<StartAudio/>` exactly** (autoplay
backstop, RESEARCH §6). **Keep avatar dynamic-import + `360px` region unchanged**
(AVTR-01).

### Invariants
- `<LiveKitRoom>` stays mounted for the whole live session — never unmount for a
  settings visit (RESEARCH §5, criterion 3).
- Avatar mount gated on `avatarOn` + dynamic-imported (`ssr:false`) — preserve.

---

## File 7 — `web/app/SettingsDrawer.tsx` (NEW, in-room overlay)

**Role:** Reversible-navigation surface (criterion 3, UI-SPEC pattern (a)). An
overlay/drawer **inside `<LiveKitRoom>`** hosting the existing live-tweak panels
(Persona/Interview/Model/KB) plus a destructive "Leave session" affordance (copy
only; teardown = Phase 14).

**Data flow:** open/close from a parent boolean; renders the same panels, which keep
their existing RPC-on-apply logic (they have room context). "Leave session" →
confirm → `setToken(null)` (the only disconnect path).

### Analog A — the panel row (self) — VoiceRoom.tsx:141-147

```tsx
// web/app/VoiceRoom.tsx:141-147 (the panels to relocate into the drawer)
<div style={{ display:"flex", gap:"1rem", alignItems:"flex-start", marginTop:"1rem" }}>
  <PersonaPanel /><InterviewPanel /><ModelPanel /><KbPanel />
</div>
```

The drawer hosts these unchanged — their `performRpc`/`sendFile` apply logic is
**reused, not deleted** (RESEARCH §2.4, §5). Live tweaks apply to the running agent.

### Analog B — the destructive color + the existing teardown signal — VoiceRoom.tsx:37, 82

```tsx
// web/app/VoiceRoom.tsx:37 (the token state — null => <LiveKitRoom> unmounts => back to setup)
const [token, setToken] = useState<string | null>(null);
// web/app/VoiceRoom.tsx:82 (the existing #f85149 destructive text pattern)
{error && <p style={{ color: "#f85149", ... }}>{error}</p>}
```

"Leave session" uses `#f85149` + a confirm dialog; on confirm sets `token = null`.
UI-SPEC copy: "End this conversation and return to setup? Your transcript will
clear." **Phase 13 builds the affordance + copy only** — full clear-all/teardown
semantics are Phase 14 (CONTEXT.md Deferred, UI-SPEC §Copywriting note).

### Invariants (RESEARCH §5 — hard rules)
- **Do NOT toggle `<LiveKitRoom>` mounting for a settings visit.** Unmounting drops
  the agent, clears the transcript, tears down the avatar — the forbidden "broken
  state".
- Keyboard: Escape closes the overlay; focus trap; visible `#58a6ff` 2px focus ring.

---

## File 8 — `web/app/VoiceRoom.tsx` (MODIFY → shell/orchestrator)

**Role:** Becomes the thin shell: holds `sessionConfig` + `token` + phase state
(`"setup"|"connecting"|"talking"`); renders `SetupScreen` (pre-token) and the
in-room `TalkingScreen` (post-token) with the cross-fade; passes `micDeviceId` into
`audioCaptureDefaults`; renders `<ApplySetupOnConnect>`. Keeps the single-gesture
Start and the avatar dynamic import.

**Data flow:** owns the lifted state; `setToken` is the connect trigger; phase state
drives the CSS cross-fade class.

### Analog — self (the existing structure already encodes the split)

```tsx
// web/app/VoiceRoom.tsx:36-47 (the state already lifted here — the template to extend)
export default function VoiceRoom() {
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [avatarOn, setAvatarOn] = useState(false);
  const [personaName] = useState("Cybersecurity Trainer");   // already lifted for avatar
```

```tsx
// web/app/VoiceRoom.tsx:24-28 (the mic-deviceId plumb point)
const AUDIO_CAPTURE_DEFAULTS = {
  echoCancellation: true, noiseSuppression: true, autoGainControl: true,
};
```

`personaName` already being lifted to VoiceRoom for the avatar (line 47) is the
template for lifting the rest of `sessionConfig` up here. `micDeviceId` plugs into
`AUDIO_CAPTURE_DEFAULTS` as `deviceId` at connect (RESEARCH §1.1, §9).

```tsx
// web/app/VoiceRoom.tsx:16 (the avatar dynamic import — KEEP exactly)
const AvatarStage = dynamic(() => import("./AvatarStage"), { ssr: false });
```

### Cross-fade (RESEARCH §3.2)
Keep both screens mountable; cross-fade via a CSS class toggled on phase state.
Because `<LiveKitRoom>` must NOT unmount once connected (criterion 3), the
transition is a visual opacity/transform change, not a conditional unmount. Render
the talking screen as soon as token is set with an entering class; render setup with
an exit class; let CSS handle the 240ms fade/slide. Avoid mount/unmount-based exit
animations (extra machinery in React 19).

### Invariants
- Single-gesture Start preserved (`setToken` → room mounts in the same click render).
- `<LiveKitRoom connect>` auto-connects on mount — unchanged.
- Avatar stays dynamic-imported, absent from voice-only bundle (AVTR-01).

---

## File 9 — `web/app/Transcript.tsx` (MODIFY → smart auto-scroll)

**Role:** Add a bounded scroll container, `atBottom` tracking, stick-to-bottom on
new segments, a "Jump to latest ↓" pill, interim/final styling, and empty-state
copy. Self-contained, no new deps (success criterion 4).

**Data flow:** `useTranscriptions()` (new array each token update) → effect sticks
scroll if `atBottom` → scroll listener recomputes `atBottom` → pill visibility.

### Analog — self (the flat `<ul>` to wrap) — Transcript.tsx:15-38

```tsx
// web/app/Transcript.tsx:15-38 (today: no scroll container, no atBottom, no interim styling)
export default function Transcript() {
  const segments = useTranscriptions();
  return (
    <ul style={{ listStyle:"none", padding:0, textAlign:"left" }}>
      {segments.map((segment) => {
        const identity = segment.participantInfo.identity;
        const isUser = identity.startsWith(USER_IDENTITY_PREFIX);
        return (
          <li key={segment.streamInfo.id} data-from={isUser ? "user" : "agent"}
            style={{ textAlign: isUser ? "right" : "left",
                     color: isUser ? "#e6edf3" : "#58a6ff", margin:"0.25rem 0" }}>
            <strong>{isUser ? "You" : "Agent"}:</strong> {segment.text}
          </li>
        );
      })}
    </ul>
  );
}
```

The two-sided split (user right `#e6edf3`, agent left `#58a6ff`) and the
`USER_IDENTITY_PREFIX = "user-"` attribution (Transcript.tsx:7) are **preserved**.
Wrap the `<ul>` in a `overflow-y:auto` container with bounded height
(`flex:1` + `min-height:0` in a flex column — RESEARCH §4: the `<ul>` is unbounded
today so no scroll exists).

### Pattern to add (RESEARCH §4)

```tsx
const containerRef = useRef<HTMLDivElement>(null);
const atBottomRef = useRef(true);            // ref, not state — avoid re-render churn
const [showJump, setShowJump] = useState(false);
const THRESHOLD = 32;                        // px

function onScroll() {
  const el = containerRef.current!;
  atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= THRESHOLD;
  setShowJump(!atBottomRef.current && segments.length > 0);
}
useEffect(() => {                            // stick only if atBottom
  const el = containerRef.current;
  if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;   // instant, no thrash
}, [segments]);
```

- **Instant `scrollTop = scrollHeight`** for streaming updates; reserve
  `scrollTo({behavior:"smooth"})` for the explicit Jump-pill click.
- **"Jump to latest ↓" pill:** accent `#58a6ff`, bottom-center, shows when
  `!atBottom`; click → smooth-scroll + `atBottomRef = true`.
- **Interim vs final:** finals full-opacity, interim `0.7`/italic. The current code
  ignores the in-progress flag — verify the exact field on `TextStreamData`
  (`segment.streamInfo`/attributes) in `@livekit/components-react@2.9.21` at
  implementation (RESEARCH §4, §9).
- **Empty state:** heading "Start talking" + body "Say hello, ask a question, or
  describe what you want to practice." (muted, centered — UI-SPEC copy).

### Analog (effect discipline) — KbPanel's useEffect-on-data — KbPanel.tsx:86-97
The stick effect keyed on `[segments]` mirrors KbPanel's `[attributes]` effect shape.

### Invariants
- Token streaming MUST NOT animate (instant render) regardless of motion prefs.
- Guard the programmatic `scrollTop` write against falsely flipping `atBottom`
  (threshold ≥ a few px — RESEARCH §4 React 19 gotcha).

---

## Files 10-13 — `PersonaPanel.tsx` / `ModelPanel.tsx` / `InterviewPanel.tsx` / `KbPanel.tsx` (MODIFY)

**Role:** Import shared styles from `ui/tokens.ts` (remove the copy-pasted
`panelStyle`/`labelStyle`/`inputStyle`/`STATUS_*` blocks); **optionally** accept
lifted `value` + `onChange` so the setup screen and the settings drawer can both
render them (controlled-component refactor). Keep their RPC/`sendFile` apply logic
for the live-tweak (drawer) path.

**Data flow:** (drawer path, unchanged) local state → `performRpc`/`sendFile` →
agent. (setup path, if controlled) lifted state ← `onChange`.

### Analog — self; the move is mechanical

```tsx
// web/app/ModelPanel.tsx:35-62 → DELETE, replace with:
import { panelStyle, labelStyle, inputStyle, STATUS_LABEL, STATUS_COLOR } from "./ui/tokens";
```

The **agent-mirrored constants STAY** (byte-identical, RESEARCH §1.3):

```tsx
// web/app/ModelPanel.tsx:10-17 (FROZEN — do not move into presentational tokens)
const CHOICES = ["fast", "better"] as const;
const CHOICE_LABEL: Record<(typeof CHOICES)[number], string> = {
  fast: "Fast (snappier)", better: "Better (more thoughtful)",
};
```

```tsx
// web/app/PersonaPanel.tsx:11-31 (FROZEN — VOICE_IDS, enums, DEFAULT_PERSONA)
const VOICE_IDS = [ "af_heart", "af_bella", ... ] as const;   // mirrors agent/persona.py
const DEFAULT_PERSONA = { role_text:"", display_name:"Cybersecurity Trainer",
  difficulty:"intermediate", verbosity:"balanced", correction:"gentle", voice_id:"af_bella" };
```

```tsx
// web/app/InterviewPanel.tsx:9-18 (FROZEN — modes/roles mirror agent/interview.py)
const MODE_LEARN = "learn"; const MODE_INTERVIEW = "interview";
const ROLES = ["soc_analyst", "security_engineer", "grc"] as const;
```

```tsx
// web/app/KbPanel.tsx:10-17 (FROZEN — topic/attribute/size mirror agent/main.py)
const KB_UPLOAD_TOPIC = "kb.upload"; const KB_STATE_ATTRIBUTE = "kb.state";
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
```

**KbPanel extra (setup path):** for the setup screen, files must be **queued** in
`sessionConfig.kbFiles` (no room yet) and uploaded by `ApplySetupOnConnect` after
connect (File 5). The drawer path keeps the immediate `sendFile`. KbPanel's
`STATUS_LABEL`/`STATUS_COLOR` are a **different union** (`KbStatus`, not
`ApplyState`) — leave its status maps in place or give them their own token export;
do not merge with the `ApplyState` maps.

### Invariants
- Refactor is **presentational only** — not one agent-mirrored key dropped/renamed
  (RESEARCH §1.3, §7.4; UI-SPEC token-module contract).
- RPC/`sendFile` apply logic preserved for the live-tweak drawer path.

---

## File 14 — `web/app/AgentStatePill.tsx` (MODIFY → token import only)

**Role:** Token import only; **colors unchanged** (RESEARCH §8, UI-SPEC §Screen B).

### Analog — self — AgentStatePill.tsx:7-13

```tsx
// web/app/AgentStatePill.tsx:7-13 (these state colors are LOCKED — only their source moves)
const STATE_COLORS: Record<string, string> = {
  initializing: "#8b949e", idle: "#8b949e", listening: "#3fb950",
  thinking: "#d29922", speaking: "#58a6ff",
};
```

Optionally source `#0b0f14`/font/radius from tokens; the per-state colors stay
byte-identical. Add the 150ms `background-color` transition via a globals.css class
(UI-SPEC Animation Contract) — but keep the color values.

### Invariants
- Colors unchanged; `useVoiceAssistant().state` binding unchanged.

---

## File 15 — `web/app/page.tsx` (MODIFY → drop inline wordmark)

**Role:** Drop the inline `<h1>Adept</h1>` (the wordmark moves into SetupScreen);
keep `<main>`/`<VoiceRoom/>` or fold into the shell.

### Analog — self — page.tsx:1-10

```tsx
// web/app/page.tsx:1-10 (today)
export default function Home() {
  return (
    <main style={{ textAlign: "center" }}>
      <h1 style={{ margin: "0 0 1rem" }}>Adept</h1>   // ← remove (moves to SetupScreen Display wordmark)
      <VoiceRoom />
    </main>
  );
}
```

The "Adept" wordmark becomes the Display-typography heading at the top of
SetupScreen (UI-SPEC Typography + Copywriting). `<main>` may need its centering
relaxed so the talking screen can fill (coordinate with File 16).

---

## File 16 — `web/app/layout.tsx` (MODIFY → import CSS, relax body centering)

**Role:** `import "./globals.css";`; relax the body flex-center so the two
full-screen layouts own their own centering. **Do NOT move the importmap.**

### Analog — self — layout.tsx:14-43

```tsx
// web/app/layout.tsx:14-30 (the importmap — MUST stay in <head> before any avatar module — DO NOT MOVE)
const AVATAR_IMPORTMAP = JSON.stringify({ imports: {
  three: "/vendor/three/three.module.js",
  "three/addons/": "/vendor/three/addons/",
  talkinghead: "/vendor/talkinghead/talkinghead.mjs",
}});
// ...<head><script type="importmap" dangerouslySetInnerHTML={{__html: AVATAR_IMPORTMAP}} /></head>
```

```tsx
// web/app/layout.tsx:31-42 (the body flex-center to relax)
<body style={{
  fontFamily: "system-ui, sans-serif", margin: 0, minHeight: "100vh",
  display: "flex", alignItems: "center", justifyContent: "center",   // ← setup centers; talking wants full-height column
  background: "#0b0f14", color: "#e6edf3",
}}>
```

Add `import "./globals.css";` at the top. The body is a global flex-center today;
the setup screen still wants centering but the talking screen wants a full-height
column (RESEARCH §1.4, §9 two-layout centering). Plan the body style so setup
centers and talking fills — e.g. body becomes a plain full-height block and each
screen owns its layout.

### Invariants (RESEARCH §7.3)
- Importmap stays emitted in `<head>` **before** any avatar module — untouched.
- `font-family: system-ui` and the dark bg/text unchanged.

---

## Cross-cutting invariants (RESEARCH §7 — must not break)

1. **Zero server diff** — `git diff -- agent/ stt/ tts/ docker-compose.yml` empty.
   No RPC method / payload-key / stream-topic / attribute changes; only *when* the
   client fires them moves (Files 5, 10-13).
2. **Voice-only byte-for-byte** — avatar stays dynamic-imported (`ssr:false`),
   absent from the voice-only bundle. **No new runtime dependency** (kills any
   framework/motion-lib). `tokens.ts` + `globals.css` add zero JS deps.
3. **`layout.tsx` importmap** in `<head>` before any avatar module — untouched (File 16).
4. **Agent-mirrored constants** byte-identical after the de-dup refactor (Files 10-13).
5. **Single user gesture** for entry (mic-permission + autoplay-unlock + connect) —
   the new "Start session" click must still end in `setToken` → room mounts (Files 3, 8).
6. **Persona prompt unchanged** (server-side; UI can't touch beyond `role_text`).
7. **Strict-Mode double-effect** — the apply-once and stick-scroll effects need ref
   guards (Files 5, 9).

---

## Suggested slice boundaries (RESEARCH §8 grouping)

- **13-01 (foundation/de-dup):** File 1 `ui/tokens.ts`, File 2 `globals.css`,
  Files 10-14 token-import refactor, File 16 layout (CSS import + body relax),
  File 15 page. Presentational-only; agent-mirrored constants frozen. Verifiable:
  no visual regression, no server diff, constants byte-identical.
- **13-02 (setup-before-connect):** File 3 `SetupScreen`, File 4 `MicPicker`,
  File 5 `ApplySetupOnConnect`, File 8 `VoiceRoom` shell refactor (lift
  `sessionConfig`, phase state, cross-fade). The KEY TENSION resolution.
- **13-03 (talking polish):** File 6 `TalkingScreen`, File 7 `SettingsDrawer`,
  File 9 `Transcript` smart auto-scroll + jump pill + interim styling + empty state.

---

## PATTERN MAPPING COMPLETE

**Created:** `.planning/phases/13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis/13-PATTERNS.md`
