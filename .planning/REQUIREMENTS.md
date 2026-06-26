# Requirements: Adept — Near-Real-Time Voice Persona Trainer

**Defined:** 2026-06-26
**Milestone:** v1.1 Local-First Pipeline Swap + Avatar
**Core Value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.

> Scope note: Parts A/B/C touch the server pipeline; **Part D (avatar) is frontend-only and MUST NOT change the server pipeline in any way.** The cybersecurity-trainer persona prompt is UNCHANGED and is the ONLY content guardrail (the new LLMs are uncensored/abliterated). REQ-IDs `SESS-01..04` and `REL-01/02` are the deferred v1.0 polish carried verbatim into v1.1; new categories (`LLM`, `STT`, `AVTR`) and continued numbering (`DEPLOY-04+`, `PERF-04`) are new to v1.1.

## v1.1 Requirements

Requirements for the v1.1 milestone. Each maps to a roadmap phase.

### LLM — User-Selectable Models (Part A)

- [x] **LLM-01**: User can select a response model via a Fast / Better picker in the UI (plain-language labels — "Fast (snappier)" / "Better (more thoughtful)" — never raw Ollama tags)
- [x] **LLM-02**: The selected model is configurable-default Fast (E2B), persists for the session, and a switch takes effect on the next turn without tearing down the session or interrupting current TTS
- [x] **LLM-03**: Both models are pulled and served via Ollama — Fast `evalengine/unbound-e2b:latest`, Better `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` — and the LiveKit agent's LLM plugin targets the selected model's tag
- [x] **LLM-04**: Both models preserve thinking DISABLED, token-by-token streaming, OLLAMA_KEEP_ALIVE (model stays resident), flash attention on, lean/sliding-window context, and a capped num_predict
- [ ] **LLM-05**: Each model build is verified before wiring — chat template is sane AND thinking-off actually suppresses reasoning with no stray `<think>`/`<|channel|>`/`<|analysis|>` artifacts in streamed output; a misbehaving build falls back to stock `gemma4:e2b` / `gemma4:e4b`
- [ ] **LLM-06**: The persona prompt's ethical boundary (security at interview-appropriate level, not step-by-step attack instructions) remains the sole content guardrail and is verified intact against the abliterated models

### STT — Nemotron Streaming ASR + Placement (Parts B & C)

- [ ] **STT-01**: faster-whisper is replaced by `nvidia/nemotron-speech-streaming-en-0.6b`, served via NeMo behind a local HTTP server and wired into the LiveKit agent as the STT plugin
- [ ] **STT-02**: STT streams a growing interim transcript as the user speaks and finalizes within ~100ms of end-of-speech (interim styled distinctly from final in the existing transcript panel)
- [ ] **STT-03**: Native punctuation and capitalization are enabled and surfaced as-is (clean, cased text to both the transcript and the LLM; no client-side post-processing)
- [ ] **STT-04**: `att_context_size` is exposed as a config knob (default balanced `[56,3]`) and a fine-tune-on-cyber-vocabulary hook/note is left for a later phase (NOT implemented now)
- [ ] **STT-05**: A 4-bit ONNX CPU runtime of nemotron-speech-streaming-en (~0.67GB, off-GPU) is supported as an alternate STT runtime behind the same server contract
- [ ] **STT-06**: STT placement (GPU full-NeMo vs CPU ONNX) is resolved ONCE at session start from VRAM headroom coupled to the selected LLM — no mid-session GPU↔CPU thrashing
- [ ] **STT-07**: A simplest-robust fallback pins STT to the CPU ONNX runtime globally for both LLM choices when E4B + GPU-STT + Kokoro are measured not to co-fit the target GPU (the picker is VRAM-safe; no runtime switching)

### AVTR — Optional 3D Avatar (Part D, frontend-only)

- [x] **AVTR-01**: A "Voice only / Avatar" UI toggle (default **Voice only**) renders an optional met4citizen/TalkingHead (Three.js/WebGL) talking head inside the existing voice UI; turning it off fully restores voice-only with no residual overhead or running avatar code
- [ ] **AVTR-02**: Avatar lip-sync is Path-A audio-driven — LiveKit's INBOUND Kokoro WebRTC audio is routed through the HeadAudio worklet for real-time viseme detection — with NO server change, no transcription, and no timestamps (audio plays normally in parallel)
- [ ] **AVTR-03**: Avatar barge-in reuses the existing LiveKit user-speech-start interrupt to call `streamInterrupt()`, stopping avatar audio + lip-sync instantly — no second VAD
- [ ] **AVTR-04**: The avatar holds eye contact while speaking AND listening (`makeEyeContact`, speaking/listening eye-contact factors, `lookAtCamera` on sentence start) and applies persona mood via `setMood`
- [x] **AVTR-05**: Camera framing is interview-appropriate (`cameraView` "upper" or "head")
- [ ] **AVTR-06**: Persona config is extended so each persona may specify an avatar (GLB url) + mood, reusing its existing Kokoro voice; the default cyber-trainer persona ships a default avatar so Avatar mode works out of the box
- [ ] **AVTR-07**: Each avatar GLB is verified to have a Mixamo-compatible rig + ARKit (52) and Oculus viseme (15) blend shapes before lip-sync is wired, and its license is confirmed to permit the intended (personal/internal) use
- [x] **AVTR-08**: Rendering is client-side WebGL with ZERO server VRAM/GPU cost; it targets ~30fps with Meshopt/Draco-compressed GLBs and degrades gracefully on weak devices (the toggle is the escape hatch)

### SESS — Session Lifecycle (deferred v1.0 polish, rolled in)

- [ ] **SESS-01**: User can start a new session
- [ ] **SESS-02**: User can reset the current session (cleared context, same session)
- [ ] **SESS-03**: User can end the session, clearing all ephemeral state including the KB brief, history, transcript, model choice, decoder cache, and any avatar GLB
- [ ] **SESS-04**: User can export/download the session transcript (txt/md, speaker labels + timestamps; no server round-trip)

### REL — Graceful Failure (deferred v1.0 polish, rolled in)

- [ ] **REL-01**: When mic permission is denied, the user sees a clear, actionable prompt explaining how to grant it — no silent failure
- [ ] **REL-02**: When a finalized transcription is empty or garbled, the agent reprompts ("didn't catch that") rather than generating a response to noise (built on Part B's finalize)

### DEPLOY — Consumer-Machine Deployment

- [ ] **DEPLOY-04**: `docker compose up` runs the full stack directly on the user's own machine — `docker compose` is the sole supported deployment (no VM/Proxmox/PCIe-passthrough path)
- [ ] **DEPLOY-05**: Consumer-GPU detection and passthrough work via the NVIDIA Container Toolkit (`--gpus` / `deploy.resources.reservations.devices`), with a preflight GPU "doctor" giving a clear, actionable message on driver/CUDA/VRAM/non-NVIDIA failure (falling back to CPU-ONNX STT + Fast model where the GPU is sub-spec)

### PERF — Latency (continued)

- [ ] **PERF-04**: Voice-to-voice latency holds P50 < 1.0s / P95 < 1.5s for BOTH LLM choices with the new STT leg, the STT finalize leg drops toward sub-100ms, and Avatar mode adds NO latency regression and ZERO server VRAM (voice-only stays byte-for-byte identical)

## Future Requirements

Deferred to a future release. Tracked but not in the current roadmap.

### LLM

- **LLM-F1**: Per-persona model defaults (a persona defaults to Better without per-session re-picking)
- **LLM-F2**: A larger "Best" model tier (Gemma 26B-A4B / Qwen3 8B) on 24GB hardware

### STT

- **STT-F1**: Nemotron fine-tuning on cybersecurity vocabulary/acronyms (hook noted in STT-04)
- **STT-F2**: Operator-exposed `att_context_size` profiles (low-latency vs high-accuracy)

### AVTR

- **AVTR-F1**: More avatar moods / gesture vocabulary (`speakWithHands`, emoji)
- **AVTR-F2**: User-selectable avatar GLB per session (beyond the persona default)

## Out of Scope

Explicitly excluded for v1.1. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Avatar in-browser TTS (TalkingHead Path B / HeadTTS / in-browser Kokoro) | TTS stays server-side Kokoro; lip-sync is audio-driven Path A only — preserves pipeline isolation |
| Avatar moving/duplicating TTS to the client | Same — Parts A/B/C own the server pipeline; Part D must not touch it |
| Webcam / real video capture of the user | Privacy violation of local-first posture; the avatar is the agent's face, not the user's |
| Public redistribution of avatar GLB assets | Licensing risk (RPM/Avaturn/CC BY-NC terms); personal/internal use only unless re-confirmed |
| Second VAD / separate avatar turn-taking | Two turn-taking sources desync; reuse the single existing LiveKit interrupt |
| Multilingual STT (nemotron-3.5) | English checkpoint is the one with the 4-bit ONNX CPU port Part C needs; app is English cyber/interview prep |
| Mid-session STT GPU↔CPU thrashing / auto-rebalancing | Reloading a model mid-call stalls the loop and risks OOM; resolve once at session start |
| More than two LLMs / a model zoo in the picker | Each model needs per-build verification + a VRAM placement story; exactly two curated options |
| Per-turn / always-prompting model switch | Friction in a live voice loop; persist per session, apply next turn |
| Latency/token-speed numbers in the model picker | Outcome labels only; metrics stay in the internal instrumentation |
| Cross-session persistence of transcripts/KB | Conflicts with the ephemeral/privacy posture; export-on-demand only |
| Changing the persona prompt | Persona prompt is unchanged and is the sole content guardrail |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| LLM-01 | Phase 8 | Complete |
| LLM-02 | Phase 8 | Complete |
| LLM-03 | Phase 8 | Complete |
| LLM-04 | Phase 8 | Complete |
| LLM-05 | Phase 8 | Pending |
| LLM-06 | Phase 8 | Pending |
| STT-01 | Phase 9 | Pending |
| STT-02 | Phase 9 | Pending |
| STT-03 | Phase 9 | Pending |
| STT-04 | Phase 9 | Pending |
| STT-05 | Phase 10 | Pending |
| STT-06 | Phase 10 | Pending |
| STT-07 | Phase 10 | Pending |
| AVTR-01 | Phase 12 | Complete |
| AVTR-02 | Phase 12 | Pending |
| AVTR-03 | Phase 12 | Pending |
| AVTR-04 | Phase 12 | Pending |
| AVTR-05 | Phase 12 | Complete |
| AVTR-06 | Phase 12 | Pending |
| AVTR-07 | Phase 12 | Pending |
| AVTR-08 | Phase 12 | Complete |
| SESS-01 | Phase 13 | Pending |
| SESS-02 | Phase 13 | Pending |
| SESS-03 | Phase 13 | Pending |
| SESS-04 | Phase 13 | Pending |
| REL-01 | Phase 13 | Pending |
| REL-02 | Phase 13 | Pending |
| DEPLOY-04 | Phase 11 | Pending |
| DEPLOY-05 | Phase 11 | Pending |
| PERF-04 | Phase 13 | Pending |

**Coverage:**

- v1.1 requirements: 30 total
- Mapped to phases: 30 (100%) ✓
- Unmapped: 0

**Phase distribution:**

- Phase 8 (LLM Speed Selector / Part A): LLM-01..06 (6)
- Phase 9 (Nemotron Streaming ASR / Part B): STT-01..04 (4)
- Phase 10 (VRAM-Aware STT Placement / Part C): STT-05..07 (3)
- Phase 11 (Consumer-GPU Deployment / Part E): DEPLOY-04, DEPLOY-05 (2)
- Phase 12 (Optional 3D Avatar / Part D): AVTR-01..08 (8)
- Phase 13 (Deferred v1.0 Polish, rolled in): SESS-01..04, REL-01/02, PERF-04 (7)

---
*Requirements defined: 2026-06-26*
*Last updated: 2026-06-26 after initial v1.1 definition*
