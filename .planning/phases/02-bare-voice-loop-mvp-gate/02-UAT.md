---
status: testing
phase: 02-bare-voice-loop-mvp-gate
source: [02-VERIFICATION.md]
started: 2025-02-14T00:00:00Z
updated: 2025-02-14T00:00:00Z
---

## Current Test

number: 2
name: Greeting + per-turn loop + first-sentence TTS + no `<think>`
expected: |
  On join the agent audibly greets exactly once as the Cybersecurity Trainer; speak →
  relevant spoken reply via the full streamed mic→STT→LLM→TTS loop, beginning on its
  first completed sentence; no `<think>` preamble appears in the transcript and TTFT is
  not inflated by a reasoning preamble.
awaiting: user response

## Tests

### 1. [02-01] Room join + audio + pill + transcript
expected: Page-load → one "Start talking" button (no setup) → join within seconds, hands-free (open-mic, no PTT); agent TTS plays through `<RoomAudioRenderer/>`; pill shows listening/thinking/speaking matching reality; both sides stream live into the transcript (DEPLOY-03, PERS-01, VOICE-05/06/07).
result: pass
verified: 2026-06-25 via Chrome CDP (Chromium 149, fake mic). Page loaded over TLS at https://localhost showing single "Start talking" button (no config). Click joined room "adept" within seconds (signal connected, LiveKit v1.10.0, state→connected). Agent participant joined and published an audio track (voice greeting). Pill cycled Listening→Thinking→Speaking→Listening matching reality. Greeting streamed word-by-word into the transcript: "Alright, welcome in. Let's start with the basics – what's the first thing that comes to mind when you hear the phrase 'cybersecurity'?" (Cybersecurity Trainer persona, PERS-01). No TTS errors after fixes.
notes: |
  Four blockers fixed to get the one-compose path working end-to-end:
  1. .env missing LIVEKIT_URL → agent worker could not register. Added
     LIVEKIT_URL=ws://livekit-server:7880 (internal compose network, plain ws;
     TLS is browser-facing Caddy only).
  2. NEXT_PUBLIC_LIVEKIT_URL not present at web build time → client logged "no
     livekit url provided" and never opened wss://. NEXT_PUBLIC_* is inlined at
     build, so added Dockerfile ARG + compose build.args (web/Dockerfile,
     docker-compose.yml web service).
  3. openai.STT(extra_kwargs=...) invalid in livekit-plugins-openai 1.6.4 →
     agent job crashed on every join (TypeError), agent left room immediately,
     UI stuck "Connecting". Removed the unsupported kwarg (the beam_size/
     vad_filter whisper tuning has no pass-through in this plugin version).
  4. kokoro TTS: pinned image v0.2.4 bundles PyTorch sm_50..sm_90 and crashes on
     the RTX 5090 (Blackwell sm_120): "no kernel image is available for execution
     on the device". Repinned to v0.5.0-cu128 (CUDA 12.8). Then the livekit
     plugin's SSE path (used for any model != tts-1/tts-1-hd) pushed zero frames
     because kokoro ignores stream_format=sse and returns raw audio/mpeg; set
     KOKORO_MODEL="tts-1" to route through the plain audio-stream path.
  Note: model ladder fell through to rung 3 (gemma3:4b-it-qat); gemma4 tags did
  not resolve. .env now pinned to gemma3:4b-it-qat.

### 2. [02-02] Greeting + per-turn loop + first-sentence TTS + no `<think>`
expected: On join the agent audibly greets exactly once as the Cybersecurity Trainer; speak → relevant spoken reply via the full streamed mic→STT→LLM→TTS loop, beginning on its first completed sentence; no `<think>` preamble appears in the transcript and TTFT is not inflated by a reasoning preamble (VOICE-01, VOICE-02, PERS-01).
result: [pending]

### 3. [02-03] Barge-in + slow-speech endpointing + acoustic echo + real e2e P50
expected: Talking over the agent stops its speech within ~1 frame, with no self-interrupt on its own echo tail or short backchannels (VOICE-03); hesitant speech ("let me think… the answer is…") is not cut off mid-thought and there is no dead air after a clear finish (VOICE-04); laptop speakers + built-in mic in a small room produces no self-echo interruption and the headphones path is clean (VOICE-08 echo defense); over N turns the per-turn metric lines show populated stage numbers and a rolling e2e P50 < ~1.2s (VOICE-08, PERF-01).
result: [pending]

## Summary

total: 3
passed: 1
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
