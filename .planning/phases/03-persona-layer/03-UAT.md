---
status: testing
phase: 03-persona-layer
source: [03-VERIFICATION.md]
started: 2026-06-25T00:00:00Z
updated: 2026-06-25T00:00:00Z
---

## Current Test

number: 1
name: Persona panel renders + role/name/knobs/voice editable in side panel
expected: |
  On the Proxmox VM + LAN browser, the persona side panel renders inside the
  LiveKit room with a role textarea, display-name input, three knob selects
  (difficulty/verbosity/correction), a Kokoro voice select, an Apply button,
  and an idle/applying/applied/error status line.
awaiting: user response

## Tests

### 1. [03-02] Persona panel renders + fields editable (PERS-02, PERS-03, PERS-04, PERS-05)
expected: The side panel renders inside `<LiveKitRoom>` beside the transcript with a role `<textarea>` (PERS-02), display-name `<input>` (PERS-03), three knob `<select>`s for difficulty/verbosity/correction (PERS-04), and a Kokoro voice `<select>` from the frozen `VOICE_IDS` list (PERS-05); all fields are editable and the seed values mirror the default Cybersecurity Trainer (intermediate/balanced/gentle/af_bella).
result: pending

### 2. [03-02] Live hot-swap via Apply with "applying…→applied" feedback (PERS-06)
expected: Editing role/name/knobs/voice then clicking Apply shows "applying…" then clears to "applied"; the NEXT turn reflects the new persona without any restart (one-turn re-prefill, PERS-06); the selected Kokoro voice swaps on the next utterance without glitching the in-flight one (PERS-05). The RPC return value is the ack. The one re-prefill turn's elevated `llm_ttft_ms` / `over_budget:["llm_ttft"]` is EXPECTED — not a bug. The per-turn metrics key set is unchanged.
result: pending

### 3. [03-01] Correction knob audibly scales; default trainer regression (PERS-07, PERS-01, DEPLOY-03)
expected: On browser join the agent greets and converses identically to Phase 2 with the default persona (Cybersecurity Trainer, gentle correction, `af_bella` voice) — no behavior change (PERS-01 / DEPLOY-03). Adjusting the correction-aggressiveness knob (gentle→moderate→aggressive) audibly scales how firmly the trainer corrects sloppy terminology (PERS-07).

result: pending

### 4. [VM-INTROSPECT] API-signature reconcile on the installed builds
expected: Confirm on the VM — `Agent.update_instructions` is a coroutine; `openai.TTS.update_options(voice=)` accepts the voice kwarg and mutates the existing TTS (metrics subscription survives); `rtc.LocalParticipant.register_rpc_method` (snake_case) exists and the handler arg is `RpcInvocationData` with `.payload`; client `performRpc`/`registerRpcMethod` work on `livekit-client@2.20.0` and `useVoiceAssistant().agent.identity` is the correct RPC destination. If `update_options` is missing → recreate just the TTS plugin AND re-attach metrics; if RPC is missing → participant-attributes fallback (per 03-02-4).
result: pending

### 5. [VM-INTROSPECT] Kokoro voice-list reconcile
expected: `curl http://kokoro:8880/v1/audio/voices` returns a list that includes every entry in the client/server `VOICE_IDS` (af_heart, af_bella, af_nicole, af_sarah, af_kore, am_michael, am_fenrir, am_puck, am_adam, bf_emma, bf_alice, bm_george, bm_daniel). Drop or correct any id the server does not serve.
result: pending

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
