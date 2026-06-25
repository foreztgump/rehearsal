# Stack Research

**Domain:** Local-first, near-real-time voice-to-voice conversational AI agent (LiveKit Agents pipeline) on a single 16GB-VRAM GPU
**Researched:** 2026-06-24
**Confidence:** HIGH (all versions verified against live PyPI / Ollama library / Docker Hub / official docs, June 2026)

> **Read this first — three PRD assumptions are now wrong or outdated:**
> 1. **"Gemma 4 E4B Q4 ~5GB" is incorrect on size.** Gemma 4 *does* now exist in Ollama (it shipped — `gemma4:e4b`), but the E4B tag is **9.6GB**, not ~5GB. The 5GB/7.5GB figure was Gemma **3n** E4B (the older edge model). See [LLM section](#llm-the-brain) — this materially changes the 16GB VRAM budget.
> 2. **Gemma 4 has a thinking/reasoning mode that is a latency killer.** It MUST be explicitly disabled for a sub-second voice loop. See [§ Gemma 4 latency caveat](#gemma-4-latency-caveat).
> 3. **The standalone turn-detector plugin is now deprecated**, and its official replacement (`inference.TurnDetector`) defaults to LiveKit *Cloud* inference — which violates local-first. There is still a fully-local path; see [Turn detection](#turn-detection-semantic-endpointing).

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **livekit-agents (Python)** | `~=1.5` (1.5.2 latest, Apr 2026) | Orchestration: WebRTC transport, streaming STT→LLM→TTS pipeline, VAD, turn detection, barge-in, per-turn latency metrics | The de-facto 2026 framework for realtime voice agents; `AgentSession` runs all four stages concurrently so user never waits for a prior stage. Native interruption/barge-in + per-turn metrics are exactly the PRD's instrumented P50/P95 requirement. |
| **livekit-server** | `v1.10.x` (1.10.1, Mar 2026) | Self-hosted WebRTC SFU the agent + browser connect to | Single 35MB Go binary / Docker image; satisfies "self-host from day one, local-first." No cloud dependency. |
| **faster-whisper** | `1.2.1` (Oct 2025) | STT — Whisper `large-v3-turbo` at **int8** on GPU | CTranslate2 backend, ~4× faster than reference Whisper, int8 quant ≈2GB VRAM, <180ms on a 4090-class GPU. Fits the latency + VRAM budget. |
| **Ollama** | `0.6+` (current 2026 build) | Local LLM server, OpenAI-compatible `/v1/chat/completions` | Officially supported by LiveKit via `openai.LLM.with_ollama()`. Keep-alive keeps model resident; flash-attention + KV-cache quant shrink the prefix/KV cache the inline-KB design depends on. |
| **Gemma 4 E4B** (or fallback) | `gemma4:e4b` (9.6GB) — see caveats | The persona "brain" | Generates far faster than speech is spoken; native system-prompt role (new in Gemma 4) cleanly carries the persona + domain brief. **But see VRAM math — on a strict 16GB floor prefer a smaller/quantized tag.** |
| **Kokoro-82M** | via `ghcr.io/remsky/kokoro-fastapi-gpu:latest` (pin a release tag) | TTS, OpenAI-compatible `/v1/audio/speech`, streaming | 82M params, ~2–3GB VRAM at inference, RTF ~0.03, 54 preset voices (the PRD's "Kokoro preset voices" requirement). Swappable later for VoxCPM behind the same OpenAI interface. |
| **LiveKit JS/React client SDK** | `livekit-client ~=2.x` (+ optional `@livekit/components-react`) | Single-page browser client: mic capture, audio playback, transcript, agent-state UI | Same vendor as the server/agents; handles WebRTC, track subscription, and exposes agent state + transcription events for the listening/thinking/speaking indicator and live transcript. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **livekit-plugins-openai** | `~=1.5` | Drives Ollama (LLM), Kokoro (TTS), and faster-whisper-server (STT) — all via OpenAI-compatible `base_url` | Always. One plugin covers all three local services. |
| **livekit-plugins-silero** | latest (matches agents 1.5) | Silero VAD — speech presence + interruption trigger | Always (open-mic VAD requirement + barge-in). Runs on CPU. |
| **livekit-plugins-turn-detector** | latest (`MultilingualModel`) | Semantic end-of-turn detection, **runs locally on CPU, <500MB RAM** | Use the local `MultilingualModel` — NOT `inference.TurnDetector` (cloud). See note below. |
| **faster-whisper-server** *(or Speaches)* | latest GPU image | Wraps faster-whisper in an OpenAI `/v1/audio/transcriptions` endpoint | Lets `openai.STT(base_url=...)` use local Whisper with **no custom plugin code**. Speaches bundles both STT+TTS if you want one container. |
| **pymupdf** | `1.27.x` | PDF/TXT/MD/EPUB → text/markdown (fast, C-backed) | KB ingestion for PDF/TXT/MD. 10–50× faster than pure-Python PDF libs. |
| **pymupdf4llm** | latest | Layout-aware, LLM-ready Markdown from PDF/DOCX | When you want clean structured markdown for the "domain brief" distillation. |
| **python-docx** | `1.1.x` | DOCX → text | DOCX KB uploads (PyMuPDF base needs Pro for Office; python-docx is the free path). |
| **markitdown** | `0.1.6` (May 2026) | One-call "any file → Markdown" (PDF/DOCX/PPTX/XLSX/MD/TXT) | Optional convenience wrapper to normalize all upload types to markdown before distillation. Note: AGPL-adjacent deps; verify license fit. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **Docker Compose + NVIDIA Container Toolkit** | One-command stack with GPU passthrough | Services: `livekit-server`, `ollama`, `kokoro`, `whisper-server`, `agent`, `web`. Each GPU service needs `deploy.resources.reservations.devices` (or `--gpus all`) + `NVIDIA_VISIBLE_DEVICES`. |
| **uv** | Python env / dependency manager for the agent | LiveKit's own docs/quickstarts standardized on `uv` in 2026 (`uv add "livekit-agents[openai,silero,turn-detector]~=1.5"`). |
| **`python -m livekit.agents download-files`** | Pre-fetch VAD + turn-detector weights | MUST run at image-build time so the container starts offline-capable. |

## Installation

```bash
# Agent (Python, with uv)
uv add "livekit-agents[openai,silero,turn-detector]~=1.5"
uv add pymupdf pymupdf4llm python-docx markitdown

# Pre-download local model weights (VAD + turn detector) — bake into Docker image
python -m livekit.agents download-files

# Pull the LLM (choose tag per VRAM budget — see VRAM math)
ollama pull gemma4:e4b           # 9.6GB — needs ~14GB total stack, 16GB is TIGHT
# or, safer on a strict 16GB floor:
ollama pull gemma3:4b-it-qat     # ~3.3GB QAT, big headroom

# Whisper as OpenAI-compatible server (Docker)
docker run -d --gpus all -p 8000:8000 \
  -e WHISPER__MODEL=deepdml/faster-whisper-large-v3-turbo-ct2 \
  -e WHISPER__COMPUTE_TYPE=int8 \
  fedirz/faster-whisper-server:latest-cuda

# Kokoro TTS (Docker, OpenAI-compatible)
docker run -d --gpus all -p 8880:8880 \
  ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.x   # pin a release tag, not :latest

# Frontend
npm install livekit-client @livekit/components-react
```

Wiring in the agent (`AgentSession`):

```python
from livekit.agents import AgentSession
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://whisper:8000/v1", model="Systran/faster-whisper-large-v3-turbo", api_key="none"),
    llm=openai.LLM.with_ollama(model="gemma4:e4b", base_url="http://ollama:11434/v1"),
    tts=openai.TTS(base_url="http://kokoro:8880/v1", model="kokoro", voice="af_bella", api_key="none"),
    turn_detection=MultilingualModel(),   # local CPU, <500MB — keeps it local-first
)
```

---

## Plugin Availability: Official vs Custom

| Service | Official LiveKit plugin? | How to integrate |
|---------|--------------------------|------------------|
| **Ollama (LLM)** | ✅ Yes — `openai.LLM.with_ollama()` convenience method in `livekit-plugins-openai` | Built-in. Just set `model` + `base_url`. |
| **faster-whisper (STT)** | ❌ No first-party plugin | Two options: (a) **recommended** — run faster-whisper behind an OpenAI-compatible server (faster-whisper-server / Speaches) and point `openai.STT(base_url=...)` at it (zero custom code); (b) write a thin custom STT plugin wrapping the `faster_whisper` lib (e.g. community `taresh18/livekit-whisper`). Prefer (a). |
| **Kokoro (TTS)** | ❌ No first-party plugin | Run `kokoro-fastapi` (OpenAI-compatible) and point `openai.TTS(base_url=...)` at it. Zero custom code. |
| **Turn detection** | ✅ `livekit-plugins-turn-detector` (`MultilingualModel`, local CPU) | Built-in, local. The newer `inference.TurnDetector` is cloud-routed — avoid for local-first (see below). |
| **VAD** | ✅ `livekit-plugins-silero` | Built-in, local CPU. |

**Net:** Only STT and TTS need the "OpenAI-compatible sidecar" pattern, and neither needs bespoke plugin code if you front them with a compatible server. No custom plugin authoring is strictly required for v1.

---

## LLM (the brain)

### Gemma model-tag reality check (verified against Ollama library, June 2026)

| What the PRD says | Reality in Ollama today | Action |
|-------------------|-------------------------|--------|
| "Gemma 4 E4B Q4 ~5GB" | `gemma4:e4b` **exists** but is **9.6GB** (8B total / 4.5B effective params, 128K ctx, text+image+audio) | Pin `gemma4:e4b` only if VRAM allows; otherwise use a smaller tag. The "~5GB" number was Gemma **3n** E4B (`gemma3n:e4b` = 7.5GB Q4_K_M). |
| "Gemma 4 26B-A4B MoE (24GB option)" | `gemma4:26b` **exists** = 18GB, MoE 8/128 experts, 3.8B active, 256K ctx | Valid 24GB-class option. Confirmed real. |
| Qwen3 8B fallback | Qwen3 family present in Ollama | Valid 24GB fallback. |

**Verified Gemma 4 tags:** `gemma4:e2b` (7.2GB), `gemma4:e4b` (9.6GB), `gemma4:12b` (7.6GB), `gemma4:26b` (18GB, MoE A4B), `gemma4:31b` (20GB dense). All 128K–256K context.

### VRAM math on the 16GB floor — this is the real constraint

```
gemma4:e4b           9.6 GB
faster-whisper turbo int8   ~2.0 GB
Kokoro-82M               ~2.5 GB
-----------------------------------
                       ~14.1 GB   → fits 16GB, but headroom is thin
```
With KB prefix/KV cache growth + CUDA buffers + turn-detector/VAD (CPU, negligible VRAM), 16GB is **workable but tight** with `gemma4:e4b`. Recommendations by tier:

- **16GB floor, safest:** `gemma3:4b-it-qat` (~3.3GB) or a quantized Gemma 4 E4B tag → large headroom for KV cache, the thing that protects TTFT.
- **16GB, want Gemma 4 quality:** `gemma4:e4b` with `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` to keep the KB/conversation cache small. Validate no OOM under a loaded KB.
- **24GB recommended:** `gemma4:e4b` comfortably, or step up to `gemma4:26b` (18GB) / Qwen3 8B for stronger personas.

### Gemma 4 latency caveat

Gemma 4 is a **reasoning model with a thinking mode** (triggered by a `<|think|>` token in the system prompt). Thinking emits a long internal-reasoning preamble *before* the first user-visible token — catastrophic for TTFT and the "start TTS on first sentence" design. **Disable thinking** (omit the `<|think|>` token; Ollama's template handles the rest) and do **not** carry prior-turn thoughts in history. The E2B/E4B variants degrade most gracefully with thinking off.

### Ollama latency config (all required for the sub-second target)

```bash
OLLAMA_FLASH_ATTENTION=1        # memory-efficient attention as KB context grows
OLLAMA_KV_CACHE_TYPE=q8_0       # halve KV cache memory; requires flash attention
OLLAMA_KEEP_ALIVE=-1            # keep model resident forever (no cold reload between turns)
```
Plus, per the PRD, **sliding-window / summarize conversation history** so growing history doesn't re-inflate prefill on every turn. Sampling per Gemma 4 guidance: `temperature=1.0, top_p=0.95, top_k=64` (tune down temperature for a more consistent trainer voice).

---

## Turn detection (semantic endpointing)

**Use the local `MultilingualModel` from `livekit-plugins-turn-detector`** (fine-tuned Qwen2.5-0.5B, runs on CPU in-process, <500MB RAM, 14 languages). It is the semantic endpointer the PRD wants and keeps everything local.

**Caveat / decision point:** PyPI marks `livekit-plugins-turn-detector` "deprecated," steering users to the built-in `livekit.agents.inference.TurnDetector`. **But** that built-in path defaults to LiveKit *Cloud* inference for the new audio v1 model — which breaks the local-first hard requirement. Until the open-weight `v1-mini` is confirmed running fully locally through `inference.TurnDetector`, pin the local `MultilingualModel`. Pairs with Silero VAD (VAD = interruption trigger + speech presence; turn-detector = semantic "is the turn actually over"). This combo is also what delivers correct **barge-in** behavior.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `gemma4:e4b` (LLM) | `gemma3:4b-it-qat` / `gemma3n:e4b` | Strict 16GB with a large KB; want guaranteed KV-cache headroom over peak quality. |
| `gemma4:e4b` | `gemma4:26b` (MoE) or Qwen3 8B | 24GB GPU; want stronger reasoning/persona fidelity. |
| faster-whisper-server (OpenAI sidecar) | Custom `faster_whisper` STT plugin | You need tighter control (warmup, partials, batching) than the HTTP server exposes. |
| Kokoro-FastAPI | Speaches (STT+TTS in one container) | Want a single sidecar for both STT and TTS; willing to download voice weights via its API. |
| Local `MultilingualModel` turn detector | `inference.TurnDetector` (cloud v1) | You later relax local-first, or LiveKit ships confirmed-local v1-mini. |
| PyMuPDF + python-docx | markitdown (single entrypoint) | You want one `convert()` call across all file types and accept its heavier dep tree / license. |
| Kokoro | VoxCPM | Later: custom/cloned trainer voice — drop-in behind the same OpenAI TTS interface, no rewiring. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Per-turn vector RAG (embed → retrieve) in v1** | Adds an embedder + vector store to VRAM and injects retrieval latency into every turn's TTFT — directly fights the P50<1.0s metric. KB is small. | Inline-and-cache: distill docs once to a compact domain brief, load into context, rely on Ollama prefix/KV caching (free after turn 1). Reserve RAG for oversized KBs in v2+. |
| **`gemma4:e4b` with thinking mode on** | Reasoning preamble destroys TTFT and breaks first-sentence TTS streaming. | Disable thinking; sliding-window history. |
| **`inference.TurnDetector` (default cloud)** | Routes turn detection to LiveKit Cloud → violates local-first; adds network latency. | Local `MultilingualModel`. |
| **Trusting "Gemma 4 E4B Q4 = 5GB" from the PRD** | Wrong; real `gemma4:e4b` is 9.6GB and changes the VRAM budget. | Recompute VRAM (see math) and pick the tag deliberately. |
| **Whisper `large-v3` (non-turbo) for realtime** | Slower; turbo variant is purpose-built for low-latency streaming. | `large-v3-turbo` int8. |
| **`:latest` Docker tags for Kokoro/Whisper in the Compose file** | Non-reproducible; silent breaking changes. | Pin explicit release tags. |
| **Push-to-talk fallback** | PRD explicitly decided against it. | Open-mic Silero VAD + semantic turn detection from day one. |

## Stack Patterns by Variant

**If GPU = 16GB (floor):**
- LLM: `gemma3:4b-it-qat` (safe) or `gemma4:e4b` + `q8_0` KV cache (quality, tight)
- Keep KB brief compact; aggressive history windowing
- Because every extra GB of KV cache headroom is what protects TTFT under a loaded KB

**If GPU = 24GB (recommended):**
- LLM: `gemma4:e4b` comfortably, or `gemma4:26b` / Qwen3 8B for stronger personas
- Room for f16 KV cache (lower-latency than q8_0) and longer context
- Because the VRAM headroom lets you trade quantization back for speed/quality

**If local-first is ever relaxed (not v1):**
- Could swap turn detection to cloud `inference.TurnDetector` v1 and STT/TTS to managed providers — but this contradicts the project's hard privacy requirement, so v1 stays fully local.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `livekit-agents ~=1.5` | Python 3.10–3.14 | 1.4.0 dropped Python 3.9; min is 3.10. |
| `livekit-agents 1.5.x` | `livekit` server SDK ≥1.1.3 | 1.5.1 bumped the minimum server SDK. |
| `livekit-plugins-turn-detector` | `transformers` 4.x–5.x | 1.5.1 relaxed the upper bound to allow transformers 5.x. |
| `livekit-agents` ↔ `livekit-server` | agents 1.5.x ↔ server 1.10.x | Both current as of 2026-Q2; keep server/agents within a release cycle. |
| `faster-whisper 1.2.1` | CUDA + cuBLAS + cuDNN 9.x | int8/fp16 on GPU needs matching NVIDIA libs (pip `nvidia-cudnn-cu12`). |
| `pymupdf 1.27.x` | Python 3.10–3.14 | Office (DOCX) input needs PyMuPDF **Pro**; use python-docx for free DOCX. |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | requires `OLLAMA_FLASH_ATTENTION=1` | And the model arch must be on Ollama's flash-attn allowlist or it silently falls back to f16 (→ higher VRAM). Verify Gemma 4 is on the allowlist before relying on q8_0 savings. |

## Sources

- Ollama library — `gemma4` page (verified `e4b`=9.6GB, `26b`=18GB, thinking mode, sampling params), `gemma3n:e4b` (7.5GB), `gemma3` tags — HIGH
- PyPI — `livekit-plugins-turn-detector` (deprecation notice, local CPU <500MB), `markitdown` 0.1.6, `livekit-plugins-openai` — HIGH
- LiveKit community forum — `livekit-agents` 1.4.x/1.5.x release threads (1.5.2 Apr 2026, Python 3.14, MultilingualModel) — HIGH
- LiveKit docs — Ollama LLM plugin (`with_ollama`), OpenAI-compatible LLMs (`base_url`), turn-detector plugin, OpenAI STT plugin, self-hosting VM/Docker — HIGH
- GitHub `livekit/agents` llm.py — `with_ollama` signature (default `llama3.1`, `api_key="ollama"`) — HIGH
- GitHub `livekit/livekit` CHANGELOG — server v1.10.1 (Mar 2026); Docker Hub `livekit/livekit-server` — HIGH
- GitHub `SYSTRAN/faster-whisper` — v1.2.1 (Oct 2025), CTranslate2, int8; faster-whisper-server / Speaches OpenAI-compatible serving — HIGH
- GitHub `remsky/Kokoro-FastAPI` + Spheron/Railway deploy guides — OpenAI-compatible `/v1/audio/speech`, GPU image, ~2–3GB, streaming — HIGH
- Ollama docs FAQ — `OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE` (q8_0 needs flash attn), keep-alive — HIGH
- LiveKit blog "Solving end-of-turn detection v1" — cloud-default for new turn detector, local v1-mini open weights — MEDIUM (confirm local execution path before final pin)
- pymupdf.io / GitHub `pymupdf/PyMuPDF` — 1.27.x, Office needs Pro — HIGH

---
*Stack research for: local-first near-real-time voice persona trainer (LiveKit Agents + faster-whisper + Ollama/Gemma + Kokoro)*
*Researched: 2026-06-24*
