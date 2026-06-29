---
title: R5 Expressive Avatar Design
date: 2026-06-29
status: draft for user review
scope: v1.2 R5
---

# R5 - Expressive Avatar Design

## Summary

R5 makes the avatar feel like an expressive presenter without changing the voice
pipeline shape.

Chosen path: **Option A - Presenter Motion Slice**.

- Add conversation-state moods for idle, listening, thinking, and speaking.
- Add light face, head, torso, and hand/arm motion while the avatar is active.
- Reuse the vendored TalkingHead APIs already in the app.
- Fix Path-B multi-sentence lip-sync anchoring after the expression work.
- Keep captioned-TTS streaming as measure-first fallback work, not default R5
  scope.

## Goals

- Make avatar-on conversations visibly more alive.
- Keep the avatar behavior local-first and deterministic.
- Avoid adding sentiment analysis, LLM emotion metadata, or a new animation
  dependency.
- Preserve the existing voice-to-voice flow and manual avatar framing controls.
- Fix the documented Path-B bug where later sentence schedules can miss their
  audio-start anchor.

## Non-Goals

- No LLM emotion metadata protocol.
- No local sentiment classifier.
- No new animation library.
- No full-body character pass beyond light presenter movement.
- No Kokoro captioned-TTS streaming rewrite unless verification shows a clear
  avatar-on latency regression.

## Alternatives Considered

### A. Presenter Motion Slice

Expression first, then Path-B reliability.

This is the selected design. It matches the R5 priority: a visible improvement
to avatar-on conversations with a small reliability fix for lip-sync.

### B. Lip-Sync Reliability Slice

Fix Path-B first, then add only minimal expression.

This is safer for timing correctness but less aligned with the goal of making
R5 visibly improve the avatar.

### C. Latency/Streaming Slice

Measure avatar ON/OFF first audio and rewrite captioned-TTS streaming if needed.

This is deferred unless smoke or measurement shows avatar-on first audio has
regressed. It is useful work, but too invisible for R5 without evidence.

## Architecture

R5 stays mostly in the existing avatar frontend path.

`AvatarStage.tsx` already owns the TalkingHead instance, audio-level state,
avatar mood calls, and Path-B schedule handling. R5 should extend that path
instead of adding a separate animation controller.

`captioned_tts.py` should stay mostly unchanged. Touch it only if the Path-B fix
needs a tiny schedule metadata adjustment.

No agent code should branch on emotional state. R5 uses conversation state, not
LLM output, to choose avatar behavior.

## Components

### Conversation-State Mood

Map existing UI/conversation state to TalkingHead calls:

- idle: avatar present but not in an active turn
- listening: user is speaking or microphone input is active
- thinking: transcript is accepted and the agent is preparing a response
- speaking: remote audio is active

Use existing `setMood` support and avatar config values where possible. Keep the
mapping deterministic and small.

### Presenter Motion

Add restrained motion that reads as presenter behavior:

- subtle idle/listening head and torso motion
- stronger speaking motion while remote audio is active
- light hand/arm gestures during speech

Use vendored TalkingHead methods such as `setMood`, `speakWithHands`, and
existing gesture support. Do not add a gesture scheduler unless the direct API
calls are insufficient.

### Path-B Multi-Sentence Anchoring

Fix the current schedule handling so each captioned sentence can get its own
audio-start anchor. The bug is that anchoring is tied too closely to the first
silence-to-sound edge, so later sentence schedules can fall back to Path-A.

Prefer a small queue or sequence correction inside existing schedule handling.
Do not build a new scheduling abstraction.

### Captioned-TTS Latency

R5 does not rewrite Kokoro streaming by default. If avatar-on smoke feels slow,
measure avatar ON/OFF first-audio timing. Only scope the streaming rewrite when
there is a clear regression.

## Data Flow

The live turn remains unchanged:

1. Browser sends microphone audio through LiveKit.
2. Agent performs STT, LLM, and TTS through the existing local services.
3. Agent emits audio through LiveKit.
4. If avatar mode is enabled, captioned TTS publishes word timings over
   `lk.avatar.lipsync`.
5. The web app receives audio and timing schedules.
6. `AvatarStage.tsx` drives mood, presenter motion, and mouth movement from the
   existing audio/conversation state.

## Error Handling

- If a TalkingHead gesture or mood call is unavailable, fail soft and keep the
  avatar speaking.
- If gesture calls overlap awkwardly, throttle or skip the next gesture rather
  than queueing a complex animation backlog.
- If Path-B lacks a valid schedule, fall back to the existing Path-A audio-level
  mouth behavior.
- If avatar-on first audio is clearly slower than avatar-off, record the timing
  and treat captioned-TTS streaming as follow-up work.

## Verification

Required:

- Manual full-stack smoke with avatar ON:
  - voice input reaches the agent
  - voice output returns
  - avatar changes state visibly
  - avatar speaks with light gestures
  - multi-sentence responses stay aligned enough to validate Path-B behavior
- Focused automated test for Path-B schedule anchoring, especially
  multi-sentence schedules arriving before or during audio.
- Existing relevant frontend checks/tests if available.
- `git diff --check`.

Optional only if smoke feels slow:

- Compare avatar ON vs OFF first-audio timing.
- If avatar ON clearly regresses P50 or first-audio timing, scope the
  captioned-TTS streaming fix.

Exit criteria:

- Avatar-on conversation feels like an expressive presenter, not a static head.
- Light hand/arm gestures appear while speaking.
- Path-B no longer drops later sentence anchors in multi-sentence responses.
- The existing voice-to-voice flow still works.

## Implementation Notes

Keep the implementation boring:

- Extend `AvatarStage.tsx` before creating new modules.
- Reuse TalkingHead APIs before adding code.
- Prefer deterministic conversation-state moods over text analysis.
- Use one focused test for the Path-B bug.
- Skip streaming work until measurement proves it is needed.
