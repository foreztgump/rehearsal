# Feature Research

**Domain:** v1.1 Local-First Pipeline Swap + Avatar — LLM speed selector, streaming ASR, VRAM-aware STT placement, optional 3D talking-head avatar, deferred v1.0 polish (Adept)
**Researched:** 2026-06-26
**Confidence:** HIGH

This is a SUBSEQUENT-milestone feature study. The v1.0 feature landscape (voice loop, persona, KB, interview mode, latency instrumentation) is already shipped and is NOT re-researched here — it is treated as the *existing pipeline* that every v1.1 feature depends on. Scope is strictly the four new parts (A LLM selector, B streaming ASR, C STT placement, D avatar) plus the rolled-in deferred polish (SESS-/REL-).

Grounded in: **met4citizen/TalkingHead + HeadAudio + HeadTTS** API surface and the OpenAI-Realtime/HeadAudio WebRTC Path-A demo; **NVIDIA Nemotron streaming ASR / Cache-Aware FastConformer** streaming semantics; **LiveKit Agents** STT-plugin + interrupt model; streaming-ASR partial/final UX guidance (Deepgram, AssemblyAI, Forasoft 2026 playbook); and product precedent for model/speed selectors (ChatGPT model picker, Perplexity Fast/Pro, GitHub Copilot model dropdown).

---

## Feature Landscape

Each v1.1 part is categorized internally as table stakes / differentiator / anti-feature, because a single part (e.g. the avatar) contains all three.

### Table Stakes (Users Expect These)

Missing any of these and the corresponding v1.1 part feels broken or unfinished relative to the apps users already use.

| Feature | Why Expected | Complexity | Dependency on existing pipeline | Notes |
|---------|--------------|------------|---------------------------------|-------|
| **A. Persistent speed/quality selector with a sane default** | Every model picker (ChatGPT, Copilot, Perplexity) remembers your last choice; a selector that resets each turn feels broken | LOW | Persona/session layer; selected LLM feeds the existing Ollama `with_ollama` brain | Two options only — "Fast" (default) / "Better". Persist for the session (localStorage / session state). Switch applies **next turn** (next session acceptable per scope). |
| **A. Plain-language labels, not model IDs** | Users pick an *experience*, not a GGUF tag; exposing `gemma-4-E4B...heretic-Q4_K_M` is a leak | LOW | None (UI string mapping) | Label by outcome: "Fast — snappier replies" / "Better — more thoughtful". Hide the underlying Ollama tag. |
| **A. Switch takes effect without tearing down the session** | A persona hot-swap already works mid-session; a model swap that drops the call feels worse | MEDIUM | Reuses the `persona.update`-style in-session RPC + Ollama keep-alive (both models resident or warm-swapped) | Next-turn application is fine; do NOT interrupt current TTS to switch. |
| **B. Growing (interim) transcript while the user speaks** | Native streaming ASR's whole point; users see words appear as they talk, like dictation/captions everywhere | MEDIUM | Replaces faster-whisper behind the existing LiveKit STT plugin; feeds the existing two-sided transcript panel | Interim text visually distinct from final (lighter/italic). This *replaces* whisper's chunked "appears after you stop" behavior. |
| **B. Fast finalize at end-of-speech (~100ms)** | After you stop talking the line must "lock" almost immediately, or it feels laggy even if the LLM is fast | MEDIUM | Couples to existing turn-detection/endpointing; finalize must precede LLM trigger | "~100ms finalize" = the gap between end-of-speech and the transcript line becoming final/committed, NOT total latency. User-visible effect: the interim text stops shimmering and settles instantly. |
| **B. Native punctuation + capitalization in the displayed transcript** | A wall of lowercase unpunctuated text reads as low-quality; Nemotron emits caps/punctuation natively | LOW | Display-only; transcript panel already exists | No client-side truecasing/punctuation post-processing needed — surface what the model emits. Improves both transcript readability and LLM input quality. |
| **C. STT placement is invisible and decided once** | Users should never see or choose GPU-vs-CPU STT; it must "just work" within VRAM | MEDIUM | Coupled to the Part-A LLM choice + the 16GB budget; resolved at **session start** | Resolve once per session (no mid-session thrash). Global CPU-ONNX fallback if E4B+GPU-STT+Kokoro can't co-fit. Failure mode to avoid: OOM crash instead of graceful CPU placement. |
| **D. Default-OFF avatar toggle ("Voice only / Avatar")** | An avatar that's forced on, or that you can't turn off, is an anti-feature; voice-only is the proven product | LOW | Frontend-only; voice-only path must stay byte-for-byte identical to pre-avatar | The toggle IS the escape hatch. Default Voice only. No server pipeline change in either mode. |
| **D. Audio-driven lip-sync that tracks the actual Kokoro audio** | A talking head whose mouth doesn't match the audio is uncanny and worse than no face | MEDIUM-HIGH | Routes the **inbound** Kokoro WebRTC audio through HeadAudio (Path A); zero server change | Path-A HeadAudio worklet does viseme detection on the audio stream itself — no transcript/timestamps, no TTS change. |
| **D. Avatar stops instantly on barge-in** | The existing barge-in is a core value; an avatar that keeps mouthing after the user interrupts breaks the illusion | MEDIUM | Reuses the existing LiveKit user-speech-start interrupt → `streamInterrupt()` | One turn-taking source of truth. No second VAD. When LiveKit fires interrupt, call `streamInterrupt()` to halt avatar speech/lip-sync. |
| **SESS-01/02/03. Session controls: new / reset / end** | Basic lifecycle; "start over" / "end and clear" is expected in any session tool | LOW-MEDIUM | Must clear ephemeral KB + history + transcript; ties into existing ephemeral-session design | End MUST clear all ephemeral state incl. the KB brief (privacy posture). Reset = same session id, cleared context. New = fresh session. |
| **SESS-04. Transcript export/download** | The live transcript already exists; users expect to save it for review | LOW | Serializes the existing in-memory two-sided transcript | Plain, openable format (`.txt` and/or `.md`), with speaker labels + timestamps. No server round-trip needed. |
| **REL-01. Graceful mic-permission-denied prompt** | Voice apps fail predictably; a silent dead mic reads as "app is broken" | LOW-MEDIUM | Wraps the existing `navigator.mediaDevices` getUserMedia gesture | Detect denied/blocked permission, show an actionable prompt (how to re-enable), don't silently no-op. |
| **REL-02. Garbled/empty-transcription reprompt** | Responding to noise/empty STT with a hallucinated answer feels broken | LOW-MEDIUM | Gate between the new streaming STT final and the LLM trigger | If final transcript is empty/below a confidence/length floor, agent says a short "didn't catch that" reprompt instead of generating on noise. Streaming ASR makes empties more frequent (more endpoints) — explicitly handle. |

### Differentiators (Competitive Advantage)

Where v1.1 raises Adept above its own v1.0 and above generic voice agents. These map to Core Value: *a credible expert at sub-1s latency* — now extended to *interview-credible eye contact*.

| Feature | Value Proposition | Complexity | Dependency on existing pipeline | Notes |
|---------|-------------------|------------|---------------------------------|-------|
| **A. User-controlled latency↔quality trade per session** | Most local voice apps pin one model; letting the user pick "snappy drilling" vs "thoughtful answers" without leaving the session is a genuine usability edge | MEDIUM | Both models served by the same Ollama; keep-alive/flash-attn/thinking-off/capped num_predict preserved for both | The differentiator is *the user owns the trade-off*, live. Fast=E2B default keeps the headline sub-1s feel; Better=E4B for depth. |
| **B. True streaming feel (dictation-like) on a local English ASR** | faster-whisper felt chunky; Nemotron's growing transcript makes the user feel *heard in real time* — a qualitative leap for a practice tool | MEDIUM-HIGH | Drop-in behind LiveKit STT plugin; NeMo HTTP server | The perceptual win is the live shimmer + instant lock, not raw WER. `att_context_size [56,3]` is the latency/accuracy knob (smaller left-context = lower latency). |
| **B. `att_context_size` as a config knob** | Lets the operator tune the streaming latency/accuracy point to the target GPU without re-architecting | LOW (knob) / MEDIUM (validate) | Config surface on the NeMo server | Not user-facing; a deployment dial. Document the default `[56,3]` and the trade. |
| **D. Eye contact held while speaking AND while listening** | **The eye contact IS the point** for interview framing — a credible mock interviewer looks at you when they ask and when they listen. Yoodli/Interview Warmup have no embodied gaze at all | MEDIUM | Frontend; driven by avatar state + LiveKit speaking/listening events | `makeEyeContact(t)` to hold gaze; tune speaking-eye-contact vs listening-eye-contact factors so gaze persists through both turns. `lookAtCamera()` on sentence starts (HeadAudio `onstarted` + >150ms pause heuristic) for natural re-engagement. |
| **D. Mood / affect mapped per persona** | A "hostile panel interviewer" persona that looks neutral-friendly undercuts the difficulty knob; mood makes the persona embodied | MEDIUM | Persona config extended with an avatar mood; reuses existing persona system | `setMood(mood)` from persona config (neutral/happy/etc). Map difficulty/correction knobs → mood where sensible. |
| **D. Interview camera framing ("upper" / "head")** | An interview is shot head-and-shoulders; full-body breaks the framing. Selectable framing makes it read as a real interview | LOW | Frontend `cameraView` option | `cameraView: "upper"` (head-and-shoulders) default for interview; `"head"` for close eye-contact. Set at avatar init / on mode change. |
| **D. Persona↔avatar GLB mapping (reuse the voice)** | Each persona can carry a face + mood while keeping its Kokoro voice — the persona system becomes audiovisual without a second config surface | MEDIUM | Extends the existing persona dataclass (already maps voice); default cyber-trainer gets a default GLB | Persona specifies an avatar GLB + mood; voice unchanged. Default persona ships a default avatar so Avatar mode works out of the box. |
| **D. Graceful ~30fps degradation** | A talking head that tanks the frame rate on a busy GPU/older client is worse than voice-only; smooth degradation keeps it credible | MEDIUM | Client-side WebGL only; zero server VRAM | Target `modelFPS: 30`, Draco/Meshopt-compressed GLBs. Degrade frame rate / detail rather than stutter; the toggle remains the hard escape hatch. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **A. More than two models / a full model zoo** | "Let me pick any Ollama model" | Choice overload; each model needs per-build chat-template + thinking-off verification and a VRAM placement story; explodes the Part-C matrix | Exactly two curated, verified options (Fast/Better). Larger model is a documented 24GB future hook, not a UI option. |
| **A. Per-turn / always-prompting model switch** | "Ask me which model each time" | Adds friction to a live voice loop; defeats the persistence table-stake | Persist for the session; switch silently takes effect next turn. |
| **A. Showing latency numbers / token speed in the picker** | "Power users want metrics" | Turns a simple choice into a benchmark UI; the P50/P95 instrumentation is internal | Outcome labels only. Keep latency instrumentation in the existing internal metrics, not the picker. |
| **B. Client-side punctuation/truecasing post-processing** | "Clean up the transcript" | Nemotron emits native caps/punctuation; re-processing adds latency and can fight the model | Surface the model's native output as-is. |
| **B. Mid-session STT GPU↔CPU thrashing / auto-rebalancing** | "Dynamically use the best device" | Reloading a NeMo/ONNX model mid-call stalls the loop and risks OOM; placement churn is user-visible jank | Resolve placement ONCE at session start; global CPU-ONNX fallback. (Already Out of Scope in PROJECT.md.) |
| **B. Multilingual STT (nemotron-3.5)** | "Support other languages" | English checkpoint is the one with the 4-bit ONNX CPU port Part C needs; app is English cyber/interview prep | English-only by design. (Out of Scope.) |
| **D. In-browser TTS (TalkingHead Path B / HeadTTS / in-browser Kokoro)** | "Avatar could speak on its own / save a hop" | Replaces the server-side Kokoro the whole pipeline is built on; duplicates TTS; breaks pipeline isolation | **Path A only** — drive lip-sync from the inbound Kokoro audio. TTS stays server-side. (Out of Scope.) |
| **D. Webcam / real video capture of the user** | "Show me on camera like a real interview" | Privacy violation of the local-first posture; not needed — the avatar is the *agent's* face, not the user's | Rendered talking head only; no `video` track from the user. (Out of Scope.) |
| **D. Public redistribution of avatar GLB assets** | "Bundle nice avatars for everyone" | Licensing risk; RPM/Avaturn GLBs have usage terms | Personal/internal use only for v1.1; confirm licensing before any redistribution. (Out of Scope.) |
| **D. Avatar gating / replacing voice-only as default** | "It looks cooler, make it default" | Voice-only is the proven, lowest-overhead, most-reliable path; avatar is additive | Default Voice only; avatar is an explicit opt-in with a guaranteed-identical voice-only fallback. |
| **D. Second VAD / separate avatar turn-taking** | "Avatar needs to know when to stop" | Two turn-taking sources desync; double-trigger barge-in | Reuse the existing LiveKit interrupt → `streamInterrupt()`. One source of truth. |
| **SESS. Persisting transcripts/KB across sessions for "history"** | "Let me see past sessions" | Conflicts with the ephemeral/privacy posture; End must *clear* state | Export-on-demand only; no cross-session persistence. (Out of Scope.) |

---

## Feature Dependencies

```
EXISTING PIPELINE (v1.0, shipped — do not rebuild)
  LiveKit Agents (transport, turn-detect, barge-in interrupt)
  Ollama brain (keep-alive, flash-attn, thinking-off, capped num_predict)
  Kokoro TTS (server-side, OpenAI-compatible)
  Persona system (maps voice; frozen-prefix + KB cache)
  Two-sided live transcript + agent-state indicator
  Ephemeral session + KB
  Per-turn latency instrumentation (P50/P95)

PART A — LLM speed selector
    ├──requires──> Ollama serving BOTH models (E2B Fast / E4B Better)
    ├──requires──> per-build chat-template + thinking-off verification (stock gemma4 fallback)
    ├──requires──> session-persisted selection (UI) + next-turn in-session swap (reuses persona.update-style RPC)
    └──couples───> PART C (selected LLM determines VRAM headroom → STT placement)

PART B — Nemotron streaming ASR
    ├──replaces──> faster-whisper behind the existing LiveKit STT plugin
    ├──requires──> NeMo local HTTP server (multi-GB, ~10-min first install)
    ├──exposes───> growing interim transcript + ~100ms finalize + native caps/punct  ──> existing transcript panel
    ├──exposes───> att_context_size knob (latency/accuracy)
    ├──feeds─────> turn-detection/endpointing (finalize before LLM trigger)
    └──enables───> REL-02 (empty/garbled final → reprompt gate)

PART C — VRAM-aware STT placement
    ├──requires──> PART A (which LLM) + 16GB budget accounting
    ├──decides───> GPU full-NeMo  OR  4-bit ONNX CPU port  (resolved once at session start)
    └──fallback──> global CPU-ONNX STT (simplest-robust; makes the picker VRAM-safe)

PART D — Avatar (frontend-only, MUST NOT touch server pipeline)
    ├──requires──> inbound Kokoro WebRTC audio (Path-A HeadAudio worklet → visemes)
    ├──requires──> existing LiveKit interrupt ──> streamInterrupt() (barge-in, no 2nd VAD)
    ├──requires──> persona config extended with GLB + mood (reuses voice mapping)
    ├──provides──> makeEyeContact / lookAtCamera (eye contact speaking+listening)
    ├──provides──> setMood (persona affect), cameraView upper/head (interview framing)
    ├──requires──> ~30fps WebGL render, Draco/Meshopt GLB, graceful degradation
    └──guarded───> default-OFF toggle; voice-only path byte-for-byte unchanged

DEFERRED POLISH (rolled in)
  SESS-01/02/03 (new/reset/end) ──requires──> ephemeral session + KB clearing
  SESS-04 (export) ──requires──> existing in-memory transcript
  REL-01 (mic-denied) ──wraps──> getUserMedia gesture
  REL-02 (garbled/empty) ──requires──> PART B final + LLM-trigger gate
  Latency tuning ──validates──> PART A (both LLMs) + PART B (sub-100ms finalize) hold P50<1.0s/P95<1.5s
```

### Dependency Notes

- **Part A couples to Part C, not just the UI:** the selected LLM is the *input* to STT placement. The picker can't be considered done until Part C guarantees the chosen model + STT + Kokoro co-fit (or the CPU-ONNX fallback engages). This is the single most important cross-part dependency.
- **Part B replaces, it does not add:** Nemotron slots into the *existing* LiveKit STT plugin seat faster-whisper occupied. The interim/final stream feeds the *existing* transcript panel and the *existing* endpointing — no new UI subsystem, but the panel must learn to render interim-vs-final styling.
- **Part B enables REL-02:** streaming ASR produces more endpoints (and thus more empty/garbled finals); the empty/garbled reprompt gate is the natural place to filter them before the LLM. Build REL-02 on top of Part B's final, not on whisper's old behavior.
- **Part D is strictly downstream of the audio + interrupt events and changes nothing server-side:** every avatar behavior is driven by signals the pipeline already emits (inbound audio, speaking/listening state, interrupt). This is what lets voice-only stay byte-for-byte identical and keeps server VRAM cost at zero.
- **The avatar's interview credibility is a *bundle*, not one feature:** eye-contact-while-speaking + eye-contact-while-listening + mood + upper/head framing must ship together, or the "credible interviewer" effect doesn't land. Eye contact alone with wrong framing, or framing alone with a dead stare, both read as uncanny.
- **Persona system is the integration point for Part A (model is per-session, not per-persona) and Part D (GLB+mood is per-persona):** note the asymmetry — the *model choice* is a session-level user control, while the *avatar/mood* is persona-level config that reuses the existing voice mapping.
- **SESS-03 (end) is the privacy keystone:** it must clear the KB brief and history, consistent with the ephemeral posture. Avatar GLB unload happens here too.

---

## MVP Definition

### Launch With (v1.1)

The whole milestone is the "launch." Parts A/B/C and the SESS/REL polish are required; Part D is optional/default-off but in scope.

- [ ] **A** Two-option Fast/Better picker, default Fast, session-persisted, next-turn swap — the user-owned latency/quality trade
- [ ] **A** Both models preserve thinking-off / streaming / keep-alive / flash-attn / capped num_predict; per-build template + thinking-off verification with stock gemma4 fallback
- [ ] **B** Nemotron streaming ASR behind LiveKit STT plugin: growing interim transcript, ~100ms finalize, native caps/punctuation, `att_context_size` knob
- [ ] **C** STT placement resolved once at session start, coupled to the selected LLM, with global CPU-ONNX fallback (no mid-session thrash, no OOM)
- [ ] **SESS-01/02/03** New / reset / end session, end clears ephemeral state incl. KB
- [ ] **SESS-04** Transcript export/download (txt/md, speaker labels + timestamps)
- [ ] **REL-01** Graceful mic-permission-denied prompt
- [ ] **REL-02** Garbled/empty-transcription reprompt (built on Part B final)
- [ ] **Latency tuning** Confirm P50<1.0s / P95<1.5s holds for BOTH LLMs and the new STT leg
- [ ] **D (optional, default-OFF)** Avatar toggle, Path-A lip-sync on Kokoro audio, `streamInterrupt()` barge-in, eye-contact (speaking+listening), mood, upper/head framing, persona↔GLB mapping, ~30fps graceful degradation

### Add After Validation (v1.x)

- [ ] Per-persona model defaults — trigger: users want a persona to default to Better without per-session re-picking
- [ ] More avatar moods / gesture vocabulary (`speakWithHands`, emoji) — trigger: avatar adopted and base behaviors feel flat
- [ ] User-selectable avatar GLB per session (beyond persona default) — trigger: demand for face customization
- [ ] Operator-exposed `att_context_size` profiles (low-latency vs high-accuracy) — trigger: hardware variance across user machines

### Future Consideration (v2+)

- [ ] Larger "Best" model tier (Gemma 26B-A4B / Qwen3 8B) on 24GB — defer: needs headroom most target machines lack; keep two-option simplicity for v1.1
- [ ] Nemotron cyber-vocab fine-tuning — defer: explicit future hook, prompt-engineering covers v1.1
- [ ] Multilingual STT — defer: out of scope; English checkpoint required for the CPU-ONNX port
- [ ] In-browser TTS / Path B / cloned avatar voice — defer: pipeline isolation; TTS stays server-side Kokoro
- [ ] Avatar GLB redistribution bundle — defer: licensing must be re-confirmed first

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| A. Fast/Better picker (default+persist+next-turn) | HIGH | MEDIUM | P1 |
| A. Both-model template/thinking-off verify + fallback | HIGH (correctness) | MEDIUM | P1 |
| B. Streaming interim transcript + ~100ms finalize | HIGH | MEDIUM-HIGH | P1 |
| B. Native punctuation/capitalization surfacing | MEDIUM | LOW | P1 |
| B. att_context_size knob | LOW (user) / MEDIUM (ops) | LOW | P1 |
| C. Session-start VRAM-aware placement + CPU-ONNX fallback | HIGH (no-crash) | MEDIUM | P1 |
| SESS-01/02/03 new/reset/end + KB clear | MEDIUM | LOW-MEDIUM | P1 |
| SESS-04 transcript export | MEDIUM | LOW | P1 |
| REL-01 mic-denied prompt | MEDIUM | LOW-MEDIUM | P1 |
| REL-02 garbled/empty reprompt | MEDIUM | LOW-MEDIUM | P1 |
| Final latency tuning (both LLMs) | HIGH | MEDIUM | P1 |
| D. Default-off avatar toggle + voice-only isolation | MEDIUM | LOW | P1 (of optional Part D) |
| D. Path-A Kokoro-audio lip-sync | HIGH (if avatar on) | MEDIUM-HIGH | P1 (of optional Part D) |
| D. streamInterrupt() barge-in | HIGH (if avatar on) | MEDIUM | P1 (of optional Part D) |
| D. Eye contact speaking+listening (the point) | HIGH (interview) | MEDIUM | P1 (of optional Part D) |
| D. Mood + upper/head framing + persona↔GLB | HIGH (interview) | MEDIUM | P1 (of optional Part D) |
| D. ~30fps graceful degradation | MEDIUM | MEDIUM | P2 |

**Priority key:**
- P1: Required for the v1.1 milestone (Part D's P1s apply *if* Avatar mode is built — it's optional but, if shipped, these are its non-negotiables)
- P2: Should-have within its part
- P3: Future

---

## Competitor / Precedent Feature Analysis

| Feature | Precedent A | Precedent B | Our Approach (Adept v1.1) |
|---------|-------------|-------------|---------------------------|
| Speed/quality model selector | ChatGPT model picker (named models, persisted) | Perplexity "Fast/Pro", Copilot model dropdown | Two outcome-labeled options (Fast default / Better), session-persisted, next-turn swap, model IDs hidden |
| Streaming ASR transcript UX | Deepgram/AssemblyAI partial→final WebSocket (interim styled, final committed) | Dictation/live captions (growing text) | Nemotron native streaming: growing interim, ~100ms finalize, native caps/punct into the existing two-sided panel |
| Talking-head avatar | met4citizen TalkingHead + HeadAudio Path-A (audio-driven visemes, moods, gaze) | HeyGen/OmniHuman (cloud, video-gen, heavy) | Local client-side WebGL, Path-A on Kokoro audio, eye-contact+mood+framing, default-off, zero server cost |
| Embodied interview gaze | Yoodli / Interview Warmup (no embodied gaze at all) | Generic 3D agents (look-ahead only) | `makeEyeContact` held while speaking AND listening + `lookAtCamera` on sentence start — eye contact is the point |
| Session lifecycle + export | Most chat tools (new/clear/export) | Voice tools (end-call clears) | new/reset/end with ephemeral KB clear; on-demand transcript export; no cross-session persistence |

**Net differentiation:** v1.1 keeps Adept's local-first, sub-1s, fully-private wedge while adding (1) a user-owned latency↔quality dial no fixed-model local app offers, (2) a genuinely streaming local English ASR that feels like real-time dictation, and (3) an optional, interview-credible embodied interviewer whose held eye contact (speaking and listening) is something the named interview-prep competitors — being non-conversational and faceless — structurally cannot match. All three are achieved with zero added server GPU cost for the avatar and no regression to the existing voice loop.

---

## Sources

- met4citizen/TalkingHead — class API (`makeEyeContact`, `lookAtCamera`, `setMood`, `streamInterrupt`, `streamAudio`/`streamStart`, `cameraView` full/mid/upper/head, `modelFPS`, Draco): github.com/met4citizen/talkinghead, examples/minimal.html
- met4citizen/HeadAudio — Path-A audio-driven viseme worklet, `onstarted`/`onended` sentence-gap eye-contact heuristic (>150ms → `lookAtCamera`), TalkingHead `opt.update` binding: libraries.io/npm/@met4citizen/headaudio, npmjs.com/~met4citizen; OpenAI-Realtime + HeadAudio WebRTC Path-A demo
- Streaming ASR partial/final UX — interim (fast, may change) vs final (confirmed) two-output model; sub-300ms TTFT enabling barge-in/full-duplex: Deepgram real-time guide, AssemblyAI "choosing a STT API for voice agents", Forasoft 2026 speech+NLP playbook
- NVIDIA Nemotron streaming ASR / Cache-Aware FastConformer-RNNT — native streaming, `att_context_size` left/right context as the latency/accuracy knob, 4-bit ONNX CPU port (English checkpoint): PROJECT.md decisions + LiveKit Nemotron voice-agent example
- Model-selector product precedent — ChatGPT model picker, Perplexity Fast/Pro, GitHub Copilot model dropdown (persisted, plain-label patterns)
- Project context — .planning/PROJECT.md (v1.1 Active list, Out of Scope, Context, Key Decisions), .planning/MILESTONES.md (deferred SESS-/REL- requirements)

---
*Feature research for: v1.1 Local-First Pipeline Swap + Avatar (LLM selector, streaming ASR, VRAM-aware STT placement, optional talking-head avatar, deferred polish)*
*Researched: 2026-06-26*
