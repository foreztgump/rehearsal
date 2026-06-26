# Stack Research

**Domain:** v1.1 Local-First Pipeline Swap + optional Avatar for a near-real-time voice persona trainer (LiveKit Agents + Ollama + Next.js, single consumer GPU)
**Researched:** 2026-06-26
**Confidence:** HIGH on Ollama tags, NeMo serving path, LiveKit STT integration, TalkingHead/HeadAudio, and consumer-GPU passthrough (all verified live June 2026). MEDIUM on the exact 4-bit ONNX CPU port sourcing (community export, not first-party — flagged below).

> **Scope discipline — this file covers ONLY what is NEW for v1.1.** The v1.0 stack (LiveKit server/agents, Silero VAD, local `MultilingualModel` turn detector, Kokoro TTS, Next.js client, KB parse deps) is shipped and unchanged. Do not re-research it. Three things are being swapped (LLM tags, STT engine, deployment target) and one thing is being added (frontend avatar). Everything else stays byte-for-byte.

> **Read this first — five v1.1 findings that pin or correct the milestone plan:**
> 1. **Both named Ollama tags are real and verified (June 2026), and BOTH are lighter than stock E4B.** Fast `evalengine/unbound-e2b:latest` = **3.4GB** (128K ctx, text-only, Apache-2.0). Better `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` = **5.3GB** (128K ctx, text-only). Both << the ~9.6GB stock `gemma4:e4b`. See [Part A](#part-a--llm-swap-two-selectable-ollama-models).
> 2. **The community GGUF chat-template risk is REAL and documented.** Community Gemma-4 GGUF uploads frequently ship a *wrong* chat template (incorrect turn delimiters) that makes the model emit `---` on repeat instead of replies, unless `RENDERER gemma4`/`PARSER gemma4` is set. This is exactly why PROJECT.md's Part A.5 per-build verification + stock fallback exists. See [Part A.5](#a5--per-build-template--thinking-off-verification-the-real-risk).
> 3. **The model is `nemotron-speech-streaming-en-0.6b` and the LiveKit integration path is a documented blog + reference repo** (`ShayneP/local-teleprompter`) — NeMo behind an OpenAI-compatible `/v1/audio/transcriptions` + `/v1/audio/stream` WebSocket server, wired via the **OpenAI STT plugin for finalized turns** and a **small custom `LocalNemotronSTT` plugin for true word-by-word streaming**. NeMo + torch is a ~several-GB / ~10-min first install. See [Part B](#part-b--stt-swap-nemotron-streaming-asr-via-nemo).
> 4. **The 4-bit ONNX CPU port is a community export, not NVIDIA-first-party.** NVIDIA confirmed on HF they have *no* official quant. Two real sources exist: `danielbodart/nemotron-speech-600m-onnx` (int8-dynamic ~0.88GB, direct NeMo export, onnxruntime) and the Microsoft Foundry Local catalog entry (int4, ~0.67GB, the arXiv 2604.14493 work). PROJECT.md's "~0.67GB 4-bit" number matches the Foundry/arXiv int4 build. See [Part C](#part-c--cpu-onnx-stt-runtime-the-vram-fallback) — sourcing risk flagged.
> 5. **TalkingHead 1.7.0 + HeadAudio 0.1.0 are pinned, MIT, and target Three.js r0.180.0 via importmap/CDN.** HeadAudio is a Web Audio `AudioWorklet` — it consumes a *Web Audio node*, not a raw `MediaStreamTrack`, so the WebRTC inbound Kokoro track must be bridged via `AudioContext.createMediaStreamSource()`. See [Part D](#part-d--optional-avatar-frontend-only).

---

## Recommended Stack

### Core Technologies (NEW / CHANGED for v1.1)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Ollama Fast model** | `evalengine/unbound-e2b:latest` (3.4GB, 128K ctx, Apache-2.0) | Default LLM "brain" — E2B-class, lowest latency | Verified real on Ollama (455 dl, updated June 2026). Uncensored finetune of `google/gemma-4-E2B-it`; ~2B effective params; text-only (no vision overhead). Ships a sane Modelfile (`temp 0.6, top_p 0.95, top_k 64, repeat_penalty 1.05, num_ctx 8192`). Smallest VRAM footprint of the two — frees the most headroom for GPU-STT co-residency. |
| **Ollama Better model** | `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` (5.3GB, 128K ctx) | Higher-quality LLM "brain" — E4B Q4_K_M | Verified real (1,189 dl, updated June 2026). Q4_K_M abliterated/heretic finetune of Gemma-4-E4B; still ~4GB lighter than stock `gemma4:e4b`. Couples to CPU-ONNX STT when its larger footprint tightens GPU headroom. |
| **Stock LLM fallbacks** | `gemma4:e2b` (7.2GB) / `gemma4:e4b` (9.6GB) | Drop-in fallback if a community build misbehaves | Official Ollama tags with correct built-in `RENDERER gemma4`/`PARSER gemma4`. The guaranteed-sane template + thinking-off path required by Part A.5. |
| **NVIDIA NeMo toolkit** | `nemo_toolkit[asr] >= 2.5.0` (2.8.x current line) | Serves `nemotron-speech-streaming-en-0.6b` (Cache-Aware FastConformer-RNNT) for GPU streaming STT | The model's native runtime. `ASRModel.from_pretrained(...)` + `conformer_stream_step()` is the cache-aware streaming loop. `att_context_size` and punctuation/caps are native. |
| **nemotron-speech-streaming-en-0.6b** | HF checkpoint `nvidia/nemotron-speech-streaming-en-0.6b` (March 2026 checkpoint; `.nemo` ~2.4GB) | 600M streaming English ASR | Native streaming (cache-aware, no buffered re-processing), ~100ms end-of-utterance on GPU, native punctuation + capitalization, `att_context_size [56,3]` balanced default. English-only → has the CPU-ONNX port the multilingual 3.5 model also has but PROJECT scopes out. |
| **PyTorch (NeMo dep)** | `torch ~=2.6` (whatever NeMo 2.8 pins; install via NeMo, do not pin independently) | NeMo backend | Pulled transitively by NeMo. This + NeMo is the "~several GB, ~10-min first install" PROJECT.md calls out — bake into the STT image. |
| **onnxruntime** | `onnxruntime ~=1.21` (CPU build for the fallback; `onnxruntime-gpu` only if you ever run ONNX on CUDA) | Runs the 4-bit/int8 ONNX CPU port of the model | The CPU STT runtime. CPU wheel is small; avoids dragging torch+NeMo into the CPU-only fallback path. |
| **@met4citizen/talkinghead** | `1.7.0` (MIT) | Client-side 3D talking-head avatar (Three.js/WebGL) | Pinned npm/CDN release. Renders RPM/Mixamo-rigged GLB with ARKit(52)+Oculus(15) visemes, mood, eye-contact, hand gestures. Zero server cost. |
| **@met4citizen/headaudio** | `0.1.0` (MIT) | Audio-driven (Path A) viseme detection worklet | MFCC + Mahalanobis classifier in an `AudioWorklet`; emits Oculus viseme blendshapes from *any* audio stream — no transcript/timestamps, no server change. Drives TalkingHead lip-sync off the inbound Kokoro WebRTC audio. |
| **three** | `0.180.0` | WebGL renderer TalkingHead depends on | The version TalkingHead 1.7.0's official `examples/minimal.html` importmap pins. Match it exactly to avoid Three.js API drift. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **livekit-agents** | bump `~=1.5` pin to `>=1.5.6` (1.5.6 latest stable, Apr 2026; 1.5.19rc on the plugins line) | Orchestration — unchanged role | Keep the existing pin; no upgrade strictly required for v1.1. The custom STT node API (`stt.STT` base class, `SpeechStream`, `SpeechEvent`) is stable across 1.5.x. |
| **livekit-plugins-openai** | `~=1.5` (already installed) | Drives Ollama LLM **and** the Nemotron OpenAI-compatible STT endpoint | `openai.STT(base_url=..., model="nemotron-speech-streaming-en-0.6b", language="en")` for the finalize-only path; `with_ollama(...)` unchanged for the LLM. |
| **`LocalNemotronSTT`** (custom, ~150 LOC, vendored) | from `ShayneP/local-teleprompter` agent reference | True word-by-word streaming STT over the WebSocket `/v1/audio/stream` | Use when you want growing partials + ~100ms finalize (PROJECT Part B). It subclasses `livekit.agents.stt.STT` and pushes `INTERIM_TRANSCRIPT`/`FINAL_TRANSCRIPT` events into the session. |
| **livekit-plugins-nvidia** | `1.5.x` | NVIDIA **Riva** STT plugin | NOT for local Nemotron — Riva defaults to `grpc.nvcf.nvidia.com` (cloud) and needs a Riva NIM server. Only relevant if you self-host Riva; the NeMo+OpenAI-server path is simpler and avoids the Riva export step. Listed here so the roadmapper doesn't mistake it for the path. |
| **soundfile / numpy** | latest compatible | Audio I/O for the NeMo STT server | Server-side WAV/PCM handling in the STT sidecar. |
| **fastapi + uvicorn** | latest | Hosts the OpenAI-compatible `/v1/audio/transcriptions` + `/v1/audio/stream` endpoints around NeMo | The STT sidecar web layer (mirrors the teleprompter `stt-server`). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **NVIDIA Container Toolkit** | Consumer-GPU passthrough for `docker compose up` on the user's machine (the sole supported deployment — no VM/PCIe path) | Install on host: `nvidia-container-toolkit` apt package + `nvidia-ctk runtime configure --runtime=docker` + restart Docker. Each GPU service keeps its existing `deploy.resources.reservations.devices` block (already in the compose file). |
| **`ollama pull` in an init step** | Pre-pull both LLM tags + run template/thinking-off verification before the agent registers | Extend the existing `ollama/pull-and-pin.sh` to pull both tags and run the Part A.5 probe per build. |
| **HF CLI (`hf download`)** | Fetch the ONNX CPU port + the `.nemo` checkpoint at build time | Bake into the STT image so the container starts offline-capable (mirrors v1.0's `download-files`). |

## Installation

```bash
# --- Part A: LLM (Ollama) — pull both, plus stock fallbacks ---
ollama pull evalengine/unbound-e2b:latest                                   # Fast, 3.4GB (default)
ollama pull defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest  # Better, 5.3GB
ollama pull gemma4:e2b   # stock fallback for Fast
ollama pull gemma4:e4b   # stock fallback for Better

# --- Part B: STT GPU runtime (NeMo) — bake into a dedicated STT image ---
# Python 3.10+; install pulls torch + NeMo (~several GB, ~10 min first build).
uv pip install "nemo_toolkit[asr]>=2.5.0" soundfile fastapi uvicorn numpy
# Checkpoint (~2.4GB .nemo) — pre-fetch at build time:
#   ASRModel.from_pretrained("nvidia/nemotron-speech-streaming-en-0.6b")

# --- Part C: STT CPU fallback (ONNX) — small, no torch/NeMo ---
uv pip install "onnxruntime~=1.21"
# Community 4-bit/int8 ONNX export (see sourcing risk):
hf download danielbodart/nemotron-speech-600m-onnx int8-dynamic/ shared/ config.json --local-dir ./model
# (or the Foundry Local int4 ~0.67GB build — see Part C)

# --- Part D: Avatar (frontend-only, web/) ---
npm install @met4citizen/talkinghead@1.7.0 @met4citizen/headaudio@0.1.0 three@0.180.0
# OR via CDN importmap (no bundler change) — see Part D.
```

Agent wiring (the only server change for Parts A/B; C is a runtime-select swap):

```python
# Part A — LLM tag resolved from session-selected pick (Fast default), thinking-off preserved
llm = openai.LLM.with_ollama(
    model=selected_llm_tag(),            # "evalengine/unbound-e2b:latest" | "defyma85/...:latest"
    base_url=OLLAMA_BASE_URL,
    reasoning_effort="none",             # UNCHANGED — maps to Ollama Think=false over /v1
)

# Part B — finalize-only path (zero custom code) via OpenAI-compatible Nemotron server:
stt = openai.STT(
    base_url="http://nemotron-stt:8000/v1",
    model="nemotron-speech-streaming-en-0.6b",
    api_key="unused",
    language="en",
)
# Part B (streaming) — vendored custom plugin for word-by-word partials over WS:
# stt = LocalNemotronSTT(base_url="ws://nemotron-stt:8000", language="en")

# Part C — placement resolved ONCE at session start by VRAM headroom (coupled to LLM pick):
#   GPU NeMo server (nemotron-stt-gpu)  when Fast/E2B leaves headroom
#   CPU ONNX server (nemotron-stt-cpu)  when Better/E4B tightens it (or global fallback)
```

---

## Plugin Availability: Official vs Custom (v1.1 delta)

| Service | Official LiveKit plugin? | How to integrate |
|---------|--------------------------|------------------|
| **Ollama (LLM, both tags)** | ✅ `openai.LLM.with_ollama()` — unchanged | Just swap the `model=` string per session pick. Everything else (thinking-off via `reasoning_effort="none"`, streaming, keep-alive, flash-attn, num_predict cap) is already wired and carries over verbatim. |
| **Nemotron STT (GPU, finalize-only)** | ✅ via `openai.STT(base_url=...)` | NeMo behind the OpenAI-compatible `/v1/audio/transcriptions` server (LiveKit's own documented path). Zero custom plugin code. Loses interim partials. |
| **Nemotron STT (GPU, true streaming)** | ❌ — needs a small custom plugin | Vendored `LocalNemotronSTT` (`stt.STT` subclass) talks the `/v1/audio/stream` WebSocket, emits interim + final transcripts. Source: `ShayneP/local-teleprompter` agent. ~150 LOC. |
| **Nemotron STT (CPU ONNX)** | ❌ — wrap the same OpenAI server contract around onnxruntime | Run the ONNX encoder/decoder in the *same* FastAPI server shell as the GPU one, switched by env (`STT_RUNTIME=gpu|cpu`). Then the agent points at one `base_url` and never knows the difference — keeps the agent code identical across placements. |
| **Avatar (TalkingHead/HeadAudio)** | N/A — frontend only | Pure client JS in `web/`. No LiveKit plugin. Subscribes to the existing inbound Kokoro audio track. |

**Net:** the cleanest design keeps the **agent pointed at a single STT `base_url`** and resolves GPU-vs-CPU **inside the STT sidecar** (or by choosing which sidecar container the agent's `STT_BASE_URL` resolves to at session start). That isolates the Part C placement decision from the agent's pipeline code.

---

## Part A — LLM swap (two selectable Ollama models)

### Tags verified (Ollama library, June 2026)

| Role | Tag | Size | Ctx | License | Notes |
|------|-----|------|-----|---------|-------|
| **Fast (default)** | `evalengine/unbound-e2b:latest` | 3.4GB | 128K | Apache-2.0 | Uncensored finetune of `gemma-4-E2B-it`. Refusal rate 98.46%→4.42%. Modelfile defaults: `temp 0.6, top_p 0.95, top_k 64, repeat_penalty 1.05, num_ctx 8192`. `tools`, `thinking` capabilities shown on the model page. |
| **Better** | `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` | 5.3GB | 128K | (inherits Gemma license) | Q4_K_M heretic/abliterated E4B. Repackages `llmfan46/gemma-4-E4B-it-ultra-uncensored-heretic-GGUF`. No readme on the Ollama page — treat template as unverified until A.5 probe. |
| Fallback (Fast) | `gemma4:e2b` | 7.2GB | 128K+ | Gemma | Official; correct built-in template. |
| Fallback (Better) | `gemma4:e4b` | 9.6GB | 128K+ | Gemma | Official; correct built-in template. |

### A.1–A.4 — Preserve the v1.0 latency contract for BOTH models

All of these are already wired and **carry over unchanged** — they are model-agnostic:
- **Thinking-off:** `reasoning_effort="none"` on `with_ollama` (maps to Ollama `Think=false` over `/v1`). The warmup path uses `"think": false` on `/api/generate`. Both Gemma-4 finetunes inherit Gemma's thinking capability, so this MUST stay on the hot path.
- **Token streaming:** unchanged (AgentSession streams; first-sentence TTS).
- **`OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=8192`:** service-level env in compose — apply to whichever tag is loaded. Verify q8_0 KV-cache engages (not silently F16) for the new tags via the existing `scripts/vram-validate.sh` (Gemma-4 GGUF arch must be on Ollama's flash-attn allowlist).
- **Capped `num_predict`:** keep the existing cap in the agent's LLM options.
- **Switching models:** session-persisted picker, next-turn switch. Because both are full models (not adapters), Ollama loads the second on first use; with `KEEP_ALIVE=-1` both can stay resident **only if VRAM allows** — at 3.4+5.3=8.7GB resident for both plus STT+TTS this is tight on 16GB. **Recommendation: keep only the selected model resident** (let the unselected one unload), or accept a one-turn reload on switch. This couples to Part C placement.

### A.5 — Per-build template + thinking-off verification (the real risk)

**Confirmed failure mode:** community Gemma-4 GGUF uploads ship an *incorrect* chat template (wrong turn delimiters), so the model emits `---` repeatedly instead of replies unless `RENDERER gemma4`/`PARSER gemma4` is set (documented in `pmarreck/gemma4-heretical`). The `defyma85` tag has *no readme* and is a raw GGUF repackage → **highest template risk**. `evalengine/unbound-e2b` ships its own Modelfile and is lower-risk but still must be probed.

**Per-build probe (run in `pull-and-pin.sh` after each pull):**
1. `ollama show <tag> --modelfile` → assert `RENDERER gemma4` / `PARSER gemma4` (or a correct `<start_of_turn>`/`<end_of_turn>` template) is present.
2. Send a 1-turn chat with `reasoning_effort="none"`; assert the response is non-empty, is NOT a run of `---`, and contains **no** `<think>`/`<channel>`/`<|...|>` reasoning artifacts.
3. On failure → fall back to the stock `gemma4:e2b`/`gemma4:e4b` tag for that role. This is the PROJECT.md Part A.5 gate; the stock tags are the guaranteed-sane escape hatch.

### A.6 — Content guardrail

Both models are abliterated/uncensored — model-level refusals are gone. The **persona prompt's ethical boundary is the SOLE content guardrail** and must stay intact (PROJECT constraint). No stack change; a verification concern for the persona prompt, not this file.

---

## Part B — STT swap: Nemotron streaming ASR via NeMo

### How it's served (the concrete path, not hand-waved)

LiveKit published the exact pattern (blog: "Multilingual speech-to-text on your laptop", 2026-06-05) with a reference repo (`ShayneP/local-teleprompter`). The English `nemotron-speech-streaming-en-0.6b` uses the **identical serving code** as the multilingual 3.5 model in that post — only the checkpoint name and the (fixed) language differ.

**Three layers:**
1. **NeMo directly:** `ASRModel.from_pretrained("nvidia/nemotron-speech-streaming-en-0.6b")`, then `model.encoder.set_default_att_context_size([56, 3])` (balanced), then the cache-aware loop: `CacheAwareStreamingAudioBuffer` → `model.conformer_stream_step(...)` per chunk, reading back a growing `hyps[0].text`. Native punctuation + capitalization. (English model needs no `set_inference_prompt` language call — that's a 3.5-multilingual feature.)
2. **OpenAI-compatible HTTP server (FastAPI):** wrap NeMo behind `/v1/audio/transcriptions` (one-shot/SSE) **and** `/v1/audio/stream` (WebSocket: raw PCM in, transcript deltas out). This is the `stt-server` in the reference repo.
3. **LiveKit Agents:**
   - **Finalize-only (zero custom code):** `openai.STT(base_url="http://nemotron-stt:8000/v1", model="nemotron-speech-streaming-en-0.6b", api_key="unused", language="en")`.
   - **True streaming (custom plugin):** `LocalNemotronSTT` — a `livekit.agents.stt.STT` subclass that opens the WebSocket, sends a `config` message on open, and emits `INTERIM_TRANSCRIPT` (growing) + `FINAL_TRANSCRIPT` (~100ms after end-of-speech) `SpeechEvent`s into the `AgentSession`. Vendor it from the reference repo's `agent/`.

**Recommendation:** ship the **custom `LocalNemotronSTT` streaming plugin** — PROJECT Part B explicitly wants "growing transcript while speaking, finalize within ~100ms." The finalize-only OpenAI path is the safe fallback if the WS plugin misbehaves.

### Version pins + install cost

| Item | Pin | Size / Time |
|------|-----|-------------|
| `nemo_toolkit[asr]` | `>=2.5.0` (2.8.x line current) | NeMo + torch + CUDA libs = **several GB**, **~10 min** first install (LiveKit's own number). Bake into the STT image. |
| `torch` | let NeMo pin it (≈2.6) | included above; do not pin independently or you risk a NeMo/torch mismatch. |
| `.nemo` checkpoint | March 2026 checkpoint (default branch) | ~2.4GB download; pre-fetch at build. The Jan-2026 checkpoint is on the `nemotron-speech-streaming-jan2026` branch — use the default (newer, larger-corpus). |
| `att_context_size` | `[56, 3]` balanced | knob: `[56,0]` snappiest deltas → `[56,13]` most accurate. PROJECT pins `[56,3]`. |

### VRAM (GPU placement)

Full NeMo model on GPU is ~600M params (~1.2–1.5GB fp16 + CUDA buffers). Co-residency math on 16GB:
- Fast/E2B (3.4GB) + NeMo-GPU (~1.5GB) + Kokoro (~2.5GB) ≈ **7.4GB** → comfortable headroom → **GPU STT**.
- Better/E4B (5.3GB) + NeMo-GPU (~1.5GB) + Kokoro (~2.5GB) ≈ **9.3GB** → still fits 16GB but tighter once KV cache grows → **GPU STT likely OK, but this is the case Part C de-risks** by moving STT to CPU-ONNX.

---

## Part C — CPU-ONNX STT runtime (the VRAM fallback)

### Sourcing — RISK FLAGGED

NVIDIA has **no first-party quant** (confirmed by NVIDIA staff on the HF discussion: "We don't have quantized versions to share at the moment"). Two real community/MS sources:

| Source | Variant | Size | Runtime | Confidence |
|--------|---------|------|---------|------------|
| **`danielbodart/nemotron-speech-600m-onnx`** | `int8-dynamic/` (CPU) | **~0.88GB** (encoder 799MB + decoder 34MB FP32) | onnxruntime CPU EP | HIGH it exists & loads; MEDIUM on production-readiness (single-author, exported directly from the NeMo checkpoint, full QDQ/streaming-calibration documented). License CC-BY-4.0. |
| **Microsoft Foundry Local catalog** (`nemotron-speech-streaming-en-0.6b`) | int4 k-quant (the arXiv 2604.14493 work) | **~0.67GB** | onnxruntime-genai / Foundry Local SDK 1.1.x | MEDIUM — matches PROJECT's "~0.67GB, >6× realtime, int4" exactly. BUT: requires Foundry Local 1.1.x SDK; the bundled ORT-GenAI does **not** register the `nemotron_speech` multimodal type for the standard `AudioClient.transcribe()` path (documented gotcha), so you wrap it manually. |

**PROJECT.md's "~0.67GB 4-bit, >6× realtime, negligible WER loss" = the Foundry/arXiv int4 build.** The danielbodart int8-dynamic (~0.88GB) is the more directly-usable-with-plain-onnxruntime alternative if int4-via-Foundry proves awkward to containerize.

**RISK:** neither is NVIDIA-official; both are recent community/research artifacts. **Mitigation:** PROJECT already names the **global CPU-ONNX fallback** and, failing that, the v1.0 path. If the int4 port can't be containerized cleanly, fall back to int8-dynamic (~0.88GB, still CPU, still >RT) — the extra ~0.2GB is RAM not VRAM, so it costs nothing against the GPU budget.

### How it's wired (no agent change)

Run the ONNX encoder/decoder inside the **same FastAPI server contract** as the GPU server (same `/v1/audio/transcriptions` + `/v1/audio/stream`), selected by `STT_RUNTIME=cpu`. ONNX preprocessing params are fully documented in the port's `config.json` (16kHz, 128 mel bands Slaney, 560ms/56-frame chunks + 9 cache frames, cache tensors fed forward). The agent points at one `STT_BASE_URL`; **placement is resolved once at session start** by measuring VRAM headroom against the selected LLM, then routing to the GPU or CPU sidecar. No mid-session thrash (PROJECT constraint).

**Simplest-robust landing (PROJECT-preferred):** if measurement shows E4B + GPU-STT + Kokoro can't co-fit on the target GPU, **default STT to CPU-ONNX globally** for both LLM picks — VRAM-safe, no runtime switching, ~0.67–0.88GB RAM cost.

---

## Part D — Optional avatar (frontend-only)

### Versions + delivery

| Package | Version | Delivery |
|---------|---------|----------|
| `@met4citizen/talkinghead` | **1.7.0** (MIT, last publish ~6mo) | NPM `@met4citizen/talkinghead@1.7.0` or CDN `https://cdn.jsdelivr.net/npm/@met4citizen/talkinghead@1.7.0` |
| `@met4citizen/headaudio` | **0.1.0** (MIT) | NPM `@met4citizen/headaudio@0.1.0`; worklet processor served as a static `.mjs` (`headworklet.min.mjs`) + the `model-en-mixed.bin` (~14kB) |
| `three` | **0.180.0** | importmap `"three": "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js/+esm"` + `"three/addons/"` — matches TalkingHead 1.7.0's official `examples/minimal.html` |

### How HeadAudio consumes the inbound Kokoro WebRTC audio (Path A)

**Key correction:** HeadAudio is a Web Audio `AudioWorkletNode`. It consumes a **Web Audio node**, NOT a raw `MediaStreamTrack` directly. The official example connects `head.audioSpeechGainNode` (TalkingHead's own playback node). For our case the audio arrives on a LiveKit inbound `MediaStreamTrack`, so bridge it:

```js
// 1. Get the inbound Kokoro audio track from LiveKit (existing subscription).
const mediaStream = new MediaStream([kokoroAudioTrack.mediaStreamTrack]);
// 2. Bridge WebRTC track → Web Audio graph.
const src = head.audioCtx.createMediaStreamSource(mediaStream);
// 3. Register the worklet processor, create HeadAudio, load model.
await head.audioCtx.audioWorklet.addModule("./dist/headworklet.min.mjs");
const headaudio = new HeadAudio(head.audioCtx, { parameterData: { vadGateActiveDb: -40, vadGateInactiveDb: -60 }});
await headaudio.loadModel("./dist/model-en-mixed.bin");
// 4. Pipe the WebRTC source into HeadAudio (single mono input, no audio output).
src.connect(headaudio);
// 5. Map visemes → avatar blendshapes; drive from TalkingHead's animation loop.
headaudio.onvalue = (key, value) => Object.assign(head.mtAvatar[key], { newvalue: value, needsUpdate: true });
head.opt.update = headaudio.update.bind(headaudio);
```

- **Output:** 15 Oculus visemes (`viseme_aa`, `viseme_E`, …, `viseme_sil`), `[0,1]`, ~50ms end-to-end latency, <0.1ms CPU per 128-sample block. Optional `DelayNode` (50–100ms) on the *audible* path to compensate processing latency.
- **Barge-in:** reuse the **existing LiveKit user-speech-start interrupt** (`streamInterrupt()`) — no second VAD (PROJECT constraint). HeadAudio's internal gate VAD only gates viseme detection, it is NOT a turn-taking source.
- **Eye-contact/mood/gestures:** `head.lookAtCamera()`, `head.speakWithHands()` triggered off HeadAudio `onstarted`/`onended` (sentence boundaries), exactly as the reference `openai.html` WebRTC Path-A example does.
- **GLB requirements:** Mixamo rig + ARKit(52) + Oculus(15) viseme blendshapes (RPM/Avaturn). Persona→GLB+mood mapping extends the persona config. Confirm GLB licensing before any redistribution (PROJECT out-of-scope guard).

---

## Deployment — consumer-GPU passthrough (docker compose, single machine)

**The compose file already uses the correct syntax** — no change needed to the GPU service blocks:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all          # or device_ids: ["0"] to pin a specific GPU
          capabilities: [gpu]
```
The **host setup** is the NVIDIA Container Toolkit on the machine running `docker compose` (the only supported deployment — no VM/PCIe-passthrough path):
1. Install NVIDIA driver on the host.
2. Install **NVIDIA Container Toolkit**: add the `nvidia-container-toolkit` apt/dnf repo, install, then `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`.
3. Verify: `docker run --rm --gpus all nvidia/cuda:12.x-base nvidia-smi`.
4. `docker compose up` — the existing `deploy.resources.reservations.devices` blocks now resolve against the host GPU.

**Notes/risks:**
- `deploy.resources.reservations.devices` works with `docker compose up` but is **ignored by `docker stack deploy`/Swarm** (documented). Single-machine compose is the target → fine.
- The **new `nemotron-stt-gpu` service** needs the same `devices` block; the **`nemotron-stt-cpu` service** must NOT (it's CPU-only — keep torch/NeMo out of it, onnxruntime CPU only).
- Add `NEXT_PUBLIC_*` avatar asset paths to the web build args if GLBs are bundled.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| NeMo + OpenAI-compatible server (Part B) | NVIDIA Riva NIM + `livekit-plugins-nvidia` | You already run a Riva server. Adds a `nemo2riva` export step + a heavier runtime; defaults to cloud unless `server=` is set local. Not worth it here. |
| `LocalNemotronSTT` custom streaming plugin | `openai.STT(base_url=...)` finalize-only | If interim partials aren't needed or the WS plugin is unstable — simpler, zero custom code, but loses the growing-transcript UX. |
| `danielbodart` int8-dynamic ONNX (~0.88GB) | Foundry Local int4 (~0.67GB) | int4 is smaller and matches PROJECT's number, but needs Foundry Local 1.1.x SDK + a manual transcribe path. Use int8-dynamic if you want plain `onnxruntime` with no extra SDK. |
| `evalengine/unbound-e2b` (Fast) | `gemma4:e2b` stock | If the community build fails the A.5 template/thinking probe. |
| `defyma85/...heretic-Q4_K_M` (Better) | `igorls/gemma-4-E4B-it-heretic-GGUF:Q4_K_M` (5.0GB, has README + benchmarks) | If `defyma85` (no readme, raw GGUF) fails A.5 — `igorls` documents its Heretic build and template fix and is a lower-risk Better candidate. Worth flagging to the roadmapper as a safer Better alt. |
| TalkingHead Path A (HeadAudio, audio-driven) | TalkingHead Path B (HeadTTS/in-browser TTS, text-driven) | NEVER for v1.1 — Path B moves TTS to the client; explicitly OUT of scope. |
| three@0.180.0 | newer three | Only if TalkingHead bumps its peer pin; track TalkingHead's `examples` importmap as source of truth. |

## What NOT to Use / NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Moving TTS to the client (TalkingHead Path B / HeadTTS / in-browser Kokoro)** | Explicitly out of scope; breaks the "server pipeline untouched" + voice-only-byte-for-byte invariants. | Server-side Kokoro stays; avatar lip-sync is audio-driven Path A on the inbound WebRTC track. |
| **A second VAD for the avatar** | One turn-taking source of truth (PROJECT). HeadAudio's gate VAD is for viseme gating only. | Reuse the existing LiveKit `streamInterrupt()` barge-in. |
| **Multilingual `nemotron-3.5-asr-streaming-0.6b`** | App is English cyber/interview prep; the English checkpoint has the CPU-ONNX port and avoids language-prompt overhead. | English `nemotron-speech-streaming-en-0.6b`. |
| **Mid-session GPU↔CPU STT thrashing** | Reload churn + latency spikes. | Resolve placement ONCE at session start (or global CPU-ONNX fallback). |
| **`livekit-plugins-nvidia` (Riva) for local Nemotron** | Cloud-default endpoint + a Riva export/serving step you don't need. | NeMo + OpenAI-compatible server (+ custom WS plugin). |
| **Keeping BOTH LLM tags resident with `KEEP_ALIVE=-1` on 16GB** | 3.4+5.3=8.7GB resident + STT + TTS busts the budget. | Keep only the selected tag resident; accept a one-turn reload on switch, or couple to Part C placement. |
| **Pinning `torch` independently of NeMo** | NeMo/torch/CUDA version skew → import/runtime failures. | Let `nemo_toolkit[asr]>=2.5.0` pin its torch. |
| **`:latest` on the new STT/avatar images** | Non-reproducible (same v1.0 rule). | Pin the NeMo base image + ONNX export revision + npm versions. |
| **Trusting the community GGUF chat template blindly** | Documented `---`-repeat failure from wrong delimiters. | A.5 per-build probe + stock `gemma4` fallback. |
| **Dropping `reasoning_effort="none"` for the new models** | Both inherit Gemma-4 thinking → TTFT blow-up + broken first-sentence TTS. | Keep thinking-off on the hot path for both. |

## Stack Patterns by Variant

**If GPU has comfortable headroom (Fast/E2B selected, ~16GB):**
- LLM `evalengine/unbound-e2b` (3.4GB) + **NeMo GPU STT** (~1.5GB) + Kokoro (~2.5GB) → ~7.4GB, room for KV cache.
- Lowest STT latency (~100ms finalize on GPU).

**If GPU is tight (Better/E4B selected, 16GB):**
- LLM `defyma85/...E4B` (5.3GB) + **CPU-ONNX STT** (~0.67–0.88GB RAM, 0 VRAM) + Kokoro (~2.5GB) → ~7.8GB VRAM, STT off-GPU.
- Slightly higher STT latency (still >RT on CPU) but VRAM-safe.

**Simplest-robust (PROJECT-preferred if measurement is unfavorable):**
- **Global CPU-ONNX STT** for both LLM picks. No runtime switching; picker is always VRAM-safe.

**If avatar enabled (any of the above):**
- +0 server VRAM (client WebGL). Target ~30fps, Meshopt/Draco GLB compression, graceful degradation. Voice-only mode must remain byte-for-byte pre-avatar.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `nemo_toolkit[asr]>=2.5.0` | Python 3.10–3.12, torch ≈2.6, CUDA 12.x | Pulls its own torch; don't pin torch separately. `.nemo` default branch = March-2026 checkpoint. |
| `onnxruntime~=1.21` | the danielbodart ONNX export (opset from NeMo export) | CPU EP for int8-dynamic. `nemo2riva 2.22` pins `onnxruntime-gpu==1.21.0` — keep CPU fallback on `onnxruntime` (CPU) to avoid CUDA deps. |
| Foundry Local int4 build | `foundry-local-sdk` 1.1.x | Alias `nemotron-speech-streaming-en-0.6b` only resolves in 1.1.x catalog; bundled ORT-GenAI lacks the `nemotron_speech` multimodal type for the default transcribe path — wrap manually. |
| `@met4citizen/talkinghead@1.7.0` | `three@0.180.0` | Match the version in TalkingHead's `examples/minimal.html` importmap. |
| `@met4citizen/headaudio@0.1.0` | TalkingHead 1.7.0, any modern browser (Chrome/Edge/Firefox/Safari, iOS) | No external deps; needs `AudioWorklet` (secure context — already have TLS via Caddy). Bridge WebRTC track with `createMediaStreamSource`. |
| `openai.STT(base_url=...)` | `livekit-agents ~=1.5` | The Nemotron OpenAI-server path is documented against current agents. |
| `with_ollama(reasoning_effort="none")` | both new tags | Verified mechanism unchanged from v1.0; A.5 probe confirms per build. |
| compose `deploy.reservations.devices` | `docker compose up` (NOT `docker stack`/Swarm) | Single-machine target — fine. Needs NVIDIA Container Toolkit on host. |

## Sources

- Ollama library — `evalengine/unbound-e2b` (3.4GB, 128K, Apache-2.0, Modelfile defaults, benchmarks), `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf` (5.3GB, 128K, no readme), `igorls/gemma-4-E4B-it-heretic-GGUF` (Q4_K_M 5.0GB), `gemma4:e2b/e4b` stock — HIGH (fetched June 2026)
- GitHub `pmarreck/gemma4-heretical` — community Gemma-4 GGUF wrong-template `---`-repeat failure + `RENDERER/PARSER gemma4` fix — HIGH (confirms A.5 risk)
- HF `nvidia/nemotron-speech-streaming-en-0.6b` — model card (600M, FastConformer-CacheAware-RNNT, chunk sizes 80/160/560/1120ms, native punctuation/caps, March-2026 vs jan2026 branch), discussion #6 (NVIDIA: no official quant) — HIGH
- LiveKit blog "Multilingual speech-to-text on your laptop: NVIDIA's Nemotron 3.5 ASR" + `ShayneP/local-teleprompter` — NeMo direct loop, `att_context_size`, OpenAI-compatible `/v1/audio/transcriptions` + `/v1/audio/stream`, `openai.STT` finalize path + `LocalNemotronSTT` custom streaming plugin, ~10-min torch/NeMo install — HIGH (English model shares the serving code)
- NVIDIA Dev Forums "ASR on Spark with nemotron-speech-streaming-en-0.6b" — `nemo_toolkit[all]>=2.5.0`, nemo2riva/onnxruntime pin chain — HIGH
- HF `danielbodart/nemotron-speech-600m-onnx` — int8-dynamic ~0.88GB CPU, onnxruntime load code, config.json preprocessing, CC-BY-4.0, direct NeMo export — HIGH (exists/loads), MEDIUM (production-readiness)
- arXiv 2604.14493 + Microsoft Research + Foundry Local 1.1 blog + techcommunity "On-Device Voice Assistant" — int4 k-quant ~0.67GB, 8.20% WER, 0.56s latency, >RT on CPU; Foundry 1.1.x catalog alias + ORT-GenAI `nemotron_speech` gotcha — MEDIUM/HIGH
- GitHub `met4citizen/HeadAudio` README — AudioWorklet setup, `createMediaStreamSource` bridge implied, Oculus visemes, ~50ms latency, MIT, model-en-mixed.bin ~14kB — HIGH
- npm/jsDelivr `@met4citizen/talkinghead@1.7.0` + `examples/minimal.html` (three@0.180.0 importmap), `@met4citizen/headaudio@0.1.0` — HIGH
- Docker Compose GPU docs + NVIDIA Container Toolkit install (oneuptime/lours.me/Stack Overflow) — `deploy.resources.reservations.devices` (count/device_ids), `--gpus all`, `nvidia-ctk runtime configure`, Swarm caveat — HIGH
- PyPI/Debricked — `livekit-agents` 1.5.6 (Apr 2026), `livekit-plugins-nvidia` 1.5.19rc (Riva, cloud-default) — HIGH

---
*Stack research for: v1.1 pipeline swap (two Ollama LLMs + Nemotron streaming ASR + VRAM-aware CPU-ONNX placement) + optional frontend TalkingHead avatar + consumer-GPU `docker compose up`*
*Researched: 2026-06-26*
