---
phase: 02-bare-voice-loop-mvp-gate
plan: 02-01
subsystem: ui
tags: [livekit, livekit-client, components-react, nextjs, react, webrtc, voice]

requires:
  - phase: 01-foundation-infrastructure
    provides: token-mint route (web/app/api/token/route.ts), self-hosted LiveKit server + ICE node_ip, agent AgentSession worker, secure-context (mediaDevices over Caddy TLS)
provides:
  - Browser room-join SPA (single "Start talking" gesture → token fetch → LiveKitRoom)
  - Open-mic audio publish + agent TTS playout via RoomAudioRenderer with autoplay backstop (StartAudio)
  - Client-side AEC/noise-suppression capture defaults (local-first, no cloud plugin)
  - Agent-state pill bound to useVoiceAssistant().state (listening/thinking/speaking)
  - Two-sided live transcript via useTranscriptions() split by participant identity
  - NEXT_PUBLIC_LIVEKIT_URL browser-visible WS endpoint env
affects: [02-02, 02-03, persona, transcript-export, polish]

tech-stack:
  added: ["livekit-client@2.20.0 (exact pin)", "@livekit/components-react@2.9.21 (exact pin)"]
  patterns:
    - "Single user gesture does mic-permission + autoplay-unlock + connect; <StartAudio/> is the autoplay backstop"
    - "Net-new client components mirror SecureContextProbe shape: 'use client', typed/inline-styled, thin"
    - "serverUrl read from NEXT_PUBLIC_LIVEKIT_URL (never hardcoded); secrets stay server-side in token route"

key-files:
  created:
    - web/app/VoiceRoom.tsx
    - web/app/AgentStatePill.tsx
    - web/app/Transcript.tsx
  modified:
    - web/package.json
    - web/package-lock.json
    - web/app/page.tsx
    - .env.example
    - .env

key-decisions:
  - "Pinned livekit-client@2.20.0 (2.x line, matches self-hosted server v1.10.x) and @livekit/components-react@2.9.21 as exact versions; lockfile regenerated and committed"
  - "No @livekit/components-styles CSS import: components-react@2.9.21 does not depend on it, so the layout.tsx CSS import is N/A (not applicable, not skipped)"
  - "Transcript uses the useTranscriptions() hook directly — verified present in the installed package (returns TextStreamData[] with { text, participantInfo.identity, streamInfo.id }); the registerTextStreamHandler('lk.transcription') fallback was NOT needed"

patterns-established:
  - "Inline-style client voice components composing @livekit/components-react hooks (no CSS framework)"
  - "Exact npm version pins resolved at execution time via npm view, lockfile committed (carried from 01-01 image-tag discipline)"

requirements-completed: [VOICE-05, VOICE-06, VOICE-07, DEPLOY-03, PERS-01]

duration: 12min
completed: 2026-06-25
status: complete
---

# Phase 2 Plan 02-01: Browser SPA + LiveKit SDK media/data-channel + agent-state pill + two-sided transcript Summary

**Single-gesture browser voice room: "Start talking" → /api/token → `<LiveKitRoom audio video={false}>` with client-side AEC, agent TTS playout, a `useVoiceAssistant().state` pill, and a `useTranscriptions()` two-sided transcript — wired to NEXT_PUBLIC_LIVEKIT_URL.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 5
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments

- Pinned and locked the LiveKit client SDK (`livekit-client@2.20.0`, 2.x) + React hooks (`@livekit/components-react@2.9.21`); `npm ci` and `next build` both exit 0.
- Replaced the static "stack online" probe with a real room-join SPA: one "Start talking" button does mic-permission + autoplay-unlock + connect, with `<RoomAudioRenderer/>` (agent TTS) and `<StartAudio/>` (autoplay backstop).
- Explicit client-side `audioCaptureDefaults` (echoCancellation / noiseSuppression / autoGainControl) — local-first, zero server-side cloud noise-cancellation plugins.
- Agent-state pill bound to `useVoiceAssistant().state` with a distinct color per state; two-sided transcript split USER (`user-` identity prefix) vs AGENT via `useTranscriptions()`.
- Added the single new browser env `NEXT_PUBLIC_LIVEKIT_URL`; `LIVEKIT_API_SECRET` stays server-side.

## Task Commits

1. **Task 02-01-1: pin + lock LiveKit deps** - `5779413` (feat)
2. **Task 02-01-2: VoiceRoom entry button → LiveKitRoom + audio + autoplay** - `c1ec5f7` (feat)
3. **Task 02-01-3: AgentStatePill** - `2183e2c` (feat)
4. **Task 02-01-4: Transcript two-sided** - `5bb5d46` (feat)
5. **Task 02-01-5: NEXT_PUBLIC_LIVEKIT_URL env** - `c85ff9a` (feat)

## Files Created/Modified

- `web/package.json` - added exact-pinned `livekit-client` (2.20.0) + `@livekit/components-react` (2.9.21)
- `web/package-lock.json` - regenerated locked resolutions for the new deps
- `web/app/VoiceRoom.tsx` (new) - entry button + `<LiveKitRoom>` + `<RoomAudioRenderer/>` + `<StartAudio/>` + AEC capture defaults
- `web/app/AgentStatePill.tsx` (new) - `useVoiceAssistant().state` → colored state pill
- `web/app/Transcript.tsx` (new) - `useTranscriptions()` → two-sided transcript split by identity
- `web/app/page.tsx` (modified) - renders `<VoiceRoom />` (SecureContextProbe removed)
- `.env.example` / `.env` (modified) - new `NEXT_PUBLIC_LIVEKIT_URL=wss://<lan-host>:7443`

## Decisions Made

- **Exact pins:** `livekit-client@2.20.0` (latest 2.x, major matches self-hosted server v1.10.x) and `@livekit/components-react@2.9.21`, lockfile committed.
- **No components-styles CSS import:** `@livekit/components-react@2.9.21` does not depend on `@livekit/components-styles`, so the conditional `layout.tsx` CSS import in Task 02-01-1 is genuinely not applicable. The unstyled prebuilt components (`RoomAudioRenderer`, `StartAudio`) render fine without it; the MVP UI is inline-styled.
- **Transcript hook path:** Verified `useTranscriptions` is exported by the installed package and returns `TextStreamData[]` (`{ text, participantInfo: { identity }, streamInfo: { id } }`). Used the hook directly; the documented `registerTextStreamHandler('lk.transcription', ...)` fallback was not required.

## Deviations from Plan

None - plan executed exactly as written.

One in-task adjustment worth noting (not a deviation): the explanatory comment in `VoiceRoom.tsx` was reworded to avoid literally containing the strings `krisp`/`ai_coustics`, because Task 02-01-2's prohibition acceptance grep (`grep -Ri "krisp\|ai_coustics\|noiseCancellation:" web/app`) must return nothing. The code never referenced any such plugin; only a comment mentioned them by name. Reworded to "no server-side cloud noise-cancellation plugin is used (PERF-03 local-first)" so the grep passes.

## Issues Encountered

None.

## Operator Gates (deferred — VM + LAN device)

This sandbox has **no Docker daemon, no GPU, and no browser**, so the live human-in-the-loop checks (`autonomous: false`) CANNOT be executed here and are NOT marked passed. They must be verified on the Proxmox VM with a real CA-trusted LAN device, `NEXT_PUBLIC_LIVEKIT_URL` set to `wss://<vm-lan-host>:7443`, `LIVEKIT_NODE_IP` set, and UDP 7882 / TCP 7881 open:

- **[02-01-2] Room join + audio playout:** Loading the page shows one "Start talking" button with no required config; clicking joins the room and the agent's audio track plays through `<RoomAudioRenderer/>` (DEPLOY-03, PERS-01, VOICE-05 open-mic).
- **[02-01-3] Agent-state pill during a real turn:** Pill shows `listening` while the user speaks, `thinking` during STT/LLM, `speaking` during TTS playout — matching reality (VOICE-06).
- **[02-01-4] Live two-sided transcript:** Both the user's speech and the agent's reply stream into the transcript live, on their correct sides, with partials updating (VOICE-07).
- **Phase-2 verification OPERATOR GATE:** page-load → click → talking within seconds, hands-free (open-mic, no PTT control exists); pill + two-sided transcript are live.

## Client-Verifiable Criteria (executed here — all PASS)

- `web/package.json` deps contain `livekit-client` and `@livekit/components-react` as exact versions (no `^`/`~`) — grep PASS; `livekit-client` is 2.x (2.20.0) — PASS.
- `web/package-lock.json` resolves both new packages (`grep -c '"livekit-client"'` = 3) and is committed — PASS.
- `npm install --prefix web`, `npm ci --prefix web`, `npm run build --prefix web` all exit 0 — PASS.
- VoiceRoom: `"use client"`, default-exports `VoiceRoom`, imports `RoomAudioRenderer`/`StartAudio`, `audio` + `video={false}` + `audioCaptureDefaults` (echoCancellation/noiseSuppression/autoGainControl true), serverUrl from `process.env.NEXT_PUBLIC_LIVEKIT_URL` — PASS.
- No server-side noise-cancellation plugin in `web/app` (`grep -Ri "krisp\|ai_coustics\|noiseCancellation:"` returns nothing) — PASS.
- `web/app/page.tsx` renders `<VoiceRoom />` — PASS.
- AgentStatePill: `"use client"`, default export, uses `useVoiceAssistant` reading `state`, distinct styling per state — PASS.
- Transcript: `"use client"`, default export, source `useTranscriptions()` (verified present), split by `user-` identity prefix — PASS.
- `.env.example` has `NEXT_PUBLIC_LIVEKIT_URL=wss://` with explanatory comment; `.env` has the line; no `NEXT_PUBLIC_` var exposes a secret — PASS.

## Next Phase Readiness

- Thin end-to-end "I can join and hear" slice is wired and builds clean. Ready for **02-02** (greeting + per-turn reply loop + Cybersecurity Trainer persona in `agent/main.py`).
- Operator gates above must be cleared on the VM to confirm the live loop before the Phase-2 MVP gate is fully closed.

## Self-Check: PASSED

- Created files exist on disk: `web/app/VoiceRoom.tsx`, `web/app/AgentStatePill.tsx`, `web/app/Transcript.tsx` — confirmed.
- `git log --grep="02-01"` returns 5 task commits — confirmed.
- All client-verifiable `<acceptance_criteria>` re-run and PASS; `npm ci` + `next build` exit 0 from committed state.

---
*Phase: 02-bare-voice-loop-mvp-gate*
*Completed: 2026-06-25*
