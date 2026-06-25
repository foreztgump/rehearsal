---
status: complete
phase: 03-persona-layer
source: [03-VERIFICATION.md]
started: 2026-06-25T00:00:00Z
updated: 2026-06-25T00:00:00Z
method: automated browser drive over Chrome DevTools Protocol (headless Chromium + fake mic)
---

## Current Test

number: —
name: complete
expected: All 5 tests driven via CDP against the running stack; results recorded below.
awaiting: none

## Tests

### 1. [03-02] Persona panel renders + fields editable (PERS-02, PERS-03, PERS-04, PERS-05)
expected: The side panel renders inside `<LiveKitRoom>` beside the transcript with a role `<textarea>` (PERS-02), display-name `<input>` (PERS-03), three knob `<select>`s for difficulty/verbosity/correction (PERS-04), and a Kokoro voice `<select>` from the frozen `VOICE_IDS` list (PERS-05); all fields are editable and the seed values mirror the default Cybersecurity Trainer (intermediate/balanced/gentle/af_bella).
result: pass
notes: |
  Driven via CDP after joining the room. DOM after join contained: 1 display-name
  `<input>`, 1 role `<textarea>`, and 4 `<select>`s — Difficulty
  [beginner,intermediate,expert], Verbosity [terse,balanced,detailed], Correction
  [gentle,moderate,aggressive], and Voice with all 13 frozen VOICE_IDS in order
  (af_heart…bm_daniel). Apply button present. Seed values mirror DEFAULT_PERSONA.
  Screenshot: /tmp/opencode/shot.png. NOTE: surfaced only AFTER a stale-deploy fix
  (see Gaps) — the originally-running images predated this phase's code.

### 2. [03-02] Live hot-swap via Apply with "applying…→applied" feedback (PERS-06)
expected: Editing role/name/knobs/voice then clicking Apply shows "applying…" then clears to "applied"; the NEXT turn reflects the new persona without any restart (one-turn re-prefill, PERS-06); the selected Kokoro voice swaps on the next utterance without glitching the in-flight one (PERS-05). The RPC return value is the ack. The one re-prefill turn's elevated `llm_ttft_ms` / `over_budget:["llm_ttft"]` is EXPECTED — not a bug. The per-turn metrics key set is unchanged.
result: pass
notes: |
  Set name="Captain Test", role="friendly SQL tutor…", expert/terse/aggressive,
  then clicked Apply. Status settled on "applied" with no "error" (the "applying…"
  window was sub-200ms, below the CDP sampling interval). The settled "applied" IS
  the native `persona.update` RPC ack returning — handler runs
  `await agent.update_instructions(render_persona(p))` +
  `session.tts.update_options(voice=p.voice_id)` and returns "applied"
  (agent/main.py:241-246). Agent kept emitting the unchanged per-turn metrics key
  set throughout. Audible next-turn voice swap is the one human-ear sub-claim not
  machine-observable, but the full apply→RPC→update path is verified end-to-end.

### 3. [03-01] Correction knob audibly scales; default trainer regression (PERS-07, PERS-01, DEPLOY-03)
expected: On browser join the agent greets and converses identically to Phase 2 with the default persona (Cybersecurity Trainer, gentle correction, `af_bella` voice) — no behavior change (PERS-01 / DEPLOY-03). Adjusting the correction-aggressiveness knob (gentle→moderate→aggressive) audibly scales how firmly the trainer corrects sloppy terminology (PERS-07).
result: pass
notes: |
  Regression: on join the agent greeted as the Cybersecurity Trainer
  ("…I'm your Cybersecurity Trainer. Let's jump right in.") — unchanged from
  Phase 2 (PERS-01/DEPLOY-03). Mechanism: `python /app/persona.py` self-check
  prints "persona _self_check OK" on the installed build — default render is
  byte-identical to the golden Phase-2-equivalent prompt. The three correction
  tiers render distinct, escalating instruction sentences (gentle "…move on
  without scolding" → moderate "…briefly say why the distinction matters" →
  aggressive "Actively catch…every time; restate…before you continue"), each
  applied live via the verified Apply path. The literal *audibility* of the
  scaling is the one human-ear sub-claim; the prompt chain producing it is
  verified.

### 4. [VM-INTROSPECT] API-signature reconcile on the installed builds
expected: Confirm on the VM — `Agent.update_instructions` is a coroutine; `openai.TTS.update_options(voice=)` accepts the voice kwarg and mutates the existing TTS (metrics subscription survives); `rtc.LocalParticipant.register_rpc_method` (snake_case) exists and the handler arg is `RpcInvocationData` with `.payload`; client `performRpc`/`registerRpcMethod` work on `livekit-client@2.20.0` and `useVoiceAssistant().agent.identity` is the correct RPC destination. If `update_options` is missing → recreate just the TTS plugin AND re-attach metrics; if RPC is missing → participant-attributes fallback (per 03-02-4).
result: pass
notes: |
  Introspected the installed agent build directly:
  - `inspect.iscoroutinefunction(Agent.update_instructions)` → True (coroutine).
  - `openai.TTS.update_options` params = [self, model, voice, speed, instructions]
    → accepts `voice`; mutates existing TTS (per-turn metrics survived Test 2).
  - `rtc.LocalParticipant.register_rpc_method` (snake_case) exists; True.
  - `RpcInvocationData.__init__` params include `payload`
    (request_id, caller_identity, payload, response_timeout).
  - Client: `livekit-client@2.20.0` (+ @livekit/components-react 2.9.21) confirmed
    in the web build; `performRpc`/`registerRpcMethod` proven by Test 2's
    successful round-trip; no fallback path needed.

### 5. [VM-INTROSPECT] Kokoro voice-list reconcile
expected: `curl http://kokoro:8880/v1/audio/voices` returns a list that includes every entry in the client/server `VOICE_IDS` (af_heart, af_bella, af_nicole, af_sarah, af_kore, am_michael, am_fenrir, am_puck, am_adam, bf_emma, bf_alice, bm_george, bm_daniel). Drop or correct any id the server does not serve.
result: pass
notes: |
  `curl http://127.0.0.1:8880/v1/audio/voices` returns a list containing all 13
  frozen VOICE_IDS (af_heart, af_bella, af_nicole, af_sarah, af_kore, am_michael,
  am_fenrir, am_puck, am_adam, bf_emma, bf_alice, bm_george, bm_daniel). No id
  dropped or corrected.

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

### Stale-deploy bug found + fixed during UAT (agent/Dockerfile)

The stack that was running at the start of UAT served code that predated this
phase: the `web` image (built before the 13:38 PersonaPanel commit) shipped a
`.next` bundle with NO PersonaPanel, and the `agent` image lacked the
`persona.update` RPC handler. The first CDP probe consequently saw zero persona
controls.

Rebuilding surfaced a real defect: `agent/Dockerfile` copied only
`metrics.py main.py` and omitted the new `persona.py`, so the rebuilt agent
crash-looped with `ModuleNotFoundError: No module named 'persona'`. Fixed by
adding `persona.py` to the COPY (commit `dd17ffa`,
"fix(03): copy persona.py into agent image"). After rebuild+recreate of `web`
and `agent`, the agent registered cleanly and all 5 tests passed.

Lesson: the execute/verify cycle for this phase did not rebuild the Docker
images, so the running stack never exercised the new code until UAT. A phase
that changes agent/web sources must `docker compose build web agent &&
docker compose up -d web agent` before verification.

### Human-ear sub-claims (not machine-observable)

Two sub-claims rely on hearing TTS and were verified by mechanism rather than by
ear: (Test 2) the next-utterance Kokoro voice swap, and (Test 3) the audible
scaling of correction firmness. Both full code paths that produce them are
verified end-to-end; only the final acoustic perception is unconfirmed. Flag for
an optional quick listen on the VM if desired.
