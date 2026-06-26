---
phase: 12-optional-3d-avatar-part-d
plan: 01
subsystem: ui
tags: [talkinghead, three.js, webgl, importmap, next-dynamic, avatar, vendoring]

# Dependency graph
requires:
  - phase: 11
    provides: offline/local-first deployment posture (vendored assets ship in the standalone image)
provides:
  - Vendored TalkingHead 1.7 + three.js r0.180.0 (+6 addons +3 transitive deps) under web/public/vendor with provenance/license headers
  - Same-origin importmap (three / three/addons/ / talkinghead) in layout.tsx <head>
  - avatarConfig.ts (CAMERA_VIEW framing constant + importmap specifier)
  - AvatarStage.tsx — dynamic-imported WebGL stage with full mount/unmount teardown + graceful WebGL-unavailable degrade
  - Default-OFF "Voice only / Avatar" toggle + dynamic(ssr:false) mount in VoiceRoom.tsx
  - Auditable empty server diff (isolation gate)
affects: [12-02-lipsync-persona-eyecontact]

# Tech tracking
tech-stack:
  added: [TalkingHead@1.7 (vendored), three.js@0.180.0 (vendored)]
  patterns:
    - "Vendored ESM libs loaded via same-origin importmap + runtime dynamic import (webpackIgnore) — keeps heavy libs out of the voice-only webpack bundle"
    - "default-OFF toggle gates a next/dynamic(ssr:false) component; unmount runs full WebGL/AudioContext teardown via dispose()"

key-files:
  created:
    - web/app/avatarConfig.ts
    - web/app/AvatarStage.tsx
    - web/public/vendor/talkinghead/talkinghead.mjs
    - web/public/vendor/talkinghead/dynamicbones.mjs
    - web/public/vendor/three/three.module.js
    - web/public/vendor/three/three.core.js
    - web/public/vendor/three/addons/controls/OrbitControls.js
    - web/public/vendor/three/addons/loaders/GLTFLoader.js
    - web/public/vendor/three/addons/loaders/DRACOLoader.js
    - web/public/vendor/three/addons/loaders/FBXLoader.js
    - web/public/vendor/three/addons/environments/RoomEnvironment.js
    - web/public/vendor/three/addons/libs/stats.module.js
    - web/public/vendor/three/addons/libs/fflate.module.js
    - web/public/vendor/three/addons/utils/BufferGeometryUtils.js
    - web/public/vendor/three/addons/curves/NURBSCurve.js
    - web/public/vendor/three/addons/curves/NURBSUtils.js
    - web/public/avatars/.gitkeep
  modified:
    - web/app/layout.tsx
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Pinned TalkingHead 1.7 + three r0.180.0 per TalkingHead README's documented importmap versions"
  - "Vendored the full transitive addon closure (14 lib files) so the importmap resolves entirely same-origin with no CDN/WAN fallback"
  - "Used variable specifier + webpackIgnore on the dynamic import so webpack never bundles the library — it resolves at runtime via the importmap (AVTR-01)"
  - "Teardown uses TalkingHead.dispose() which cancels rAF, suspends/disconnects AudioContext nodes, disposes the three.js scene+renderer (loseContext) and removes the canvas"

patterns-established:
  - "Provenance/license header block prepended to every vendored file (upstream URL + version + retrieval date + license)"
  - "Avatar libs gated behind importmap + dynamic import so voice-only stays byte-for-byte pre-avatar"

requirements-completed: [AVTR-01, AVTR-05, AVTR-08]

# Metrics
duration: 35 min
completed: 2026-06-26
status: complete
---

# Phase 12 Plan 01: Avatar scaffold + isolation gate Summary

**Vendored TalkingHead 1.7 + three.js r0.180.0 under web/public/vendor, wired a same-origin importmap, and mounted a dynamic-imported WebGL AvatarStage behind a default-OFF "Voice only / Avatar" toggle with full unmount teardown — zero server diff.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 5 (vendor, importmap, config+stage, toggle, gates)
- **Files modified:** 19 (17 created, 2 edited)

## Accomplishments
- Enumerated TalkingHead's import graph by reading its source and vendored the exact closure: `three` + 6 named addons (`OrbitControls`, `GLTFLoader`, `DRACOLoader`, `FBXLoader`, `RoomEnvironment`, `stats.module`) + 3 transitive deps (`BufferGeometryUtils`, `fflate.module`, `NURBSCurve`→`NURBSUtils`) + `dynamicbones.mjs` — 14 files, each with a provenance/license header.
- Same-origin importmap in `layout.tsx` `<head>` (precedes any module that resolves the specifiers).
- `AvatarStage` constructs TalkingHead with `cameraView:"upper"` framing (AVTR-05), `lipsyncModules:[]` (no dynamic lipsync imports) and empty `ttsEndpoint` (no Google-TTS pipeline / no network), empty scene (no GLB — deferred to 12-02). Cleanup runs `dispose()` for full teardown (AVTR-01/08). `try/catch` degrades to an inline "unavailable" message, no throw, no retry (AVTR-08).
- Default-OFF toggle in `VoiceRoom.tsx`; `AvatarStage` is `next/dynamic(ssr:false)`, mounted inside `<LiveKitRoom>` only when `avatarOn`. `<RoomAudioRenderer/>` untouched.

## Task Commits

1. **Vendor TalkingHead + three.js (+addons)** - `88837f5` (feat)
2. **Add same-origin importmap to layout** - `3eb9a4b` (feat)
3. **avatarConfig + AvatarStage scaffold** - `d61a585` (feat)
4. **Wire default-OFF toggle + dynamic mount** - `6da4a5c` (feat)

**Plan metadata:** this SUMMARY commit (docs).

## Files Created/Modified
See frontmatter `key-files`. Library files carry `VENDORED — DO NOT EDIT` provenance headers.

## Gate Results
- **`npm run build` (web/):** PASS — compiled in ~1.8s, TypeScript clean, 3 static pages generated.
- **AVTR-01 bundle check:** PASS — library internals (`lipsyncGetProcessor`/`dynamicbones.mjs`/`WEBGL_lose_context`) appear in NO `.next/static` chunk; the `import("talkinghead")` call stays as a runtime importmap resolution; the AvatarStage chunk is lazy-loaded via `Promise.all([...])`.
- **Isolation gate (`git diff -- agent/ stt/ tts/ docker-compose.yml`):** PASS — EMPTY both in working tree and across all 4 plan commits (`afb7b9f..HEAD`).

## Decisions Made
See frontmatter `key-decisions`.

## Deviations from Plan

The plan's `files_modified` listed only `three.module.js` + `three.core.js` and instructed the executor to enumerate TalkingHead's actual addon imports and record each vendored file as a deviation note.

### Deviation note — vendored addon set (planned enumeration, not a fix)
Reading `talkinghead.mjs`@1.7 import statements + transitive `three/addons` deps yielded these additional vendored files beyond the two named in the plan frontmatter:
- `three/addons/controls/OrbitControls.js`
- `three/addons/loaders/GLTFLoader.js`
- `three/addons/loaders/DRACOLoader.js`
- `three/addons/loaders/FBXLoader.js`
- `three/addons/environments/RoomEnvironment.js`
- `three/addons/libs/stats.module.js`
- `three/addons/utils/BufferGeometryUtils.js` (transitive via GLTFLoader)
- `three/addons/libs/fflate.module.js` (transitive via FBXLoader)
- `three/addons/curves/NURBSCurve.js` (transitive via FBXLoader)
- `three/addons/curves/NURBSUtils.js` (transitive via NURBSCurve)
- `talkinghead/dynamicbones.mjs` (TalkingHead peer module, `./dynamicbones.mjs`)

The plan explicitly anticipated this enumeration ("vendor exactly the set its importmap names — enumerate them during execution"), so this is expected planned work, not an unplanned scope change.

**Total deviations:** 0 unplanned. 1 planned enumeration note (the vendored addon closure).
**Impact on plan:** None — the enumerated set is the minimal closure required for TalkingHead's imports to resolve.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required. Assets are vendored same-origin.

## Next Phase Readiness
- Scaffold is ready for **12-02** to wire: Path-A HeadAudio lip-sync on the inbound Kokoro track (AVTR-02), barge-in (AVTR-03), eye-contact/mood (AVTR-04), and the default GLB + persona→GLB map + AVTR-07 verification (AVTR-06/07). A `TODO(12-02)` marker for `showAvatar()` is in `AvatarStage.tsx`.
- **Operator/browser gate deferred to 12-AVATAR-VERIFY.md:** actual WebGL render, unmount teardown, and graceful-degrade behavior require a real Chromium session — the sandbox has no WebGL/browser, so these were NOT executed here.

---
*Phase: 12-optional-3d-avatar-part-d*
*Completed: 2026-06-26*
