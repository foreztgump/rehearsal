# Roadmap: Adept — Near-Real-Time Voice Persona Trainer

## Overview

Adept is built as a strict downward dependency chain dictated by the research build-order: a self-hosted, instrumented foundation comes up first, then the bare streamed voice loop (the hard MVP gate — talk to the default Cybersecurity Trainer with barge-in and semantic turn detection), then each behavioral layer stacks over that same single `AgentSession` pipeline — persona, knowledge base, history management, interview mode — and finally session lifecycle + graceful-failure polish. Every phase preserves one keystone invariant: per-turn TTFT must stay flat as the session grows. Latency instrumentation and the 16GB-VRAM model decisions are not deferred — they are foundation work, because the flat-TTFT invariant cannot be defended without per-stage metrics existing from turn one.

## Milestones

- ✅ **v1.0-rc1 MVP Release Candidate** — Phases 1-6 (shipped 2026-06-26) — [archive](milestones/v1.0-rc1-ROADMAP.md)
- 🚧 **v1.0 Polish & Reliability** — Phase 7 (in progress)

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

### 🚧 v1.0 Polish & Reliability (In Progress)

- [ ] **Phase 7: Polish & Reliability** - Session controls, transcript export, and graceful failure handling

## Phase Details

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

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation & Infrastructure | v1.0-rc1 | 3/3 | Complete | 2026-06-25 |
| 2. Bare Voice Loop (MVP Gate) | v1.0-rc1 | 3/3 | Complete | 2026-06-25 |
| 3. Persona Layer | v1.0-rc1 | 2/2 | Complete | 2026-06-25 |
| 4. Knowledge Base Layer | v1.0-rc1 | 4/4 | Complete | 2026-06-25 |
| 5. History Management | v1.0-rc1 | 1/1 | Complete | 2026-06-26 |
| 6. Interview Mode | v1.0-rc1 | 2/2 | Complete | 2026-06-26 |
| 7. Polish & Reliability | v1.0 | 0/2 | Not started | - |
