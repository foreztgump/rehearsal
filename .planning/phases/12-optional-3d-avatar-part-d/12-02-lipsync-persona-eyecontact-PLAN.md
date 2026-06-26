---
plan: 12-02
title: Path-A audio-driven lip-sync on the inbound Kokoro track + barge-in on user-speech-start + eye-contact/mood + client persona→GLB map with a vendored default GLB + AVTR-07 blendshape/license attestation
phase: 12
wave: 2
depends_on: [12-01]
autonomous: false
requirements: [AVTR-02, AVTR-03, AVTR-04, AVTR-06, AVTR-07]
files_modified:
  - web/public/avatars/cyber-trainer.glb
  - web/app/avatarConfig.ts
  - web/app/AvatarStage.tsx
  - web/app/VoiceRoom.tsx
  - .planning/phases/12-optional-3d-avatar-part-d/12-AVATAR-VERIFY.md
---

# Plan 12-02: Lip-sync + persona + eye-contact

## User Story

**As** a user in Avatar mode, **I want** the talking head to load my persona's avatar, lip-sync
to the agent's spoken Kokoro audio in real time, hold eye contact while it speaks and listens,
and cut off instantly the moment I start talking, **so that** the avatar feels like a live
conversational partner — all without changing anything on the server.

## Context

This is the **behaviour half** of Phase 12, built on the 12-01 scaffold. It loads the default
GLB into the existing `AvatarStage`, taps the **inbound Kokoro WebRTC audio** (the agent's
spoken track) into TalkingHead's streaming AudioWorklet for **Path-A audio-driven** visemes,
reuses the existing user-speech-start interrupt for barge-in, drives eye-contact + `setMood`
off the agent state, and adds a **client-side** persona→GLB+mood map. It also ships the
AVTR-07 attestation. Still ZERO server diff.

### Path-A mechanism (audio-driven, no timestamps)
- TalkingHead exposes a streaming mode (`streamStart` → `streamAudio` → `streamInterrupt`)
  backed by an AudioWorklet. **Path-A = feed the inbound agent audio as PCM chunks with NO
  viseme/word timestamps**, letting the worklet drive mouth open/close from audio energy
  (`waitForAudioChunks`/energy path), or use TalkingHead's audio-only viseme estimation. NO
  transcription, NO word timing, NO server change.
- The inbound source is the agent participant's audio track from LiveKit. The existing
  `<RoomAudioRenderer/>` keeps playing it normally to the speakers (AVTR-02 "audio plays
  normally in parallel"). The avatar tap is a SECOND, read-only consumer of the same track —
  resolve via a Web Audio `MediaStreamAudioSourceNode` over the remote agent track's
  `MediaStream`, feeding chunks to `streamAudio` (or via TalkingHead's documented external-audio
  worklet). Do not mute or reroute the primary playout.
- **Exact API selection is an execution decision** — confirm against the vendored TalkingHead
  version whether energy-only visemes are driven by `streamStart({lipsyncType, waitForAudioChunks})`
  + raw `streamAudio({audio})`, or by the `HeadAudio`/`AudioMixer` external-input path; pick the
  one that needs NO timestamps. Record the choice as a deviation note.

## Files & responsibilities

### `web/public/avatars/cyber-trainer.glb` (NEW asset, AVTR-06/07)
- A Ready Player Me half-body avatar exported with `morphTargets=ARKit,Oculus`, downloaded and
  **Meshopt/Draco-compressed** (gltf-transform/`gltfpack`) for ~30fps web rendering (AVTR-08).
- BEFORE wiring lip-sync, verify the GLB has a Mixamo-compatible rig + ARKit(52) + Oculus(15)
  viseme blendshapes, and confirm its license permits personal/internal use (AVTR-07). Capture
  the blendshape inventory + license in `12-AVATAR-VERIFY.md`.

### `web/app/avatarConfig.ts` (EDIT)
- Add `DEFAULT_AVATAR = { glb: "/avatars/cyber-trainer.glb", mood: "neutral", body: "F"|"M" }`.
- Add `PERSONA_AVATARS: Record<string,{glb,mood,body}>` keyed by persona `display_name` (the
  client seam in `PersonaPanel.tsx`), with the cyber-trainer default. `avatarForPersona(name)`
  returns the match or `DEFAULT_AVATAR` (so Avatar mode always works out of the box, AVTR-06).
- **Client-side only** — no server field, honoring the isolation gate. Voice (`voice_id`) is
  unchanged and stays owned by persona state.

### `web/app/AvatarStage.tsx` (EDIT)
- On mount (after the 12-01 construct): `await head.showAvatar({ url, body, ... })` for the
  active persona's GLB; show the 12-01 loading state during fetch/decode; keep the try/catch
  degrade (AVTR-08).
- **Lip-sync (AVTR-02):** subscribe to the agent's inbound audio track (LiveKit room context /
  `useVoiceAssistant().agent` or the agent participant's audio publication), build the Web Audio
  source, `streamStart(...)` once, and pump chunks via the chosen Path-A call while the agent is
  speaking. Tear all of this down in the effect cleanup (AudioWorklet + source node closed) so
  toggling Avatar OFF leaves nothing running (extends 12-01 teardown).
- **Eye contact + mood (AVTR-04):** drive off `useVoiceAssistant().state` — call
  `makeEyeContact`/`lookAtCamera` so the avatar holds eye contact while BOTH speaking and
  listening; apply `setMood(personaMood)` on load and on persona change.
- **Barge-in (AVTR-03):** on the existing user-speech-start signal (the same interrupt the call
  already uses — surfaced via LiveKit; reuse it, do NOT add a second VAD), call
  `streamInterrupt()` to stop avatar audio + lip-sync instantly.
- Framing stays `cameraView` upper/head from 12-01 (AVTR-05).

### `web/app/VoiceRoom.tsx` (EDIT)
- Pass the active persona's `display_name` (lifted from `PersonaPanel` state, or read from the
  same default seed) into `<AvatarStage persona=.../>` so the stage can resolve the GLB+mood.
  Keep the change minimal — if persona state isn't already lifted, pass the default name and
  note the persona-change reactivity as the wiring point. No server calls.

### `12-AVATAR-VERIFY.md` (NEW)
- `status: pending-operator`, `requirement_ids: [AVTR-01..08]`. Browser/operator gates (the
  sandbox has no WebGL/browser): toggle default-OFF; Avatar-ON loads the GLB + lip-syncs to
  Kokoro audio; barge-in cuts the avatar instantly on user speech; eye contact while
  speaking+listening; persona mood applied; framing upper/head; ~30fps; graceful degrade on weak
  device; voice-only ON↔OFF leaves no residual (perf identical). Plus the **AVTR-07
  attestation** (blendshape inventory + license) and the **isolation gate** result
  (`git diff -- agent/ stt/ tts/ docker-compose.yml` empty).

## Step-by-step

1. Acquire + verify + compress the default GLB; record AVTR-07 attestation facts.
2. Extend `avatarConfig.ts` with `DEFAULT_AVATAR` + `PERSONA_AVATARS` + `avatarForPersona`.
3. `AvatarStage`: `showAvatar`, then Path-A lip-sync tap on the inbound agent track, eye-contact
   + mood off agent state, barge-in via the existing interrupt; extend teardown.
4. `VoiceRoom`: pass persona name into `<AvatarStage/>`.
5. Write `12-AVATAR-VERIFY.md`.
6. `npm run build`; run the isolation gate `git diff -- agent/ stt/ tts/ docker-compose.yml`
   (MUST be empty).

## Acceptance criteria

- [ ] `web/` builds; TypeScript clean.
- [ ] Default GLB loads in Avatar mode; `avatarForPersona` returns the default for the
      cyber-trainer persona so Avatar works out of the box (AVTR-06).
- [ ] Lip-sync is Path-A: inbound Kokoro audio tapped into the TalkingHead AudioWorklet with NO
      timestamps/transcription; the primary `<RoomAudioRenderer/>` playout is untouched (AVTR-02).
- [ ] Barge-in calls `streamInterrupt()` on the EXISTING user-speech-start interrupt — no second
      VAD (AVTR-03).
- [ ] Eye contact held while speaking AND listening; `setMood` applied (AVTR-04); framing
      upper/head (AVTR-05).
- [ ] **Isolation gate:** `git diff -- agent/ stt/ tts/ docker-compose.yml` is EMPTY; no Compose
      service / server RPC / server env added.
- [ ] AVTR-07 attestation (Mixamo rig + ARKit-52 + Oculus-15 blendshapes + license) recorded in
      `12-AVATAR-VERIFY.md`; GLB is Meshopt/Draco-compressed (AVTR-08).
- [ ] Avatar-mode teardown (toggle OFF) closes the AudioWorklet + source node + disposes the
      avatar — nothing left running.

## Notes / risks

- **Sandbox limit:** no browser/WebGL/audio — `npm run build` + the isolation `git diff` are the
  only sandbox-checkable gates here; rendering, lip-sync, barge-in, fps, and degrade are
  operator/browser gates in `12-AVATAR-VERIFY.md`.
- **Track-tap correctness** is the main risk: the avatar must be a read-only second consumer of
  the inbound agent audio — never mute, reroute, or delay the real playout. If LiveKit only
  exposes one consumable MediaStreamTrack cleanly, clone it for the Web Audio source.
- **Path-A API selection** depends on the vendored TalkingHead version — pick the timestamp-free
  energy path and record it; do not pull in word timings (that would be Path-B and could imply
  server coupling).
- **Barge-in source:** reuse whatever already drives the agent interrupt today; do not introduce
  a client-side VAD (AVTR-03 explicit).
