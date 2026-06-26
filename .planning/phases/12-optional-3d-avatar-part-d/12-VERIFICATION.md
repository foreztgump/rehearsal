---
phase: 12
phase_name: optional-3d-avatar-part-d
verdict: code-complete (operator/browser gates legitimately pending)
verified_by: goal-backward analysis (no browser launched)
requirement_ids: [AVTR-01, AVTR-02, AVTR-03, AVTR-04, AVTR-05, AVTR-06, AVTR-07, AVTR-08]
sandbox_gates:
  build: pass
  typescript: pass
  isolation_gate: pass
  no_new_npm_deps: pass
  bundle_isolation: pass
commit_range: 88837f5..a7125bb
---

# Phase 12 — Optional 3D Avatar (Part D): VERIFICATION

**Verdict: CODE-COMPLETE.** Every sandbox-checkable invariant holds, all eight AVTR
requirements are satisfied-in-code or correctly deferred to the operator/browser gate,
and the hard ISOLATION GATE is provably EMPTY across the entire phase. The rendering /
lip-sync / barge-in / fps / degrade behaviours that genuinely require WebGL+audio are
captured as operator gates in `12-AVATAR-VERIFY.md` (NOT silently dropped). No browser
was launched (sandbox has no WebGL).

This verdict reflects what the codebase *delivers*; final sign-off still requires the
operator to run the 12 browser gates in `12-AVATAR-VERIFY.md`.

---

## 1. The two sandbox-checkable gates

### Build + TypeScript — PASS (independently reproduced)
```
cd web && npm run build
```
`✓ Compiled successfully in 1703ms`, `Finished TypeScript in 1149ms` (Next.js 16.2.9,
Turbopack), 3/3 static pages generated, no type errors. Reproduced this run, not taken
from the executor summary.

### ISOLATION GATE — PASS (EMPTY, the hard invariant) — independently reproduced
```
git diff -- agent/ stt/ tts/ docker-compose.yml            # working tree:  exit 0, no output
git diff 88837f5~1..a7125bb -- agent/ stt/ tts/ docker-compose.yml   # whole phase: exit 0, no output
```
Confirmed EMPTY both for the working tree AND across the full phase range (from the
commit *before* 12-01 through HEAD). Stronger confirmation via `git diff --name-only`
over the whole range: the ONLY top-level directories touched by ANY phase-12 commit are
`.planning/` and `web/`. A direct grep of the phase's changed-file list for
`^(agent/|stt/|tts/|docker-compose.yml)` returns NOTHING. No server file was touched by
any phase-12 commit. Server VRAM is identical avatar ON vs OFF (nothing server-side
changed).

Phase-12 commits audited (10 commits, 88837f5..a7125bb):
```
88837f5 vendor TalkingHead 1.7 + three.js r0.180.0 (+addons)
3eb9a4b same-origin avatar importmap to layout <head>
d61a585 avatarConfig + dynamic-imported AvatarStage (mount/unmount)
6da4a5c wire default-OFF Voice only / Avatar toggle + dynamic mount
6741270 docs(12-01)
ff7ae42 vendor Draco+WebP cyber-trainer.glb + playback-worklet.js + Draco decoder
aafae3a avatarConfig persona->GLB map
fc6cdec Path-A lip-sync + eye-contact/mood + barge-in in AvatarStage
1446a60 docs(12-AVATAR-VERIFY operator gates + AVTR-07 attestation)
a7125bb docs(12-02)
```
Non-vendor source/docs changed: `web/app/AvatarStage.tsx` (+328), `web/app/VoiceRoom.tsx`
(+58/-x), `web/app/avatarConfig.ts` (+55), `web/app/layout.tsx` (+20), plus `.planning`
docs. All within `web/` and `.planning/`.

## 2. No new npm deps — PASS
`git diff 88837f5~1..a7125bb -- web/package.json` and `web/package-lock.json` are both
EMPTY (exit 0). `web/package.json` dependencies are unchanged: `@livekit/components-react`,
`livekit-client`, `livekit-server-sdk`, `next`, `react`, `react-dom`. three.js and
TalkingHead are vendored under `web/public/vendor/`, loaded via a same-origin importmap —
NOT added as npm deps. Confirmed.

## 3. Avatar JS is dynamic-imported / out of the voice-only bundle (AVTR-01) — PASS
Two-layer isolation, both verified against the actual build output:
- **React/Next boundary:** `VoiceRoom.tsx:16` — `const AvatarStage = dynamic(() =>
  import("./AvatarStage"), { ssr: false })`. Build output: all avatar code (`AvatarStage`,
  `talkinghead`, `streamAudio`, `makeEyeContact`, "3D avatar unavailable", "loading
  avatar…") lands in a SINGLE chunk `static/chunks/2kjw50gc-ma_s.js`, which is referenced
  ONLY by `.next/server/app/page/react-loadable-manifest.json` (the lazy boundary) — it is
  NOT in `build-manifest.json` `rootMainFiles` and NOT in any eager page entry. So the
  voice-only bundle does not load avatar JS until the toggle mounts AvatarStage.
- **Importmap boundary:** `AvatarStage.tsx:86-88` — `await import(/* webpackIgnore: true */
  TALKINGHEAD_SPECIFIER)` where the specifier `"talkinghead"` resolves at runtime via the
  `<script type="importmap">` in `layout.tsx`. So the 216 KB TalkingHead module + 592 KB
  three.js never enter webpack/Turbopack's graph at all — they load same-origin from
  `/vendor` only when Avatar mode turns ON.

## 4. Default GLB is a real binary asset + AVTR-07 attestation — PASS
`web/public/avatars/cyber-trainer.glb`:
- **Real binary, not a placeholder.** `file` reports `glTF binary model, version 2, length
  3035272 bytes`. Header parse: declared length 3035272 == file size; JSON chunk 103208 B
  + a genuine `BIN\0` chunk of 2,932,036 B. A fabricated/empty placeholder would have no
  2.9 MB binary chunk.
- **sha256 matches the attestation exactly:**
  `67621d7c2fb4bd4f941a7acaa12ae154f2b7a89360055fd7ba07f512dc7f015d`.
- **Independently re-read the glTF JSON:** `generator: "glTF-Transform v4.4.0"`,
  `extensionsUsed: ["EXT_texture_webp","KHR_draco_mesh_compression"]` (the Draco geometry +
  WebP texture compression claimed for AVTR-08), 10 meshes, 17 images, 1 skin.
- **Blendshape inventory verified directly (72 morph targets):** all **15 Oculus visemes**
  present (`viseme_sil,PP,FF,TH,DD,kk,CH,SS,nn,RR,aa,E,I,O,U`), ARKit set present
  (`jawOpen`, `eyeBlinkLeft`, `browInnerUp`, `mouthSmileLeft`, `tongueOut`, …). Mixamo rig
  confirmed (`Hips`, `Head`, `LeftHand` bones present). This matches the AVTR-07 attestation
  in `12-AVATAR-VERIFY.md` (15 Oculus + 52 ARKit + 5 RPM helpers = 72).
- **License recorded:** CC BY-NC 4.0 (RPM `brunette.glb` from the TalkingHead repo);
  attribution captured; non-commercial/internal use permitted; commercial-swap caveat noted.
  TalkingHead lib itself MIT. Recorded in `12-AVATAR-VERIFY.md`.

## 5. Per-requirement status

| Req | Status | Evidence |
|-----|--------|----------|
| **AVTR-01** Default-OFF toggle, dynamic import, no residual | **satisfied-in-code** | `VoiceRoom.tsx:40` `useState(false)` (default Voice only); `:16` `dynamic(...,{ssr:false})`; `:136` avatar only mounts when `avatarOn`. Build confirms avatar chunk is lazy-only. Full teardown in `AvatarStage.tsx:136-161` (processor/source/sink disconnect, cloned track.stop, `head.dispose()`). Residual-free behaviour is operator gate 11/12. |
| **AVTR-02** Path-A audio-driven lip-sync, audio untouched | **satisfied-in-code** (perceptual quality = operator gate 4/5) | `AvatarStage.tsx:181-280`: clones the inbound `useVoiceAssistant().audioTrack` (read-only 2nd consumer), `streamStart({gain:0,...})` mutes only the avatar's copy, `ScriptProcessor` feeds Float32 PCM to `streamAudio` — no timestamps/transcription. `<RoomAudioRenderer/>` playout never rerouted. API confirmed against vendored `talkinghead.mjs`. |
| **AVTR-03** Barge-in via existing LiveKit interrupt | **satisfied-in-code** (live behaviour = operator gate 6) | `AvatarStage.tsx:302-308`: on `state === "listening"` (the existing user-speech-start signal) calls `head.streamInterrupt()`. No second VAD. |
| **AVTR-04** Eye contact (speak+listen) + persona mood | **satisfied-in-code** (visual = operator gate 7/8) | `AvatarStage.tsx:291-298` `makeEyeContact(2000)`+`lookAtCamera(500)` while `speaking||listening`; `:123` + `:170-179` `setMood(avatar.mood)` on load and persona change. |
| **AVTR-05** Interview framing | **satisfied-in-code** (visual = operator gate 3) | `avatarConfig.ts:7` `CAMERA_VIEW="upper"`; passed to `TalkingHead({cameraView})` `AvatarStage.tsx:96`. |
| **AVTR-06** Persona→GLB map, default ships | **satisfied-in-code** | `avatarConfig.ts:44-55` client-only `PERSONA_AVATARS` + `avatarForPersona()` fallback to `DEFAULT_AVATAR`; `VoiceRoom.tsx:47` passes `personaName="Cybersecurity Trainer"`. ZERO server field. (Known scope note: live GLB swap on persona change deferred — PersonaPanel state un-lifted; mood DOES react. Default persona works out of the box.) |
| **AVTR-07** GLB rig/viseme/license verification | **satisfied** (attested + independently re-verified above) | sha256 match; 72 morphs incl. 15 visemes; Mixamo bones; Draco+WebP; CC BY-NC 4.0. Recorded in `12-AVATAR-VERIFY.md`. |
| **AVTR-08** Client WebGL, ~30fps, graceful degrade, zero server VRAM | **satisfied-in-code** (fps/degrade = operator gate 9/10) | Draco+WebP GLB (−36%, 3.0 MB) + same-origin Draco decoder (`avatarConfig.ts:19`, vendored, avoids gstatic CDN); error path `AvatarStage.tsx:125-128,321-325` renders "3D avatar unavailable" and never throws; zero server VRAM proven by the empty isolation diff. |

## 6. Vendoring completeness (offline / local-first)
`web/public/vendor/` contains: `talkinghead/{talkinghead.mjs (216K), dynamicbones.mjs,
playback-worklet.js (12K, real `AudioWorkletProcessor`)}`, `three/{three.module.js (592K),
three.core.js, addons/...}` including `addons/libs/draco/{draco_decoder.js,
draco_decoder.wasm (286K), draco_wasm_wrapper.js}` and `addons/loaders/{GLTFLoader,
DRACOLoader,FBXLoader}.js`. The importmap (`layout.tsx:14-20`) maps `three`,
`three/addons/`, `talkinghead` to these same-origin paths. No CDN/WAN runtime dep.
Note: `talkinghead.mjs` retains the upstream `gstatic.com/draco/v1/decoders/` *default*
string, but it is overridden by `dracoDecoderPath: DRACO_DECODER_PATH` at construction
(`AvatarStage.tsx:101`), so the offline path is the one actually used.

---

## Gaps / concerns

1. **Operator/browser gates are genuinely pending (not a code gap).** The sandbox has no
   WebGL/audio, so rendering, lip-sync fidelity, barge-in timing, ~30fps, and graceful
   degrade MUST be validated by the operator via the 12 gates in `12-AVATAR-VERIFY.md`.
   These are correctly captured, not dropped. Phase cannot be marked operationally "done"
   until those run. `12-AVATAR-VERIFY.md` front-matter `status: pending-operator` is the
   honest state.

2. **Lip-sync is approximate by design (Path-A energy path).** TalkingHead 1.7's streaming
   energy path scales existing queued viseme morphs by analyzer volume; with no viseme/word
   data, mouth motion tracks loudness, not phonemes. Documented as the deliberate Path-A
   trade-off (no transcription = no server coupling). Operator gate 4 judges perceived
   quality. This is a known limitation, not a defect.

3. **Persona→GLB reactivity is partial.** `VoiceRoom` passes a fixed `personaName`
   ("Cybersecurity Trainer") because `PersonaPanel` owns un-lifted persona state. `setMood`
   reacts to persona change but a live GLB swap does not. AVTR-06 is satisfied for the
   default persona (works out of the box); multi-persona live GLB swap is a noted future
   wiring point (lift `PersonaPanel.display_name`). Acceptable for this phase's goal.

4. **License is CC BY-NC 4.0 (non-commercial).** Fine for the stated personal/internal
   LAN use; flagged here because it would block commercial shipping without swapping for a
   CC0/commercial GLB. Caveat is already recorded in the attestation.

None of these block the phase goal: an OPTIONAL, default-OFF, frontend-only 3D avatar with
Path-A lip-sync, barge-in, eye-contact/mood/framing, and a client persona↔GLB map, with a
provably EMPTY server diff and zero new npm deps. The codebase delivers it.

## Bottom line
**CODE-COMPLETE.** All 5 requested skeptical checks verified against actual files + git
history (not executor summaries): build+TS clean, isolation gate EMPTY across the whole
phase, zero new npm deps, avatar JS lazy-only, real 2.9 MB Draco/WebP GLB with sha256 +
72-morph (15-viseme) + Mixamo-rig attestation. Operator/browser gates remain legitimately
pending in `12-AVATAR-VERIFY.md`.
