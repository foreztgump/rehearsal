# Roadmap: Adept — Near-Real-Time Voice Persona Trainer

## Overview

Adept is built as a strict downward dependency chain dictated by the research build-order: a self-hosted, instrumented foundation comes up first, then the bare streamed voice loop (the hard MVP gate — talk to the default Cybersecurity Trainer with barge-in and semantic turn detection), then each behavioral layer stacks over that same single `AgentSession` pipeline — persona, knowledge base, history management, interview mode — and finally session lifecycle + graceful-failure polish. Every phase preserves one keystone invariant: per-turn TTFT must stay flat as the session grows. Latency instrumentation and the 16GB-VRAM model decisions are not deferred — they are foundation work, because the flat-TTFT invariant cannot be defended without per-stage metrics existing from turn one.

**v1.1 (Local-First Pipeline Swap + Avatar)** is an *integration* milestone over that shipped substrate. It swaps three pipeline stages and bolts on one optional frontend layer, in a fixed order so each server change re-proves the latency/VRAM gates before the next stacks on, and the frontend-only avatar comes last so its "changed nothing server-side" claim is trivially auditable (empty server diff after the deployment phase): **A** user-selectable Ollama LLMs → **B** Nemotron streaming ASR → **C** VRAM-aware STT placement → **E** consumer-GPU deployment → **D** avatar (frontend-only, isolated) → **Polish** (rolled-in session/reliability + final latency tuning). The keystone invariant for v1.1: voice-to-voice P50 < 1.0s / P95 < 1.5s must hold for BOTH LLMs, and the avatar must add zero server VRAM and zero latency.

## Milestones

- ✅ **v1.0-rc1 MVP Release Candidate** — Phases 1-6 (shipped 2026-06-26) — [archive](milestones/v1.0-rc1-ROADMAP.md)
- 🚧 **v1.1 Local-First Pipeline Swap + Avatar** — Phases 8-13 (in progress)

> **Note on Phase 7:** v1.0's *Phase 7 (Polish & Reliability)* was defined but never started (0/2 plans). Its requirements (SESS-01..04, REL-01/02, final latency tuning) were **rolled into v1.1** and now live in this milestone's REQUIREMENTS.md. v1.1 **supersedes the unstarted Phase 7** — the standalone Phase 7 is folded into the v1.1 polish phase (Phase 13) so its coverage is not double-counted. v1.1 phases continue numbering from **Phase 8**.

## Phases

<details>
<summary>✅ v1.0-rc1 MVP Release Candidate (Phases 1-6) — SHIPPED 2026-06-26</summary>

Full conversational MVP: self-hosted GPU stack, streamed voice loop with barge-in, live-editable persona, ephemeral KB (upload→distill→inline-cache), history management, and interview mode — all over one `AgentSession` holding the flat-TTFT invariant. Full phase details in [milestones/v1.0-rc1-ROADMAP.md](milestones/v1.0-rc1-ROADMAP.md).

- [x] Phase 1: Foundation & Infrastructure (3/3 plans) — completed 2026-06-25
- [x] Phase 2: Bare Voice Loop (MVP Gate) (3/3 plans) — completed 2026-06-25
- [x] Phase 3: Persona Layer (2/2 plans) — completed 2026-06-25
- [x] Phase 4: Knowledge Base Layer (4/4 plans) — completed 2026-06-25
- [x] Phase 5: History Management (1/1 plan) — completed 2026-06-26
- [x] Phase 6: Interview Mode (2/2 plans) — completed 2026-06-26

</details>

<details>
<summary>⊘ Phase 7: Polish & Reliability — SUPERSEDED (folded into v1.1 Phase 13)</summary>

Phase 7 was defined in the v1.0 plan but **never started** (0/2 plans). Its scope — SESS-01..04, REL-01/02, and final latency tuning — was carried verbatim into v1.1 and is now delivered by **Phase 13 (Deferred v1.0 Polish, rolled in)**. Do not plan or execute a standalone Phase 7; its requirements are covered (and coverage-counted) under Phase 13.

</details>

### 🚧 v1.1 Local-First Pipeline Swap + Avatar (In Progress)

- [x] **Phase 8: LLM Speed Selector (Part A)** — Two user-selectable Ollama models with per-build verification and the sole-guardrail persona check
- [x] **Phase 9: Nemotron Streaming ASR (Part B)** — Replace faster-whisper with NeMo streaming STT behind a local server *(code-complete; GPU gate pending-operator)*
- [x] **Phase 10: VRAM-Aware STT Placement (Part C)** — GPU-NeMo vs CPU-ONNX resolved once at session start, with global-CPU-ONNX fallback *(code-complete; GPU gate pending-operator)*
- [ ] **Phase 11: Consumer-GPU Deployment (Part E)** — `docker compose up` on the user's machine with GPU detection/preflight doctor
- [ ] **Phase 12: Optional 3D Avatar (Part D, frontend-only)** — TalkingHead Path-A avatar that must not touch the server pipeline
- [ ] **Phase 13: Deferred v1.0 Polish (rolled in)** — Session lifecycle, graceful failure, and final latency tuning for both LLMs

## Phase Details

### Phase 8: LLM Speed Selector (Part A)

**Goal**: Replace the single stock LLM with two user-selectable Ollama models (Fast E2B default / Better E4B) exposed via a plain-language UI picker, session-persisted, switchable on the next turn without session teardown — while preserving the latency optimizations (thinking-off/streaming/keep-alive/flash-attn/lean-context/capped num_predict) and verifying per-build that the abliterated community GGUFs have a sane chat template, leak no reasoning artifacts, and leave the persona prompt as the sole intact content guardrail.
**Mode:** mvp
**Depends on**: Phase 6 (shipped v1.0-rc1 pipeline)
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06
**Success Criteria** (what must be TRUE):

  1. User sees a Fast/Better picker with plain-language labels (never raw Ollama tags), defaulting to Fast (E2B); the choice persists for the session and a switch takes effect on the next turn with no session teardown and no interruption of current TTS
  2. Both models are pulled/served via Ollama and the LiveKit agent re-targets the selected tag in place (LLM plugin mutated, not reassigned) so the speech_id metrics subscription survives and flat-TTFT holds across a switch (one-turn cold-prefill bump only)
  3. Both models run with thinking DISABLED, token-by-token streaming, OLLAMA_KEEP_ALIVE resident, flash attention on, lean context, and a capped num_predict
  4. Each model build passes a verification gate — chat-template diff vs stock + raw-token artifact check (no stray `<think>`/`<|channel|>`/`<|analysis|>` in streamed output) — and a misbehaving build falls back to stock `gemma4:e2b`/`gemma4:e4b`
  5. The persona prompt's ethical boundary is verified intact as the SOLE content guardrail against both abliterated models (red-team boundary probes pass)

**Plans**: 2/2 plans executed

- [x] 08-01-llm-picker-agent-swap-PLAN.md
- [x] 08-02-pull-pin-verify-build-PLAN.md

### Phase 9: Nemotron Streaming ASR (Part B)

**Goal**: Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b` served via NeMo behind a local HTTP server and wired into the LiveKit agent as the STT plugin, delivering a growing interim transcript while speaking, ~100ms finalize after end-of-speech, native punctuation/capitalization surfaced as-is, and an `att_context_size` config knob — without regressing voice-to-voice P50 < 1.0s.
**Mode:** mvp
**Depends on**: Phase 8
**Requirements**: STT-01, STT-02, STT-03, STT-04
**Success Criteria** (what must be TRUE):

  1. faster-whisper is removed and the agent's STT plugin streams to a `nemo-stt` service running `nvidia/nemotron-speech-streaming-en-0.6b` behind a local HTTP server (no audio leaves the local network)
  2. The transcript shows a growing interim while the user speaks (styled distinctly from final) and finalizes within ~100ms of end-of-speech, coupled to the existing VAD/semantic endpoint with a stall watchdog so long run-on (interview) answers are not stranded by the documented RNNT decoder stall
  3. Native punctuation and capitalization are enabled and passed as-is to both the transcript and the LLM (no client-side post-processing)
  4. `att_context_size` is exposed as a config knob (default `[56,3]`); the cyber-vocab fine-tune hook is noted only, not implemented
  5. Voice-to-voice P50 still < 1.0s with the new STT leg (the STT finalize leg tightens toward sub-100ms)

**Plans**: TBD

### Phase 10: VRAM-Aware STT Placement (Part C)

**Goal**: Ship the mechanism to run STT either as full GPU NeMo or as the off-GPU 4-bit ONNX CPU port, resolved ONCE at session start from VRAM headroom coupled to the selected LLM, with a single env-flagged global-CPU-ONNX fallback that makes the picker VRAM-safe with zero runtime switching — gated on an operator co-residency measurement on the real consumer GPU.
**Mode:** mvp
**Depends on**: Phase 9
**Requirements**: STT-05, STT-06, STT-07
**Success Criteria** (what must be TRUE):

  1. A 4-bit ONNX CPU runtime of nemotron-speech-streaming-en (~0.67GB, off-GPU) is supported as an alternate STT runtime behind the same server contract (`nemo-stt-cpu` service), benchmarked >6× realtime with negligible WER loss under contention
  2. STT placement (GPU full-NeMo vs CPU ONNX) is resolved exactly once at session start by `placement.py` from the selected LLM + VRAM headroom, with NO mid-session GPU↔CPU thrashing
  3. The `STT_FORCE_CPU` global fallback pins STT to CPU-ONNX for BOTH LLM choices via a single env flag, removing the per-session branch and keeping the picker VRAM-safe
  4. **(Operator GPU gate — verifiable only on the real consumer GPU)** The extended `vram-validate.sh` co-residency matrix `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}` is measured at the KB-load prefill peak (q8_0 engaged, peak < total−1GB); the safe default is set to global CPU-ONNX unless E4B + GPU-STT + Kokoro proves to co-fit on the target GPU

**Plans**: TBD

### Phase 11: Consumer-GPU Deployment (Part E)

**Goal**: Drop the Proxmox-VM assumption so `docker compose up` brings the full stack up directly on the user's consumer machine, with consumer-GPU detection/passthrough via the NVIDIA Container Toolkit and a preflight GPU "doctor" that gives a clear, actionable message on driver/CUDA/VRAM/non-NVIDIA failure (falling back to CPU-ONNX STT + Fast model where the GPU is sub-spec).
**Mode:** mvp
**Depends on**: Phase 10
**Requirements**: DEPLOY-04, DEPLOY-05
**Success Criteria** (what must be TRUE):

  1. `docker compose up` runs the full stack on the user's consumer machine with no Proxmox-VM/PCIe-passthrough assumption; GPU exposure works via the NVIDIA Container Toolkit (`--gpus` / `deploy.resources.reservations.devices`) and the chosen STT runtime boots behind its Compose profile
  2. A preflight GPU doctor detects driver/CUDA/VRAM/non-NVIDIA problems and prints an exact, actionable remedy instead of a silent hang (NeMo image bloat/first-run download surfaced via healthcheck/`start_period`, not a hung-looking `up`)
  3. On a sub-spec or non-NVIDIA host the stack degrades to CPU-ONNX STT + the Fast model and still comes up usable

**Plans**: TBD

### Phase 12: Optional 3D Avatar (Part D, frontend-only)

**Goal**: Add an OPTIONAL, default-OFF client-side 3D talking-head avatar (met4citizen/TalkingHead, Three.js/WebGL) with Path-A audio-driven lip-sync on the inbound Kokoro WebRTC audio, barge-in via the existing LiveKit interrupt, eye-contact/mood/framing, and a client-side persona↔GLB mapping — strictly frontend-only with ZERO server VRAM cost and an auditable empty server diff. This phase MUST NOT change the server pipeline (Parts A/B/C) in any way.
**Mode:** ui
**Depends on**: Phase 11 (server pipeline frozen and proven)
**Requirements**: AVTR-01, AVTR-02, AVTR-03, AVTR-04, AVTR-05, AVTR-06, AVTR-07, AVTR-08
**Success Criteria** (what must be TRUE):

  1. A "Voice only / Avatar" toggle (default Voice only) renders the TalkingHead avatar inside the existing voice UI; turning it off fully unmounts the canvas + AudioWorklet so voice-only is byte-for-byte the pre-avatar build with zero residual overhead (dynamic-imported; no avatar JS in the voice-only bundle)
  2. **Isolation gate (auditable):** the avatar adds ZERO files under `agent/`, ZERO Compose services, ZERO server RPC/byte-stream/attributes, and ZERO server env — `git diff -- agent/ stt/ tts/ docker-compose.yml` is empty for this phase and server VRAM is identical avatar ON/OFF
  3. Lip-sync is Path-A audio-driven — the inbound Kokoro track is tapped through the HeadAudio worklet for real-time visemes (no transcription, no timestamps, audio still plays normally); barge-in reuses the existing user-speech-start interrupt to call `streamInterrupt()` with no second VAD
  4. The avatar holds eye contact while speaking AND listening, applies persona mood (`setMood`), uses interview-appropriate framing (`cameraView` upper/head), and each persona maps to a GLB+mood client-side (default cyber-trainer ships a default avatar) reusing its existing Kokoro voice
  5. Each GLB is verified to have a Mixamo rig + ARKit(52) + Oculus(15) viseme blendshapes and a license permitting personal/internal use before lip-sync is wired; rendering targets ~30fps with Meshopt/Draco compression and degrades gracefully (the toggle is the escape hatch)

**Plans**: TBD

### Phase 13: Deferred v1.0 Polish (rolled in)

**Goal**: Close the loop with session lifecycle and graceful-failure handling — new/reset/end session with a full ephemeral-teardown audit (clearing KB, history, transcript, model choice, decoder cache, avatar GLB), transcript export, mic-permission-denied prompt, and empty/garbled-transcription reprompt (built on Part B's finalize) — and run the final latency-tuning pass confirming P50 < 1.0s / P95 < 1.5s for BOTH LLM choices with the new STT leg and the avatar adding no regression. This phase supersedes the unstarted v1.0 Phase 7.
**Mode:** mvp
**Depends on**: Phase 12
**Requirements**: SESS-01, SESS-02, SESS-03, SESS-04, REL-01, REL-02, PERF-04
**Success Criteria** (what must be TRUE):

  1. User can start a new session, reset the current session (cleared context, same session), and end the session — end clears ALL ephemeral v1.1 state including the KB brief, history, transcript, model choice, decoder cache, and any avatar GLB
  2. User can export/download the session transcript (txt/md, speaker labels + timestamps, no server round-trip)
  3. When mic permission is denied the user sees a clear, actionable prompt (no silent failure); when a finalized transcription is empty or garbled the agent reprompts ("didn't catch that") rather than responding to noise
  4. **(Operator GPU gate — verifiable only on the real consumer GPU)** Voice-to-voice latency holds P50 < 1.0s / P95 < 1.5s for BOTH LLM choices with the new STT leg, the STT finalize leg drops toward sub-100ms, and Avatar mode adds NO latency regression and ZERO server VRAM (voice-only stays byte-for-byte identical)

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → ~~7 (superseded)~~ → 8 → 9 → 10 → 11 → 12 → 13

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation & Infrastructure | v1.0-rc1 | 3/3 | Complete | 2026-06-25 |
| 2. Bare Voice Loop (MVP Gate) | v1.0-rc1 | 3/3 | Complete | 2026-06-25 |
| 3. Persona Layer | v1.0-rc1 | 2/2 | Complete | 2026-06-25 |
| 4. Knowledge Base Layer | v1.0-rc1 | 4/4 | Complete | 2026-06-25 |
| 5. History Management | v1.0-rc1 | 1/1 | Complete | 2026-06-26 |
| 6. Interview Mode | v1.0-rc1 | 2/2 | Complete | 2026-06-26 |
| 7. Polish & Reliability | — | — | Superseded → folded into Phase 13 | - |
| 8. LLM Speed Selector (Part A) | v1.1 | 2/2 | Complete | 2026-06-26 |
| 9. Nemotron Streaming ASR (Part B) | v1.1 | 2/2 | Code-complete (GPU gate pending) | 2026-06-26 |
| 10. VRAM-Aware STT Placement (Part C) | v1.1 | 2/2 | Code-complete (GPU gate pending) | 2026-06-26 |
| 11. Consumer-GPU Deployment (Part E) | v1.1 | 0/2 | Planned (ready to execute) | 2026-06-26 |
| 12. Optional 3D Avatar (Part D) | v1.1 | 0/? | Not started | - |
| 13. Deferred v1.0 Polish (rolled in) | v1.1 | 0/? | Not started | - |
