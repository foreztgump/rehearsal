# Project Research Summary

**Project:** Adept — Near-Real-Time Voice Persona Trainer
**Milestone:** v1.1 Local-First Pipeline Swap + Avatar
**Domain:** Subsequent-milestone swap/extension of a shipped local-first LiveKit voice-agent stack (two selectable Ollama LLMs + Nemotron streaming ASR + VRAM-aware STT placement + optional frontend TalkingHead avatar) on a 16GB consumer GPU via `docker compose up`
**Researched:** 2026-06-26
**Confidence:** HIGH (with two flagged MEDIUM sourcing/API items)

## Executive Summary

v1.1 is an **integration milestone, not a greenfield one**: the shipped v1.0 pipeline (LiveKit Agents, Silero VAD + MultilingualModel turn-detection, Ollama brain with thinking-off/keep-alive/flash-attn, Kokoro TTS, Next.js client, ephemeral KB, per-turn speech_id metrics) is the substrate and stays byte-for-byte. Four parts bolt onto it: **A** swaps the single stock LLM for two user-selectable Ollama models (Fast `evalengine/unbound-e2b` 3.4GB default / Better `defyma85/gemma-4-E4B…heretic-Q4_K_M` 5.3GB — both lighter than stock E4B, both abliterated); **B** replaces faster-whisper with NVIDIA `nemotron-speech-streaming-en-0.6b` served behind a local OpenAI-compatible HTTP server; **C** resolves GPU-NeMo vs CPU-ONNX STT placement **once at session start** from VRAM headroom; **D** adds an OPTIONAL, default-OFF, **frontend-only** TalkingHead/HeadAudio Path-A avatar that lip-syncs off the inbound Kokoro audio. Deployment drops the Proxmox VM for consumer-GPU `docker compose up` via the NVIDIA Container Toolkit. Deferred v1.0 polish (session new/reset/end, transcript export, mic/STT graceful failure, final latency tuning) folds in.

The recommended approach keeps every change surgical and reuses verified v1.0 idioms. Part A clones the verified `persona.update` RPC pattern and **mutates the existing LLM plugin in place** (`session.llm.update_options(model=)`) rather than reassigning it — reassignment orphans the metrics subscription and silently breaks the flat-TTFT instrument. Part B keeps the agent pointed at a **single STT `base_url`** and hides GPU-vs-CPU inside the sidecar, so Part C's placement decision never touches agent pipeline code. Part D is gated at the React mount boundary (`next/dynamic ssr:false`) so voice-only loads zero avatar JS. The keystone invariant carried forward: **voice-to-voice P50 < 1.0s / P95 < 1.5s must hold for BOTH LLMs**, and the avatar must add **zero** server VRAM and **zero** latency.

The dominant risks are concentrated in the abliterated community GGUFs and the streaming ASR. Both LLM tags are third-party `:latest` re-quants that frequently ship a **wrong chat template** (the documented `---`-repeat failure) and can **leak reasoning artifacts** despite `reasoning_effort="none"` — and because abliteration removes model-level refusals, **the persona prompt's ethical clause is now the SOLE content guardrail**. This mandates a per-build A-gate (template diff + raw-token artifact check + per-model red-team) with a stock `gemma4` fallback ladder and digest pinning. On the ASR side, `nemotron-speech-streaming-en-0.6b` has a **documented RNNT decoder stall** after sentence boundaries that can strand long interview answers — mitigate with endpoint-coupled finalize + a stall watchdog, and treat the CPU-ONNX port as the safer default if unresolved. The 16GB co-residency math must be **measured** (KV pre-alloc + a 4th GPU process lie in static param math), with global CPU-ONNX as the simplest-robust fallback.

## Key Findings

### Recommended Stack

Three swaps + one addition; everything else unchanged. The two new Ollama tags are verified-real and both lighter than stock E4B (frees STT co-residency headroom). Nemotron is served via NeMo behind an OpenAI-compatible `/v1/audio/transcriptions` + `/v1/audio/stream` server (LiveKit's own documented path, ref repo `ShayneP/local-teleprompter`); a ~150 LOC vendored `LocalNemotronSTT` plugin gives true word-by-word streaming, with `openai.STT(base_url=...)` finalize-only as the safe fallback. The CPU-ONNX port is a **community export, not NVIDIA first-party** (flagged). The avatar is pure client JS pinned against Three.js r0.180.0.

**Core technologies (NEW/CHANGED):**
- **Ollama Fast** `evalengine/unbound-e2b:latest` (3.4GB, Apache-2.0) — default LLM, lowest latency, smallest footprint
- **Ollama Better** `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` (5.3GB) — higher-quality E4B; no readme → highest template risk
- **Stock fallbacks** `gemma4:e2b` (7.2GB) / `gemma4:e4b` (9.6GB) — guaranteed-sane template/thinking-off escape hatch
- **NVIDIA NeMo** `nemo_toolkit[asr]>=2.5.0` + `nemotron-speech-streaming-en-0.6b` — native cache-aware streaming, ~100ms finalize, native punctuation/caps, `att_context_size [56,3]`
- **onnxruntime ~=1.21** + CPU-ONNX port (`danielbodart` int8-dynamic ~0.88GB, or Foundry int4 ~0.67GB) — off-GPU VRAM fallback
- **@met4citizen/talkinghead@1.7.0 + @met4citizen/headaudio@0.1.0 + three@0.180.0** (MIT) — client WebGL avatar, audio-driven Path-A visemes, zero server cost
- **NVIDIA Container Toolkit** — replaces Proxmox PCIe passthrough; existing compose `deploy.resources.reservations.devices` blocks are already correct

See [STACK.md](STACK.md) for verified tags, install costs, and version-compatibility matrix.

### Expected Features

Scope is strictly the four new parts plus rolled-in deferred polish. See [FEATURES.md](FEATURES.md).

**Must have (table stakes):**
- **A** Persistent Fast/Better selector, plain-language labels (hide tags), default Fast, session-persisted, next-turn swap without session teardown
- **B** Growing interim transcript while speaking + ~100ms finalize + native punctuation/caps surfaced as-is
- **C** Invisible STT placement decided once at session start (no GPU/CPU user choice, no thrash, no OOM)
- **D** Default-OFF "Voice only / Avatar" toggle; audio-driven lip-sync tracking Kokoro; instant barge-in stop via existing interrupt
- **SESS-01/02/03** New / reset / end (end clears ephemeral KB) · **SESS-04** transcript export (txt/md, labels+timestamps)
- **REL-01** Graceful mic-permission-denied prompt · **REL-02** garbled/empty-transcription reprompt gate

**Should have (differentiators):**
- **A** User-owned latency↔quality dial live in-session (no fixed-model local app offers this)
- **B** True dictation-like streaming feel on a local English ASR
- **D** Eye contact held while speaking AND listening (the interview point), persona→mood mapping, upper/head framing, persona↔GLB mapping

**Defer (v1.x / v2+):**
- Per-persona model defaults; more avatar moods/gestures; user-selectable GLB per session; operator `att_context_size` profiles
- Larger "Best" 24GB tier; Nemotron cyber-vocab fine-tune; multilingual STT; in-browser TTS / Path B; GLB redistribution bundle

### Architecture Approach

An *integration* document, not greenfield: map Parts A–D onto the verified six-service Compose / single `AgentSession` / `persona.update`-style RPC substrate. Parts A/B/C touch the server pipeline; **Part D must not** (its server diff is provably empty). The cleanest seams: a `model.update` RPC clone for A that mutates the LLM plugin in place; a single STT `base_url` for B with placement hidden in the sidecar; a pure livekit-free `agent/placement.py` for C resolved once in `entrypoint` before `build_session()`; a dynamic-imported, mount-gated `<AvatarStage>` for D. See [ARCHITECTURE.md](ARCHITECTURE.md) for verified file:line anchors and the New-vs-Modified inventory.

**Major components:**
1. **Part A — LLM selector** — NEW `web/app/ModelPanel.tsx` + `model.update` handler + `current_model` holder + two-tag env; mutate-in-place re-target (`[VERIFY]` the `update_options(model=)` setter)
2. **Part B — Nemotron STT service** — NEW `nemo-stt` GPU Compose service + STT plugin rewire in `build_session()`; remove `whisper`
3. **Part C — VRAM-aware placement** — NEW `agent/placement.py` (pure) + `nemo-stt-cpu` service + `STT_FORCE_CPU` flag + Compose profiles (`stt-gpu`/`stt-cpu`)
4. **Part D — Avatar** — NEW `web/app/avatar/*` (TalkingHead + HeadAudio Path-A tap + client-side persona→GLB map); MODIFIES only `VoiceRoom.tsx` (toggle + gated mount)
5. **Part E — Deployment** — NVIDIA Container Toolkit + GPU preflight doctor; existing `deploy.devices` blocks unchanged

### Critical Pitfalls

Top risks from [PITFALLS.md](PITFALLS.md) (v1.1 set replaces v1.0; v1.0 pitfalls are now regression surfaces):

1. **A1/A2/A3 — Community GGUF template drift + reasoning leak + sole-guardrail abliteration** — a wrong chat template degrades silently (`---`-repeat, KB-prefix byte drift); `reasoning_effort="none"` may not suppress baked-in reasoning (first-sentence TTS speaks "`<think>`"); abliteration removes the only refusal so the persona clause is the SOLE guardrail. **Avoid:** a single per-build A-gate — `ollama show --template` diff vs stock + raw-token artifact regex check across ≥20 reasoning-bait prompts + per-model red-team boundary probes; stock `gemma4` fallback ladder; pin by digest, not `:latest`.
2. **B2 — RNNT decoder stall after sentence boundaries** — documented HF issue: transcript freezes ~2–3s and spoken content is lost on long run-on (interview) answers. **Avoid:** couple finalize to LiveKit's VAD/semantic endpoint (not decoder end-punctuation), add a watchdog that force-finalizes on K identical partials while VAD active, pin a mitigated NeMo version; fall to CPU-ONNX if unresolved.
3. **C1 — 16GB co-residency OOM from static param math** — KV pre-alloc (`num_ctx=8192` upfront) + a 4th torch GPU process + fragmentation bust the budget at the KB-load prefill peak. **Avoid:** extend `scripts/vram-validate.sh` into a `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}` peak-measurement matrix (q8_0 engaged, < total−1GB), record in STATE.md; adopt global CPU-ONNX if E4B×GPU-NeMo fails. **Operator gate — needs the real GPU.**
4. **D1 — Avatar quietly touches the server** — lip-sync "wants" phoneme/timestamp data and the easy source is server-side, breaking byte-for-byte voice-only. **Avoid:** CI diff guard (`git diff -- agent/ stt/ tts/` must be empty for avatar changes) + byte-for-byte voice-only proof + identical server VRAM ON/OFF; Path A audio-driven only; reuse the existing interrupt (no second VAD).
5. **B1 / DEPLOY1 — NeMo image bloat + GPU driver/CUDA mismatch** — `nemo_toolkit[all]` + first-run checkpoint download makes `compose up` look hung; consumer driver/CUDA mismatch breaks `--gpus all`. **Avoid:** `[asr]` extra + multi-stage + baked checkpoint + healthcheck/`start_period`; pin container CUDA ≤ host max; ship a preflight `nvidia-smi` doctor with exact remedy text; sub-spec/non-NVIDIA → force CPU-ONNX + Fast.

## Implications for Roadmap

Research strongly converges on a single ordering (ARCHITECTURE.md "Suggested Build Order"), chosen so each server change re-proves the latency/VRAM gates before the next stacks on, and the frontend-only avatar comes last so its "changed nothing server-side" claim is trivially auditable (empty server diff after step 4).

### Phase 1: Part A — LLM Speed Selector
**Rationale:** Lowest risk; clones the verified `persona.update` RPC pattern; doesn't perturb the latency path's structure.
**Delivers:** Two-tag env + extended pull/pin ladder with the per-build A-gate; `model.update` RPC + `current_model` holder; `ModelPanel.tsx`.
**Addresses:** A. persistent Fast/Better picker, plain labels, next-turn swap, user-owned latency dial.
**Avoids:** A1/A2/A3/A4 (template diff + raw-token artifact gate + per-model red-team + digest pin); Anti-Pattern 1 (mutate-in-place, never reassign `session.llm`).

### Phase 2: Part B — Nemotron Streaming ASR Service + Rewire
**Rationale:** Replaces a pipeline stage; must re-prove the STT latency budget before placement can be measured (C depends on B existing).
**Delivers:** `nemo-stt` GPU service (baked checkpoint, healthcheck); STT plugin rewire in `build_session()`; vendored `LocalNemotronSTT` streaming plugin; remove `whisper`.
**Uses:** NeMo + `nemotron-speech-streaming-en-0.6b`, OpenAI-compatible server, `att_context_size [56,3]`.
**Avoids:** B1 (image diet), B2 (decoder-stall watchdog + endpoint-coupled finalize), B3 (non-overlapping cache-reuse loop, measured finalize/punct), B4 (interim emission + async, validated against v1.0 metrics).

### Phase 3: Part C — VRAM-Aware STT Placement + CPU-ONNX Fallback
**Rationale:** Needs B's service to exist and the consumer-GPU co-fit measurement to set its default.
**Delivers:** `nemo-stt-cpu` service + `agent/placement.py` + `STT_FORCE_CPU` + Compose profiles; the co-residency matrix run on the target GPU; safe default set (global CPU-ONNX unless E4B+GPU-STT+Kokoro proves to co-fit).
**Implements:** Part C placement resolver; single-`base_url` agent isolation.
**Avoids:** C1 (measured matrix, not param math), C2 (resolve once, no migration path), C3 (CPU-ONNX benchmarked under contention).

### Phase 4: Part E — Consumer-GPU Deployment
**Rationale:** Folds in with C since C's default depends on the target-GPU measurement; drops Proxmox.
**Delivers:** NVIDIA Container Toolkit path, GPU preflight doctor + clear failure message, `.env`/README shift, `agent.depends_on` updates.
**Avoids:** DEPLOY1 (pinned CUDA + preflight), DEPLOY2 (VRAM/vendor detection → CPU-ONNX + Fast).

### Phase 5: Part D — Avatar (OPTIONAL, frontend-only, isolated)
**Rationale:** LAST and isolated — the server pipeline must be frozen and proven before a frontend-only layer observes it, making the empty-server-diff claim auditable.
**Delivers:** Dynamic-imported `<AvatarStage>` + HeadAudio Path-A tap + existing-interrupt barge-in + client-side persona→GLB map + default-OFF toggle; eye-contact/mood/framing bundle.
**Avoids:** D1 (server-diff guard + byte-for-byte voice-only), D2 (no second VAD), D3 (Mixamo+ARKit-52+Oculus-15 blendshape assert), D4 (Meshopt/Draco + FPS floor + degrade-to-voice), D5 (no non-redistributable GLB bundled).

### Phase 6: Deferred v1.0 Polish (rolled in)
**Rationale:** Slots after the pipeline is stable; REL-02 couples to Part B's finalize behavior.
**Delivers:** SESS-01/02/03 (new/reset/end + ephemeral teardown incl. KB), SESS-04 export, REL-01 mic-denied, REL-02 garbled/empty reprompt, final P50<1.0s/P95<1.5s tuning for both LLMs.
**Avoids:** POLISH1 (extend teardown to v1.1 state — LLM choice, decoder cache, avatar, placement — + privacy re-audit of the NeMo server).

### Phase Ordering Rationale

- **A before B** — A is a contained RPC clone; B restructures the latency path, so prove A's flat-TTFT first.
- **B before C** — placement cannot be measured without the NeMo service existing.
- **C with/before E** — the consumer-GPU co-fit measurement sets C's safe default; E's hardware detection feeds C.
- **D strictly last** — server frozen after step 4 ⇒ Part D's server diff is provably empty.
- **Polish after the pipeline is stable** — REL-02 builds on B's finalize, teardown must cover all new v1.1 state.

### Research Flags

Phases likely needing deeper research/verification during planning:
- **Phase 1 (A):** `[VERIFY]` `session.llm.update_options(model=)` exists in the installed `livekit-plugins-openai` (introspect; fallback = reassign + `metrics.reattach_llm()`). The A-gate harness design (raw-token capture + red-team set) is net-new.
- **Phase 2 (B):** `[VERIFY]` the exact LiveKit Nemotron/`openai.STT` plugin shape and interim/final contract; reproduce + mitigate the B2 RNNT stall; tune `att_context_size` on a dev-set.
- **Phase 3 (C):** **Operator gate** — co-residency matrix MUST be captured on the real consumer GPU (sandbox has no GPU/Docker). CPU-ONNX port sourcing is MEDIUM (community, not first-party).
- **Phase 5 (D):** GLB rig/blendshape validation + licensing per persona; consumer-laptop FPS validation.

Phases with standard patterns (lighter research):
- **Phase 4 (E):** Well-documented NVIDIA Container Toolkit setup; existing compose blocks already correct.
- **Phase 6 (Polish):** Mostly known v1.0 deferrals; main novelty is auditing the v1.1 state teardown.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Ollama tags, NeMo serving path, LiveKit STT integration, TalkingHead/HeadAudio, consumer-GPU passthrough all verified live June 2026. MEDIUM only on exact 4-bit ONNX CPU port sourcing (community export). |
| Features | HIGH | Grounded in TalkingHead/HeadAudio API surface, Nemotron streaming semantics, LiveKit interrupt model, ASR partial/final UX precedent, model-selector product precedent. |
| Architecture | HIGH | Verified against real agent/web/compose code (file:line anchors). MEDIUM `[VERIFY]` on two installed-API signatures (LLM model setter, Nemotron STT plugin shape) — sandbox cannot import livekit. |
| Pitfalls | HIGH | Verified against the Nemotron model card + open RNNT-stall discussion, Ollama/GGUF template-drift threads, TalkingHead rig requirements, NVIDIA Container Toolkit tracker. VRAM numbers are estimates flagged for per-GPU measurement. |

**Overall confidence:** HIGH

### Gaps to Address

- **`update_options(model=)` setter existence** — introspect the installed plugin first thing in Phase 1; ship the reassign+`reattach_llm` fallback if absent.
- **CPU-ONNX port production-readiness + WER/latency on the real CPU** — community export; benchmark on target CPU under contention (Phase 3); int8-dynamic (~0.88GB) is the lower-risk alternative to int4 (~0.67GB).
- **16GB co-residency peak** — must be measured on the consumer GPU (operator gate); global CPU-ONNX is the safe default until the matrix proves a GPU split fits.
- **RNNT decoder-stall mitigation durability** — track upstream HF discussion; CPU-ONNX is the structural fallback if the stall persists.
- **Per-build chat-template/thinking/guardrail validity of mutable `:latest` community tags** — A-gate + digest pin; `igorls/gemma-4-E4B-it-heretic-GGUF` is a documented lower-risk Better alternative.
- **GLB blendshape rig + licensing per persona** — validate at config time (Mixamo+ARKit-52+Oculus-15); ship only redistribution-cleared assets.

## Sources

### Primary (HIGH confidence)
- Ollama library — `evalengine/unbound-e2b`, `defyma85/…heretic-Q4_K_M`, `gemma4:e2b/e4b` (sizes, ctx, licenses, Modelfile defaults) — fetched June 2026
- HF `nvidia/nemotron-speech-streaming-en-0.6b` model card + discussion #5 (RNNT decoder stall) + #6 (no official quant)
- LiveKit blog "Multilingual speech-to-text on your laptop" + `ShayneP/local-teleprompter` (NeMo serving, `openai.STT` finalize + `LocalNemotronSTT` streaming)
- GitHub `met4citizen/talkinghead` + `HeadAudio` README + `examples/minimal.html` (three@0.180.0 importmap, Path-A worklet, rig/blendshape requirements)
- Docker Compose GPU docs + NVIDIA Container Toolkit install (`deploy.resources.reservations.devices`, `nvidia-ctk runtime configure`)
- Real repository code — `agent/main.py`, `agent/persona.py`, `agent/metrics.py`, `docker-compose.yml`, `web/app/*`, `ollama/*`, `scripts/vram-validate.sh` (verified file:line integration anchors)

### Secondary (MEDIUM confidence)
- HF `danielbodart/nemotron-speech-600m-onnx` (int8-dynamic ~0.88GB CPU) — exists/loads HIGH, production-readiness MEDIUM
- Microsoft Foundry Local int4 (~0.67GB) + arXiv 2604.14493 — matches PROJECT's number; needs Foundry 1.1.x SDK + manual transcribe path
- GitHub `pmarreck/gemma4-heretical` + HF discuss threads — community Gemma-4 GGUF wrong-template `---`-repeat failure and `RENDERER/PARSER gemma4` fix
- Streaming-ASR UX (Deepgram, AssemblyAI, Forasoft 2026); model-selector precedent (ChatGPT, Perplexity, Copilot)

### Tertiary (LOW confidence / needs validation)
- Installed `livekit-plugins-openai` LLM `update_options(model=)` setter signature — `[VERIFY]` by introspection in Phase 1
- Exact LiveKit Nemotron STT plugin shape vs `openai.STT` repoint — `[VERIFY]` against installed packages
- Per-consumer-GPU VRAM co-residency peaks — operator measurement required

---
*Research completed: 2026-06-26*
*Ready for roadmap: yes*
