# Adept — Near-Real-Time Voice Persona Trainer

## What This Is

Adept is a voice-first, local-first web app where a single user holds a spoken, near-real-time conversation with a configurable AI expert persona to build domain fluency and interview confidence. The default persona is a Cybersecurity Trainer; the user can edit the persona live to become any domain expert, attach their own documents as a per-session knowledge base, and flip into an Interview Mode that role-plays realistic interviews with feedback. It's for working professionals upskilling or prepping for interviews who want to *sound* like a practitioner — not just pass a written test.

## Core Value

The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud, not reading about it.

## Business Context

<!-- Not monetized — self-hosted single-user homelab tool. -->

- **Customer**: Tee (owner) and similar self-hosting professionals prepping for interviews / upskilling
- **Revenue model**: None — local, free-to-run, private by design
- **Success metric**: Voice-to-voice P50 < 1.0s with a conversation that subjectively "feels live"
- **Strategy notes**: Local execution is a hard requirement — sensitive material (study notes, employer-specific prep) and per-token API cost would discourage the long repetitive practice that builds fluency

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet — ship to validate)

### Active

<!-- Current scope. Building toward these. -->

- [ ] Voice loop: capture mic → transcribe → LLM → speak response, fully streamed
- [ ] Barge-in: agent stops speaking instantly when the user starts talking
- [ ] Semantic turn detection (endpointing, not a fixed timer) so it doesn't cut in on pauses
- [ ] Open-mic VAD input mode (decided: VAD from the start, not push-to-talk)
- [ ] Visible agent state indicator: listening / thinking / speaking
- [ ] Live two-sided transcript
- [ ] Default Cybersecurity Trainer persona (practitioner voice, pulls user into articulating, gently corrects terminology)
- [ ] Persona editor: role/instructions, name, behavior knobs (difficulty, verbosity, correction-aggressiveness), applied in-session
- [ ] Voice selection per persona (Kokoro preset voices)
- [ ] Knowledge base: upload docs (PDF, TXT, MD, DOCX) at session start
- [ ] KB distillation: parse + distill into a compact domain brief at upload time
- [ ] KB loaded into session context once; rely on Ollama prefix/KV caching (no per-turn RAG)
- [ ] KB ephemeral per-session (cleared at session end)
- [ ] KB active indicator + upload size guard
- [ ] Learn/Converse mode (default open conversation)
- [ ] Interview Mode: agent asks one question at a time, user answers, agent critiques + gives a model answer; role picked at mode entry
- [ ] Session controls: new / reset / end
- [ ] Export/download session transcript
- [ ] Voice-to-voice latency P50 < 1.0s, P95 < 1.5s (instrumented via LiveKit per-turn metrics)
- [ ] Runs entirely on local hardware (16GB VRAM floor)
- [ ] Single-page UI; talk to default trainer within seconds of load
- [ ] Containerized — one Docker Compose stack to bring up
- [ ] Graceful handling of mic-permission denial, garbled transcription, KB upload failure

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Multi-user accounts / auth / SaaS multi-tenancy — single-user homelab tool; concurrency is a future scaling problem
- Telephony / phone calls — web/mic only
- Native mobile app — web-first
- Persistent cross-session memory or user profiles — simplicity + privacy for v1
- Model fine-tuning or training — prompt-engineer the personas instead
- Payments / billing — not monetized
- Avatars or video — voice-first only
- Analytics dashboards — not needed for single user
- True vector RAG (chunk → embed → retrieve) — deferred to v2+; inline-and-cache covers small KBs and avoids per-turn TTFT inflation; RAG reserved for oversized KBs
- Saved persona library — single default + live editing for v1; named library is v2+
- Persistent/named KB collections — ephemeral per-session for v1 (privacy + simplicity)
- Delivery coaching (filler-word counting, vagueness flags, pacing notes) — stretch goal, v2+
- Push-to-talk input — decided against; open-mic VAD from the start

## Context

- **Stack converged during planning:** LiveKit Agents (orchestration/transport/turn-detection/barge-in), faster-whisper turbo int8 (STT), Gemma 4 E4B via Ollama with keep-alive + flash attention (LLM), Kokoro via OpenAI-compatible server (TTS).
- **LLM model (decided):** `gemma4:e4b-it-q4_K_M` served by Ollama, with the model's **thinking/reasoning mode turned OFF** (it inflates TTFT and breaks first-sentence TTS streaming — a research-flagged correction). Note: research found the default `gemma4:e4b` is ~9.6GB; the q4_K_M quant is the smaller-footprint choice for the 16GB VRAM floor.
- **Latency is the headline metric.** Design optimizes time-to-first-token and first-sentence streaming, NOT throughput — E4B generates far faster than speech is spoken. Start TTS on the first completed sentence rather than waiting for the full LLM response.
- **KB is inline + cached, not RAG.** Documents distilled to a compact domain brief at upload (setup-time work where latency is invisible), loaded into context once, held in prefix/KV cache so it costs prefill only on turn one and is effectively free afterward.
- **Hardware:** 16GB VRAM floor (E4B Q4 ~5GB + faster-whisper turbo int8 ~2GB + Kokoro ~2–3GB; no embedder or vector store in v1). 24GB recommended for headroom and an optional larger model (Gemma 4 26B-A4B MoE or Qwen3 8B fallback).
- **Deployment:** Docker Compose; GPU passthrough into a Proxmox VM (homelab). LiveKit self-hosted from day one (decided).
- **TTS is swappable** via the OpenAI-compatible interface — VoxCPM for a custom/cloned trainer voice is a later option without rewiring.
- **History management matters:** sliding-window the conversation history / summarize older turns so growing history doesn't inflate per-turn TTFT.

## Constraints

- **Tech stack**: LiveKit Agents + faster-whisper turbo + Gemma 4 E4B (Ollama) + Kokoro — all locally hosted, models pluggable behind LiveKit
- **Performance**: Voice-to-voice P50 < 1.0s, P95 < 1.5s — drives every architecture decision (stream every stage, keep models resident, lean context)
- **Hardware**: 16GB VRAM floor, 24GB recommended; GPU passthrough into Proxmox VM
- **Privacy / local-first**: No audio, transcripts, or KB content leaves the local network in v1 — sensitive material is the use case
- **Concurrency**: Single concurrent user assumed for v1
- **Simplicity**: Single-page UI; sensible defaults; talk within seconds of load; hard MVP gate — ship the bare voice loop with the default persona before anything else

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Open-mic VAD from the start (not PTT) | More natural; aligns with the "feels live" core value | — Pending |
| Self-host LiveKit from day one | Local-first purity; no external dependency ever | — Pending |
| KB ephemeral per-session for v1 | Privacy + simplicity | — Pending |
| Interview role picked at mode entry | Flexibility across SOC analyst / security engineer / GRC etc. | — Pending |
| Inline-and-cache KB, not per-turn RAG | Avoids inflating TTFT — the metric the design depends on | — Pending |
| `gemma4:e4b-it-q4_K_M` via Ollama as the brain | Smaller quant fits the 16GB VRAM floor; generates faster than speech is spoken | — Pending |
| Disable Gemma thinking/reasoning mode | Thinking mode inflates TTFT and breaks first-sentence TTS streaming | — Pending |
| Stream every stage; start TTS on first sentence | Only way to hit sub-second voice-to-voice latency | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-24 after initialization*
