# Phase 13: UI/UX Overhaul — Landing/Setup Screen & Talking Screen Polish - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

A frontend-only (mode `ui`) two-screen experience for Adept:

1. **Landing / Setup screen** — the app loads here first. The user configures
   *everything* for the session (persona, knowledge base, response model, mic
   selection, avatar on/off) **before** any connection to the agent. Only an
   explicit "Connect / Start" action joins the LiveKit room.
2. **Talking screen** — the live conversation view. The transcript
   **auto-scrolls** to keep the newest line in view. Agent-state, transcript,
   avatar (when on), and controls are laid out cleanly.

The whole app is restyled to be **simple but elegant, clean, animated, and
well-organized** — easy to use, easy to navigate, polished and well-crafted
throughout.

**Isolation constraint (carried from v1.1):** This phase is frontend-only and
MUST NOT change the server pipeline (agent / STT / LLM / TTS) or the avatar's
Path-A audio-driven lip-sync contract. Voice-only mode must stay
byte-for-byte identical in behavior. The persona prompt is unchanged.

</domain>

<decisions>
## Implementation Decisions

### Setup Screen Layout
- **D-01:** The landing/setup screen is a **single elegant panel** — all config
  (persona, knowledge base, model, mic, avatar) grouped on one organized screen
  with a prominent "Connect / Start" action. NOT a multi-step wizard, NOT a card
  dashboard. Fastest path from load → talking; sections can be expanded to
  customize.
- **D-02:** **Sensible defaults, one click to start.** Default persona
  (Cybersecurity Trainer), Fast model, default mic, avatar OFF are all
  pre-selected so a first-time user can hit Start immediately. No required
  pre-connect choices gate the Start button; customization is optional.

### Visual / UX Direction (vision — the agent has implementation latitude)
- **D-03:** Simple but elegant, clean, animated, well-organized. Tasteful,
  performant transitions between states and screens (no janky/distracting
  motion). Intuitive, easy-to-navigate, polished/well-crafted feel throughout.
  Be creative — the user wants it to "look well done."

### Talking Screen
- **D-04:** The live transcript **auto-scrolls** to the latest line. (Per the
  ROADMAP success criteria: stick-to-bottom while the user is at the bottom;
  do NOT yank the view when the user has scrolled up to read history.)

### the agent's Discretion
The user explicitly kept this discussion light — the goal was to confirm the
full spec is captured, not to over-specify. Downstream agents (researcher,
planner, gsd-ui-researcher) have latitude on:
- The concrete styling approach (refine the existing inline-styled dark theme
  vs. introduce CSS modules / a utility framework) and the animation mechanism
  (CSS transitions vs. a motion library) — choose what best delivers D-03
  without violating the isolation constraint or regressing bundle weight for
  voice-only.
- The exact talking-screen arrangement of agent-state pill, transcript, avatar,
  and controls.
- Navigation pattern between setup ↔ talking (must be reversible without
  breaking the live room — ROADMAP success criterion 3).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & success criteria
- `.planning/ROADMAP.md` §"Phase 13: UI/UX Overhaul" (lines ~134–148) — goal +
  the 5 success criteria that define DONE (landing-before-connect, clean/
  animated/organized design, reversible navigation, smart auto-scroll,
  responsive + accessible + no console errors).
- `.planning/REQUIREMENTS.md` — v1.1 scope note (frontend-only isolation,
  persona is the sole guardrail). Phase 13 has no dedicated REQ-IDs (success is
  defined by the ROADMAP criteria above); SESS/REL/PERF requirements belong to
  Phase 14, not here.

### Current UI to overhaul (the files this phase touches)
- `web/app/page.tsx` — current root (just `<h1>Adept</h1>` + `<VoiceRoom>`).
- `web/app/VoiceRoom.tsx` — **the central file.** Today the "Start talking"
  button connects to LiveKit immediately, then renders all panels inside
  `<LiveKitRoom>`. This is where the setup-screen-before-connect split lives.
- `web/app/layout.tsx` — global body styles + the avatar importmap (do not
  break the importmap-before-avatar-module ordering).
- `web/app/PersonaPanel.tsx`, `web/app/ModelPanel.tsx`, `web/app/KbPanel.tsx`,
  `web/app/InterviewPanel.tsx` — existing config panels (RPC-on-apply pattern).
- `web/app/Transcript.tsx` — the transcript to add smart auto-scroll to.
- `web/app/AgentStatePill.tsx`, `web/app/AvatarStage.tsx`,
  `web/app/avatarConfig.ts` — talking-screen elements (avatar is dynamic-import,
  default-off; preserve AVTR-01 isolation).
- `web/package.json` — deps are LiveKit + Next 16 + React 19 only; no CSS
  framework or animation lib currently. Adding one is a discretion call (D-03).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Shared inline-style tokens:** `panelStyle` / `labelStyle` / `inputStyle` and
  the `STATUS_LABEL` / `STATUS_COLOR` "applying…→applied" pattern are duplicated
  across PersonaPanel, ModelPanel, KbPanel. The dark palette
  (`#0b0f14` bg, `#0d1117` panel, `#30363d` border, `#58a6ff` accent, `#3fb950`
  action, `#8b949e` muted, `#f85149` error) is the de-facto design system to
  refine into the new look.
- **Avatar toggle pattern:** the segmented "Voice only / Avatar" control in
  `VoiceRoom.tsx:103-134` is a reusable UI idiom.

### Established Patterns
- **Config-applies-to-a-LIVE-agent (KEY TENSION):** today PersonaPanel /
  ModelPanel send `persona.update` / `model.update` RPCs, and KbPanel uploads
  files as a LiveKit **byte stream that rides the open room connection**
  (`room.localParticipant.sendFile`). All three require an *already-connected*
  agent. **The setup-before-connect goal conflicts with this** — research MUST
  resolve how pre-connect config is held and applied (e.g., hold all choices in
  client state on the setup screen, then connect and apply on entry; KB needs
  the room, so its upload likely fires right after connect). This is the single
  highest-risk implementation decision in the phase.
- **Single user gesture for entry:** the current Start click does mic-permission
  + autoplay-unlock + connect in one gesture. Keep that constraint when
  designing the new Start button.
- **Duplication seams:** PersonaPanel `VOICE_IDS` and ModelPanel `CHOICES` MUST
  stay mirrored with `agent/persona.py` / `agent/main.py` (no get-RPC). A UI
  refactor must not silently drop or rename these.

### Integration Points
- `<LiveKitRoom>` wraps everything that needs room context; the setup screen
  lives *outside* it (no room yet), the talking screen *inside* it.
- Avatar mount is gated on `avatarOn` and dynamic-imported (ssr:false) — keep it
  absent from the voice-only bundle (AVTR-01 isolation gate).

</code_context>

<specifics>
## Specific Ideas

Direct from the user's phase request (verbatim intent):
- "load the first landing screen where user can set everything up there before
  connect to the agent"
- "then at the talking screen, the transcribe should auto scroll"
- "Simple but elegant. Clean and animated. It should be organized."
- "easy to use and navigate", "everything should look well done", "be creative"

The user kept the discussion intentionally light, confirming the spec above is
complete rather than over-specifying — trusting craft latitude on execution.

</specifics>

<deferred>
## Deferred Ideas

- **Session lifecycle controls (new / reset / end), transcript export,
  mic-denial prompt, garbled-STT reprompt** — these are **Phase 14** (SESS-01..04,
  REL-01/02) and explicitly out of Phase 13. Phase 13 builds the UI *surface*
  they will later plug into, but does not implement the session/teardown logic.
- **Final latency tuning (PERF-04 P50<1.0s)** — Phase 14.

</deferred>

---

*Phase: 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis*
*Context gathered: 2026-06-26*
