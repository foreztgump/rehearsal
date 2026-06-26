---
phase: 12-optional-3d-avatar-part-d
plan: 02
subsystem: ui
tags: [talkinghead, threejs, webgl, webrtc, livekit, lipsync, audioworklet, draco, glb, kokoro]

requires:
  - phase: 12-01-avatar-scaffold-isolation
    provides: vendored TalkingHead 1.7 + three r0.180.0 + importmap + dynamic-imported AvatarStage scaffold + Voice-only/Avatar toggle
provides:
  - Default avatar asset cyber-trainer.glb (Draco+WebP RPM half-body, AVTR-06/07)
  - Path-A audio-driven lip-sync on the inbound Kokoro WebRTC track (AVTR-02)
  - Barge-in via the existing LiveKit user-speech-start interrupt (AVTR-03)
  - Eye-contact + persona mood off the agent state (AVTR-04)
  - Client-only persona->GLB map (avatarForPersona) honoring the isolation gate (AVTR-06)
  - AVTR-07 blendshape/rig/license attestation + operator verification doc
affects: []

tech-stack:
  added:
    - "gltf-transform (build-time GLB Draco+WebP compression)"
    - "vendored three r0.180.0 Draco decoder (offline KHR_draco_mesh_compression)"
    - "TalkingHead playback-worklet.js (streaming Path-A worklet)"
  patterns:
    - "Path-A energy lip-sync: streamStart({gain:0}) + streamAudio(Float32) energy path, NO timestamps"
    - "Read-only second consumer of the inbound LiveKit track via a CLONED MediaStreamTrack"
    - "Client-only persona->asset map keyed by display_name (zero server diff)"

key-files:
  created:
    - web/public/avatars/cyber-trainer.glb
    - web/public/vendor/talkinghead/playback-worklet.js
    - web/public/vendor/three/addons/libs/draco/draco_decoder.js
    - web/public/vendor/three/addons/libs/draco/draco_wasm_wrapper.js
    - web/public/vendor/three/addons/libs/draco/draco_decoder.wasm
    - .planning/phases/12-optional-3d-avatar-part-d/12-AVATAR-VERIFY.md
  modified:
    - web/app/avatarConfig.ts
    - web/app/AvatarStage.tsx
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Path-A = streamStart({gain:0, waitForAudioChunks:false}) + streamAudio(Float32 frames); gain:0 mutes the avatar's own playout so it never double-plays over <RoomAudioRenderer/>, while the analyzer still drives energy visemes — no timestamps/transcription"
  - "Tap the inbound agent track by CLONING the MediaStreamTrack (read-only second consumer); capture PCM with a ScriptProcessorNode on head.audioCtx (no extra worklet file)"
  - "Draco (not Meshopt) compression: TalkingHead 1.7's GLTFLoader wires DRACOLoader, not setMeshoptDecoder; vendored the r0.180.0 Draco decoder locally + set dracoDecoderPath to a same-origin path (library default is the gstatic CDN, which breaks offline)"
  - "Barge-in maps agent state 'listening' -> streamInterrupt() (the existing LiveKit signal); no second client VAD"
  - "Persona->GLB map is a client-only constant keyed by display_name; VoiceRoom passes a fixed default personaName (PersonaPanel state not yet lifted) — Avatar works out of the box for the seed persona"

patterns-established:
  - "Energy/audio-driven viseme lip-sync with muted avatar playout (gain:0) as the double-audio mitigation"
  - "Vendoring runtime decoders (Draco) + worklets same-origin to preserve the offline/LAN posture"

requirements-completed: [AVTR-02, AVTR-03, AVTR-04, AVTR-06, AVTR-07]

duration: 1h 5m
completed: 2025-06-26
status: complete
---

# Phase 12 Plan 02: Lip-sync + Persona + Eye-contact Summary

**Path-A energy lip-sync on the inbound Kokoro WebRTC track (streamStart gain:0 + streamAudio), barge-in via the existing LiveKit interrupt, eye-contact/mood off agent state, and a client-only persona→GLB map with a Draco/WebP RPM default avatar — ZERO server diff.**

## Performance

- **Duration:** ~1h 5m
- **Tasks:** 5 logical steps (GLB acquire/compress, avatarConfig, AvatarStage, VoiceRoom, verify doc)
- **Files created:** 6 | **Files modified:** 3

## Accomplishments
- Acquired, verified, and Draco+WebP-compressed the default GLB (`cyber-trainer.glb`, 4.72MB→3.03MB) with the full AVTR-07 attestation: 67-bone Mixamo rig + 52 ARKit + 15 Oculus visemes (72 morphs total), CC BY-NC 4.0 license.
- Wired Path-A audio-driven lip-sync tapping the inbound agent track as a read-only second consumer; the primary `<RoomAudioRenderer/>` playout is untouched (`gain:0` mutes only the avatar's copy).
- Barge-in via the existing LiveKit `listening` state → `streamInterrupt()`; eye-contact + `setMood` off `useVoiceAssistant().state`.
- Client-only `avatarForPersona()` map; `VoiceRoom` passes the persona display_name into `<AvatarStage/>`.
- Closed two 12-01 gaps (missing `playback-worklet.js`, missing offline Draco decoder).

## Task Commits

1. **GLB asset + streaming/decoder prerequisites** - `ff7ae42` (feat)
2. **avatarConfig persona→GLB map** - `aafae3a` (feat)
3. **AvatarStage Path-A lip-sync + eye-contact + barge-in + VoiceRoom wiring** - `fc6cdec` (feat)
4. **12-AVATAR-VERIFY doc + AVTR-07 attestation** - `1446a60` (docs)

## Files Created/Modified
- `web/public/avatars/cyber-trainer.glb` - Draco+WebP RPM half-body default avatar (AVTR-06/07).
- `web/public/vendor/talkinghead/playback-worklet.js` - streaming worklet required by `streamStart()` (12-01 gap).
- `web/public/vendor/three/addons/libs/draco/*` - r0.180.0 Draco decoder for offline decode.
- `web/app/avatarConfig.ts` - `AvatarSpec`, `DEFAULT_AVATAR`, `PERSONA_AVATARS`, `avatarForPersona`, `DRACO_DECODER_PATH`.
- `web/app/AvatarStage.tsx` - `showAvatar`, Path-A tap, eye-contact/mood, barge-in, extended teardown.
- `web/app/VoiceRoom.tsx` - lifts persona display_name, passes `<AvatarStage persona=.../>`.
- `.planning/.../12-AVATAR-VERIFY.md` - operator gates + AVTR-07 attestation + Path-A note.

## Decisions Made
See `key-decisions` frontmatter. Headline: `gain:0` mute is the double-audio mitigation; Draco (not Meshopt) because TalkingHead 1.7 only wires DRACOLoader.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `playback-worklet.js` missing from 12-01 vendoring**
- **Found during:** Path-A API confirmation (pre-AvatarStage)
- **Issue:** `streamStart()` does `audioWorklet.addModule(new URL('./playback-worklet.js', import.meta.url))` (talkinghead.mjs:41); 12-01 vendored only talkinghead.mjs + dynamicbones.mjs, so streaming would throw at runtime.
- **Fix:** Vendored `playback-worklet.js` from the pinned `@1.7` tag (byte-identical to upstream master), same-origin/offline.
- **Files modified:** web/public/vendor/talkinghead/playback-worklet.js
- **Verification:** `registerProcessor("playback-worklet", …)` present; `diff` vs master IDENTICAL.
- **Committed in:** ff7ae42

**2. [Rule 1 - Tool/loader constraint] Draco (not Meshopt) + vendored offline decoder**
- **Found during:** GLB compression step
- **Issue:** Plan allows "Meshopt/Draco" but TalkingHead 1.7's GLTFLoader wires `DRACOLoader` only (never `setMeshoptDecoder`); a Meshopt-required GLB would fail to load. The library's `dracoDecoderPath` also defaults to the gstatic CDN, breaking the offline constraint.
- **Fix:** Compressed with Draco geometry + WebP textures; vendored the r0.180.0 Draco decoder under `/vendor/three/addons/libs/draco/` and set `dracoDecoderPath` to that same-origin path.
- **Files modified:** web/public/avatars/cyber-trainer.glb, web/public/vendor/three/addons/libs/draco/*, web/app/avatarConfig.ts (DRACO_DECODER_PATH), web/app/AvatarStage.tsx (dracoEnabled)
- **Verification:** Post-compression re-read confirms 72 morphs + 67 bones + 17 textures intact; `npm run build` passes.
- **Committed in:** ff7ae42 / aafae3a / fc6cdec

**3. [Execution decision] Path-A API + double-audio mute (recorded as required by the plan)**
- **Found during:** AvatarStage wiring
- **Issue:** The plan required confirming the timestamp-free Path-A API and recording it. The stream worklet plays fed audio to destination → double audio.
- **Fix:** `streamStart({gain:0, waitForAudioChunks:false})` + `streamAudio({audio:Float32})`; `gain:0` mutes the avatar copy while the analyzer drives energy visemes. Cloned-track ScriptProcessor capture.
- **Files modified:** web/app/AvatarStage.tsx
- **Verification:** Build clean; full detail in 12-AVATAR-VERIFY.md "Path-A API selection".
- **Committed in:** fc6cdec

**4. [Scope note] Persona-change GLB reactivity deferred**
- **Issue:** PersonaPanel's display_name isn't lifted, so a live GLB swap on persona change isn't wired.
- **Fix:** VoiceRoom passes the fixed default `personaName` ("Cybersecurity Trainer"); `setMood` still reacts. Avatar works out of the box for the seed persona (AVTR-06 satisfied). Noted as the wiring point.
- **Committed in:** fc6cdec / 1446a60

---

**Total deviations:** 4 (1 missing-critical, 1 tool-constraint, 1 execution-decision, 1 scope-note).
**Impact on plan:** Deviations 1–2 were essential to make Path-A streaming + offline GLB decode actually work; 3 is the required Path-A recording; 4 is a documented minor scope boundary. No server diff, no scope creep.

## Issues Encountered
- Ready Player Me API (`models.readyplayer.me`) is network-blocked in the sandbox. Resolved by using the canonical TalkingHead example RPM avatar (`brunette.glb`) from the reachable repo (github/jsdelivr), which is the documented default and carries the same morphTargets=ARKit,Oculus export.

## Sandbox Gates
- **`npm run build`** (web/): PASS — compiled, TypeScript clean.
- **Isolation gate** `git diff -- agent/ stt/ tts/ docker-compose.yml`: PASS — EMPTY (working tree and full phase range `afb7b9f..HEAD`).
- **Bundle isolation (AVTR-01):** all avatar code in a single lazy chunk referenced only via react-loadable-manifest.json; voice-only bundle unchanged.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 12 code-complete (both waves). All sandbox-checkable gates pass.
- **Operator gate pending:** 12-AVATAR-VERIFY.md needs a real Chromium session to confirm rendering, lip-sync quality, barge-in, eye-contact, ~30fps, and graceful degrade (sandbox has no WebGL/audio).

---
*Phase: 12-optional-3d-avatar-part-d*
*Completed: 2025-06-26*

## Self-Check: PASSED
- key-files.created exist on disk (GLB, worklet, 3 draco files, verify doc) — verified.
- `git log --grep="12-02"` returns 4 commits.
- Acceptance criteria re-run: build PASS, isolation EMPTY, AVTR-07 attestation recorded, teardown closes worklet+source+clone.
