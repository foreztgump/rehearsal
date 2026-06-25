# Architecture Research

**Domain:** Local near-real-time voice agent (LiveKit Agents: STT→LLM→TTS) with inline cached knowledge base
**Researched:** 2026-06-24
**Confidence:** HIGH (LiveKit `AgentSession` 1.x pipeline, Ollama prefix/KV caching, and streaming model are well-documented; persona/KB layering is project-specific design built on confirmed primitives)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          BROWSER (single page)                         │
│  ┌──────────────┐  ┌────────────────────────────────────────────────┐ │
│  │ LiveKit Web  │  │ Custom UI State (React/Svelte)                  │ │
│  │ SDK          │  │  • transcript view  • persona editor panel     │ │
│  │  • mic capt. │  │  • KB upload + status  • mode toggle           │ │
│  │  • playback  │  │  • agent-state pill (listening/thinking/speak) │ │
│  │  • WebRTC    │  │  • session controls (new/reset/end/export)     │ │
│  └──────┬───────┘  └───────────────────┬────────────────────────────┘ │
└─────────┼──────────────────────────────┼──────────────────────────────┘
          │ WebRTC (audio tracks)        │ data channel / RPC + REST
          │ + data channel (state/text)  │ (persona edits, KB upload)
┌─────────▼──────────────────────────────▼──────────────────────────────┐
│                     livekit-server (SFU, self-hosted)                  │
│            routes media tracks + data messages between peers           │
└─────────┬──────────────────────────────────────────────────────────────┘
          │ agent joins room as a participant
┌─────────▼──────────────────────────────────────────────────────────────┐
│                     AGENT WORKER (Python, LiveKit Agents)               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                       AgentSession (orchestrator)                  │  │
│  │   VAD ─▶ turn-detector ─▶ STT ─▶ LLM ─▶ TTS ─▶ audio out          │  │
│  │   (silero)  (semantic)  (whisper)(Ollama)(Kokoro)                 │  │
│  │   ▲ barge-in: VAD on user track cancels TTS + rolls back turn     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────┐ ┌────────────────┐ ┌──────────────────────────────┐ │
│  │ Persona config │ │ KB distiller   │ │ History manager              │ │
│  │ (system prompt │ │ (parse→brief→  │ │ (sliding window / summarize) │ │
│  │  + voice id)   │ │  size guard)   │ │                              │ │
│  └────────────────┘ └────────────────┘ └──────────────────────────────┘ │
└──────┬───────────────┬───────────────────┬──────────────────────────────┘
       │ HTTP          │ HTTP              │ OpenAI-compatible HTTP
┌──────▼──────┐ ┌──────▼───────┐ ┌─────────▼──────────┐
│  whisper    │ │   ollama     │ │      kokoro        │
│ faster-     │ │ Gemma 4 E4B  │ │ TTS (preset voices)│
│ whisper     │ │ Q4 + KV/     │ │                    │
│ turbo int8  │ │ prefix cache │ │                    │
└─────────────┘ └──────────────┘ └────────────────────┘
        └──────── all share one GPU (16GB VRAM floor) ───────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| LiveKit Web SDK | Mic capture, WebRTC transport, audio playback, data channel | `@livekit/components-react` or vanilla `livekit-client` |
| livekit-server | SFU: routes audio tracks + data messages browser↔agent | Self-hosted container, day one |
| Agent Worker | Hosts `AgentSession`; owns persona/KB/history logic | Python `livekit-agents` 1.x, one worker process |
| `AgentSession` | Wires VAD→turn-detector→STT→LLM→TTS; streams every stage; barge-in cancel; emits state events | Framework primitive (replaces 0.x `VoicePipelineAgent`) |
| VAD | Detects speech presence on user track; drives barge-in | `silero.VAD` |
| Turn detector | Semantic endpointing (is the user *done*, not just silent) | LiveKit multilingual turn-detector model |
| STT | Streaming transcription | faster-whisper turbo int8 (local HTTP) |
| LLM | Token-streamed reasoning/response | Gemma 4 E4B Q4 via Ollama |
| TTS | Sentence-chunked streaming synthesis | Kokoro via OpenAI-compatible server |
| Persona config | Config object → system prompt + voice id; live-editable | In-process object; `update_instructions()` + TTS voice swap |
| KB distiller | Upload→parse→compact domain brief; enforces size guard | Setup-time task in worker (or sidecar) |
| History manager | Sliding window / summarize older turns to keep TTFT flat | In-process `ChatContext` mutation |

## Recommended Project Structure

```
adept/
├── docker-compose.yml          # one-stack bring-up, GPU passthrough
├── agent/                      # Python LiveKit Agents worker
│   ├── main.py                 # worker entry / job handler, AgentSession wiring
│   ├── pipeline.py             # STT/LLM/TTS plugin construction, VAD, turn-detect
│   ├── persona/
│   │   ├── config.py           # Persona dataclass (role, name, knobs, voice)
│   │   ├── prompt.py           # render persona → system prompt
│   │   └── defaults.py         # Cybersecurity Trainer default
│   ├── kb/
│   │   ├── parse.py            # PDF/TXT/MD/DOCX → raw text
│   │   ├── distill.py          # raw text → compact domain brief (LLM call)
│   │   └── guard.py            # size guard (token budget enforcement)
│   ├── history.py              # sliding-window / summarization
│   ├── modes/
│   │   ├── converse.py         # default open conversation behavior
│   │   └── interview.py        # one-question-at-a-time state machine
│   └── rpc.py                  # data-channel handlers: persona edit, mode, KB
├── web/                        # single-page frontend
│   ├── src/
│   │   ├── room.ts             # LiveKit connect, track sub, data channel
│   │   ├── state.ts            # agent-state pill, transcript store
│   │   ├── components/
│   │   │   ├── Transcript.tsx
│   │   │   ├── PersonaPanel.tsx
│   │   │   ├── KbUpload.tsx
│   │   │   └── ModeToggle.tsx
│   │   └── api.ts              # token mint + KB upload endpoint
│   └── ...
└── infra/
    └── livekit.yaml            # self-hosted server config
```

### Structure Rationale

- **agent/ as the brain:** all latency-critical and stateful logic lives in one worker process (LiveKit sessions are sticky to a worker for their full duration). Persona, KB, history, and modes are *layers over the same pipeline*, not separate services.
- **persona/ kb/ modes/ split:** matches the build order — voice loop first, then persona, then KB, then interview mode. Each folder is independently testable against a stub `AgentSession`.
- **web/ thin:** the SDK owns media; custom code owns only UI state and the data-channel protocol.

## Architectural Patterns

### Pattern 1: Streaming pipeline (turn latency = max, not sum)

**What:** Every stage boundary is a streaming interface, not a blocking handoff. STT emits partials, LLM streams tokens, TTS starts synthesizing on the **first completed sentence**. Total latency collapses from `VAD + STT + LLM + TTS` toward `max(VAD, STT, LLM, TTS)` plus first-sentence overhead.
**When to use:** Always, for sub-1s voice-to-voice. This is the whole reason to hit P50 < 1.0s.
**Trade-offs:** More moving parts; partial outputs can be wrong and get corrected. `AgentSession` handles the plumbing out of the box — never batch any stage.

**Example:**
```python
session = AgentSession(
    vad=silero.VAD.load(),
    turn_detection="multilingual",        # semantic endpointing, not a timer
    stt=whisper_stt,                       # streaming partials
    llm=ollama_llm,                        # token streaming
    tts=kokoro_tts,                        # sentence-chunked, starts on sentence 1
)
```

### Pattern 2: Persona as injected config (hot-swappable system prompt + voice)

**What:** A `Persona` config object renders to a system prompt and a Kokoro voice id. Live edits call `agent.update_instructions(new_prompt)` and swap the TTS voice mid-session; no reconnect.
**When to use:** Whenever persona is editable in-session (it is, per requirements).
**Trade-offs:** Changing the system prompt **breaks the Ollama prefix cache** for the changed bytes onward — accept a one-turn prefill cost after each edit. Keep persona text *above* the KB brief only if you accept re-prefill on edit; if KB-cache stability matters more, order matters (see Pattern 4).

**Example:**
```python
async def on_persona_edit(new: Persona):
    await agent.update_instructions(render_prompt(new, kb_brief))
    session.tts = kokoro_tts_for(new.voice_id)   # swap voice for next utterance
```

### Pattern 3: Behavioral mode as a state layer over one pipeline

**What:** Interview Mode is **not** a second pipeline. It's a state machine (`ask → listen → critique → model-answer → next`) that shapes the system prompt and gates `generate_reply`. Converse mode is the null state machine.
**When to use:** Any mode that changes *behavior* but not *transport*.
**Trade-offs:** Mode state must be serialized into the prompt/context cleanly; keep it as a small structured preamble so it doesn't bloat the cached prefix.

### Pattern 4: Inline-and-cache KB (no per-turn RAG)

**What:** Upload → parse → distill to a compact domain brief → inject into the system context **once** at session start. Rely on Ollama's implicit KV/prefix cache so the brief is prefilled on turn one and effectively free afterward. TTFT stays flat per turn.
**When to use:** Small per-session KBs (the v1 case). True vector RAG is deferred to v2+ for oversized KBs.
**Trade-offs:** Requires byte-stable prefix. Ollama cache rules: model must stay resident (`keep_alive=-1`), prefix must match byte-for-byte. **Put the KB brief and persona at the top (static); put volatile data — turn count, timestamps, mode state — at the end or out of the system prompt.** A single changed character upstream invalidates everything downstream.

**Example:**
```python
# at session start, once:
brief = distill(parse(uploaded_docs))     # setup-time, latency invisible
guard.assert_within_budget(brief)         # size guard before injection
agent_prompt = render_prompt(persona, brief)   # KB+persona = stable prefix
# keep_alive=-1 on the Ollama client so the cache survives between turns
```

### Pattern 5: Sliding-window / summarized history

**What:** Cap recent verbatim turns; summarize older ones into a running summary block placed *after* the stable KB/persona prefix. Keeps total context (and prefill) bounded so TTFT doesn't grow with conversation length.
**When to use:** Always for long sessions.
**Trade-offs:** Summarization is an extra LLM call (run async, off the critical path). The summary block changes each time it updates, invalidating cache from that point down — but the heavy KB/persona prefix above it stays cached.

## Data Flow

### Audio path (the latency-critical loop)

```
User speaks
    ↓ WebRTC audio track
livekit-server → Agent Worker
    ↓
VAD detects speech → turn-detector decides "user done"
    ↓ (streaming)
STT partials → final transcript
    ↓ (streaming tokens)
LLM (Ollama, cached KB prefix) → tokens
    ↓ first completed sentence
TTS (Kokoro) starts synthesizing sentence 1 while LLM still generating
    ↓ WebRTC audio track
livekit-server → Browser playback

Barge-in: user speech during playback → VAD fires →
TTS cancelled, interrupted LLM turn rolled back, STT restarts on new audio
```

### Text path (transcript + state)

```
STT transcript ─┐
LLM response   ─┼─▶ data channel ─▶ Browser transcript store (two-sided)
agent_state_changed (initializing/idle/listening/thinking/speaking)
    └─▶ lk.agent.state participant attribute ─▶ UI state pill
```

### KB path (setup-time, off the live loop)

```
Browser KB upload (PDF/TXT/MD/DOCX)
    ↓ REST (or data channel) to worker
parse → raw text
    ↓
size guard check (reject/flag if over token budget)
    ↓
distill (LLM call: raw → compact domain brief)
    ↓
inject into system context ONCE at session start
    ↓
Ollama prefills brief on turn 1; KV/prefix cache serves it free thereafter
KB held in memory only; cleared at session end (ephemeral)
```

### State Management (UI)

```
LiveKit data channel + lk.agent.state attribute
    ↓ (subscribe)
UI store ←→ user actions (persona edit, mode toggle, KB upload)
    ↓ (RPC / data channel)
Agent Worker mutates persona/mode/history → next turn reflects change
```

### Key Data Flows

1. **Voice turn:** audio → VAD/turn-detect → STT → LLM(streaming) → TTS(sentence 1) → audio. Streamed end-to-end; this is where the < 1.0s budget is spent.
2. **Persona edit:** UI → data channel → `update_instructions` + voice swap → applies next turn (one-turn prefill cost).
3. **KB load:** upload → parse → guard → distill → inject once → cached. Cost is paid at setup, not per turn.
4. **History growth:** after N turns, summarize older turns async → keeps prefill bounded.

## Where the Latency Budget Goes (instrument these)

| Stage | Budget intuition | Instrument |
|-------|------------------|------------|
| Endpointing / turn-detect | ~80–160ms | time from last user audio to "user done" |
| STT final transcript | ~120–250ms | partial→final latency |
| LLM first token (TTFT) | dominant local risk | time from prompt sent to first token; **watch this grow with history/KB** |
| TTS first audio | ~70–150ms | time from first sentence to first audio frame |
| **Perceived voice-to-voice** | **P50 < 1.0s, P95 < 1.5s** | LiveKit per-turn metrics (built-in) |

**The flat-TTFT invariant is the keystone:** instrument LLM TTFT per turn and assert it does *not* climb as the session grows. If it climbs, the cache is being invalidated (volatile data in the prefix) or history isn't being windowed.

## Suggested Build Order

Dependencies flow strictly downward — each layer needs the one above working first:

1. **Bare voice loop** (hard MVP gate): WebRTC client ↔ livekit-server ↔ agent worker with default-persona `AgentSession` (VAD→turn-detect→STT→LLM→TTS), streamed. Barge-in + agent-state pill + two-sided transcript. *Ship this before anything else.*
2. **Persona layer:** config object → system prompt + voice; live edit via data channel (`update_instructions` + voice swap).
3. **KB layer:** upload → parse → guard → distill → inject once → verify TTFT stays flat (the cache test).
4. **History management:** sliding window / summarization (needed once sessions run long; can land alongside KB).
5. **Interview Mode:** behavioral state machine over the same pipeline.
6. **Polish:** session controls, transcript export, error handling (mic-denial, garbled STT, KB failure).

## Deployment Topology

Docker Compose, single stack, GPU passthrough into the Proxmox VM:

| Service | Role | VRAM (approx) |
|---------|------|---------------|
| livekit-server | SFU / signaling | none (CPU) |
| agent (worker) | AgentSession host + persona/KB/history/modes | small (CPU + orchestration) |
| ollama | Gemma 4 E4B Q4, keep_alive=-1, flash attention | ~5GB |
| whisper | faster-whisper turbo int8 | ~2GB |
| kokoro | OpenAI-compatible TTS | ~2–3GB |
| web | static single-page frontend | none |

**GPU sharing:** ollama + whisper + kokoro all share the one GPU. Budget: ~5 + 2 + 2–3 ≈ 9–10GB on the 16GB floor, leaving headroom for KV cache growth and prefill working set. 24GB recommended for a larger model (Gemma 4 26B-A4B MoE or Qwen3 8B fallback) and bigger KV cache. **Keep all three models resident** (Ollama `keep_alive=-1`) — unloading dumps the KV cache and reintroduces cold-start TTFT.

## Anti-Patterns

### Anti-Pattern 1: Batching a pipeline stage

**What people do:** Wait for the full LLM response before starting TTS, or wait for full STT before sending to the LLM.
**Why it's wrong:** Turns latency into a sum (`STT+LLM+TTS`) — guarantees the conversation "feels broken" and blows the < 1.0s budget.
**Do this instead:** Stream every stage; start TTS on the first completed sentence. Never batch.

### Anti-Pattern 2: Per-turn RAG for a small KB

**What people do:** Chunk→embed→retrieve on every turn to inject KB context.
**Why it's wrong:** Adds retrieval latency *and* a fresh (uncached) context block every turn → inflates TTFT, the exact metric the design depends on.
**Do this instead:** Distill once at upload, inject once, rely on prefix/KV cache. Reserve RAG for oversized KBs in v2+.

### Anti-Pattern 3: Volatile data in the cached prefix

**What people do:** Put timestamps, turn counters, or mode state at the top of the system prompt.
**Why it's wrong:** Ollama's prefix cache requires byte-for-byte match. Any change upstream invalidates everything downstream → recomputes the whole KB/persona prefill every turn.
**Do this instead:** Static content (persona + KB brief) at the top; volatile content at the very end or out of the system prompt entirely.

### Anti-Pattern 4: Fixed-timer turn detection

**What people do:** Wait N ms of silence, then assume the user is done.
**Why it's wrong:** Cuts the user off on mid-sentence pauses / "um" / breaths — kills the "feels live" quality.
**Do this instead:** Semantic turn-detector model for endpointing; keep VAD active during playback for barge-in.

### Anti-Pattern 5: Modes as separate pipelines

**What people do:** Build Interview Mode as a parallel STT→LLM→TTS stack.
**Why it's wrong:** Duplicates the latency-critical plumbing and doubles maintenance/GPU cost.
**Do this instead:** One pipeline; modes are behavioral state machines that shape the prompt and gate replies.

### Anti-Pattern 6: Letting history grow unbounded

**What people do:** Append every turn verbatim to context forever.
**Why it's wrong:** Prefill grows with the conversation → TTFT climbs → latency degrades over a session.
**Do this instead:** Sliding window + async summarization, placed after the stable cached prefix.

## Integration Points

### External Services (all local)

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Ollama | HTTP, OpenAI-compatible (`/v1`); LiveKit `openai.LLM` pointed at local base_url | `keep_alive=-1`, flash attention; cache is implicit on shared prefix |
| faster-whisper | LiveKit STT plugin / local HTTP | turbo int8; streaming partials |
| Kokoro | OpenAI-compatible TTS server; LiveKit `openai.TTS` base_url | swappable (VoxCPM later) via same interface |
| livekit-server | WebRTC SFU; agent + browser join as participants | self-hosted from day one |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Browser ↔ livekit-server | WebRTC (audio) + data channel | SDK-owned |
| Browser ↔ Agent (control) | data channel / RPC + REST (KB upload) | persona edits, mode toggle, KB |
| Agent ↔ models | local HTTP (OpenAI-compatible where possible) | models pluggable behind LiveKit |
| Persona/KB/History/Modes ↔ AgentSession | in-process (same worker) | sessions are sticky to a worker for their lifetime |

## Sources

- LiveKit — Sequential Pipeline Architecture for Voice Agents (`max(VAD,STT,LLM,TTS)` streaming model, barge-in)
- LiveKit — Voice Agent Architecture: STT, LLM, TTS Pipelines Explained
- LiveKit — Turn Detection for Voice Agents (VAD, endpointing, model-based)
- LiveKit Docs — Agent session / Events (`agent_state_changed`, states, `lk.agent.state`); `update_instructions`, `update_chat_ctx` API
- LiveKit `agents` repo — `AgentSession` source (1.x unified primitive)
- Ollama — implicit KV/prefix caching; `keep_alive` rule; exact-prefix byte-match; improved cross-conversation cache (Mar 2026)
- BentoML LLM Inference Handbook — Prefix caching (exact-prefix requirement, eviction)
- Project PROJECT.md §Context / Key Decisions (stack convergence, inline-and-cache, VRAM budget)

---
*Architecture research for: local near-real-time voice agent (LiveKit Agents) with inline cached KB*
*Researched: 2026-06-24*
</content>
</invoke>
