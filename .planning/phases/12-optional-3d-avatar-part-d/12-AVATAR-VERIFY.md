---
status: pending-operator
phase: 12
requirement_ids: [AVTR-01, AVTR-02, AVTR-03, AVTR-04, AVTR-05, AVTR-06, AVTR-07, AVTR-08]
sandbox_gates:
  build: pass
  isolation_gate: pass
operator_gates: pending
---

# Phase 12 — Optional 3D Avatar: Verification

This phase is **frontend-only with ZERO server cost**. The sandbox has no
WebGL/browser/audio, so rendering, lip-sync, barge-in, fps, and graceful-degrade
are **operator/browser gates** below. The two **sandbox-checkable** gates
(`npm run build` + the isolation `git diff`) are recorded as PASS.

---

## Sandbox-checkable gates (PASS)

### Build
```
cd web && npm run build
```
Result: **PASS** — `✓ Compiled successfully`, `Finished TypeScript` clean
(Next.js 16.2.9, Turbopack). No type errors.

### Isolation gate (the auditable empty server diff)
```
git diff -- agent/ stt/ tts/ docker-compose.yml
```
Result: **PASS — EMPTY** (exit 0, no output), both for the working tree and across
the whole phase range (`afb7b9f..HEAD`, i.e. from before 12-01). The avatar adds
ZERO files under `agent/`/`stt/`/`tts/`, ZERO Compose services, ZERO server
RPC/byte-stream/attributes, ZERO server env. Server VRAM is identical avatar ON vs
OFF (nothing server-side changed).

### Bundle isolation (AVTR-01)
All avatar code (`TalkingHead`, `streamAudio`, `makeEyeContact`, the AvatarStage
"3D avatar unavailable" marker, the `webpackIgnore` dynamic import) lives in a
single lazy chunk referenced only via `react-loadable-manifest.json` (the
`dynamic(ssr:false)` boundary) — NOT the eager page entry. The voice-only bundle is
byte-for-byte the pre-avatar build until the Avatar toggle mounts AvatarStage.

---

## AVTR-07 attestation — GLB rig + blendshape inventory + license

**Asset:** `web/public/avatars/cyber-trainer.glb`
**Provenance:** met4citizen/TalkingHead example avatar `brunette.glb` (a Ready
Player Me half-body, `generator: "Ready Player Me"`), downloaded from the pinned
TalkingHead repo (`avatars/brunette.glb`, 4,721,528 bytes), then **Draco geometry +
WebP texture compressed** with `gltf-transform` → 3,035,272 bytes (−36%).
**Compressed file sha256:** `67621d7c2fb4bd4f941a7acaa12ae154f2b7a89360055fd7ba07f512dc7f015d`

**Verified post-compression (re-read with @gltf-transform/core):**

- **Mixamo-compatible rig — YES.** 67-bone skeleton with canonical Mixamo naming:
  `Hips → Spine → Spine1 → Spine2 → Neck → Head (+HeadTop_End, LeftEye, RightEye)`,
  `Left/RightShoulder → Arm → ForeArm → Hand` + full finger chains
  (`Thumb/Index/Middle/Ring/Pinky 1–4`), `Left/RightUpLeg → Leg → Foot → ToeBase →
  Toe_End`.

- **Oculus visemes (15) — YES.** Exactly the 15 OVR shape keys:
  `viseme_sil, viseme_PP, viseme_FF, viseme_TH, viseme_DD, viseme_kk, viseme_CH,
  viseme_SS, viseme_nn, viseme_RR, viseme_aa, viseme_E, viseme_I, viseme_O,
  viseme_U`.

- **ARKit blendshapes (52) — YES.** The full ARKit set is present, including:
  `browDownLeft/Right, browInnerUp, browOuterUpLeft/Right, eyeBlinkLeft/Right,
  eyeSquintLeft/Right, eyeWideLeft/Right, eyeLookDown/Up/In/Out Left/Right,
  cheekPuff, cheekSquintLeft/Right, noseSneerLeft/Right, jawForward/Left/Right/Open,
  mouthClose/Funnel/Pucker/Left/Right, mouthSmileLeft/Right, mouthFrownLeft/Right,
  mouthDimpleLeft/Right, mouthStretchLeft/Right, mouthRollLower/Upper,
  mouthShrugLower/Upper, mouthPressLeft/Right, mouthLowerDownLeft/Right,
  mouthUpperUpLeft/Right, tongueOut`.

- **Total morph targets: 72** = 15 Oculus + 52 ARKit + 5 RPM helpers
  (`mouthOpen, mouthSmile, eyesClosed, eyesLookUp, eyesLookDown`).
- Meshes (10), textures (17), and the skin all survive compression intact.

**License — CONFIRMED for personal/internal use.** Per the TalkingHead README
(asset attributions): *"Example avatar 'brunette.glb' was created at Ready Player
Me. The avatar is free to all developers for non-commercial use under the
**CC BY-NC 4.0 DEED**."* CC BY-NC 4.0 permits the intended personal/internal
(non-commercial) use with attribution; attribution is recorded here and in the
commit. (TalkingHead library itself: MIT, © 2024 Mika Suominen.) If this avatar is
ever used commercially, swap for a CC0 / commercially-licensed GLB before shipping.

**Compression (AVTR-08):** Draco `KHR_draco_mesh_compression` (geometry) +
`EXT_texture_webp` (textures). Both are natively supported by the vendored
three r0.180.0 `GLTFLoader`; Draco decodes via the same-origin vendored decoder at
`/vendor/three/addons/libs/draco/` (no gstatic CDN), WebP is browser-native.

---

## Operator / browser gates (status: pending-operator)

Run a real Chromium session against the deployed `web/` (LAN). For each, record
PASS/FAIL + notes.

| # | Gate | Requirement | Expected | Result |
|---|------|-------------|----------|--------|
| 1 | Toggle defaults to **Voice only** | AVTR-01 | On load, "Voice only" is selected; no avatar canvas; no avatar JS chunk fetched (Network tab) | ☐ |
| 2 | Avatar-ON renders the GLB | AVTR-06 | Flipping to "Avatar" loads `cyber-trainer.glb`, shows "loading avatar…" then the half-body, framed upper-body | ☐ |
| 3 | Framing is interview-appropriate | AVTR-05 | Upper-body framing (`cameraView:"upper"`); head + shoulders visible | ☐ |
| 4 | Lip-sync to Kokoro audio (Path-A) | AVTR-02 | While the agent speaks, the avatar's mouth moves in time with the audio; audio still plays normally through the speakers (no double audio, no muting/stutter of the real playout) | ☐ |
| 5 | Audio plays in parallel, untouched | AVTR-02 | Toggling Avatar ON/OFF does not change agent audio playback at all (the avatar is a read-only second consumer; `streamStart({gain:0})` mutes only the avatar's copy) | ☐ |
| 6 | Barge-in cuts the avatar instantly | AVTR-03 | Start talking while the avatar is mid-utterance → avatar audio + lip-sync stop immediately (agent enters `listening` → `streamInterrupt()`); no second client VAD involved | ☐ |
| 7 | Eye contact while speaking AND listening | AVTR-04 | Avatar holds eye contact (looks at camera) both while it speaks and while it listens to the user | ☐ |
| 8 | Persona mood applied | AVTR-04 | The persona's resting mood (`neutral` for cyber-trainer) is visible via `setMood` on load | ☐ |
| 9 | ~30fps on a typical device | AVTR-08 | Smooth rendering ~30fps (Draco/WebP-compressed GLB) | ☐ |
| 10 | Graceful degrade on weak/no-WebGL device | AVTR-08 | If WebGL is unavailable or the GLB fails, the "3D avatar unavailable — use Voice only" message shows; the app never crashes; voice still works | ☐ |
| 11 | Toggle OFF leaves NO residual | AVTR-01 | Flipping back to "Voice only" unmounts the canvas, closes the AudioWorklet + ScriptProcessor + cloned track (no running rAF, no extra AudioContext); perf identical to pre-avatar | ☐ |
| 12 | Voice-only ON↔OFF perf parity | AVTR-01/08 | Repeated toggles leave no leaked WebGL contexts / audio nodes (check `chrome://gpu` + Performance memory) | ☐ |

### How the operator drives each gate
- **Gate 1/11/12:** DevTools → Network, filter JS; confirm the avatar chunk only
  loads after Avatar-ON and that toggling OFF stops all avatar activity (Performance
  → no rAF, Memory → no growing AudioContext/WebGL count).
- **Gate 4/5/6:** Use headphones to avoid the agent hearing itself. Speak over the
  agent to test barge-in. Confirm the speaker audio is never interrupted by the
  avatar tap.
- **Gate 10:** Test on a low-end device or disable WebGL
  (`chrome://flags` → "Override software rendering list" off, or a VM without GPU).

---

## Path-A API selection (deviation note — execution decision)

Confirmed against the vendored TalkingHead 1.7 source
(`web/public/vendor/talkinghead/talkinghead.mjs`):

- **Chosen API:** `streamStart({ gain:0, lipsyncType:"visemes", lipsyncLang:"en",
  waitForAudioChunks:false })` once, then `streamAudio({ audio: Float32Array })`
  per captured PCM frame, and `streamInterrupt()` for barge-in. This is the
  **timestamp-free energy path**: the `playback-worklet` plays the fed PCM and its
  output is connected to `audioAnalyzerNode`; the render loop reads that analyzer's
  energy (`getByteFrequencyData`) while `isSpeaking` and scales the `viseme_*`
  morphs by volume. **No visemes/words/timestamps are ever fed** → no Path-B, no
  server coupling.
- **Double-audio mitigation (key decision):** the stream worklet also connects to
  `audioStreamGainNode → audioReverbNode → destination`, so without intervention
  TalkingHead's own AudioContext would play the inbound Kokoro audio a second time
  over the speakers. `streamStart({gain:0})` sets `audioStreamGainNode.gain = 0`,
  silencing the avatar's copy while the analyzer (a separate connection) still
  receives full-energy signal. The primary `<RoomAudioRenderer/>` playout is never
  muted or rerouted.
- **Capture mechanism:** the inbound `MediaStreamTrack` from
  `useVoiceAssistant().audioTrack` is **cloned** (read-only second consumer) into a
  `MediaStreamAudioSourceNode` → `ScriptProcessorNode(4096)` on `head.audioCtx`;
  each frame's Float32 channel data is copied and handed to `streamAudio`. A
  ScriptProcessor (vs. a custom AudioWorklet) was chosen to avoid vendoring an
  extra worklet module — TalkingHead converts Float32→Int16 internally.

### Honest limitation (operator must validate gate 4)
TalkingHead 1.7's streaming energy path scales **existing queued** `viseme_*`
morphs by analyzer volume (talkinghead.mjs ~L2464). With pure energy and no viseme
data, mouth motion is driven by audio loudness rather than phoneme shapes, so
lip-sync is approximate (open/close tracking) rather than phoneme-accurate. This is
the documented Path-A trade-off (no transcription/timestamps = no server coupling).
Gate 4 confirms the perceived quality in-browser; if it is too subtle, a future,
still-server-free refinement is a client-side viseme estimator feeding `streamAudio`
`visemes` derived locally (NOT word timings).

---

## Deviations recorded in this plan

1. **[Rule 2 — missing critical] `playback-worklet.js` was missing from the 12-01
   vendoring.** `streamStart()` calls `audioCtx.audioWorklet.addModule(workletUrl)`
   where `workletUrl = new URL('./playback-worklet.js', import.meta.url)`
   (talkinghead.mjs:41). 12-01 vendored only `talkinghead.mjs` + `dynamicbones.mjs`,
   so Path-A streaming would have thrown at runtime. Restored the file from the
   pinned `@1.7` tag (byte-identical to upstream master), same-origin/offline.
2. **[Rule 1 — gltf tool/loader constraint] Draco (not Meshopt) compression.** The
   plan allows "Meshopt/Draco". TalkingHead 1.7's `GLTFLoader` wires a `DRACOLoader`
   when `dracoEnabled:true` but never calls `setMeshoptDecoder`, so a
   Meshopt-required GLB would fail to load. Compressed with Draco geometry + WebP
   textures instead, and vendored the r0.180.0 Draco decoder locally + set
   `dracoDecoderPath` to the same-origin path (the library default points at the
   `gstatic.com` CDN, which would break the offline constraint).
3. **[Execution decision] Path-A API + double-audio mute** — documented above.
4. **[Scope note] Persona-change GLB reactivity.** `VoiceRoom` passes a fixed
   default `personaName` ("Cybersecurity Trainer") because PersonaPanel owns its own
   un-lifted persona state. `setMood` reacts to persona changes; a live GLB swap on
   persona change is the noted wiring point (lift PersonaPanel's `display_name`).
   Avatar mode works out of the box for the seed persona (AVTR-06 satisfied).
