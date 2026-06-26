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

<!-- Shipped + verified. Moved out of Active as phases complete. Shipped in v1.0-rc1 (Phases 1-6). -->

- ✓ Self-hosted Docker Compose stack (LiveKit, agent, Ollama, Whisper, Kokoro, web) with GPU passthrough, pinned `gemma4:e4b-it-q4_K_M`, defended 16GB VRAM budget, per-stage metrics scaffold — v1.0-rc1 (Phase 1; live Docker/GPU proofs operator-gated on the Proxmox VM)
- ✓ Fully streamed voice loop: open-mic VAD → semantic turn-detect → STT → LLM → first-sentence TTS — v1.0-rc1 (Phase 2)
- ✓ Barge-in: agent stops speaking instantly when the user starts talking — v1.0-rc1 (Phase 2)
- ✓ Visible agent-state indicator (listening/thinking/speaking) + live two-sided transcript — v1.0-rc1 (Phase 2)
- ✓ Per-turn voice-to-voice latency instrumented (speech_id-keyed buffer, rolling P50/P95) — v1.0-rc1 (Phase 2; P50<1.0s/P95<1.5s target confirmation operator-gated on the VM)
- ✓ Default Cybersecurity Trainer persona (practitioner voice, pulls user into articulating, gently corrects terminology) — v1.0-rc1 (Phases 2-3)
- ✓ Persona editor: role/instructions, name, behavior knobs (difficulty, verbosity, correction-aggressiveness), applied in-session via hot-swap — v1.0-rc1 (Phase 3)
- ✓ Voice selection per persona (Kokoro preset voices) — v1.0-rc1 (Phase 3)
- ✓ Ephemeral KB: upload PDF/TXT/MD/DOCX → parse + size-guard → distill once into a compact brief → inject once into the frozen prefix → Ollama prefix/KV cache (no per-turn RAG); KB-active indicator + clear upload-failure handling — v1.0-rc1 (Phase 4; flat-TTFT turn-2≪turn-1 proof operator-gated on the VM)
- ✓ Sliding-window conversation history (`HistoryWindowAgent`, items capped each turn behind the frozen persona+KB prefix) keeps per-turn TTFT flat over long sessions — v1.0-rc1 (Phase 5; flat-TTFT-over-time proof operator-gated on the VM)
- ✓ Interview Mode: toggle in, pick a target role (SOC analyst / security engineer / GRC), agent asks one role-relevant question at a time, waits, then gives a rubric-structured critique + a strong model answer; slow-speech endpointing re-tune — v1.0-rc1 (Phase 6; live loop + strong-vs-weak critique gate operator-gated on the VM via `06-INTERVIEW-VERIFY.md`)

### Active

<!-- Current scope. Building toward these. Remaining v1.0 work = Phase 7. -->

- [ ] Session controls: new / reset / end (clearing ephemeral state incl. KB) — Phase 7 (SESS-01/02/03)
- [ ] Export/download session transcript — Phase 7 (SESS-04)
- [ ] Graceful mic-permission-denial prompt (no silent failure) — Phase 7 (REL-01)
- [ ] Garbled/empty-transcription reprompt instead of responding to noise — Phase 7 (REL-02)
- [ ] Final latency tuning pass to confirm P50 < 1.0s / P95 < 1.5s on target hardware — Phase 7

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

- **Shipped v1.0-rc1 (Phases 1-6) on 2026-06-26:** the full conversational MVP — self-hosted stack, streamed voice loop with barge-in, live-editable persona, ephemeral KB, history management, interview mode. ~21,180 LOC across 112 commits / 113 files. Remaining for v1.0: Phase 7 (session controls, transcript export, graceful-failure handling, final latency tuning).
- **Verification posture:** the agent/web code and self-checks are green, but several keystone proofs are operator-runbook gates needing the live RTX/Proxmox VM — KB flat-TTFT (turn-2≪turn-1), three-models-under-16GB with q8_0, P50<1.0s confirmation, and strong-vs-weak interview-critique discrimination. These are documented runbooks (`04-KB-VERIFY.md`, `06-INTERVIEW-VERIFY.md`), not yet operator-signed.
- **Stack converged during planning:** LiveKit Agents (orchestration/transport/turn-detection/barge-in), faster-whisper large-v3 (STT), Gemma 4 E4B via Ollama with keep-alive + flash attention (LLM), Kokoro via OpenAI-compatible server (TTS).
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
| Open-mic VAD from the start (not PTT) | More natural; aligns with the "feels live" core value | ✓ Phase 2 — Silero VAD @0.65, semantic endpointing on `turn_handling` |
| Self-host LiveKit from day one | Local-first purity; no external dependency ever | ✓ Phase 1 — LAN-pinned ICE (udp mux 7882), no STUN egress |
| KB ephemeral per-session for v1 | Privacy + simplicity | ✓ Phase 4 — in-memory docs, cleared at session end |
| Interview role picked at mode entry | Flexibility across SOC analyst / security engineer / GRC etc. | ✓ Phase 6 — role picker drives `mode.update` prompt swap |
| Inline-and-cache KB, not per-turn RAG | Avoids inflating TTFT — the metric the design depends on | ✓ Phase 4 — distill-once → frozen `KB_SLOT` → prefix cache (VM proof pending) |
| `gemma4:e4b-it-q4_K_M` via Ollama as the brain | Smaller quant fits the 16GB VRAM floor; generates faster than speech is spoken | ✓ Phase 1 — tag verified real on RTX 5090 host |
| Disable Gemma thinking/reasoning mode | Thinking mode inflates TTFT and breaks first-sentence TTS streaming | ✓ Phase 2 — `with_ollama(reasoning_effort="none")` |
| Stream every stage; start TTS on first sentence | Only way to hit sub-second voice-to-voice latency | ✓ Phase 2 — first-sentence TTS streaming wired (P50 VM proof pending) |
| Pin effective Ollama context to 8192 (`num_ctx`) | Default silently truncated at 4096, dropping the KB brief — surfaced by Phase-4 UAT | ✓ Phase 4 — service env pin + persona+brief+history+headroom accounting |
| Cap history via `truncate(max_items=20)`+`update_chat_ctx` behind the prefix | Keeps TTFT flat over long sessions without ever busting the cached persona+KB prefix | ✓ Phase 5 — first `Agent` subclass, prefix untouched |
| Persona knobs render fixed-string fragments, not interpolated numbers | Byte-stable frozen prefix the Phase-4 KB cache depends on; small models follow prose better than a bare dial | ✓ Phase 3 — byte-stability self-check green |
| Live persona hot-swap via `persona.update` RPC (in-place `update_instructions`+`update_options`) | One-turn re-prefill with no session/agent/TTS teardown; native RPC return is the "applied" ack | ✓ Phase 3 — verified live via CDP |

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
*Last updated: 2026-06-26 after v1.0-rc1 milestone (Phases 1-6 — MVP Release Candidate)*
