---
status: testing
phase: 02-bare-voice-loop-mvp-gate
source: [02-VERIFICATION.md]
started: 2025-02-14T00:00:00Z
updated: 2025-02-14T00:00:00Z
---

## Current Test

number: 1
name: Room join + audio + agent-state pill + two-sided transcript
expected: |
  Page-load shows one "Start talking" button with no required config. Clicking joins
  the room within seconds, hands-free (open-mic, no push-to-talk control exists). The
  agent's TTS audio plays through the browser. The agent-state pill shows
  listening/thinking/speaking matching reality, and both the user's and the agent's
  speech stream live into the two-sided transcript on their correct sides.
awaiting: user response

## Tests

### 1. [02-01] Room join + audio + pill + transcript
expected: Page-load → one "Start talking" button (no setup) → join within seconds, hands-free (open-mic, no PTT); agent TTS plays through `<RoomAudioRenderer/>`; pill shows listening/thinking/speaking matching reality; both sides stream live into the transcript (DEPLOY-03, PERS-01, VOICE-05/06/07).
result: [pending]

### 2. [02-02] Greeting + per-turn loop + first-sentence TTS + no `<think>`
expected: On join the agent audibly greets exactly once as the Cybersecurity Trainer; speak → relevant spoken reply via the full streamed mic→STT→LLM→TTS loop, beginning on its first completed sentence; no `<think>` preamble appears in the transcript and TTFT is not inflated by a reasoning preamble (VOICE-01, VOICE-02, PERS-01).
result: [pending]

### 3. [02-03] Barge-in + slow-speech endpointing + acoustic echo + real e2e P50
expected: Talking over the agent stops its speech within ~1 frame, with no self-interrupt on its own echo tail or short backchannels (VOICE-03); hesitant speech ("let me think… the answer is…") is not cut off mid-thought and there is no dead air after a clear finish (VOICE-04); laptop speakers + built-in mic in a small room produces no self-echo interruption and the headphones path is clean (VOICE-08 echo defense); over N turns the per-turn metric lines show populated stage numbers and a rolling e2e P50 < ~1.2s (VOICE-08, PERF-01).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
