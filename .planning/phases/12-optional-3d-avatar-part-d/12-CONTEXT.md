---
phase: 12
phase_name: optional-3d-avatar-part-d
mode: ui
depends_on: [11]
requirements: [AVTR-01, AVTR-02, AVTR-03, AVTR-04, AVTR-05, AVTR-06, AVTR-07, AVTR-08]
plans:
  - 12-01-avatar-scaffold-isolation
  - 12-02-lipsync-persona-eyecontact
---

# Phase 12 — Optional 3D Avatar (Part D, frontend-only): CONTEXT

## Goal (verbatim)

Add an OPTIONAL, default-OFF client-side 3D talking-head avatar (met4citizen/TalkingHead,
Three.js/WebGL) with Path-A audio-driven lip-sync on the inbound Kokoro WebRTC audio, barge-in
via the existing LiveKit interrupt, eye-contact/mood/framing, and a client-side persona↔GLB
mapping — strictly frontend-only with ZERO server VRAM cost and an auditable empty server diff.
This phase MUST NOT change the server pipeline (Parts A/B/C) in any way.

## Requirements owned

- **AVTR-01** — "Voice only / Avatar" toggle (default **Voice only**) renders the TalkingHead
  avatar inside the existing voice UI; OFF fully restores voice-only with NO residual overhead
  or running avatar code (dynamic-imported; no avatar JS in the voice-only bundle).
- **AVTR-02** — Lip-sync is **Path-A audio-driven** — LiveKit's INBOUND Kokoro WebRTC audio is
  routed through TalkingHead's HeadAudio worklet for real-time visemes — NO server change, no
  transcription, no timestamps (audio plays normally in parallel).
- **AVTR-03** — Barge-in reuses the existing LiveKit user-speech-start interrupt to stop avatar
  audio + lip-sync instantly — no second VAD.
- **AVTR-04** — Eye contact while speaking AND listening (`makeEyeContact`, eye-contact factors,
  `lookAtCamera`), and persona mood via `setMood`.
- **AVTR-05** — Interview-appropriate framing (`cameraView` "upper" or "head").
- **AVTR-06** — Each persona MAY specify an avatar (GLB url) + mood, reusing its existing Kokoro
  voice; the default cyber-trainer persona ships a default avatar so Avatar mode works out of
  the box. **Client-side mapping only** (isolation gate).
- **AVTR-07** — Each GLB is verified to have a Mixamo-compatible rig + ARKit(52) + Oculus(15)
  viseme blend shapes before lip-sync is wired, and its license is confirmed to permit the
  intended (personal/internal) use.
- **AVTR-08** — Rendering is client-side WebGL with ZERO server VRAM/GPU cost; targets ~30fps
  with Meshopt/Draco-compressed GLBs and degrades gracefully (the toggle is the escape hatch).

## Discuss decisions (all 4 grey areas — "Accept all (Recommended)")

### Area 1 — TalkingHead + three.js delivery
- **Vendor locally under `web/public`** — copy the TalkingHead module + a pinned three.js build
  into `web/public`, loaded via a same-origin importmap. Keeps the install fully offline /
  local-first (consistent with Phase 11's offline posture and the LAN-only deployment). NO CDN
  runtime dependency.
- The library is **dynamic-imported** only when Avatar mode turns ON, so the voice-only bundle
  is byte-for-byte the pre-avatar build (AVTR-01).

### Area 2 — Default avatar GLB (AVTR-06/07)
- **Ready Player Me half-body, vendored + documented.** Use an RPM avatar exported with the
  `morphTargets=ARKit,Oculus` query (TalkingHead's documented path), download the GLB,
  Meshopt/Draco-compress it into `web/public/avatars/`, and record the blendshape inventory +
  license in the AVTR-07 verification note. Ships so the default cyber-trainer persona's Avatar
  mode works out of the box.

### Area 3 — Persona↔avatar map (isolation gate)
- **Pure client-side map in `web/`** — a client-only constant (persona display_name/id →
  `{glb, mood}`) with a default fallback avatar. ZERO change to `agent/persona.py` or the
  `persona.update` RPC. Reuses the existing Kokoro `voice_id` already in persona state.
- This honors the **empty-server-diff isolation gate**:
  `git diff -- agent/ stt/ tts/ docker-compose.yml` MUST be empty for this phase.

### Area 4 — Plan slicing
- **12-01 — scaffold + isolation:** vendored lib + dynamic-imported Avatar canvas + Voice-only/
  Avatar toggle + clean unmount (canvas + AudioWorklet teardown) + `cameraView` framing
  (AVTR-01, AVTR-05, AVTR-08, isolation gate).
- **12-02 — lip-sync + persona + eye-contact:** Path-A HeadAudio lip-sync on the inbound Kokoro
  track + barge-in on user-speech-start + eye-contact/mood + client persona→GLB map + AVTR-07
  GLB verification note (AVTR-02, AVTR-03, AVTR-04, AVTR-06, AVTR-07).

## Hard constraints / invariants

- **ISOLATION GATE (auditable):** the avatar adds ZERO files under `agent/`, `stt/`, `tts/`,
  ZERO Compose services, ZERO server RPC/byte-stream/attributes, ZERO server env.
  `git diff -- agent/ stt/ tts/ docker-compose.yml` is EMPTY for this phase; server VRAM is
  identical avatar ON vs OFF.
- **Voice-only is the pre-avatar build.** Avatar code is dynamic-imported; turning Avatar OFF
  fully unmounts the canvas + AudioWorklet — zero residual overhead, no avatar JS in the
  voice-only bundle.
- **Path-A only.** Lip-sync is energy/audio-driven off the inbound Kokoro WebRTC track via the
  HeadAudio worklet; no transcription, no word timestamps, no second VAD. Audio still plays
  normally through the existing `<RoomAudioRenderer />`.
- **Reuse existing seams** — `useVoiceAssistant()` agent state (listening/speaking) for
  eye-contact + the existing user-speech-start interrupt for barge-in; the Kokoro `voice_id`
  already in persona state. No new server-facing protocol.
- **Local-first / offline** — TalkingHead + three.js + the default GLB are vendored under
  `web/public`; no CDN/WAN runtime dependency (consistent with Phase 11).

## Grounding (current frontend)

- `web/app/VoiceRoom.tsx` — single-gesture entry; renders `<LiveKitRoom audio video={false}>`
  with `<RoomAudioRenderer/>`, `<StartAudio/>`, `<AgentStatePill/>`, and the panel row
  (Persona/Interview/Model/Kb/Transcript). The Avatar canvas + toggle mount here, inside
  `<LiveKitRoom>` for room context.
- `web/app/AgentStatePill.tsx` — `useVoiceAssistant().state` ∈ {initializing, idle, listening,
  thinking, speaking}; speaking/listening drive eye-contact, speaking drives lip-sync gating.
- `web/app/PersonaPanel.tsx` — client persona state incl. `display_name` + `voice_id` (the
  duplication seam mirroring `agent/persona.py`). The client persona→GLB map keys off this; the
  default seed is "Cybersecurity Trainer" / `af_bella`.
- `web/package.json` — deps: `@livekit/components-react` 2.9.21, `livekit-client` 2.20.0,
  Next 16, React 19. three.js + TalkingHead are NOT added as npm deps — vendored in
  `web/public` and loaded via importmap (Area 1).
- `web/next.config.mjs` — `output: "standalone"`; static assets in `web/public` ship in the
  image.
- No avatar/GLB/TalkingHead references exist anywhere yet (grep clean) — greenfield in `web/`.

## Verification shape

- **12-AVATAR-VERIFY.md** — operator/browser gate (a real Chromium session; the sandbox has no
  WebGL/browser): toggle default-OFF, Avatar-ON renders + lip-syncs to Kokoro audio, barge-in
  cuts avatar instantly, eye-contact/mood/framing, ~30fps, graceful degrade. Plus the AVTR-07
  GLB-blendshape+license attestation.
- **Isolation gate is sandbox-checkable** (and MUST be in 12-02 acceptance):
  `git diff -- agent/ stt/ tts/ docker-compose.yml` empty across the phase.
