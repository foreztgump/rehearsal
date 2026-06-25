# Roadmap: Adept — Near-Real-Time Voice Persona Trainer

## Overview

Adept is built as a strict downward dependency chain dictated by the research build-order: a self-hosted, instrumented foundation comes up first, then the bare streamed voice loop (the hard MVP gate — talk to the default Cybersecurity Trainer with barge-in and semantic turn detection), then each behavioral layer stacks over that same single `AgentSession` pipeline — persona, knowledge base, history management, interview mode — and finally session lifecycle + graceful-failure polish. Every phase preserves one keystone invariant: per-turn TTFT must stay flat as the session grows. Latency instrumentation and the 16GB-VRAM model decisions are not deferred — they are foundation work, because the flat-TTFT invariant cannot be defended without per-stage metrics existing from turn one.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Infrastructure** - Self-hosted, GPU-passthrough Docker Compose stack with pinned models, VRAM budget, and per-stage metrics scaffold (completed 2026-06-25)
- [ ] **Phase 2: Bare Voice Loop (MVP Gate)** - End-to-end streamed voice-to-voice conversation with the default trainer, barge-in, and instrumented latency
- [ ] **Phase 3: Persona Layer** - Live-editable expert persona (role, name, knobs, voice) over the frozen-prefix prompt layout
- [ ] **Phase 4: Knowledge Base Layer** - Upload → distill → inline-and-cache ephemeral docs while preserving the flat-TTFT invariant
- [ ] **Phase 5: History Management** - Sliding-window / summarization behind the frozen prefix so long sessions keep flat TTFT
- [ ] **Phase 6: Interview Mode** - One-question-at-a-time role-play interview with critique and model answer
- [ ] **Phase 7: Polish & Reliability** - Session controls, transcript export, and graceful failure handling

## Phase Details

### Phase 1: Foundation & Infrastructure

**Goal**: Stand up the entire self-hosted stack (LiveKit server, agent worker, Ollama, Whisper, Kokoro, frontend shell) from one Docker Compose with GPU passthrough, the corrected model pins, a defended VRAM budget, and a per-stage latency-metrics scaffold — before any voice flows.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: PERF-02, PERF-03, DEPLOY-01, DEPLOY-02
**Success Criteria** (what must be TRUE):

  1. `docker compose up` brings up all services (LiveKit server, agent worker, Ollama, Whisper, Kokoro, web) with GPU passthrough into the Proxmox VM
  2. `gemma4:e4b-it-q4_K_M` is served by Ollama with thinking/reasoning mode disabled, `keep_alive=-1`, `OLLAMA_FLASH_ATTENTION=1`, and `OLLAMA_KV_CACHE_TYPE=q8_0`
  3. STT + LLM + TTS are co-resident within the 16GB VRAM floor (verified by `nvidia-smi` under load) with no embedder or vector store
  4. LiveKit is fully self-hosted including the local `MultilingualModel` turn detector — no call ever routes to LiveKit Cloud or any external network
  5. A per-stage metrics logging scaffold exists and emits VAD/STT/LLM/TTS timings, ready to instrument turns

**Plans**: 3/3 plans complete

Plans:

- [x] 01-01-PLAN.md
- [x] 01-02-PLAN.md
- [x] 01-03-PLAN.md

**Wave 1**

- [x] 01-01: Docker Compose stack + GPU passthrough + HTTPS-on-LAN (mkcert) secure context

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02: Ollama model pin (q4_K_M, thinking off) + flash-attn/KV-quant env + VRAM validation under load

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03: Self-hosted LiveKit server + ICE/node_ip config + local turn-detector + per-stage metrics scaffold

### Phase 2: Bare Voice Loop (MVP Gate)

**Goal**: Ship the hard MVP gate — a browser SPA where the user speaks open-mic and holds a fully streamed near-real-time conversation with the default Cybersecurity Trainer: VAD → semantic turn-detect → STT → LLM → first-sentence TTS, with instant barge-in, an agent-state indicator, a live two-sided transcript, and per-turn latency instrumentation.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05, VOICE-06, VOICE-07, VOICE-08, PERS-01, PERF-01, DEPLOY-03
**Success Criteria** (what must be TRUE):

  1. User loads the single-page UI and is talking to the default Cybersecurity Trainer within seconds, hands-free via open-mic VAD
  2. Agent begins speaking on its first completed sentence and stops instantly (barge-in) when the user starts talking
  3. Agent waits for a finished thought using semantic endpointing (tuned `min_endpointing_delay` ~250–350ms), not a fixed silence timer
  4. User sees a live listening/thinking/speaking state indicator and a live two-sided transcript
  5. Voice-to-voice latency is instrumented per-turn and meets P50 < ~1.2s in this phase (tightening toward < 1.0s by polish)

**Plans**: TBD

Plans:

- [ ] 02-01: Browser SPA + LiveKit SDK media/data-channel + agent-state pill + two-sided transcript
- [ ] 02-02: AgentSession pipeline (VAD → turn-detect → STT → LLM → first-sentence TTS) with default trainer persona
- [ ] 02-03: Barge-in + open-mic AEC/noise-suppression + endpointing tuning + per-turn latency metrics

### Phase 3: Persona Layer

**Goal**: Layer a live-editable expert persona over the working loop — role/instructions, display name, behavior knobs (difficulty, verbosity, correction-aggressiveness), and Kokoro voice selection — establishing the byte-stable frozen-prefix prompt layout that KB caching will depend on, with in-session hot-swap and "applying…" feedback.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: PERS-02, PERS-03, PERS-04, PERS-05, PERS-06, PERS-07
**Success Criteria** (what must be TRUE):

  1. User can edit the persona's role/instructions and display name in a side panel
  2. User can adjust difficulty, verbosity, and correction-aggressiveness knobs and select a Kokoro preset voice
  3. Persona changes apply within the current session without a restart (one-turn re-prefill with "applying…" feedback)
  4. The default trainer gently corrects sloppy terminology toward precise practitioner phrasing, scaled by the correction-aggressiveness knob
  5. The prompt is laid out as `[static persona] + [static KB slot] + [rolling history] + [new turn]` — frozen prefix ready for KB caching

**Plans**: TBD

Plans:

- [ ] 03-01: Persona config → system prompt + voice id; frozen-prefix prompt layout
- [ ] 03-02: Persona editor side panel (role, name, knobs, voice) + live update_instructions/voice swap

### Phase 4: Knowledge Base Layer

**Goal**: Add ephemeral per-session knowledge — upload PDF/TXT/MD/DOCX, parse, size-guard, distill once into a compact domain brief, inject once into the frozen prefix, and rely on Ollama prefix/KV cache so KB cost is paid only at session start — proving the flat-TTFT invariant holds (turn-2 TTFT ≪ turn-1 with a large KB).
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: KB-01, KB-02, KB-03, KB-04, KB-05, KB-06, KB-07, KB-08, REL-03
**Success Criteria** (what must be TRUE):

  1. User can upload PDF/TXT/MD/DOCX at session start; docs are parsed and distilled into a compact domain brief
  2. With a KB loaded the agent demonstrably references the user's material; with none, it does not
  3. Per-turn TTFT stays flat whether or not a KB is loaded — the brief is injected once and held in the prefix/KV cache
  4. KB is ephemeral (cleared at session end); a KB-active indicator shows doc count and an upload-size guard warns/distills harder on oversize uploads
  5. A failed KB upload (parse error, oversize) surfaces a clear error and the session continues without the KB

**Plans**: TBD

Plans:

- [ ] 04-01: Upload + parser (pymupdf4llm/python-docx) + size guard + parse-failure handling
- [ ] 04-02: Setup-time distillation pass → compact brief; inject once; KB-active indicator + ephemeral teardown
- [ ] 04-03: Prefix-cache invalidation verification (turn-2 TTFT ≪ turn-1) + KB-load VRAM re-check

### Phase 5: History Management

**Goal**: Keep long sessions fast by managing conversation history — sliding-window plus async summarization placed *behind* the frozen KB/persona prefix — so growing history never inflates per-turn TTFT and never busts the KB prefix cache.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: SESS-05
**Success Criteria** (what must be TRUE):

  1. Conversation history is sliding-windowed and/or summarized as the session grows
  2. Per-turn TTFT stays flat across a long session (measured — does not climb with turn count)
  3. History management sits behind the frozen persona/KB prefix and does not invalidate the prefix cache

**Plans**: TBD

Plans:

- [ ] 05-01: Sliding-window + async summarization behind frozen prefix; flat-TTFT-over-time verification

### Phase 6: Interview Mode

**Goal**: Add a constrained dialogue state machine over the same pipeline — user toggles Interview Mode and picks a target role, the agent asks one realistic role-relevant question at a time, waits for the spoken answer, then critiques it and demonstrates a strong model answer — with a re-tuned slow-speech endpointing profile.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: MODE-01, MODE-02, MODE-03, MODE-04, MODE-05
**Success Criteria** (what must be TRUE):

  1. Learn/Converse is the default mode; the user can toggle into Interview Mode from the side panel
  2. On entering Interview Mode the user picks the target role (e.g., SOC analyst, security engineer, GRC)
  3. The agent asks one realistic, role-relevant question at a time and waits for the user's spoken answer
  4. After each answer the agent gives a critique and demonstrates a strong model answer
  5. Endpointing is re-tuned for deliberate interview-answer speech so the agent does not cut in mid-thought

**Plans**: TBD

Plans:

- [ ] 06-01: Mode toggle + role picker + Interview state machine (ask → listen → critique → model-answer → next)
- [ ] 06-02: Rubric-structured critique prompts + slow-speech endpointing re-tune + 24GB fallback documented

### Phase 7: Polish & Reliability

**Goal**: Close the loop with session lifecycle and graceful failure handling — new/reset/end session, transcript export, ephemeral-teardown audit, and clear recovery for mic-permission denial and empty/garbled transcription — and tighten voice-to-voice latency toward the P50 < 1.0s / P95 < 1.5s target.
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: SESS-01, SESS-02, SESS-03, SESS-04, REL-01, REL-02
**Success Criteria** (what must be TRUE):

  1. User can start a new session, reset the current session, and end the session (clearing ephemeral state including the KB)
  2. User can export/download the session transcript
  3. When mic permission is denied, the user sees a clear prompt explaining how to grant it (no silent failure)
  4. When transcription is empty or garbled, the agent reprompts ("didn't catch that") rather than responding to noise
  5. Voice-to-voice latency meets P50 < 1.0s and P95 < 1.5s on the target hardware

**Plans**: TBD

Plans:

- [ ] 07-01: Session controls (new/reset/end) + ephemeral-teardown audit + transcript export
- [ ] 07-02: Graceful failure handling (mic-denial prompt, garbled-STT reprompt) + final latency tuning pass

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Infrastructure | 3/3 | Complete    | 2026-06-25 |
| 2. Bare Voice Loop (MVP Gate) | 0/3 | Not started | - |
| 3. Persona Layer | 0/2 | Not started | - |
| 4. Knowledge Base Layer | 0/3 | Not started | - |
| 5. History Management | 0/1 | Not started | - |
| 6. Interview Mode | 0/2 | Not started | - |
| 7. Polish & Reliability | 0/2 | Not started | - |
