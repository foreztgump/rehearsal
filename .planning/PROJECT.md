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

## Current Milestone: v1.1 Local-First Pipeline Swap + Avatar

**Goal:** Swap the voice pipeline to user-selectable Ollama LLMs and NVIDIA Nemotron streaming ASR with VRAM-aware STT placement, drop the Proxmox-VM assumption so `docker compose up` runs on the user's consumer machine with GPU detection/passthrough, add an optional client-side 3D avatar, and finish the deferred v1.0 polish — without regressing sub-1s voice-to-voice latency or the persona content guardrail.

**Target features:**
- **LLM (Part A):** Two user-selectable Ollama models (Fast = E2B, Better = E4B Q4_K_M), UI picker defaulting to Fast, session-persisted, thinking-off/streaming/keep-alive/flash-attn/capped num_predict preserved, per-build template + thinking-off verification with stock fallback.
- **STT (Part B):** Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b` (NeMo behind a local HTTP server) as the LiveKit STT plugin — true streaming, ~100ms finalize, `att_context_size [56,3]` knob, native punctuation/caps.
- **STT placement (Part C):** GPU vs 4-bit ONNX CPU port resolved at session start by VRAM headroom coupled to the selected LLM; simplest-robust fallback is global CPU-ONNX STT.
- **Avatar (Part D, frontend-only, optional):** met4citizen/TalkingHead talking head with Path-A HeadAudio lip-sync on the inbound Kokoro WebRTC audio, barge-in via the existing LiveKit interrupt, "Voice only / Avatar" toggle (default Voice only), eye-contact/mood, persona↔avatar GLB mapping. Zero server GPU cost; MUST NOT touch the server pipeline.
- **Deployment:** `docker compose up` on the user's machine; consumer-GPU detection/passthrough.
- **Deferred v1.0 polish (rolled in):** session controls, transcript export, graceful mic/STT failure handling, final latency tuning.

### Active

<!-- Current scope. Building toward these. v1.1 = pipeline swap + avatar + deferred v1.0 polish. -->

**v1.1 pipeline swap + avatar:**
- [ ] Two user-selectable Ollama LLMs (Fast E2B default / Better E4B) with a UI picker, session-persisted, next-turn switch
- [ ] Preserve thinking-off, token streaming, OLLAMA_KEEP_ALIVE, flash attention, lean context, capped num_predict for both models
- [ ] Per-build verification that chat template is sane and thinking-off suppresses reasoning artifacts; stock gemma4 fallback if a build misbehaves
- [ ] Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b` served via NeMo behind a local HTTP server, wired as the LiveKit STT plugin
- [ ] True streaming STT: growing transcript while speaking, finalize within ~100ms of end-of-speech, `att_context_size` config knob, native punctuation + capitalization
- [ ] VRAM-aware STT placement resolved at session start (GPU full-NeMo vs 4-bit ONNX CPU port), coupled to the selected LLM, with a global CPU-ONNX fallback
- [ ] Optional client-side 3D avatar (TalkingHead) with Path-A HeadAudio lip-sync, existing-interrupt barge-in, eye-contact/mood, persona↔avatar GLB mapping, default-off toggle, zero server GPU cost
- [ ] `docker compose up` on the user's machine with consumer-GPU detection/passthrough (no Proxmox-VM assumption)

**Deferred v1.0 polish (rolled into v1.1):**
- [ ] Session controls: new / reset / end (clearing ephemeral state incl. KB) — SESS-01/02/03
- [ ] Export/download session transcript — SESS-04
- [ ] Graceful mic-permission-denial prompt (no silent failure) — REL-01
- [ ] Garbled/empty-transcription reprompt instead of responding to noise — REL-02
- [ ] Final latency tuning pass to confirm P50 < 1.0s / P95 < 1.5s on target hardware

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Multi-user accounts / auth / SaaS multi-tenancy — single-user homelab tool; concurrency is a future scaling problem
- Telephony / phone calls — web/mic only
- Native mobile app — web-first
- Persistent cross-session memory or user profiles — simplicity + privacy for v1
- Model fine-tuning or training — prompt-engineer the personas instead (Nemotron cyber-vocab fine-tuning is a noted future hook, not built in v1.1)
- Payments / billing — not monetized
- Analytics dashboards — not needed for single user
- True vector RAG (chunk → embed → retrieve) — deferred to v2+; inline-and-cache covers small KBs and avoids per-turn TTFT inflation; RAG reserved for oversized KBs
- Saved persona library — single default + live editing for v1; named library is v2+
- Persistent/named KB collections — ephemeral per-session for v1 (privacy + simplicity)
- Delivery coaching (filler-word counting, vagueness flags, pacing notes) — stretch goal, v2+
- Push-to-talk input — decided against; open-mic VAD from the start
- ~~Avatars or video~~ — REVERSED in v1.1: an OPTIONAL, default-off, frontend-only 3D talking-head avatar is now in scope (Part D). The server pipeline stays voice-first and untouched.
- In-browser TTS (TalkingHead Path B / HeadTTS / in-browser Kokoro) — out of scope; TTS stays server-side Kokoro. Avatar lip-sync is audio-driven (Path A) only.
- Client-side webcam/video capture — still out; the avatar is a rendered talking head, not real video.
- Multilingual STT (nemotron-3.5) — out; app is English cyber/interview prep and the English checkpoint has the 4-bit ONNX CPU port Part C requires.
- Runtime mid-session STT GPU↔CPU thrashing — out; placement is resolved once at session start (or globally pinned to CPU-ONNX via the fallback).
- Public redistribution of avatar GLB assets — out unless licensing is re-confirmed; personal/internal use only for v1.1.

## Context

- **Shipped v1.0-rc1 (Phases 1-6) on 2026-06-26:** the full conversational MVP — self-hosted stack, streamed voice loop with barge-in, live-editable persona, ephemeral KB, history management, interview mode. ~21,180 LOC across 112 commits / 113 files. Remaining for v1.0: Phase 7 (session controls, transcript export, graceful-failure handling, final latency tuning).
- **Verification posture:** the agent/web code and self-checks are green, but several keystone proofs are operator-runbook gates needing the live RTX/Proxmox VM — KB flat-TTFT (turn-2≪turn-1), three-models-under-16GB with q8_0, P50<1.0s confirmation, and strong-vs-weak interview-critique discrimination. These are documented runbooks (`04-KB-VERIFY.md`, `06-INTERVIEW-VERIFY.md`), not yet operator-signed.
- **Stack converged during planning:** LiveKit Agents (orchestration/transport/turn-detection/barge-in), faster-whisper large-v3 (STT), Gemma 4 E4B via Ollama with keep-alive + flash attention (LLM), Kokoro via OpenAI-compatible server (TTS).
- **LLM model (decided):** `gemma4:e4b-it-q4_K_M` served by Ollama, with the model's **thinking/reasoning mode turned OFF** (it inflates TTFT and breaks first-sentence TTS streaming — a research-flagged correction). Note: research found the default `gemma4:e4b` is ~9.6GB; the q4_K_M quant is the smaller-footprint choice for the 16GB VRAM floor.
- **Latency is the headline metric.** Design optimizes time-to-first-token and first-sentence streaming, NOT throughput — E4B generates far faster than speech is spoken. Start TTS on the first completed sentence rather than waiting for the full LLM response.
- **KB is inline + cached, not RAG.** Documents distilled to a compact domain brief at upload (setup-time work where latency is invisible), loaded into context once, held in prefix/KV cache so it costs prefill only on turn one and is effectively free afterward.
- **Hardware:** 16GB VRAM floor (E4B Q4 ~5GB + faster-whisper turbo int8 ~2GB + Kokoro ~2–3GB; no embedder or vector store in v1). 24GB recommended for headroom and an optional larger model (Gemma 4 26B-A4B MoE or Qwen3 8B fallback).
- **Deployment:** Docker Compose; GPU passthrough into a Proxmox VM (homelab). LiveKit self-hosted from day one (decided).
- **v1.1 — Deployment shift:** drop the Proxmox-VM assumption. `docker compose up` must run directly on the user's consumer machine, with consumer-GPU detection and passthrough (NVIDIA Container Toolkit / `--gpus all` path) rather than VM PCIe passthrough. The 16GB target GPU budget and local-first privacy posture are unchanged.
- **v1.1 — LLM pipeline swap:** the single stock `gemma4:e4b-it-q4_K_M` is replaced by TWO user-selectable Ollama models — Fast `evalengine/unbound-e2b:latest` (E2B-class, default, lower latency) and Better `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` (E4B Q4_K_M, higher quality). Both community GGUF finetunes need per-build chat-template + thinking-off verification; fall back to stock `gemma4:e2b`/`gemma4:e4b` if a build misbehaves. Both are uncensored/abliterated, so the persona prompt's ethical boundary is the ONLY content guardrail and must stay intact. Both must be lighter than the ~9GB stock E4B default tag.
- **v1.1 — STT pipeline swap:** faster-whisper is replaced by `nvidia/nemotron-speech-streaming-en-0.6b` (600M Cache-Aware FastConformer-RNNT, native streaming) served via NeMo behind a local HTTP server and wired into LiveKit's STT plugin per LiveKit's Nemotron voice-agent example. English-only by design — as-good-or-better on English AND has the 4-bit ONNX CPU port the multilingual model lacks. NeMo+torch is a several-GB, ~10-min first install — account for it in the container build.
- **v1.1 — STT placement coupling:** STT runs on GPU (full NeMo) when the Fast/E2B LLM leaves VRAM headroom, or on the 4-bit ONNX CPU port (~0.67GB, >6× realtime, negligible WER loss) when the Better/E4B LLM makes GPU headroom tight. Placement is resolved ONCE at session start (no mid-session thrashing). Preferred simplest-robust fallback: if measurement shows E4B + GPU-STT + Kokoro can't coexist on the target GPU, default STT to CPU-ONNX globally for both LLM choices.
- **v1.1 — Optional 3D avatar (frontend-only):** met4citizen/TalkingHead (MIT, Three.js/WebGL) renders an optional talking head inside the existing voice UI. Path A lip-sync routes LiveKit's INBOUND Kokoro audio through the HeadAudio worklet for audio-driven viseme detection — no server change. Barge-in reuses the existing LiveKit user-speech-start interrupt (`streamInterrupt()`), no second VAD. Default-off "Voice only / Avatar" toggle; voice-only mode must be byte-for-byte pre-avatar with zero residual overhead. Persona config extends to map each persona to an avatar GLB + mood (reusing its voice). GLBs need a Mixamo rig + ARKit(52) + Oculus(15) viseme blendshapes (RPM/Avaturn). Rendering is client-side WebGL — ZERO server VRAM cost; target ~30fps, Meshopt/Draco compression, graceful degradation. Confirm GLB licensing before any redistribution. Reference precedent: met4citizen EdgeSpeaker + the repo's OpenAI-Realtime + HeadAudio WebRTC Path-A example.
- **TTS is swappable** via the OpenAI-compatible interface — VoxCPM for a custom/cloned trainer voice is a later option without rewiring. v1.1 keeps Kokoro server-side; in-browser TTS (TalkingHead Path B) is explicitly out.
- **History management matters:** sliding-window the conversation history / summarize older turns so growing history doesn't inflate per-turn TTFT.

## Constraints

- **Tech stack (v1.1)**: LiveKit Agents + NVIDIA Nemotron streaming ASR (NeMo / 4-bit ONNX CPU port) + two user-selectable Ollama LLMs (E2B/E4B) + Kokoro — all locally hosted, models pluggable behind LiveKit. Optional frontend: Three.js + met4citizen/TalkingHead + HeadAudio (client-side only).
- **Performance**: Voice-to-voice P50 < 1.0s, P95 < 1.5s — drives every architecture decision (stream every stage, keep models resident, lean context). v1.1: must hold for BOTH LLM choices; STT leg target drops toward sub-100ms finalize; avatar mode adds NO latency regression.
- **Hardware**: 16GB VRAM floor, 24GB recommended. v1.1: `docker compose up` on the user's consumer machine with consumer-GPU detection/passthrough (NVIDIA Container Toolkit), NOT Proxmox-VM PCIe passthrough. Avatar rendering is client-side WebGL — zero server GPU cost.
- **Content guardrail (v1.1)**: the new LLMs are uncensored/abliterated — the persona prompt's ethical boundary (security at interview-appropriate level, not step-by-step attack instructions) is the ONLY content guardrail and must stay intact.
- **Pipeline isolation (v1.1)**: the avatar (Part D) is frontend-only and MUST NOT change the server pipeline (Parts A/B/C) in any way.
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
| **v1.1** Two user-selectable Ollama LLMs (Fast E2B default / Better E4B) instead of one stock model | Speed is the priority; let the user trade latency for quality per session | — Pending (v1.1 Part A) |
| **v1.1** Verify community GGUF chat-template + thinking-off per build; stock gemma4 fallback | Uncensored finetunes can ship broken templates or leak `<think>`/`<channel>` artifacts | — Pending (v1.1 Part A.5) |
| **v1.1** Persona prompt is the SOLE content guardrail | New LLMs are abliterated — model-level refusals are gone | — Pending (v1.1 Part A.6) |
| **v1.1** Replace faster-whisper with NVIDIA Nemotron streaming ASR (English) | Native streaming → sub-100ms finalize; English checkpoint has the 4-bit ONNX CPU port Part C needs | — Pending (v1.1 Part B) |
| **v1.1** Resolve STT GPU-vs-CPU placement once at session start, coupled to the LLM | Avoids mid-session thrash; CPU-ONNX frees VRAM for the heavier E4B | — Pending (v1.1 Part C) |
| **v1.1** Simplest-robust fallback: global CPU-ONNX STT if E4B+GPU-STT+Kokoro can't co-fit | Makes the picker VRAM-safe with no runtime switching | — Pending (v1.1 Part C) |
| **v1.1** Optional avatar is frontend-only (TalkingHead Path A), MUST NOT touch server pipeline | Zero server GPU cost; voice-only stays byte-for-byte identical | — Pending (v1.1 Part D) |
| **v1.1** Avatar lip-sync is audio-driven (HeadAudio on inbound Kokoro WebRTC), TTS stays server-side | No transcription/timestamps, no server change; Path B in-browser TTS rejected | — Pending (v1.1 Part D.2/D.4) |
| **v1.1** Avatar barge-in reuses the existing LiveKit interrupt (no second VAD) | One turn-taking source of truth | — Pending (v1.1 Part D.3) |
| **v1.1** Drop Proxmox-VM assumption; `docker compose up` on the user's machine with consumer-GPU detection/passthrough | Lower friction; consumer-GPU target instead of homelab VM | — Pending (v1.1 deployment) |
| **v1.1** Pull deferred v1.0 Phase 7 polish (SESS-01..04, REL-01/02, latency tuning) into v1.1 | Ship lifecycle + graceful-failure polish alongside the pipeline swap | — Pending (v1.1) |

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
*Last updated: 2026-06-26 after starting milestone v1.1 (Local-First Pipeline Swap + Avatar)*
