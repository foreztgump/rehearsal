---
phase: 15
sub_phase: 15b
kind: design
status: deferred → moved to v1.2 roadmap R3 (hardware-aware engines + models)
source: Phase-15 brainstorming (2026-06-27)
addresses: 15-BACKLOG.md item 1 (the "faster-whisper on a different setup" half)
build_order: deferred (out of Phase 15; built in v1.2 R3)
depends_on: 15a-DESIGN.md
---

> **DEFERRED (2026-06-27).** Phase 15 ships as **15a only**. This selectable-engines work is the
> same problem as the v1.2 roadmap's **R3 — hardware-aware engines + models** (and overlaps R2 ~6GB
> lifecycle, R6 AMD, R7 installer). Building it inside Phase 15 would design the install/selection
> pattern twice, so it moves to R3 and is designed once there. The architecture below stands as the
> starting point for R3 — kept as-is, not built now. See `.planning/ROADMAP.md` → v1.2.

# Phase 15b — Selectable, installable STT engines

Let an operator **choose and install** the STT engine that suits their hardware. The default
stays the low-latency streaming Nemotron; faster-whisper (and later others) become **opt-in
accuracy-mode engines** — not replacements. Designed now; built after 15a, and only as far as
there's a concrete second engine to justify the pattern (YAGNI on the rest).

## Goal

`STT_ENGINE=nemotron-streaming` (default) keeps today's behaviour byte-for-byte. An operator on
stronger hardware can set `STT_ENGINE=faster-whisper`, build that engine's image, and get higher
accuracy in exchange for higher latency and no live partials — a deliberate, documented trade.

## Why this is tractable (the seam already exists)

`server.py` already dispatches every backend through one five-callable seam —
`load_model / new_stream_state / decode_chunk / finalize / reset_turn_state` — and `STT_RUNTIME`
already selects `backend_nemo` (GPU) vs `backend_onnx` (CPU). 15b **extends the selector to
engine families**, it does not invent a new abstraction.

## Architecture

### 1. Engine selector (deploy/build-time)
- New env `STT_ENGINE` ∈ `{nemotron-streaming (default), faster-whisper, …}`, resolved the same
  single-sourced way as `STT_MODEL` (KeyError→SystemExit; no hardcoded tag). It selects (a) the
  backend module and (b) the build profile/image. **Operator-chosen at install — not a live
  in-app switch** (YAGNI; "install based on hardware" is a deploy decision).

### 2. Streaming vs. buffered, on the *same* seam
- **Streaming engines** (Nemotron, any cache-aware model): per-chunk `decode_chunk` emits growing
  partials — today's behaviour, unchanged.
- **Buffered engines** (faster-whisper, parakeet-offline): implement the *same* seam, but
  `decode_chunk` **accumulates PCM into `state`** and returns no partial; `finalize` transcribes
  the whole buffer once. The server already buffers and calls `finalize` at end-of-turn, so this
  needs **little-to-no seam change** — a backend `STREAMS = True/False` capability flag is likely
  all the server needs to skip partial emission for buffered engines.
- **Honest trade for buffered engines:** no word-by-word partials, higher TTFT, **off the
  P50<1.0s hot path by design**. This is the accuracy-mode contract.

### 3. Install isolation (separate images / compose profiles)
- faster-whisper (CTranslate2) and NeMo+torch have **conflicting heavy deps** — do not co-install.
  Add `stt/Dockerfile.faster-whisper` selected by a **compose profile** keyed to `STT_ENGINE`,
  mirroring the existing `Dockerfile` + `Dockerfile.cpu` split. Each engine bakes only its own
  weights/deps and starts offline-capable (local-first).

### 4. First concrete engine — faster-whisper-large-v3
The genuine accuracy upgrade and the backlog's stated intent ("faster-whisper reintroduced on a
different setup, not the streaming path"). GPU via CTranslate2 CUDA on stronger hardware, or CPU.
**Parakeet and any others are documented as the same pattern but NOT built until an operator
actually wants one** (YAGNI — the pattern needs one real second engine, not a catalogue).

### 5. "Pick your STT by hardware" doc
A short table in `README.md` / STACK.md: streaming Nemotron = default for 16GB / lowest latency;
faster-whisper = accuracy mode for stronger hardware or when latency matters less; how to set
`STT_ENGINE` + build the profile.

## Open decisions (resolve at the start of the 15b build cycle)

- faster-whisper **model size** (large-v3 vs distil) and **GPU-vs-CPU default**, given VRAM
  contention with the LLM on 16GB.
- Whether the agent-side plugin (`LocalNemotronSTT`) needs a **"no partials" signal** for buffered
  engines, or whether finalize-only already degrades gracefully.
- Exact `STT_ENGINE` → (module, build profile, default `STT_MODEL`) mapping table.
- Whether buffered accuracy-mode also wants a small fixed **chunked** mode (periodic re-transcribe)
  for partial responsiveness, or stays pure finalize-only (default: pure — KISS).

## Non-goals
- Not replacing or changing the default engine.
- Not a live, in-conversation model switcher.
- Not building parakeet/other engines speculatively — pattern + faster-whisper only.

## References
- Existing seam: `stt/server.py`, `stt/backend_nemo.py`, `stt/backend_onnx.py`, `stt/backend_common.py`.
- Install-isolation precedent: `stt/Dockerfile`, `stt/Dockerfile.cpu`, `docker-compose.yml` STT services.
- Engine facts (Parakeet offline, faster-whisper non-streaming): Phase-15 research, 2026-06-27.
