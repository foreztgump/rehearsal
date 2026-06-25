# Project Research Summary

**Project:** Adept — Near-Real-Time Voice Persona Trainer
**Domain:** Local-first, near-real-time voice-to-voice conversational AI agent (LiveKit Agents pipeline) on a single 16GB-VRAM GPU
**Researched:** 2026-06-24
**Confidence:** HIGH

## Executive Summary

Adept is a voice-first, local-first spoken practice tool: a single user holds a near-real-time conversation (P50 < 1.0s voice-to-voice) with a configurable expert persona, can attach ephemeral documents as a knowledge base, and can flip into an Interview Mode. Experts build this class of product as a **streaming STT→LLM→TTS pipeline** orchestrated by LiveKit Agents (`AgentSession`), with all models self-hosted on one GPU behind OpenAI-compatible HTTP endpoints. The entire design is organized around one metric — latency that "feels live" — which dictates streaming every stage, keeping models resident, and keeping per-turn context lean.

The recommended approach is confirmed and largely matches PROJECT.md: LiveKit Agents + faster-whisper turbo (int8) + Gemma 4 via Ollama + Kokoro TTS, wired with Silero VAD and a **local** semantic turn detector. The knowledge base is handled by "inline-and-cache" — distill docs once at upload into a compact brief, inject once, and rely on Ollama's prefix/KV cache — explicitly **not** per-turn vector RAG, which would inflate the time-to-first-token (TTFT) the whole design depends on.

**Three PRD assumptions are now wrong and must be corrected before roadmap planning** (all from STACK.md): (1) the real `gemma4:e4b` is **9.6GB, not ~5GB** — that raises the resident-model total to ~14GB and makes the 16GB floor *tight*, not comfortable; (2) Gemma 4 ships a **thinking/reasoning mode that must be explicitly disabled** or it destroys TTFT; (3) the **standalone turn-detector plugin is deprecated** and its official replacement defaults to LiveKit *Cloud* — violating local-first — so the local `MultilingualModel` must be pinned. Beyond these, the keystone architectural constraint is the **flat-TTFT invariant** (TTFT must not climb as a session grows), the single biggest P50 lever is **`min_endpointing_delay` tuning** (~500ms default ≈ half the budget), and the KB cache only pays off if the **prompt prefix stays byte-identical** across turns.

## Key Findings

### Recommended Stack

The stack is the de-facto 2026 realtime-voice approach: LiveKit Agents runs the four pipeline stages concurrently so the user never waits on a prior stage, with native barge-in and per-turn latency metrics that directly satisfy the instrumented P50/P95 requirement. Only STT and TTS need the "OpenAI-compatible sidecar" pattern (faster-whisper-server and Kokoro-FastAPI); no bespoke plugin code is required for v1. See **STACK.md** for full version matrix and VRAM math.

**Core technologies:**
- **livekit-agents `~=1.5`** (+ `livekit-server v1.10.x`): orchestration, WebRTC transport, streaming pipeline, barge-in, per-turn metrics — the keystone framework; self-hosted from day one.
- **faster-whisper `1.2.1` (large-v3-turbo, int8)**: STT, ~2GB VRAM, <180ms — fits latency + VRAM budget; served behind an OpenAI-compatible endpoint.
- **Ollama `0.6+` + Gemma 4**: local LLM, OpenAI-compatible; keep-alive + flash-attention + KV-cache quant are what protect the cache the KB strategy relies on.
- **Kokoro-82M** (pinned Docker tag): TTS, ~2–3GB, RTF ~0.03, preset voices; swappable for VoxCPM behind the same interface.
- **livekit-plugins-silero (VAD)** + **livekit-plugins-turn-detector (`MultilingualModel`, local CPU <500MB)**: open-mic VAD + semantic endpointing + correct barge-in.

> **Three PRD corrections (surface prominently — these reshape the roadmap):**
> 1. **Gemma 4 E4B real size ≈ 9.6GB, not ~5GB.** The "~5GB" figure was the older Gemma **3n** E4B. Real `gemma4:e4b` = 9.6GB. New resident-model total: 9.6 (LLM) + 2.0 (Whisper) + 2.5 (Kokoro) ≈ **14.1GB → fits 16GB but headroom is thin**, before KV-cache growth + CUDA overhead. On a strict 16GB floor, prefer `gemma3:4b-it-qat` (~3.3GB) for KV headroom, or run `gemma4:e4b` only with `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`. 24GB makes E4B comfortable.
> 2. **Gemma 4 thinking-mode must be disabled.** Gemma 4 is a reasoning model; thinking emits a long internal preamble before the first user-visible token — catastrophic for TTFT and first-sentence TTS. Omit the `<|think|>` token and don't carry prior-turn thoughts in history.
> 3. **The standalone turn-detector plugin is deprecated; its official replacement is cloud-routed.** `inference.TurnDetector` defaults to LiveKit Cloud → breaks local-first. Pin the local `MultilingualModel` from `livekit-plugins-turn-detector` until an open-weight local v1 path is confirmed.

### Expected Features

Full landscape in **FEATURES.md** (grounded in Yoodli, Google Interview Warmup, Speak/Talkpal/Langua). Net differentiation: Adept fuses live spoken dialogue + one-question-at-a-time interviews + a **model answer** (which competitors omit) + **live-editable any-domain persona** + **your-own-docs grounding** + **local/private/unlimited** practice.

**Must have (table stakes):**
- Full streamed voice loop (mic→STT→LLM→TTS), first-sentence TTS — the product premise
- Low voice-to-voice latency (P50 < 1.0s) — drives architecture, not a later add-on
- Barge-in, semantic turn detection + open-mic VAD — natural turn-taking
- Agent-state indicator + live two-sided transcript — users must know whose turn it is
- Default Cybersecurity Trainer persona, voice selection, session controls, graceful failure

**Should have (competitive differentiators):**
- Live-editable expert persona + behavior knobs (difficulty/verbosity/correction) — the signature flexibility
- Ephemeral per-session KB (upload → distill → inline-cache) — grounded, private, no per-turn RAG
- Interview Mode (ask → critique → **model answer**) — the teaching moment competitors miss
- History management (sliding-window/summarize) — not user-facing, but protects the latency target

**Defer (v2+):**
- Post-session delivery coaching (filler words, pacing) — needs word-level timestamps; keep off the live path
- Cloned trainer voice (VoxCPM), larger model on 24GB, saved persona library, true vector RAG, scoring rubric

### Architecture Approach

Full design in **ARCHITECTURE.md**. A thin browser SPA (LiveKit SDK owns media; custom code owns UI state + a data-channel control protocol) connects through a self-hosted livekit-server SFU to a single Python agent worker. The worker hosts one `AgentSession` and layers persona, KB, history, and modes *over the same pipeline* — never as separate pipelines. All three models share one GPU via local HTTP.

**Major components:**
1. **AgentSession (orchestrator)** — wires VAD→turn-detector→STT→LLM→TTS; streams every stage; barge-in cancel; emits state events.
2. **Persona config** — renders to system prompt + Kokoro voice id; hot-swappable via `update_instructions` (accepts one-turn re-prefill cost).
3. **KB distiller + inline-cache** — upload→parse→guard→distill once→inject once; relies on Ollama prefix/KV cache.
4. **History manager** — sliding-window/summarize *behind* the frozen KB/persona prefix to keep prefill bounded.
5. **Mode state machines** — Interview Mode is a constrained dialogue flow over the same pipeline, not a second stack.

**The flat-TTFT invariant is the keystone architectural constraint.** Streaming makes turn latency `max(VAD,STT,LLM,TTS)` + first-sentence overhead, *not* the sum — but only if LLM TTFT stays flat across the session. Instrument TTFT per turn and assert it does not climb. If it climbs, either the prefix cache is being invalidated (volatile data in the prefix) or history isn't windowed. Everything else (KB caching, history management, prompt layout) exists to protect this invariant.

### Critical Pitfalls

Top items from **PITFALLS.md** (14 detailed, with phase mapping):

1. **`min_endpointing_delay` is the single biggest P50 contributor** — its 500ms default is ~half the entire 1.0s budget. Lower it to ~250–350ms *under the semantic turn-detector's guard* (the model lets you be faster and safer simultaneously). Instrument every stage from day one; never ship with only one timer around the LLM.
2. **KB prefix-cache invalidation** — Ollama's prefix cache requires a **byte-identical** prefix. Lay the prompt out as `[static persona] + [static KB brief] + [rolling history] + [new turn]`; freeze everything before history; put timestamps/turn-counters/mode-state at the very end or out of the prompt. A live persona edit re-prefills one turn (show "applying…") — never edit per turn. Verify empirically: turn-2 TTFT must drop sharply vs turn-1 with a large KB.
3. **VRAM OOM on 16GB under load** — static math ignores KV-cache pre-allocation (`num_ctx` reserves VRAM upfront) + ~0.5–1GB CUDA overhead per process. Size `num_ctx` to the real worst case, enable Flash Attention + `q8_0` KV cache, plan ~12–13GB usable, add an `nvidia-smi` watchdog. The KB-load moment is peak memory.
4. **Cold start / keep-alive eviction** — `keep_alive=-1`, warm all three models at session start, fire a KB priming turn while the user reads "ready."
5. **Open-mic risks (false triggers + echo)** — enable browser AEC/noise-suppression in `getUserMedia`, tune Silero threshold, gate barge-in sensitivity during agent speech; recommend headphones. Plus the **HTTPS/LAN blocker**: `getUserMedia` only works in a secure context, so plain `http://192.168.x.x` breaks the mic entirely — plan HTTPS (mkcert) in Phase 0.

## Implications for Roadmap

The build-order dependency chain from ARCHITECTURE.md is strict and non-negotiable — **each layer needs the one above working first**:

> **bare voice loop → persona → KB → history → interview → polish**

### Phase 0: Environment & Infrastructure
**Rationale:** Several pitfalls are hard blockers that must be solved before any voice flows — HTTPS secure-context (Pitfall 12), VRAM config (Pitfall 9), keep-alive (Pitfall 3), and the metrics scaffold (Pitfall 1).
**Delivers:** Docker Compose stack with GPU passthrough; HTTPS on LAN (mkcert); LiveKit network/ICE config; Ollama env (`keep_alive=-1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, tightly-sized `num_ctx`); per-stage metric logging scaffold; **the deliberate model-tag decision** (gemma4:e4b vs gemma3:4b-it-qat) given the 9.6GB correction.
**Avoids:** Pitfalls 1, 3, 9, 12.

### Phase 1: Bare Voice Loop (hard MVP gate)
**Rationale:** PROJECT.md mandates shipping this before anything else; everything downstream layers on it.
**Delivers:** WebRTC client ↔ livekit-server ↔ agent worker with default-persona `AgentSession` (VAD→turn-detect→STT→LLM→TTS), fully streamed with first-sentence TTS; barge-in; agent-state pill; two-sided transcript.
**Uses:** livekit-agents, faster-whisper sidecar, Ollama/Gemma (**thinking disabled**), Kokoro, Silero VAD, local `MultilingualModel`.
**Addresses:** All table-stakes voice features.
**Avoids:** Pitfalls 2 (first-sentence TTS gate), 4 + 5 (open-mic false triggers + echo), 6 (**tune `min_endpointing_delay`** — the biggest P50 lever), 13 (faster-whisper streaming settings), basic Pitfall 10 (initial history window).

### Phase 2: Persona Layer
**Rationale:** First behavioral layer over the working loop; cheapest high-value differentiator.
**Delivers:** Persona config → system prompt + voice id; behavior knobs; live edit via data channel (`update_instructions` + voice swap) with "applying…" feedback.
**Implements:** Persona config component (Architecture Pattern 2).
**Avoids:** Pitfall 7 — establish the frozen-prefix prompt layout *here*, before KB depends on it.

### Phase 3: Knowledge Base Layer
**Rationale:** Highest-complexity differentiator; depends on a stable prompt prefix from Phase 2. This is the peak-VRAM moment, so re-validate Phase 0 budgets here.
**Delivers:** Upload (PDF/TXT/MD/DOCX) → parse → size guard → distill → inject once → KB-active indicator; ephemeral teardown.
**Uses:** pymupdf/pymupdf4llm + python-docx; one setup-time LLM distillation pass.
**Avoids:** Pitfall 7 (**prefix-cache-invalidation rule** — verify turn-2 TTFT ≪ turn-1), 8 (distillation drops fact anchors), 9 (re-check OOM at KB-load peak), 14 (document-parsing quality gate — reject scanned PDFs clearly).

### Phase 4: History Management
**Rationale:** Can land alongside KB; needed once sessions run long. Protects the flat-TTFT invariant.
**Delivers:** Sliding-window + async summarization placed *behind* the frozen KB/persona prefix.
**Avoids:** Pitfall 10 (TTFT creep / `num_ctx` eviction) without busting the KB cache (Pitfall 7 tension).

### Phase 5: Interview Mode
**Rationale:** Behavioral state machine over the same pipeline; depends on persona + KB + a re-tuned slow-speech endpointing profile.
**Delivers:** ask → listen → critique → model-answer → next; role picked at entry.
**Avoids:** Pitfall 6 re-tune (deliberate "let me think…" speech), Pitfall 11 (E4B critique depth — rubric-structured prompts; document the 24GB fallback).

### Phase 6: Polish
**Delivers:** Session controls (new/reset/end), transcript export, graceful failure handling (mic-denial, garbled STT, KB failure), ephemeral-teardown audit.

### Phase Ordering Rationale

- **Strict downward dependency:** the chain (voice loop → persona → KB → history → interview → polish) is dictated by ARCHITECTURE.md; each layer is testable only once the layer above works.
- **Frozen-prefix layout must exist before KB:** persona (Phase 2) establishes the byte-stable prompt layout that KB caching (Phase 3) depends on — building KB first would force a rework.
- **Metrics + VRAM + HTTPS go to Phase 0:** they are blockers or cheap-now/expensive-later, and the flat-TTFT invariant can't be defended without per-stage instrumentation existing from turn one.
- **Endpointing tuning recurs:** set in Phase 1, re-tuned in Phase 5 (interview slow-speech differs) — it's the largest single P50 contributor, so it earns explicit attention twice.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 0:** Confirm Gemma 4 is on Ollama's flash-attn allowlist (else `q8_0` silently falls back to F16, breaking the VRAM budget); validate the local `MultilingualModel` path and LiveKit ICE/`node_ip` config on the Proxmox VM.
- **Phase 3:** KB distillation quality — fact-anchor preservation and the size-vs-fidelity threshold; document-parser selection for scanned/multi-column/encoding edge cases.
- **Phase 5:** Whether E4B critique meets a feedback-quality bar; define the model-by-mode / 24GB swap trigger.

Phases with standard patterns (lighter research):
- **Phase 2 (persona):** straightforward system-prompt assembly + `update_instructions`.
- **Phase 6 (polish):** conventional UI/session lifecycle work.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against live PyPI / Ollama / Docker Hub / official docs (June 2026); three PRD corrections explicitly resolved. |
| Features | HIGH | Grounded in named comparables (Yoodli, Interview Warmup, Speak/Talkpal/Langua) + platform guidance. |
| Architecture | HIGH | LiveKit `AgentSession` 1.x pipeline + Ollama caching well-documented; persona/KB layering is project-specific design on confirmed primitives. |
| Pitfalls | HIGH | Stack-specific behaviors verified; a few VRAM numbers are estimates flagged inline. |

**Overall confidence:** HIGH

### Gaps to Address

- **Gemma 4 flash-attn allowlist + KV-quant sensitivity:** if Gemma 4 isn't on the allowlist, `q8_0` silently reverts to F16 and the 16GB budget breaks. Validate empirically in Phase 0 before committing to `gemma4:e4b`.
- **Local turn-detector longevity:** the local `MultilingualModel` is officially deprecated (cloud is the steer). Pin it for v1; track LiveKit's open-weight local v1-mini as the eventual replacement.
- **E4B coaching depth:** unresolved until tested in Interview Mode — gate the phase on a strong-vs-weak-answer check; keep the 24GB larger-model swap behind LiveKit's interface.
- **faster-whisper word-level timestamps:** confirm exposed before committing v2 delivery coaching.

## Sources

### Primary (HIGH confidence)
- Ollama library — `gemma4` page (verified `e4b`=9.6GB, `26b`=18GB, thinking mode, sampling params), `gemma3n:e4b`=7.5GB, `gemma3` tags
- PyPI — `livekit-plugins-turn-detector` (deprecation notice, local CPU <500MB), `livekit-plugins-openai`, `markitdown` 0.1.6
- LiveKit docs — Ollama plugin (`with_ollama`), OpenAI-compatible LLM/STT/TTS (`base_url`), turn detection (VAD/endpointing/model), `AgentSession`/events, noise & echo cancellation, self-hosting
- LiveKit blogs — sequential pipeline `max(...)` model + barge-in; transformer end-of-turn detection (`min_endpointing_delay` default 500ms)
- GitHub — `livekit/agents` (`with_ollama`, `AgentSession`), `livekit/livekit` CHANGELOG (server v1.10.1), `SYSTRAN/faster-whisper` v1.2.1, `remsky/Kokoro-FastAPI`
- Ollama docs — `OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE` (q8_0 needs flash attn), keep-alive, prefix caching byte-match + `num_ctx` pre-allocation
- MDN — getUserMedia secure-context (HTTPS/localhost) requirement
- Competitor sources — Yoodli, Google Interview Warmup, Speak/Talkpal/Langua; Telnyx/Inworld latency guidance

### Secondary (MEDIUM confidence)
- LiveKit blog "Solving end-of-turn detection v1" — cloud-default for new turn detector; local v1-mini open weights (confirm local execution before relying on it)
- KV-cache quantization (q8_0/q4_0) high-attention-head sensitivity notes — verify Gemma 4 behaves

### Tertiary (LOW confidence)
- VRAM point estimates (per-process CUDA overhead, Kokoro 2–3GB) — flagged inline; validate with `nvidia-smi` under real load

---
*Research completed: 2026-06-24*
*Ready for roadmap: yes*
