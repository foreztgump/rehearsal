---
plan: 12-01
title: Avatar scaffold + isolation — vendor TalkingHead + three.js under web/public, dynamic-imported Avatar canvas mounted behind a default-OFF "Voice only / Avatar" toggle with clean unmount (canvas + AudioWorklet teardown) and interview framing; ZERO server diff
phase: 12
wave: 1
depends_on: []
autonomous: false
requirements: [AVTR-01, AVTR-05, AVTR-08]
files_modified:
  - web/public/vendor/talkinghead/talkinghead.mjs
  - web/public/vendor/three/three.module.js
  - web/public/vendor/three/three.core.js
  - web/public/avatars/.gitkeep
  - web/app/layout.tsx
  - web/app/VoiceRoom.tsx
  - web/app/AvatarStage.tsx
  - web/app/avatarConfig.ts
---

# Plan 12-01: Avatar scaffold + isolation gate

## User Story

**As** a user who wants either a clean voice-only call or an optional 3D talking head,
**I want** a default-OFF "Voice only / Avatar" toggle that, when flipped ON, mounts a WebGL
avatar inside the existing call and, when flipped OFF, fully tears the canvas down with no
residual cost, **so that** voice-only stays byte-for-byte the pre-avatar build and the avatar
never touches the server or its VRAM.

## Context

This is the **scaffold + isolation half** of Phase 12. It vendors met4citizen/TalkingHead +
a pinned three.js build under `web/public/vendor/` (offline / local-first, consistent with
Phase 11), wires a same-origin importmap, and adds a **dynamic-imported** `AvatarStage`
component gated behind a default-OFF toggle in `VoiceRoom.tsx`. Plan 12-02 then wires Path-A
lip-sync, barge-in, eye-contact/mood, and the persona→GLB map onto this stage. No lip-sync,
no audio tap, no persona wiring in THIS plan — just the mount/unmount lifecycle, the framing,
and the auditable isolation gate.

**The whole phase is frontend-only.** This plan touches ONLY `web/`. The isolation gate
(`git diff -- agent/ stt/ tts/ docker-compose.yml` empty) is an explicit acceptance check.

### Why vendored + importmap (not npm)
- three.js + TalkingHead are loaded via a `<script type="importmap">` in `layout.tsx` pointing
  at `/vendor/...` same-origin assets, then `await import("talkinghead")` is called lazily
  inside `AvatarStage`'s effect. This keeps them OUT of the Next/webpack voice-only bundle
  entirely (AVTR-01: "no avatar JS in the voice-only bundle"), and keeps the install offline
  (no CDN). `web/public` ships in the `output: "standalone"` image as static assets.
- Pin exact versions in a comment at the top of each vendored file (source URL + version +
  retrieval date) so the provenance is auditable. TalkingHead's README documents importing
  three.js as a peer via importmap — mirror that.

## Files & responsibilities

### `web/public/vendor/three/*` + `web/public/vendor/talkinghead/talkinghead.mjs`
- Vendored, version-pinned copies. three.js module build (`three.module.js` + `three.core.js`
  as shipped by the three release) and the TalkingHead class module (`modules/talkinghead.mjs`
  from a tagged TalkingHead release). Header comment in each: upstream URL, version/tag,
  retrieval date, license (three = MIT, TalkingHead = MIT).
- **Do not edit library internals.** If TalkingHead needs additional peer modules (it imports
  three addons like `GLTFLoader`, `DRACOLoader`, plus `dynamicbones`), vendor exactly the set
  its importmap names — enumerate them during execution by reading the module's import
  statements and add each as its own `files_modified` entry via a deviation note.

### `web/public/avatars/.gitkeep`
- Placeholder dir; the actual default GLB lands in 12-02 (AVTR-06/07). Keeps the path stable.

### `web/app/layout.tsx` (EDIT)
- Add a `<script type="importmap">` mapping bare specifiers (`three`, `three/addons/`,
  `talkinghead`) to the same-origin `/vendor/...` URLs, rendered in `<head>`. In Next App
  Router, emit it with a raw `<script type="importmap" dangerouslySetInnerHTML={{__html}}/>`
  BEFORE any module that resolves those specifiers. Guard: importmaps must appear before the
  first module script — place it high in `<head>`. This is inert for voice-only (nothing
  imports those specifiers until AvatarStage loads).

### `web/app/avatarConfig.ts` (NEW)
- Pure client constants shared by 12-01/12-02. In THIS plan: framing defaults only —
  `CAMERA_VIEW = "upper"` (AVTR-05; "head" is the alternate), and the importmap specifier
  string. The persona→GLB map + default GLB url are added in 12-02. Keep it dependency-free
  (no React) so it tree-shakes cleanly.

### `web/app/AvatarStage.tsx` (NEW, dynamic-imported)
- `"use client"`. Renders a single `<div ref>` host for the TalkingHead canvas. On mount
  (effect): `const { TalkingHead } = await import("talkinghead")`, construct against the host
  div with `cameraView: CAMERA_VIEW`, `lipsyncModules: []` (no lip-sync yet), and **no TTS**
  (TalkingHead's Google-TTS default must NOT be used — we are audio-only; construct with
  `ttsEndpoint:null`/equivalent so it never calls out). Show a tiny "loading avatar…" state
  while the dynamic import + WebGL init run.
- **Clean teardown (AVTR-01/AVTR-08):** the effect's cleanup MUST call TalkingHead's
  `stop()`/dispose path, remove the canvas from the DOM, drop the instance ref, and (defensive)
  cancel any rAF. After unmount there is zero running avatar code. No GLB is loaded yet in
  12-01 (the stage renders an empty scene / placeholder); loading is added in 12-02 — keep the
  showAvatar call as a 12-02 TODO marker, not a stub that fetches.
- **Graceful degrade (AVTR-08):** wrap init in try/catch; on WebGL-unavailable or import
  failure, render an inline "3D avatar unavailable on this device — use Voice only" message and
  do NOT throw (the toggle is the escape hatch). No retry loop.

### `web/app/VoiceRoom.tsx` (EDIT)
- Add `const [avatarOn, setAvatarOn] = useState(false)` (**default OFF** = Voice only).
- Add a small segmented "Voice only / Avatar" toggle in the existing UI (near `AgentStatePill`).
- Dynamic-import the stage so it is absent from the voice-only bundle:
  `const AvatarStage = dynamic(() => import("./AvatarStage"), { ssr: false })` (Next `dynamic`).
  Render `{avatarOn && <AvatarStage/>}` — when `avatarOn` is false the component is unmounted,
  triggering the teardown cleanup. Mount it INSIDE `<LiveKitRoom>` (it needs room context in
  12-02). Keep `<RoomAudioRenderer/>` exactly as-is (audio always plays normally — AVTR-02).
- Do not remove or reorder existing panels; the avatar is additive.

## Step-by-step

1. Vendor three.js + TalkingHead (+ the addon modules its imports name) under
   `web/public/vendor/`, each with a provenance/license header comment. Enumerate the addon set
   by reading TalkingHead's import statements; add a deviation note listing every vendored file.
2. Add the importmap `<script>` to `layout.tsx` `<head>`.
3. Write `avatarConfig.ts` (CAMERA_VIEW + specifier constant).
4. Write `AvatarStage.tsx` (dynamic-import TalkingHead, construct with framing, no-TTS,
   no-lipsync, empty scene; full teardown cleanup; try/catch degrade).
5. Wire the default-OFF toggle + `dynamic(ssr:false)` mount in `VoiceRoom.tsx`.
6. `npm run build` in `web/` — must compile; confirm the voice-only entry does NOT bundle
   three/talkinghead (they resolve via importmap at runtime, not webpack).
7. Run the isolation gate: `git diff -- agent/ stt/ tts/ docker-compose.yml` MUST be empty.

## Acceptance criteria

- [ ] `web/` builds (`npm run build` succeeds); TypeScript clean.
- [ ] Toggle defaults to **Voice only** (avatarOn=false); the `<AvatarStage>` is unmounted and
      its module is dynamic-imported (not in the initial/voice-only chunk).
- [ ] `AvatarStage` constructs TalkingHead with `cameraView` upper/head (AVTR-05) and with no
      TTS path engaged; unmount runs a full teardown (stop/dispose + canvas removed + ref
      dropped).
- [ ] WebGL-unavailable path renders the inline fallback message and does not throw (AVTR-08).
- [ ] **Isolation gate:** `git diff -- agent/ stt/ tts/ docker-compose.yml` is EMPTY.
- [ ] three.js + TalkingHead (+ addons) are vendored under `web/public/vendor` with provenance
      + license headers; no CDN/runtime WAN dependency; no new npm deps in `web/package.json`.

## Out of scope (→ 12-02)

- Path-A HeadAudio lip-sync + the inbound Kokoro audio tap (AVTR-02).
- Barge-in on user-speech-start (AVTR-03).
- Eye-contact + `setMood` (AVTR-04).
- The default GLB asset + persona→GLB map + AVTR-07 verification (AVTR-06/07).

## Notes / risks

- **Sandbox limit:** no browser/WebGL here — `npm run build` + the isolation `git diff` are the
  sandbox-checkable gates; actual rendering/teardown is an operator/browser gate in
  12-AVATAR-VERIFY.md.
- **Next App-Router importmap ordering** is the main footgun: the importmap script must precede
  the first module that uses those specifiers. Since AvatarStage is dynamic-imported only on
  toggle-ON and the importmap is in `<head>`, ordering holds — verify the constructed
  `import()` resolves at runtime during the operator gate.
- If `dynamic(ssr:false)` still pulls a tiny loader into the main chunk, that's fine — the
  heavy three/talkinghead payload stays behind the runtime importmap, satisfying "no avatar JS
  in the voice-only bundle" for the library itself.
