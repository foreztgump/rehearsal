# Phase 2 Research: Bare Voice Loop (MVP Gate)

**Phase goal:** Ship the hard MVP gate — a browser SPA where the user speaks open-mic
and holds a fully streamed near-real-time conversation with the default Cybersecurity
Trainer: VAD → semantic turn-detect → STT → LLM → first-sentence TTS, with instant
barge-in, an agent-state indicator, a live two-sided transcript, and per-turn latency
instrumentation.

**Mode:** mvp / vertical slices. First slice = thinnest end-to-end *audible* loop:
browser mic in → agent speaks back. Everything else (barge-in tuning, AEC, metrics
polish) layers on the working loop.

**Requirements covered:** VOICE-01..08, PERS-01, PERF-01, DEPLOY-03
**Plans:** 02-01 (SPA + LiveKit SDK + state pill + transcript), 02-02 (AgentSession
pipeline + default trainer persona), 02-03 (barge-in + AEC/noise-suppression +
endpointing tuning + per-turn metrics)

**Researched:** 2026-06-25 — grounded in the existing `.planning/research/{STACK,
ARCHITECTURE,PITFALLS}.md`, the Phase 1 summaries/patterns (what already exists), and
live verification of the LiveKit Agents 1.5 `AgentSession` API surface (endpointing,
interruption, agent-state events, frontend hooks) via Context7.

---

## TL;DR — What you must know to plan this phase well

1. **Almost everything is already wired — Phase 2 is mostly "turn it on."** Phase 1
   (`01-03`) already built `agent/main.py` with a fully-constructed `AgentSession`
   (Silero VAD + faster-whisper STT + Ollama LLM + Kokoro TTS + local
   `MultilingualModel` turn detector) and `session.start(...)`. **It does NOT speak yet**
   because there is no `generate_reply` / greeting and the browser never joins a room
   (the web app is a static "stack online" probe). Phase 2's job: add the agent's first
   utterance + entrypoint reply loop, build the real browser room-join UI, and tune the
   already-present pipeline. **Do not re-plumb the session, transport, metrics, or token
   path** — extend them.

2. **The endpointing-config API has TWO surfaces and you MUST verify which one the
   pinned `livekit-agents~=1.5` exposes before writing config.** Older/stable 1.5 takes
   `min_endpointing_delay` / `max_endpointing_delay` as direct `AgentSession(...)`
   kwargs. Newer docs show a `TurnHandlingOptions(turn_detection=..., endpointing={
   "mode": "dynamic"|"fixed", "min_delay":..., "max_delay":...})` object. **These are not
   interchangeable** — passing the wrong one throws `TypeError`. Action: in 02-03 (or a
   spike at 02-02 start) introspect the installed signature
   (`python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.__init__))"`)
   and pin the correct knob. The success criterion's target value is **`min_endpointing_delay`
   ~250–350ms** regardless of which surface carries it.

3. **First-sentence TTS streaming is FREE — `AgentSession` does it out of the box.** The
   pipeline already splits the LLM token stream on sentence boundaries and fires Kokoro on
   sentence 1 while the LLM keeps generating. You do **not** hand-roll a sentence splitter.
   The Phase-2 work is *verifying* it (first audio precedes full text; latency flat vs.
   response length — Pitfall 2) and tuning, plus optionally enabling
   `preemptive_generation=True` to start the LLM before end-of-turn commits (latency win,
   tune carefully against false interruptions).

4. **Barge-in is also built in — it's a tuning problem, not a build problem.** The
   `AgentSession` cancels TTS + rolls back the turn when the user starts talking. The
   risk is the *open-mic + speakers* case (Pitfalls 4 & 5): the agent hears itself and
   self-interrupts. Two defenses, both in-scope for 02-03: (a) browser-side AEC + noise
   suppression in `getUserMedia` constraints (`echoCancellation/noiseSuppression/
   autoGainControl: true`) — the primary echo defense, must be client-side; (b) raise the
   interruption gate (`min_interruption_duration` / VAD `activation_threshold`) so the
   agent's own tail and backchannels ("mm-hmm") don't cancel speech. **Server-side Krisp/
   ai-coustics noise-cancellation plugins are CLOUD — do NOT use them** (violates PERF-03
   local-first). Browser WebRTC AEC is the local path.

5. **The frontend should use `@livekit/components-react` + `useVoiceAssistant`, not
   raw `livekit-client` plumbing.** `useVoiceAssistant()` returns `{ agent, state,
   audioTrack, ... }` where `state` is exactly the listening/thinking/speaking pill
   (VOICE-06). `useTranscriptions()` (or the transcription text-stream) gives the live
   two-sided transcript (VOICE-07). `<RoomAudioRenderer/>` plays agent audio;
   `<StartAudio/>` handles the browser autoplay-gesture gate. The Phase-1 web app already
   has `@` nothing of this — only the token route exists. Add `livekit-client` +
   `@livekit/components-react` to `web/package.json`.

6. **Browser autoplay policy will silently swallow the agent's first audio** unless you
   gate playback behind a user gesture. The "click to start talking" button that requests
   mic permission doubles as the audio-unlock gesture. Plan one entry button that does
   both: `getUserMedia` (mic) + room connect + `room.startAudio()` / `<StartAudio/>`.

7. **Per-turn voice-to-voice latency instrumentation already has a scaffold
   (`agent/metrics.py`) — Phase 2 fills it with real numbers.** The per-plugin
   `metrics_collected` handlers are wired but only the warmup TTFT has ever fired. Phase 2
   drives real turns so EOU/STT/LLM-TTFT/TTS-TTFB populate. The one missing piece is the
   **end-to-end voice-to-voice number** (`e2e_ms`): LiveKit's `EOUMetrics` +
   per-stage metrics give the components, but you must define the v2v anchor (last user
   audio frame → first agent audio frame) and compute P50/P95 over a rolling window (the
   aggregation is currently a stub). Target this phase: **P50 < ~1.2s** (tightening to
   <1.0s by Phase 7).

---

## Requirement decoding

| ID | Means for this phase | Verification |
|----|----------------------|--------------|
| **VOICE-01** | Full streamed mic→STT→LLM→TTS loop produces spoken replies | Speak; hear a relevant spoken answer end-to-end |
| **VOICE-02** | Agent starts speaking on its first completed sentence (built into AgentSession) | First audio frame precedes full response text in transcript; latency flat vs. response length |
| **VOICE-03** | Instant barge-in: user speech cancels TTS | Talk over the agent; it stops within ~1 frame |
| **VOICE-04** | Semantic endpointing (MultilingualModel), not a fixed silence timer; `min_endpointing_delay` ~250–350ms | Agent waits through mid-thought pauses; no cut-in on "let me think…"; doesn't lag after a clear finish |
| **VOICE-05** | Hands-free open-mic VAD (no PTT) | No button held; Silero VAD drives turns |
| **VOICE-06** | Visible listening/thinking/speaking state pill | `useVoiceAssistant().state` drives a pill that matches reality |
| **VOICE-07** | Live two-sided transcript (user + agent) as it happens | Both sides stream into the transcript; partials update |
| **VOICE-08** | Per-turn voice-to-voice latency instrumented + visible | Structured per-turn metric line with EOU/STT/LLM-TTFT/TTS-TTFB + e2e; P50/P95 computed |
| **PERS-01** | Default Cybersecurity Trainer available immediately on load (no setup) | Page loads → connect → talking to the trainer within seconds |
| **PERF-01** | Voice-to-voice P50 < ~1.2s this phase (→ <1.0s by polish) | Instrumented e2e P50 over a session of turns |
| **DEPLOY-03** | Single-page UI; start talking within seconds; config optional/tucked aside | One entry button; no required setup before first turn |

---

## What Phase 1 already built (DO NOT rebuild — extend)

From `01-03-SUMMARY.md` and the live code (`agent/main.py`, `agent/metrics.py`,
`web/app/api/token/route.ts`):

| Asset | State after Phase 1 | Phase 2 action |
|-------|---------------------|----------------|
| `agent/main.py` `build_session()` | Full `AgentSession` (VAD/STT/LLM/TTS/MultilingualModel) constructed | Add the reply loop: greeting / `generate_reply` on user turn; default trainer persona text |
| `session.start(agent=Agent(instructions=...), room=ctx.room)` | Called, but no turn ever generated | Drive real turns; agent must speak |
| `PERSONA_INSTRUCTIONS` (main.py:53) | Generic "domain expert trainer" placeholder | Replace with the **Cybersecurity Trainer** default persona (PERS-01) |
| faster-whisper STT | `beam_size=1`, `condition_on_previous_text=False`, `vad_filter=True`, `language="en"` already set | Keep as-is (Pitfall 13 already handled) |
| Ollama LLM | `with_ollama`, resolved `OLLAMA_MODEL` tag, thinking OFF | Keep; confirm thinking stays off in live turns |
| Kokoro TTS | `af_bella` voice, streaming | Keep; voice selection is Phase 3 |
| `MultilingualModel()` turn detector | Local, weights baked, attached | Keep; **tune endpointing delay** (the live work) |
| `agent/metrics.py` | Per-plugin `metrics_collected` wired; warmup TTFT only; P50/P95 STUB; budgets encoded | Fill with real per-turn data; implement real rolling P50/P95; add e2e v2v anchor |
| `web/app/api/token/route.ts` | Mints a valid LiveKit JWT (`roomJoin`, `canPublish`, `canSubscribe`), room `adept` | Reuse as-is; the SPA fetches a token from here |
| `web/app/page.tsx` + `SecureContextProbe` | Static "stack online" + mediaDevices probe | Replace with the real room-join voice UI |
| Caddy TLS (443 web, **7443 LiveKit WS vhost**) | Secure context proven; `wss://` pre-fronted | Browser connects to `wss://<lan-host>:7443` |
| livekit.yaml | LAN ICE (udp mux 7882, node_ip), keys via env | Operator sets `LIVEKIT_NODE_IP` + opens UDP 7882/TCP 7881 for real media |

**Net:** Phase 2 is "make it speak + build the UI + tune," not "build the pipeline."

---

## Plan 02-01: Browser SPA + LiveKit SDK + agent-state pill + two-sided transcript

### Dependencies to add (`web/package.json`)
```
livekit-client            (~=2.x — the WebRTC client SDK)
@livekit/components-react (React hooks + prebuilt components)
```
`livekit-server-sdk@2.15.5` is already present (token mint). Match the client SDK major
to the server (server v1.10.x ↔ client 2.x is current per STACK.md).

### Room connection flow (the "within seconds" path — DEPLOY-03)
1. Page loads → render a single **"Start talking"** entry button (no config required).
2. Click → `fetch('/api/token')` → get `{ token, room }`.
3. Wrap UI in `<LiveKitRoom serverUrl={wss://<lan-host>:7443} token={token} connect
   audio video={false}>`. `audio` enables mic publish (open-mic — VOICE-05); the click is
   the secure-context gesture that also unlocks autoplay.
4. `<RoomAudioRenderer/>` inside the room renders the agent's audio track (plays the TTS).
5. `<StartAudio/>` (or `room.startAudio()`) covers the autoplay-gesture gate so the first
   agent audio isn't silently dropped by browser policy (TL;DR #6).

### Agent-state pill (VOICE-06)
`useVoiceAssistant()` returns `{ agent, state, audioTrack }`. `state` is one of
`initializing | idle | listening | thinking | speaking` — bind it directly to the pill.
The agent worker emits these via `agent_state_changed`; the SDK surfaces them through the
participant attribute `lk.agent.state` (no custom data-channel protocol needed for state).
(Optional prebuilt: `<BarVisualizer state={state} .../>` for a richer indicator.)

### Two-sided transcript (VOICE-07)
- The agent forwards STT (user) + LLM/TTS (agent) text over LiveKit **transcriptions** (a
  text stream on topic `lk.transcription`). On the frontend, `useTranscriptions()` (or
  the lower-level `room.registerTextStreamHandler('lk.transcription', ...)`) yields
  segments tagged by participant identity → render user vs. agent sides.
- For word-synced agent captions, enable `use_tts_aligned_transcript=True` on the
  `AgentSession` (verify the kwarg exists on the pinned version — see API-surface note).
  Without it you still get sentence-level agent transcript; aligned is a polish nicety,
  not required for VOICE-07.
- Partials update live; render the in-progress user partial so a VAD false-trigger shows
  as "visible nothing," not a hidden LLM call (UX pitfall).

### Frontend file layout (greenfield `web/app` — extend, don't restructure)
Per `.planning/research/ARCHITECTURE.md` the thin-web split is: `room` connect/track-sub,
`state` store (pill + transcript), components (`Transcript`, state pill). Keep it minimal
for the MVP slice — `@livekit/components-react` provides most of it; you mainly compose
hooks + a transcript list + a pill.

### Mic-permission / secure-context (carried enabler from Phase 1)
Phase 1 proved `navigator.mediaDevices` is defined over Caddy TLS. Phase 2 actually calls
`getUserMedia` (the SDK does it on connect with `audio`). Full mic-denial UX (REL-01) is
Phase 7 — but don't crash on denial here; a basic catch + message is cheap.

---

## Plan 02-02: AgentSession pipeline + default trainer persona

### Making it speak (the core MVP gate)
The session is constructed; what's missing is a reply. Two pieces:
- **Greeting on connect** (PERS-01 "talking within seconds"): after `session.start(...)`,
  call `session.generate_reply(instructions="Greet the user as the Cybersecurity Trainer
  and invite them to start.")` so the agent speaks first and the user immediately has a
  partner. (Or `say(...)` a fixed line — but `generate_reply` exercises the full LLM→TTS
  path and proves the loop.)
- **Per-turn replies**: with VAD + turn detector + STT + LLM + TTS all wired, the
  `AgentSession` automatically runs a turn when the user finishes speaking — no manual
  glue. Confirm the default behavior generates a reply per completed user turn.

### Default Cybersecurity Trainer persona (PERS-01)
Replace the placeholder `PERSONA_INSTRUCTIONS` (main.py:53) with a concrete Cybersecurity
Trainer system prompt: role, tone (gently corrects sloppy terminology toward precise
practitioner phrasing — PERS-07 is Phase 3, but the *default trainer* lands here), and a
"hold a natural spoken conversation that pulls the user into articulating the subject"
directive. Keep it as plain `Agent(instructions=...)`. **Forward-compat note:** Phase 3
introduces the frozen-prefix layout `[persona]+[KB]+[history]+[turn]`; write this persona
as the static top block so Phase 3 can slot a KB beneath it without a rewrite (don't build
the layout machinery now — just don't put volatile data in the system prompt).

### LLM thinking-OFF in live turns (latency-critical)
Phase 1 set `think=false` at warmup. Verify it holds for `AgentSession`-driven LLM calls
via `with_ollama` — a `<think>` preamble would destroy TTFT and break first-sentence TTS.
If `with_ollama` doesn't forward `think:false`, pass it through the model's options /
extra kwargs (the OpenAI-compat `/v1` endpoint has no native `think` field). Note: the
`adept-gemma` Modelfile's thinking-OFF is request-driven, NOT template-stripped (Modelfile:25-28)
— do not assume it bakes thinking off; if needed, ADD a template-level `<think>` strip and repoint.
**Confirm no `<think>` in live output** as a 02-02 acceptance check.

### First-sentence TTS streaming (VOICE-02) — verify, don't build
`AgentSession` streams LLM tokens → sentence splitter → Kokoro on sentence 1. Acceptance:
instrument first-TTS-audio timestamp vs. full-text-complete timestamp; the former must
precede the latter on any multi-sentence reply. Guard against bad splits on decimals/
abbreviations is the framework's job; only revisit if you hear audible mid-number glitches.

### Optional latency win: `preemptive_generation=True`
Starts the LLM generating while the turn detector is still confirming end-of-turn — shaves
perceived latency toward the P50 target. Trade-off: a wasted generation if the user wasn't
actually done (the framework discards it). Worth enabling and measuring in 02-02/02-03;
pair with endpointing tuning so it doesn't fight false interruptions.

---

## Plan 02-03: Barge-in + open-mic AEC/noise-suppression + endpointing tuning + metrics

### Endpointing tuning (VOICE-04) — the single biggest latency knob
- The semantic `MultilingualModel` decides "is the user actually done," guarded by a
  silence delay. Default `min_endpointing_delay` is **500ms** — half the entire P50
  budget (Pitfalls 1 & 6). Target **~250–350ms**: the semantic model lets you be faster
  *and* safer simultaneously (it prevents premature cut-in that a pure timer can't).
- **API-surface verification (BLOCKER — do first in 02-03):** determine whether the
  pinned `~=1.5` takes `AgentSession(min_endpointing_delay=0.3, max_endpointing_delay=...)`
  (seconds, direct kwargs — stable 1.5) **or** the newer
  `turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel(),
  endpointing={"mode":"dynamic","min_delay":0.3,"max_delay":...})`. Introspect the
  installed signature; pin the correct form. (`dynamic` mode adapts the delay to the
  user's actual pause statistics — preferable if available; `fixed` uses min/max directly.)
- Test on **deliberate, hesitant speech** ("let me think… the answer is…") — exactly the
  interview-style pattern Phase 6 will stress. No cut-in on mid-thought pauses; no dead air
  after a clear finish.

### Barge-in / interruption (VOICE-03) — built in; tune the gate
- `AgentSession` cancels TTS + rolls back the partial turn on user speech during playout.
  Knobs (verify exact names on pinned version): `allow_interruptions=True` (default),
  `min_interruption_duration` (require N ms of user speech before canceling — defends
  against the agent's own echo tail + "mm-hmm" backchannels), Silero VAD
  `activation_threshold` (raise 0.5→0.6–0.7 in noisy rooms — Pitfall 4).
- Newer 1.5 has **false-interruption handling**: if a barge-in produces no real transcript
  (a noise blip), the agent can *resume* its interrupted speech instead of dropping the
  turn. Check for `false_interruption_timeout` / `resume_false_interruption` on the pinned
  version and enable if present — it directly mitigates open-mic false triggers.

### Open-mic AEC + noise suppression (Pitfalls 4 & 5) — CLIENT-SIDE, local-first
- **The echo defense MUST run in the browser** (the reference playback signal only exists
  there). Set `getUserMedia` audio constraints explicitly:
  `{ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }`.
  The LiveKit JS SDK accepts these via track/room audio-capture options (e.g.
  `RoomOptions.audioCaptureDefaults` or the published-track constraints) — pass them when
  enabling the mic. These are on-by-default in Chrome/Firefox but **set them explicitly**
  so behavior is deterministic across browsers.
- **Do NOT use server-side noise-cancellation plugins** (`livekit.plugins.ai_coustics`,
  Krisp via `room_io.AudioInputOptions(noise_cancellation=...)`). They are cloud/licensed
  AI models → violate PERF-03 (no audio leaves the LAN) and the AGENTS.md local-first
  rule. Browser WebRTC AEC is the sanctioned local path.
- **Recommend headphones in the UI** as the clean path; if the agent self-interrupts with
  speakers, that's the #1 sign AEC/headphones are needed. Validate the worst case
  explicitly: laptop speakers + built-in mic in a small room (Pitfall 5 checklist item).

### Per-turn voice-to-voice latency metrics (VOICE-08, PERF-01)
- The scaffold (`agent/metrics.py`) already subscribes per-plugin `metrics_collected`:
  - **EOU** (`end_of_utterance_delay` on the VAD/turn metric) → `eou_ms`
  - **STT** (`duration`) → `stt_ms`
  - **LLM TTFT** (`ttft`) → `llm_ttft_ms`
  - **TTS TTFB** (`ttfb`) → `tts_ttfb_ms`
  These now fire on real turns — verify they populate (no longer null).
- **Add the end-to-end voice-to-voice number** (`e2e_ms`, currently null): the perceived
  metric is *last user audio frame → first agent audio frame*. LiveKit per-turn metrics
  give the stage components; sum/measure the v2v span and emit it per turn. Prefer
  LiveKit's built-in per-turn `MetricsReport` / `EOUMetrics` if it exposes a v2v field on
  the pinned version; otherwise compute from the stage timestamps.
- **Implement real P50/P95** (the rolling aggregation is a stub at `metrics.py:63`). One
  structured line per turn + a periodic P50/P95 summary over the rolling window
  (`ROLLING_WINDOW=100` already defined). Keep **local logs only** — no Prometheus/Opik/
  OTEL export (PERF-03). Optionally surface the latest e2e number in the UI for tuning
  ("visible for tuning" — VOICE-08), but a logged number satisfies the requirement.
- Budgets already encoded (eou 300 / stt 150 / llm_ttft 300 / tts_ttfb 150 / playout 100);
  a stage over budget is flagged. Phase-2 gate: **e2e P50 < ~1.2s**.

---

## Phase-2-relevant pitfalls (from PITFALLS.md, filtered)

| # | Pitfall | Phase 2 action |
|---|---------|----------------|
| 1 | Latency compounds silently | Fill the per-stage metrics with real numbers; enforce per-stage budgets as ACs |
| 2 | Not streaming TTS on first sentence | Verify first audio precedes full text (framework does it; prove it) |
| 4 | Open-mic VAD false triggers | Explicit `noiseSuppression`; raise Silero `activation_threshold`; semantic turn-detector guards |
| 5 | Agent hears itself (echo) | Client-side `echoCancellation:true`; raise interruption gate; recommend headphones; test speakers+mic |
| 6 | Endpointing cuts in / sluggish | Tune `min_endpointing_delay` ~250–350ms under the semantic model; test slow speech |
| 12 | (carried) HTTPS/WebRTC/LAN breaks mic | Operator sets `LIVEKIT_NODE_IP` + opens UDP 7882/TCP 7881; test on real LAN device |
| 13 | (handled in P1) faster-whisper streaming | Already configured; no change |

UX pitfalls to honor: instant unambiguous state pill (masks latency psychologically);
show the live user partial (false-trigger = visible nothing); barge-in not so aggressive it
stops on backchannels.

---

## Open questions / validation tasks to resolve during planning or execution

1. **Endpointing API surface** on the installed `livekit-agents~=1.5`:
   `min_endpointing_delay` kwarg vs. `TurnHandlingOptions`/`endpointing` dict. Introspect
   `AgentSession.__init__` signature; pin the correct knob. (Blocks 02-03.)
2. **`use_tts_aligned_transcript`, `preemptive_generation`, `min_interruption_duration`,
   `false_interruption_timeout` availability** on the pinned version — verify each kwarg
   exists before relying on it; degrade gracefully if not.
3. **Does `with_ollama` forward `think:false` in `AgentSession` LLM calls?** Confirm no
   `<think>` preamble in live replies (the `/v1` OpenAI-compat endpoint has no native
   `think` field). If it leaks, pass options explicitly over `/v1` or ADD a template-level
   `<think>` strip to the `adept-gemma` Modelfile (it is request-driven, not baked off —
   Modelfile:25-28) and repoint.
4. **LiveKit JS audio-constraint plumbing**: exact API to pass
   `echoCancellation/noiseSuppression/autoGainControl` (room `audioCaptureDefaults` vs.
   per-track publish options) on `livekit-client ~=2.x`.
5. **Transcript source on the frontend**: `useTranscriptions()` hook vs. registering a
   text-stream handler on topic `lk.transcription` — pick one; confirm both user and agent
   segments are tagged by participant for the two-sided split.
6. **v2v latency anchor**: does the pinned version expose an end-to-end voice-to-voice
   field in `MetricsReport`, or must `e2e_ms` be computed from stage timestamps? Resolve
   before implementing the metric.
7. **Client SDK major** to match server v1.10.x — confirm `livekit-client` 2.x is the
   right line and pin the exact version (AGENTS.md: never float tags).
8. **Greeting trigger**: `generate_reply` on session start vs. on first participant
   connect — pick the one that reliably fires once the browser joins.

---

## Build order within Phase 2 (vertical slices)

1. **02-01 first (thin slice to "I can join and hear"):** add `livekit-client` +
   `@livekit/components-react`; build the entry button → token fetch → `<LiveKitRoom>` →
   `<RoomAudioRenderer/>` + `<StartAudio/>`; wire `useVoiceAssistant().state` pill and
   `useTranscriptions()` transcript. (Agent may only greet at this point.)
2. **02-02 next (make it converse):** add the greeting + per-turn reply loop, swap in the
   Cybersecurity Trainer persona, verify thinking-off + first-sentence TTS streaming, try
   `preemptive_generation`.
3. **02-03 last (tune + measure):** verify/pin the endpointing API, tune
   `min_endpointing_delay` ~250–350ms, configure barge-in gate + client-side AEC/noise
   suppression, fill the metrics scaffold with real per-turn + e2e numbers and real
   P50/P95, hit e2e P50 < ~1.2s.

**Phase-2 done = all 5 success criteria TRUE:** user is talking to the trainer within
seconds hands-free; agent speaks on its first sentence and stops instantly on barge-in;
semantic endpointing (~250–350ms) waits for a finished thought; state pill + two-sided
transcript are live; per-turn v2v latency is instrumented and P50 < ~1.2s. **This is the
hard MVP gate — Phase 3 (persona) layers over the working loop.**

---

## Validation Architecture

Phase 2 is the first phase where latency claims are *measurable on real turns*, so the
validation surface is dense. Map each success criterion to an observable signal:

| Success criterion | Validation signal | Where measured |
|-------------------|--------------------|----------------|
| Talking within seconds, hands-free (1) | Time from page-load→first agent audio; no PTT button exists | Manual on real LAN device; mic via open-mic VAD only |
| First-sentence TTS + instant barge-in (2) | first-TTS-audio ts < full-text-complete ts; TTS cancels within ~1 frame of user speech | `agent/metrics.py` timestamps + manual barge-in test |
| Semantic endpointing ~250–350ms (3) | `eou_ms` distribution; no cut-in on "let me think…" pause; no dead air after finish | Per-turn metric line + slow-speech manual test |
| State pill + two-sided transcript (4) | `useVoiceAssistant().state` matches reality; both sides stream into transcript | Manual UI observation |
| v2v P50 < ~1.2s instrumented (5) | `e2e_ms` per turn; rolling P50/P95 over a session | `agent/metrics.py` rolling aggregation (local logs) |

**Nyquist relevance:** the keystone invariant is **flat per-turn TTFT** (it must not climb
as the session grows). Phase 2 establishes the *baseline* TTFT and the measurement rig;
later phases (KB, history) must prove TTFT stays flat against this baseline. So Phase 2's
metrics output is itself a validation contract for downstream phases — emit `llm_ttft_ms`
per turn from turn one and keep the structured-line format stable so Phase 4/5 can assert
turn-2-TTFT ≪ turn-1 and no creep over N turns.

**Sandbox limitation (carried from Phase 1):** this execution environment has no Docker
daemon and no browser. The audible loop, barge-in, AEC, and live latency numbers are
**operator gates** — they must be run on the Proxmox VM with the stack up and a real
CA-trusted LAN device (with `LIVEKIT_NODE_IP` set and UDP 7882/TCP 7881 open). Plans
should produce client-verifiable artifacts (compiles, type-checks, signature introspection,
config correctness) and explicitly list the hardware/browser gates for the operator, as
Phase 1 did.

---

## Sources

- Existing project research: `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md`
  (HIGH confidence, June 2026 stack verification) — pipeline model, endpointing/barge-in/
  echo pitfalls, frozen-prefix layout, VRAM budget.
- Phase 1 artifacts: `01-RESEARCH.md`, `01-PATTERNS.md`, `01-0{1,2,3}-SUMMARY.md`, and live
  code (`agent/main.py`, `agent/metrics.py`, `web/app/api/token/route.ts`,
  `web/app/page.tsx`) — what already exists.
- LiveKit Agents docs (via Context7 `/websites/livekit_io_agents`,
  `/livekit-examples/agent-starter-python`): `AgentSession` constructor
  (`preemptive_generation`, `use_tts_aligned_transcript`), turn-handling/endpointing
  (`min_delay`/`max_delay`, `mode: fixed|dynamic`, `TurnHandlingOptions`), agent-state /
  user-state events (`agent_state_changed`, states initializing/idle/listening/thinking/
  speaking), `useVoiceAssistant` React hook, `RoomAudioRenderer`/`StartAudio`,
  transcription forwarding, server-side noise-cancellation plugin (flagged as cloud —
  avoided).
- MDN getUserMedia audio constraints (`echoCancellation/noiseSuppression/autoGainControl`)
  — browser-side AEC, the local-first echo defense.

---
*Phase 2 research — Bare Voice Loop (MVP Gate). Researched 2026-06-25.*
