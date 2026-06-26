---
plan: 10-01
title: STT_RUNTIME=gpu|cpu backend split (backend_nemo.py + backend_onnx.py behind the same four callables) + lean nemo-stt-cpu image (Dockerfile.cpu, requirements-cpu.txt, export recipe) + nemo-stt-cpu Compose service + STT_ONNX_MODEL/STT_QUANT env
phase: 10
wave: 1
depends_on: []
autonomous: false
requirements: [STT-05]
files_modified:
  - stt/server.py
  - stt/backend_nemo.py
  - stt/backend_onnx.py
  - stt/Dockerfile.cpu
  - stt/requirements-cpu.txt
  - stt/export_onnx.py
  - docker-compose.yml
  - .env.example
---

# Plan 10-01: The CPU-ONNX runtime — one stt/ codebase, two backends behind STT_RUNTIME, a lean off-GPU nemo-stt-cpu service that speaks the byte-identical Phase-9 WS contract

## User Story

**As** the operator preparing a VRAM-safe deploy, **I want** the existing `stt/` server to run
either as full GPU NeMo (`STT_RUNTIME=gpu`) or as an off-GPU ONNX-Runtime CPU port
(`STT_RUNTIME=cpu`) behind the SAME `load_model`/`new_stream_state`/`decode_chunk`/`finalize`
callables and the SAME frozen `ready`/`delta`/`final`/`error` websocket contract, plus a second
lightweight `nemo-stt-cpu` Compose service that uses **no** GPU reservation, **so that** Wave 2's
placement resolver can hand the agent a CPU or GPU STT URL with zero change to the agent plugin and
zero change to the WS bytes on the wire.

## Context

This is the **runtime-mechanism half** of Phase 10. It factors the Phase-9 NeMo decode body out of
`stt/server.py` into `stt/backend_nemo.py`, adds a parallel `stt/backend_onnx.py` (the ORT
three-graph cache loop + the mel preprocessor that leaves the exported graph), wires a validated
`STT_RUNTIME=gpu|cpu` lazy backend dispatch into `server.py` (WS/HTTP/lifespan/health/lock/stall
watchdog all UNCHANGED), and ships the off-GPU image + Compose service + env surface. After this
plan, `docker compose build nemo-stt-cpu && up -d` brings up a CPU STT service health-checkable on
host port 8001; **Wave 2 (10-02)** then writes `placement.py` + the agent wiring that picks between
the two service URLs. Wave 2 depends on the `STT_RUNTIME` seam + the `nemo-stt-cpu` service URL
frozen here.

**The WS contract is FROZEN and UNCHANGED (Phase 9, `stt/server.py:9-19`).** The ONNX backend MUST
reproduce the IDENTICAL cumulative growing transcript the GPU path emits so `ready`/`delta`/`final`/
`error`, the `/health` 503-until-ready gate, the flush→final reset, the `_gpu_lock` serialize, and
the `_track_stall` watchdog are byte-for-byte unchanged at the WS layer. The ONLY new behaviour is
*inside* the four backend callables (RESEARCH §1.2, §2).

**The backend factoring (RESEARCH §2, PATTERNS §2).** `server.py` keeps the WS/HTTP layer and
dispatches: `backend = importlib.import_module("backend_nemo" if RUNTIME=="gpu" else
"backend_onnx")`. Each backend exposes the SAME four callables — `load_model() -> Any`,
`new_stream_state(model) -> dict`, `decode_chunk(model, state, pcm) -> str`,
`finalize(model, state) -> str` — plus `reset_turn_state(state)`. Heavy imports (nemo/torch in
backend_nemo; onnxruntime/numpy/sentencepiece in backend_onnx) stay LAZY/inside functions so BOTH
modules `py_compile` in the GPU-less, ORT-less sandbox. The current module-level `_model` handle
moves into the dispatch — server holds one backend module + one model handle.

**The three-graph ORT cache loop (RESEARCH §1.2 — the load-bearing reimplementation).** The single
NeMo `conformer_stream_step` becomes an explicit encoder-then-greedy-RNNT loop carrying the same
cache state. Verified tensor shapes (danielbodart `config.json`): `cache_last_channel
[1,24,70,1024]`, `cache_last_time [1,24,1024,8]`, `cache_last_channel_len [1]`, `dec_state 2×[2,1,640]`
(LSTM h/c); per 56-mel-frame (560 ms) chunk → `encoder.run(...)` updates the cache, then greedy RNNT
over enc_out frames (blank=1024, ≤10 symbols/frame, dec_state fed back) → SentencePiece-detokenize
→ the cumulative growing string (`= hyps[0].text`, the GPU analog). The 560 ms chunk matches the
server's `OFFLINE_CHUNK_MS=560` / `[56,3]` cadence — no re-tuning.

**The mel-preprocessor parity GOTCHA (RESEARCH §1.3 — HIGHEST RISK).** The NeMo
`AudioToMelSpectrogramPreprocessor` is NOT in the exported ONNX graph. The CPU backend MUST recompute
the 128-band Slaney mel itself (16 kHz, pre-emphasis 0.97, FFT 512 / hop 160 / win 400 Hann, 128
bands band-major) before the encoder session — preferably a **baked `filterbank.bin` + numpy STFT**
(numpy-only, numerically matched to the export) over a `librosa` dep. A mismatch silently tanks WER;
this is an explicit operator-gated parity check (10-PLACEMENT-VERIFY, authored in Wave 2). Only the
encoder is quantized; decoder/joiner + cache tensors stay FP32.

**Quant honesty (RESEARCH §1.1 — HIGH).** Ship **int8-dynamic (~0.88 GB on disk)** via stock
`onnxruntime.quantization.quantize_dynamic` as the CI/Docker-reproducible default (`STT_QUANT=
int8-dynamic`). Expose **`STT_QUANT=int4-kquant` (~0.67 GB, the literal STT-05 number)** as an
OPERATOR-GATED stretch profile (custom k-quant + MHA-fusion tooling per arXiv 2604.14493, NOT
stock). Do **NOT** claim 0.67 GB or 4-bit works in-sandbox; the STT-05 contract numbers (~0.67 GB,
>6× realtime, negligible WER loss) are the int4-kquant **operator-benchmark** acceptance targets.

**Single-source, no hardcoded tag (PATTERNS cross-cutting).** The `STT_ONNX_MODEL` default literal
lives ONLY in `docker-compose.yml` build.args/environment; `Dockerfile.cpu` body + `server.py`
carry it via ARG/env, mirroring `STT_MODEL` exactly (`stt/Dockerfile:15-33`, `.env.example:53-58`).

**depends_on gate change (RESEARCH §4 / Risk 6 — call it out).** The recommended path DROPS the
Phase-9 agent `depends_on: { nemo-stt: { condition: service_healthy } }` hard-gate (compose:44-52)
to `service_started` (or removes STT) so a CPU-default deploy does NOT boot/wait on the unused GPU
image. The plugin's WS connect-retry becomes the readiness point. Both STT services are defined; only
the placement-resolved one need be up. This is a deliberate change to the Phase-9 gate — state it
plainly and update the header comment (compose:42-43).

**Sandbox vs operator split (RESEARCH §9).** Sandbox-verifiable: `py_compile` of `server.py` +
both backends (heavy imports lazy); the `STT_RUNTIME` dispatch path with a STUBBED backend (no
ORT/NeMo download) exercising the WS framing/flush/delta/final/error; `docker compose config`. The
real ONNX export (`cache_support=True`), the int8/int4 quant + size check, the CPU-ONNX image build,
>6× realtime, WER-under-contention, and the mel-parity check are **operator GPU/host gates**
authored in Wave 2's `10-PLACEMENT-VERIFY.md`. Marked `autonomous: false`.

**Scope discipline (YAGNI).** NO placement logic (Wave 2). NO `agent/main.py` change (Wave 2). NO
`vram-validate.sh` change (Wave 2). NO change to the WS contract, the agent plugin
(`agent/nemo_stt.py`), `agent/metrics.py`, the `model.update` RPC, or the VAD/turn-detector. NO
committing the `.onnx` artifact (bake at build). Keep each function ≤40 lines / ≤3 params / ≤3
nesting.

## Tasks

<task id="10-01-1">
  <title>Extract the Phase-9 NeMo decode body verbatim into stt/backend_nemo.py (load_model/new_stream_state/decode_chunk/finalize/reset_turn_state), keeping heavy imports lazy</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§2 the four-callable seam + the _gpu_lock/stall-watchdog stays-in-server split)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§2 Analog A server.py:101-221 moves verbatim to backend_nemo.py; the lazy-import invariant row)
    - stt/server.py (load_model :101-117, _set_greedy_decoding :120-128, new_stream_state :131-141, _extract_features :144-153, decode_chunk :156-182, _track_stall :185-200, finalize :202-207, reset_turn_state :210-220 — the exact functions to relocate)
  </read_first>
  <action>
    Create `stt/backend_nemo.py` by moving the GPU NeMo decode body out of `stt/server.py` VERBATIM,
    adapting ONLY the call shape so the model handle is passed in (no module-global `_model` inside
    the backend):
    - Move `load_model()` (:101-117), `_set_greedy_decoding()` (:120-128), `new_stream_state()`
      (:131-141), `_extract_features()` (:144-153), `decode_chunk()` (:156-182), `_track_stall()`
      (:185-200), `finalize()` (:202-207), `reset_turn_state()` (:210-220) into `backend_nemo.py`.
    - Change the signatures to take the model explicitly so `server.py` owns the single handle:
      `new_stream_state(model) -> dict`, `decode_chunk(model, state, pcm) -> str`,
      `finalize(model, state) -> str`, `reset_turn_state(state) -> None`. `_extract_features` takes
      `model` too. The bodies that referenced the module `_model` now use the passed `model`.
    - Keep heavy imports (`nemo.collections.asr`, `torch`, `numpy`, `omegaconf`) LAZY/inside the
      functions exactly as today (server.py:109,122,146-147,162) so `py_compile` passes the GPU-less
      sandbox.
    - Move the NeMo-specific config reads it needs: `MODEL_NAME` (from `STT_MODEL`, the
      KeyError→SystemExit posture, server.py:49-52), `ATT_CONTEXT_SIZE` + `_parse_att_context_size`
      (server.py:57-75), and the stall constants `STALL_FRAMES`/`RECYCLE_MIN_CHARS`/
      `RECYCLE_HARD_CHARS` (server.py:82-84) IF `_track_stall` stays in the backend. NOTE: per RESEARCH
      §2 the stall watchdog is backend-AGNOSTIC (operates on the cumulative string) — but Phase-9
      already calls `_track_stall` INSIDE `decode_chunk`. Keep `_track_stall` co-located with each
      backend's `decode_chunk` (both backends recycle their own decoder state — NeMo resets
      `prev_hyps`, ONNX resets `dec_state` + emitted-token list) so the watchdog semantics are
      preserved per-backend; the shared constants live in backend_nemo and are imported/duplicated
      minimally in backend_onnx. Keep the `INT16_FULL_SCALE`/`SAMPLE_RATE` constants the NeMo body
      uses local to the backend.
    - Module docstring: this is the `STT_RUNTIME=gpu` backend (the Phase-9 NeMo decode body, moved);
      the four-callable shape is the seam `server.py` dispatches behind; cite RESEARCH §2.
    Do NOT change decode behaviour — this is a verbatim relocation + a model-passed-in signature
    change. The cumulative `hyps[0].text` output is identical.
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile stt/backend_nemo.py` exits 0 (NeMo/torch NOT imported at module scope — all heavy imports lazy/inside functions)
    - It exposes the four callables with the model passed in (`grep -nE "def load_model|def new_stream_state\(model|def decode_chunk\(model, state, pcm|def finalize\(model, state|def reset_turn_state" stt/backend_nemo.py`)
    - The NeMo decode call + cumulative-text return are unchanged (`grep -n "conformer_stream_step\|hyps\[0\].text" stt/backend_nemo.py`)
    - The stall watchdog recycles state without emitting FINAL (`grep -n "stall\|recycle\|prev_hyps = None\|prev_hyps\"] = None" stt/backend_nemo.py`; the recycle branch contains no `"final"` send)
    - No hardcoded model literal (`grep -n "nvidia/nemotron-speech-streaming" stt/backend_nemo.py` returns nothing; `grep -n "STT_MODEL" stt/backend_nemo.py` present)
    - OPERATOR-VERIFICATION (GPU, deferred — 10-PLACEMENT-VERIFY): `STT_RUNTIME=gpu` still decodes a real clip to growing deltas + a flush FINAL identical to Phase-9 behaviour (no regression from the extraction)
  </acceptance_criteria>
</task>

<task id="10-01-2">
  <title>Create stt/backend_onnx.py — the ORT CPU backend: encoder+decoder/joint ONNX sessions, three-graph cache loop, 128-band Slaney mel preprocessor, SentencePiece detokenize → byte-identical cumulative transcript; same four callables, lazy imports, same stall recycle</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§1.2 the three-graph cache loop + verified tensor shapes + greedy RNNT blank=1024/≤10-symbols/dec_state feedback; §1.3 the mel-preprocessor gotcha + params table; §1.4 CPU base/deps + the int8 speed caveat; §1.1 quant tiers)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§2 Analog A same four-callable shape, backend_onnx is the largest NEW code; the lazy-import + ≤40-line invariants)
    - stt/server.py (decode_chunk :156-182 + _track_stall :185-200 + new_stream_state :131-141 — the contract shape the ONNX callables must match; _extract_features :144-153 — the mel step the ONNX path REPLACES with its own recompute)
    - stt/backend_nemo.py (the sibling backend authored in 10-01-1 — match its callable signatures exactly)
  </read_first>
  <action>
    Create `stt/backend_onnx.py` — the `STT_RUNTIME=cpu` decode backend reproducing the SAME
    cumulative growing transcript over ONNX Runtime. Heavy imports (`onnxruntime`, `numpy`,
    `sentencepiece`) LAZY/inside functions so `py_compile` passes the ORT-less sandbox. Structure into
    small functions (≤40 lines / ≤3 params / ≤3 nesting):
    - **Config (module scope, no hardcoded tag):** `ONNX_MODEL = os.environ["STT_ONNX_MODEL"]`
      (KeyError→SystemExit, mirroring server.py:49-52); `QUANT = os.environ.get("STT_QUANT",
      "int8-dynamic")` validated to `{"int8-dynamic","int4-kquant"}` (SystemExit on bad value — the
      _parse_att_context_size posture). Comment that `int4-kquant` is the ~0.67 GB STT-05 stretch
      target and an operator-gated BUILD (this file only SELECTS which baked artifact to load by name;
      it does not quantize). Reuse the streaming constants the contract needs (SAMPLE_RATE 16000,
      INT16_FULL_SCALE, the stall thresholds — import from backend_nemo or re-declare minimally).
    - **`load_model() -> Any`:** build two `onnxruntime.InferenceSession(...,
      providers=["CPUExecutionProvider"])` for `encoder.onnx` + `decoder_joint.onnx` keyed off
      `ONNX_MODEL`/`QUANT`; load the SentencePiece tokenizer (`tokenizer.model`) and the baked mel
      `filterbank.bin` ([1,128,257]); return a handle bundle (dict/namedtuple) holding all four. Add a
      comment that the exact graph I/O names + cache shapes are confirmed against the export
      `config.json` at the operator build gate (the sandbox cannot download/run ORT).
    - **`new_stream_state(model) -> dict`:** init the per-connection cache zeros from the verified
      shapes — `cache_last_channel [1,24,70,1024]`, `cache_last_time [1,24,1024,8]`,
      `cache_last_channel_len [1]` int64, `dec_state` 2×`[2,1,640]` — plus `emitted_token_ids: []`,
      `prev_text: ""`, and the stall counters (`frames_since_growth`, `last_text_len`) — the SAME keys
      shape as the NeMo state so the watchdog logic is identical.
    - **`_extract_features(model, pcm) -> np.ndarray`:** int16→float32 / INT16_FULL_SCALE, pre-emphasis
      0.97, framed STFT (FFT 512, hop 160, win 400 Hann), magnitude, apply the baked 128-band Slaney
      filterbank → log-mel, return band-major `[1,128,n_frames]`. Comment LOUDLY that this REPLACES the
      NeMo preprocessor that left the ONNX graph and is the HIGHEST-RISK parity item (a mismatch
      silently tanks WER — operator WER gate is the catch, RESEARCH §1.3). Keep it numpy-only (baked
      filterbank, no librosa).
    - **`decode_chunk(model, state, pcm) -> str`:** mel via `_extract_features`; `encoder.run(...)`
      with the four cache inputs → enc_out + updated cache (store back into state); a small
      `_greedy_rnnt(model, state, enc_out)` helper runs the greedy loop (blank=1024, ≤10 symbols/frame,
      feed `dec_state` back, append non-blank token ids to `state["emitted_token_ids"]`); detokenize
      `sp.decode(state["emitted_token_ids"])` → the CUMULATIVE string; call `_track_stall(state, text)`;
      return text. The greedy loop is the second function so neither exceeds 40 lines / 3 nesting.
    - **`_track_stall(state, cumulative) -> None`:** identical semantics to backend_nemo — recycle on
      stall (reset `dec_state` + `emitted_token_ids`, CARRY the encoder cache forward), log only, NO
      FINAL. The ONNX analog of `prev_hyps=None` is `dec_state` reset + emitted-token-list reset.
    - **`finalize(model, state) -> str`:** return the current detokenized cumulative text (drain).
    - **`reset_turn_state(state) -> None`:** reset `dec_state` + `emitted_token_ids` + stall counters,
      CARRY the encoder cache forward (cache_last_* kept) — the exact analog of backend_nemo's
      reset_turn_state so per-turn FINALs don't accumulate the whole session.
    Every callable signature MUST match backend_nemo's so the server dispatch is uniform. NO language/
    prompt steering (English-only). NO mid-utterance FINAL. The real ORT run is an operator gate; this
    task is sandbox-verified by `py_compile` + the stubbed-dispatch test (task 10-01-4).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile stt/backend_onnx.py` exits 0 (onnxruntime/numpy/sentencepiece NOT imported at module scope — all heavy imports lazy/inside functions)
    - It exposes the SAME four callables + reset_turn_state with the model passed in, matching backend_nemo's signatures (`grep -nE "def load_model|def new_stream_state\(model|def decode_chunk\(model, state, pcm|def finalize\(model, state|def reset_turn_state" stt/backend_onnx.py`)
    - The three-graph cache loop is present: encoder.run + a greedy RNNT helper with blank handling + dec_state feedback (`grep -nE "encoder|decoder|greedy|blank|dec_state|cache_last_channel" stt/backend_onnx.py`)
    - A numpy-only mel preprocessor recomputes the 128-band Slaney mel (baked filterbank, no librosa) with a parity-risk comment (`grep -niE "mel|filterbank|pre-emphasis|slaney|stft|128" stt/backend_onnx.py`; `grep -n "librosa" stt/backend_onnx.py` returns nothing OR is explicitly the rejected option)
    - The model is single-sourced from STT_ONNX_MODEL + STT_QUANT validated, no hardcoded tag (`grep -n "STT_ONNX_MODEL\|STT_QUANT" stt/backend_onnx.py`; `grep -n "nvidia/nemotron\|danielbodart" stt/backend_onnx.py` returns nothing as a hardcoded default)
    - The stall recycle resets dec_state + emitted tokens, carries the encoder cache forward, and emits NO FINAL (`grep -n "stall\|recycle\|dec_state\|emitted_token_ids" stt/backend_onnx.py`; the recycle branch sends no `"final"`)
    - SentencePiece detokenize produces the cumulative growing text (native PnC as-is, no lowercase/strip) (`grep -ni "sentencepiece\|sp.decode\|detoken" stt/backend_onnx.py`; `grep -n "\.lower()\|\.strip()" stt/backend_onnx.py` returns nothing meaningful)
    - OPERATOR-VERIFICATION (host CPU + build, deferred — 10-PLACEMENT-VERIFY): the ORT backend loads encoder+decoder ONNX, mel parity vs the NeMo preprocessor holds (WER within target), a real clip streams growing deltas + a flush FINAL byte-identical in shape to the GPU path, and >6× realtime on the host CPU
  </acceptance_criteria>
</task>

<task id="10-01-3">
  <title>Wire STT_RUNTIME=gpu|cpu validated lazy dispatch into stt/server.py — move the decode body out, call through the chosen backend module, keep WS/HTTP/lifespan/health/lock/stall-watchdog UNCHANGED</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§2 the dispatch line + which layer stays in server.py)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§2 Analog A the seam + Analog B validate-or-SystemExit server.py:49-72; the dispatch snippet)
    - stt/server.py (the WS/HTTP layer to KEEP: lifespan :223-231, /health :236-242, _decode_off_loop :245-248, _handle_control :251-264, ws_stream :267-277, _stream_loop :280-296, _handle_control_frame :298-308, _emit_delta :311-319, transcribe_file :322-343; the decode body :101-220 that moves to backend_nemo)
    - stt/backend_nemo.py + stt/backend_onnx.py (the four callables server.py now dispatches to)
  </read_first>
  <action>
    Edit `stt/server.py` to dispatch the decode body behind `STT_RUNTIME` while keeping the WS/HTTP
    layer byte-identical:
    - **Remove** the decode body now living in `backend_nemo.py` (the functions :101-220 moved in
      10-01-1) — `load_model`, `_set_greedy_decoding`, `new_stream_state`, `_extract_features`,
      `decode_chunk`, `_track_stall`, `finalize`, `reset_turn_state`. Keep `MODEL_NAME`/`ATT_*`/stall
      env reads ONLY if still referenced by server (they move with the backend; leave server importing
      none of NeMo).
    - **Add the validated dispatch** near the top (mirror the `_parse_att_context_size`
      validate-or-SystemExit posture, server.py:49-72):
      `RUNTIME = os.environ.get("STT_RUNTIME", "gpu")`; `if RUNTIME not in ("gpu","cpu"): raise
      SystemExit(f"STT_RUNTIME must be gpu|cpu, got {RUNTIME!r}")`; `backend =
      importlib.import_module("backend_nemo" if RUNTIME == "gpu" else "backend_onnx")` (add `import
      importlib`).
    - **Route the callers through the backend + the single model handle.** Keep the module `_model`
      handle + `_ready` + `_gpu_lock` in server. The lifespan calls `backend.load_model()`; the WS/
      control paths call `backend.new_stream_state(_model)`, `backend.decode_chunk(_model, state,
      pcm)`, `backend.finalize(_model, state)`, `backend.reset_turn_state(state)`. Update
      `_decode_off_loop` (:245-248), `_handle_control` (:251-264), `ws_stream` (:273), `_transcribe_wav`
      (:339-343) to pass `_model` + call through `backend`. The `_gpu_lock` serialize, `/health`
      503-gate, flush→final reset, stall-watchdog (now inside each backend's decode_chunk),
      `ws_stream`/`_stream_loop`/`_handle_control_frame`/`_emit_delta` framing, and the optional
      `POST /v1/audio/transcriptions` all stay AS-IS apart from the backend call-through.
    - Add a comment that the `_gpu_lock` still serializes the single decode session per connection for
      BOTH runtimes (it serializes the one ONNX session under cpu — single-user, one active stream);
      rename the intent in the comment but KEEP the lock and its name (no behavioural change).
    - Update the module docstring to note the two runtimes behind the SAME frozen contract (RESEARCH
      §2); the WS contract section (server.py:9-19) stays verbatim.
    Do NOT change any WS message shape, the health gate, the lock, the flush→final semantics, or the
    offline endpoint. `py_compile` is the sandbox gate (NeMo/ORT not importable).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile stt/server.py` exits 0 (no NeMo/ORT import at module scope)
    - STT_RUNTIME is read + validated to gpu|cpu with a SystemExit on bad value, and the backend is imported lazily by name (`grep -nE "STT_RUNTIME|RUNTIME not in|importlib.import_module|backend_nemo|backend_onnx" stt/server.py`)
    - The decode body is GONE from server.py and the callers route through `backend.` (`grep -n "def conformer_stream_step\|conformer_stream_step" stt/server.py` returns nothing; `grep -nE "backend\.load_model|backend\.decode_chunk|backend\.finalize|backend\.new_stream_state|backend\.reset_turn_state" stt/server.py`)
    - The frozen WS contract layer is unchanged: ready/delta/final/error + /health + _gpu_lock + flush→final reset all present (`grep -nE "\"ready\"|\"delta\"|\"final\"|\"error\"|/health|_gpu_lock|reset_turn_state" stt/server.py`)
    - `git diff` shows the WS framing functions (ws_stream/_stream_loop/_handle_control_frame/_emit_delta) changed ONLY by the backend call-through, not by any message-shape edit (read the diff)
    - SANDBOX-TEST: with `STT_RUNTIME=cpu` and a STUBBED backend module on the path (echoes text, no ORT), the dispatch imports `backend_onnx` and the WS framing (ready→delta→flush→final→error) round-trips against the stub
    - OPERATOR-VERIFICATION (deferred — 10-PLACEMENT-VERIFY): both `STT_RUNTIME=gpu` (nemo-stt) and `STT_RUNTIME=cpu` (nemo-stt-cpu) serve the byte-identical contract; the agent plugin is unchanged
  </acceptance_criteria>
</task>

<task id="10-01-4">
  <title>Create stt/requirements-cpu.txt (onnxruntime CPU wheel, fastapi, uvicorn, numpy, sentencepiece — pinned, no onnxruntime-gpu/torch/NeMo) + a sandbox stubbed-backend dispatch test for the STT_RUNTIME=cpu WS path</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§1.4 CPU deps list + the onnxruntime-CPU-not-GPU note; §9 the stubbed-backend sandbox item)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§4 Analog stt/requirements.txt pin posture minus torch/CUDA)
    - stt/requirements.txt (the explicit ~= pin posture + the why-torch-is-NOT-here header to mirror)
    - stt/server.py (the dispatch authored in 10-01-3 — what the stub test drives)
  </read_first>
  <action>
    Two deliverables:
    1. **`stt/requirements-cpu.txt`** mirroring `stt/requirements.txt`'s pin posture (explicit `~=`,
       no `:latest`, no unbounded float) but for the lean CPU image: `onnxruntime` (the **CPU** wheel —
       NOT `onnxruntime-gpu`), `fastapi`, `uvicorn[standard]`, `numpy`, `sentencepiece`. NO `torch`, NO
       `nemo_toolkit`, NO `librosa` (the baked-filterbank mel is numpy-only — RESEARCH §1.3). Header
       comment: this is the off-GPU CPU-ONNX runtime's deps; torch/CUDA/NeMo are absent BY DESIGN (the
       whole point of the off-GPU port); int8 is fast only on VNNI/AMX CPUs (the >6× realtime claim is
       an operator host-CPU gate, RESEARCH §1.4).
    2. **A sandbox stubbed-backend dispatch test** proving the `STT_RUNTIME=cpu` path imports the ONNX
       backend and the WS framing round-trips WITHOUT ORT/NeMo. Place it where the repo test convention
       lives (mirror how Phase 9 sandbox-tested the stubbed decode — a small `tests/` or an inline
       `__main__` harness, planner discretion). The test: set `STT_RUNTIME=cpu` + a stub `backend_onnx`
       on `sys.path` whose `decode_chunk` echoes the pcm length as text and `finalize` returns the last
       text; assert `server.RUNTIME == "cpu"`, `server.backend` is the stub, and a fake-WS exchange
       drives `config → ready`, a binary frame → `delta`, a `flush` → `final`, and a bad control frame
       → `error`. No GPU, no ORT download.
    Keep the test small and sandbox-only (`python3` runnable). Do NOT add a real ORT dependency to the
    sandbox.
  </action>
  <acceptance_criteria>
    - `stt/requirements-cpu.txt` pins onnxruntime (CPU), fastapi, uvicorn[standard], numpy, sentencepiece with `~=` and no `:latest` (`grep -nE "onnxruntime|fastapi|uvicorn\[standard\]|numpy|sentencepiece" stt/requirements-cpu.txt`)
    - It does NOT pull onnxruntime-gpu, torch, nemo, or librosa (`grep -nE "onnxruntime-gpu|torch|nemo|librosa" stt/requirements-cpu.txt` returns nothing)
    - The stubbed-dispatch test exists and asserts the cpu dispatch + the ready/delta/final/error round-trip against a stub backend (`grep -nE "STT_RUNTIME|backend_onnx|ready|delta|final|error" <the test file>`)
    - SANDBOX-TEST: running the test exits 0 with `STT_RUNTIME=cpu` and a stub backend on the path (no onnxruntime/NeMo installed)
  </acceptance_criteria>
</task>

<task id="10-01-5">
  <title>Create stt/Dockerfile.cpu (python:3.11-slim, no CUDA, ARG STT_ONNX_MODEL bake, STT_RUNTIME=cpu, requirements-cpu.txt, python-urllib /health) + stt/export_onnx.py (operator export+quant recipe: cache_support=True → int8-dynamic default / int4-kquant stretch)</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§5 Phase A export recipe + Phase B lean image; §1.1 the int8-default/int4-stretch split; the do-NOT-commit-.onnx rule)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§3 Analog A stt/Dockerfile ARG→bake→ENV single-source + Analog B agent/Dockerfile bake-at-build)
    - stt/Dockerfile (the ARG STT_MODEL → bake → ENV → EXPOSE 8000 → python-urllib HEALTHCHECK → uvicorn CMD pattern to mirror with STT_ONNX_MODEL; the CUDA base to REPLACE with python:slim)
  </read_first>
  <action>
    Two deliverables:
    1. **`stt/Dockerfile.cpu`** — the lean off-GPU image mirroring `stt/Dockerfile`'s single-source
       bake shape but on a CPU base:
       - `FROM python:3.11-slim` (NO CUDA/NeMo/torch — comment that the off-GPU port is the whole
         point; NeMo/torch are needed only at EXPORT time, not serve time).
       - `ARG STT_ONNX_MODEL` (no default literal in the Dockerfile body — Compose `build.args`
         supplies it from the single-sourced env, mirroring `stt/Dockerfile:17`). Also `ARG STT_QUANT`.
       - `COPY requirements-cpu.txt ./` + `pip install --no-cache-dir -r requirements-cpu.txt`.
       - `COPY server.py backend_nemo.py backend_onnx.py ./` (server imports a backend lazily; both
         modules `py_compile`, and only `backend_onnx` is exercised at cpu runtime — copying both keeps
         the image self-consistent and lets `STT_RUNTIME` switch without a rebuild).
       - **Bake the ONNX bundle** keyed by `STT_ONNX_MODEL`/`STT_QUANT` (RESEARCH §5 Phase B — pick
         ONE: a multi-stage NeMo+torch builder that runs `export_onnx.py` and COPYs the `.onnx` into the
         slim final stage, OR `hf download` a prebuilt bundle at build). Comment that the multi-GB build
         is an operator gate and the `.onnx` is NEVER committed.
       - `ENV STT_ONNX_MODEL=${STT_ONNX_MODEL}`, `ENV STT_QUANT=${STT_QUANT}`, `ENV STT_RUNTIME=cpu` so
         the loaded artifact == baked artifact and the server routes to the ORT backend.
       - `EXPOSE 8000`; python-urllib `/health` HEALTHCHECK (NOT curl — parity with stt/Dockerfile:41-42;
         a SHORTER `start_period` is fine since ORT load ≪ NeMo, but keep the python-urllib probe); `CMD
         ["uvicorn","server:app","--host","0.0.0.0","--port","8000"]` (the SAME server.py).
     2. **`stt/export_onnx.py`** — the operator/build export+quant recipe (RESEARCH §5 Phase A), authored
        NOT run in the sandbox: export from the ORIGINAL `.nemo` checkpoint (`STT_MODEL`) WITH
        `model.set_export_config({'cache_support':'True'})` then `model.export(...)` → encoder +
        decoder/joint graphs; int8-dynamic via stock `quantize_dynamic` on the ENCODER ONLY (decoder/
        joint + cache tensors stay FP32); a clearly-marked `int4-kquant` STRETCH branch (operator-gated,
        custom k-quant + MHA fusion per arXiv 2604.14493 — a documented seam, not a working stock call).
        Mirror the danielbodart export/quant/warm-cache-calibration script shape. Single-source the tags
        from env (`STT_MODEL`/`STT_ONNX_MODEL`/`STT_QUANT`), no hardcoded literals. `py_compile`-clean
        with NeMo/ORT imports lazy/inside `main()`.
        **CRITICAL — emit the FULL bundle `backend_onnx.load_model` expects, not just the `.onnx` graphs
        (closes the parity-asset provenance gap):** the recipe MUST also derive and write, alongside the
        graphs, (a) the **`filterbank.bin` `[1,128,257]`** Slaney mel filterbank that `backend_onnx`'s
        numpy mel preprocessor loads — extract it from the same `.nemo` preprocessor config
        (`model.preprocessor.featurizer` mel-filter matrix → `np.asarray(...).astype('float32').tofile`)
        so the baked filterbank is BIT-IDENTICAL to what the NeMo mel produced (the mel-parity invariant —
        a mismatch silently tanks WER), and (b) the **SentencePiece `tokenizer.model`** extracted from the
        `.nemo` (`model.tokenizer.tokenizer.model_path` / the `.nemo` tar member). The `hf download`
        bundle path (Dockerfile.cpu option 2) gets these from the prebuilt bundle; the multi-stage
        export-builder path (option 1) MUST produce them here — both Dockerfile.cpu paths therefore yield
        the SAME four artifacts the CPU backend loads (`encoder.onnx`, `decoder_joint.onnx`,
        `filterbank.bin`, `tokenizer.model`).
     Do NOT commit any `.onnx`, `.bin`, or `.model` artifact. The build + export + quant + filterbank/
     tokenizer extraction are operator gates.
  </action>
  <acceptance_criteria>
    - `stt/Dockerfile.cpu` bases on python:3.11-slim with NO CUDA/NeMo/torch and a comment why (`grep -niE "python:3.11-slim|cuda|nemo|torch" stt/Dockerfile.cpu`; the grep shows slim base + NeMo/torch only in the "absent by design" comment)
    - It bakes via `ARG STT_ONNX_MODEL` (no hardcoded literal) and sets `ENV STT_RUNTIME=cpu` + `ENV STT_ONNX_MODEL`/`STT_QUANT` (`grep -nE "ARG STT_ONNX_MODEL|ENV STT_RUNTIME=cpu|ENV STT_ONNX_MODEL|ENV STT_QUANT" stt/Dockerfile.cpu`; `grep -n "nvidia/nemotron\|danielbodart" stt/Dockerfile.cpu` returns nothing)
    - It installs requirements-cpu.txt, copies server.py + both backends, EXPOSEs 8000, runs uvicorn, and HEALTHCHECKs /health via python-urllib NOT curl (`grep -nE "requirements-cpu.txt|backend_onnx|EXPOSE 8000|uvicorn|HEALTHCHECK|urllib" stt/Dockerfile.cpu`; `grep -n "curl" stt/Dockerfile.cpu` returns nothing)
    - `python3 -m py_compile stt/export_onnx.py` exits 0 (NeMo/ORT imports lazy/inside main)
    - export_onnx.py uses set_export_config cache_support=True + quantize_dynamic (encoder-only int8) + a marked int4-kquant stretch branch, single-sourced tags (`grep -niE "cache_support|set_export_config|quantize_dynamic|int4-kquant|STT_ONNX_MODEL" stt/export_onnx.py`)
    - export_onnx.py ALSO emits the `filterbank.bin` and `tokenizer.model` parity assets that `backend_onnx.load_model` loads, so both Dockerfile.cpu bake paths yield the same four artifacts (`grep -niE "filterbank|tokenizer" stt/export_onnx.py`)
    - No .onnx/.bin/.model artifact is committed (`git status --porcelain | grep -iE '\.(onnx|bin|model)$'` returns nothing)
    - OPERATOR-VERIFICATION (build, deferred — 10-PLACEMENT-VERIFY): `docker compose build nemo-stt-cpu` runs the export → int8-dynamic ~0.88 GB encoder bakes into the slim image; the int4-kquant ~0.67 GB stretch profile is a separate operator-gated build; the container loads ORT offline with no first-run download
  </acceptance_criteria>
</task>

<task id="10-01-6">
  <title>Add the nemo-stt-cpu Compose service (clone nemo-stt minus the GPU reservation, Dockerfile.cpu, STT_RUNTIME=cpu, STT_ONNX_MODEL/STT_QUANT build ARG + env, host port 8001, python-urllib /health, LAN-bound, no env_file) + drop the agent depends_on nemo-stt service_healthy hard-gate</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§4 the full nemo-stt-cpu service decisions + the depends_on §4/Risk 6 change)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§5 Analog A clone nemo-stt :101-138 minus GPU reservation :121-127 + Analog B the agent depends_on :42-52 gate this phase CHANGES)
    - docker-compose.yml (nemo-stt :101-138 to clone, the GPU reservation :121-127 to DROP, the agent depends_on :44-52 + header comment :42-43 to change, kokoro :140-158 for a non-GPU-vs-GPU contrast)
  </read_first>
  <action>
    Edit `docker-compose.yml`:
    - **ADD a `nemo-stt-cpu:` service** cloning `nemo-stt:` (:101-138) with these changes:
      - `build: { context: ./stt, dockerfile: Dockerfile.cpu, args: { STT_ONNX_MODEL:
        ${STT_ONNX_MODEL:-<the single default literal>}, STT_QUANT: ${STT_QUANT:-int8-dynamic} } }` —
        the ONE place the `STT_ONNX_MODEL` default literal lives (single-source, mirrors STT_MODEL at
        :111). Use a concrete default ONNX tag/path placeholder (planner picks the literal; it lives
        ONLY here).
      - `environment: [ STT_RUNTIME=cpu, STT_ONNX_MODEL=${STT_ONNX_MODEL:-...},
        STT_QUANT=${STT_QUANT:-int8-dynamic} ]` (matching build ARGs; no STT_MODEL needed at runtime).
      - **DROP the entire `deploy.resources.reservations.devices` GPU block** (:121-127) — this service
        runs off-GPU.
      - `ports: ["${LAN_BIND_IP:-127.0.0.1}:8001:8000"]` — distinct HOST port 8001 (internal stays
        8000; the agent reaches it by service DNS `ws://nemo-stt-cpu:8000/...`; 8001 is for host probing
        without colliding with nemo-stt's 8000).
      - The SAME python-urllib `/health` healthcheck (:132-137) — a SHORTER `start_period` is fine (ORT
        load ≪ NeMo) but keep the python-urllib probe; `networks: [adept]`; NO `env_file` (M3);
        `restart: unless-stopped`.
      - A header comment: off-GPU CPU-ONNX STT (RESEARCH §1.1, ~0.88 GB int8-dynamic default / ~0.67 GB
        int4-kquant operator stretch); both STT services are defined, only the placement-resolved one
        need be healthy per session (Wave 2 picks the URL).
    - **Add `STT_RUNTIME=gpu` to the existing `nemo-stt` environment** (:114-116) so the GPU service is
      explicit about its runtime (the server default is gpu, but make it explicit for symmetry).
    - **Change the agent `depends_on` (:44-52):** DROP `nemo-stt: { condition: service_healthy }` to
      `condition: service_started` (or remove STT from `depends_on`) so a CPU-default deploy does NOT
      wait on / require the GPU STT image it never uses; the plugin's WS connect-retry is the readiness
      point (RESEARCH §4). Do NOT add `nemo-stt-cpu` as a hard `service_healthy` gate either (same
      reason — only the resolved one is used). Update the header comment (:42-43) that documented the
      long-form `service_healthy` rationale to reflect this deliberate Phase-9 gate change.
    Do NOT touch ollama/kokoro/livekit-server/web. Do NOT add an `env_file` to nemo-stt-cpu. Do NOT
    change nemo-stt's GPU reservation or its build.
  </action>
  <acceptance_criteria>
    - `docker compose config` validates (run if a compose binary is present; else note deferred)
    - A `nemo-stt-cpu:` service exists with build Dockerfile.cpu + STT_ONNX_MODEL/STT_QUANT build args, STT_RUNTIME=cpu env, host port 8001:8000, NO GPU reservation, python-urllib /health, no env_file, restart unless-stopped (`grep -nE "nemo-stt-cpu:|Dockerfile.cpu|STT_ONNX_MODEL|STT_QUANT|STT_RUNTIME=cpu|8001:8000|/health" docker-compose.yml`)
    - The nemo-stt-cpu service has NO `deploy.resources.reservations.devices` GPU block (read the service block — the devices/nvidia block is absent under nemo-stt-cpu)
    - The STT_ONNX_MODEL default literal appears ONLY in compose build.args/environment, not in any stt/agent source (`grep -rn "<the onnx default literal>" docker-compose.yml` shows it; the same grep over stt/*.py + agent/*.py returns nothing)
    - The agent depends_on no longer hard-gates on `nemo-stt: { condition: service_healthy }` (`grep -n "service_healthy" docker-compose.yml` no longer matches the agent→nemo-stt edge; the header comment :42-43 reflects the change)
    - nemo-stt now sets STT_RUNTIME=gpu explicitly (`grep -n "STT_RUNTIME=gpu" docker-compose.yml`)
    - OPERATOR-VERIFICATION (deferred — 10-PLACEMENT-VERIFY): `docker compose build nemo-stt-cpu && up -d` brings nemo-stt-cpu to healthy on host 8001 off-GPU; a CPU-default deploy (STT_FORCE_CPU=1, Wave 2) starts the agent WITHOUT requiring the GPU nemo-stt image
  </acceptance_criteria>
</task>

<task id="10-01-7">
  <title>Extend .env.example with STT_ONNX_MODEL (single-source comment, code-default note) + STT_QUANT=int8-dynamic (int4-kquant stretch note); STT_RUNTIME stays per-service in compose, STT_FORCE_CPU/NEMO_STT_CPU_URL deferred to Wave 2</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§6 the env surface — STT_ONNX_MODEL/STT_QUANT here; STT_RUNTIME NOT here; STT_FORCE_CPU/NEMO_STT_CPU_URL are Wave 2)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§7 Analog the Phase-9 STT block .env.example:53-66 + the no-hardcoded-tag comment style)
    - .env.example (the STT block :53-66 to extend, same single-source comment style)
  </read_first>
  <action>
    Edit `.env.example` to document the new CPU-ONNX knobs below the existing STT block (:53-66),
    mirroring the single-source comment style:
    - `STT_ONNX_MODEL=...` — the CPU analog of `STT_MODEL`; comment that the literal default lives ONLY
      in compose `build.args`/`environment` (the v1.0 no-hardcoded-tag invariant, same as STT_MODEL at
      :53-58); the agent/server/Dockerfile body carry it via env/ARG.
    - `STT_QUANT=int8-dynamic` — quant profile selector; comment that `int8-dynamic` (~0.88 GB on disk)
      is the stock-ORT CI/Docker-reproducible DEFAULT, and `int4-kquant` (~0.67 GB, the literal STT-05
      number) is an OPERATOR-GATED stretch build (custom k-quant + MHA fusion, not stock) — do NOT
      claim 4-bit works out of the box.
    - A note that `STT_RUNTIME` is set PER-SERVICE in compose (gpu on nemo-stt, cpu on nemo-stt-cpu),
      NOT here.
    - A forward-note that `STT_FORCE_CPU` + `NEMO_STT_CPU_URL` arrive in Wave 2 (10-02) — do NOT add
      them here (this plan ships only the runtime/image surface; the placement knobs are Wave 2's).
    Do NOT modify the existing STT_MODEL / STT_ATT_CONTEXT_SIZE lines.
  </action>
  <acceptance_criteria>
    - `.env.example` documents STT_ONNX_MODEL with the single-source/no-hardcoded-tag rationale (`grep -nE "STT_ONNX_MODEL|single-source|no hardcoded" .env.example`)
    - STT_QUANT=int8-dynamic is documented with the int4-kquant operator-gated stretch note + the ~0.88/~0.67 GB honesty (`grep -niE "STT_QUANT=int8-dynamic|int4-kquant|operator|0.67|0.88" .env.example`)
    - It notes STT_RUNTIME is per-service in compose and does NOT add STT_FORCE_CPU/NEMO_STT_CPU_URL (`grep -n "STT_RUNTIME" .env.example` shows the per-service note; `grep -n "STT_FORCE_CPU\|NEMO_STT_CPU_URL" .env.example` returns nothing — Wave 2)
    - The existing STT_MODEL/STT_ATT_CONTEXT_SIZE lines are unchanged (`grep -n "STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b\|STT_ATT_CONTEXT_SIZE=\[56,3\]" .env.example`)
  </acceptance_criteria>
</task>

## Verification

- `python3 -m py_compile stt/server.py stt/backend_nemo.py stt/backend_onnx.py stt/export_onnx.py`
  exits 0 — all heavy imports (NeMo/torch/onnxruntime/numpy/sentencepiece) are lazy/inside functions
  so the GPU-less, ORT-less sandbox byte-compiles every module.
- `stt/server.py` reads + validates `STT_RUNTIME=gpu|cpu` (SystemExit on bad value), imports the
  backend lazily by name, and routes `load_model`/`new_stream_state`/`decode_chunk`/`finalize`/
  `reset_turn_state` through it; the frozen WS contract (`ready`/`delta`/`final`/`error`, `/health`
  503-gate, `_gpu_lock`, flush→final reset, stall watchdog) is UNCHANGED — only the backend
  call-through differs.
- `stt/backend_nemo.py` is the Phase-9 NeMo body moved verbatim (model passed in); `stt/backend_onnx.py`
  reproduces the cumulative growing transcript over the three-graph ORT cache loop + the numpy-only
  128-band Slaney mel + SentencePiece detokenize, with the SAME callable signatures + the SAME stall
  recycle (reset dec_state + emitted tokens, carry encoder cache, no FINAL).
- `stt/requirements-cpu.txt` pins onnxruntime(CPU)/fastapi/uvicorn[standard]/numpy/sentencepiece, no
  onnxruntime-gpu/torch/NeMo/librosa.
- `stt/Dockerfile.cpu` bases on python:3.11-slim (no CUDA), bakes via `ARG STT_ONNX_MODEL` (no
  hardcoded tag), sets `ENV STT_RUNTIME=cpu`, installs requirements-cpu.txt, copies server + both
  backends, EXPOSEs 8000, runs uvicorn, python-urllib `/health` HEALTHCHECK. `stt/export_onnx.py`
  authors the cache_support=True export + int8-dynamic default / int4-kquant stretch recipe (no `.onnx`
  committed).
- `docker-compose.yml`: `nemo-stt-cpu` added (Dockerfile.cpu, STT_RUNTIME=cpu, STT_ONNX_MODEL/STT_QUANT
  single-source, host 8001, NO GPU reservation, python-urllib /health, no env_file); `nemo-stt` gains
  explicit STT_RUNTIME=gpu; the agent `depends_on` nemo-stt `service_healthy` hard-gate is DROPPED to
  `service_started` (header comment updated). The STT_ONNX_MODEL default literal lives ONLY in compose.
- `.env.example` documents STT_ONNX_MODEL + STT_QUANT (int4-kquant operator-gated note); STT_RUNTIME
  per-service; no STT_FORCE_CPU/NEMO_STT_CPU_URL (Wave 2).
- SANDBOX-TEST: the stubbed-backend dispatch test drives `STT_RUNTIME=cpu` → `backend_onnx` import +
  the ready/delta/flush/final/error WS round-trip with no ORT/NeMo installed.
- BUILD-FIRST (operator, baked-image invariant): `docker compose build nemo-stt-cpu && docker compose
  up -d && docker compose ps` (nemo-stt-cpu healthy on 8001) before any live gate.
- OPERATOR GATE (GPU/host/build — deferred; authored in Wave 2's `10-PLACEMENT-VERIFY.md`): the real
  ONNX export (cache_support=True) + int8/int4 quant + size check; the CPU-ONNX image build + bake; the
  mel-parity vs the NeMo preprocessor (WER); >6× realtime on CPU + WER-under-contention; both runtimes
  serving the byte-identical contract.
- DEFER (do NOT mark passed in this plan): all GPU/Docker/ORT/accuracy operator items; the sandbox has
  no GPU/Docker daemon and cannot import NeMo/torch/onnxruntime.

## must_haves

truths:
- STT-05: the `stt/` server runs as EITHER full GPU NeMo (`STT_RUNTIME=gpu`, `backend_nemo`) OR an
  off-GPU ONNX-Runtime CPU port (`STT_RUNTIME=cpu`, `backend_onnx`) behind the SAME
  `load_model`/`new_stream_state`/`decode_chunk`/`finalize`/`reset_turn_state` callables and the SAME
  frozen `ready`/`delta`/`final`/`error` websocket contract — the agent plugin is runtime-agnostic
  (only the URL differs).
- STT-05: the CPU-ONNX backend reproduces the IDENTICAL cumulative growing transcript via the
  three-graph (encoder + decoder/joint) cache loop + a self-computed 128-band Slaney mel + SentencePiece
  detokenize; the WS bytes on the wire are unchanged; the encoder is quantized while the decoder/joiner
  + cache tensors stay FP32.
- STT-05: the shipped/CI-reproducible default is int8-dynamic (~0.88 GB, stock `quantize_dynamic`);
  int4-kquant (~0.67 GB, the literal STT-05 number) is an env-selectable OPERATOR-GATED stretch build
  (custom k-quant + MHA fusion) — never claimed to work in-sandbox.
- A second `nemo-stt-cpu` Compose service exists with NO GPU reservation, `STT_RUNTIME=cpu`, the
  single-sourced `STT_ONNX_MODEL`/`STT_QUANT` bake, host port 8001, and a python-urllib `/health` gate;
  both STT services are defined, only the placement-resolved one (Wave 2) need be healthy per session.
- The agent `depends_on` nemo-stt `service_healthy` hard-gate is DROPPED (to `service_started`) so a
  CPU-default deploy does not boot/wait on the unused GPU image — a deliberate, documented change to the
  Phase-9 gate.
- The `STT_ONNX_MODEL` default literal is single-sourced: it lives ONLY in `docker-compose.yml`
  build.args/environment; the Dockerfile body, server, and backends carry it via env/ARG.

must_haves.prohibitions:
- NO change to the Phase-9 frozen WS contract (`ready`/`delta`/`final`/`error`, `/health` gating) — the
  ONNX backend matches it byte-for-byte; the agent plugin (`agent/nemo_stt.py`) is untouched.
- NO hardcoded `STT_ONNX_MODEL` literal in `stt/server.py`, the backends, or the `Dockerfile.cpu` body
  — single-sourced via env/ARG (the v1.0 no-hardcoded-tag invariant).
- NO `onnxruntime-gpu`, `torch`, `nemo_toolkit`, or `librosa` in `requirements-cpu.txt` / the CPU image
  (off-GPU port: ORT CPU wheel + numpy-only mel by design).
- NO placement logic, NO `agent/main.py` change, NO `vram-validate.sh` change, NO `STT_FORCE_CPU`/
  `NEMO_STT_CPU_URL` — all Wave 2 (10-02).
- NO mid-utterance / heuristic FINAL from either backend — FINAL only on the agent's `flush`; the stall
  watchdog recycles decoder state and does NOT emit FINAL (turn detector owns finalize).
- NO committing any `.onnx` artifact (multi-GB — baked at build via STT_ONNX_MODEL).
- NO claim that 4-bit / 0.67 GB works in-sandbox; NO function over 40 lines / 3 params / 3 nesting.
- NO marking any GPU/Docker/ORT/accuracy OPERATOR-VERIFICATION step passed in this plan.

## Artifacts this plan produces

- `stt/backend_nemo.py` (new): the `STT_RUNTIME=gpu` backend — the Phase-9 NeMo decode body moved
  verbatim. Callables: `load_model()`, `new_stream_state(model)`, `decode_chunk(model, state, pcm)`,
  `finalize(model, state)`, `reset_turn_state(state)` (+ `_set_greedy_decoding`, `_extract_features`,
  `_track_stall`). Reads `STT_MODEL`, `STT_ATT_CONTEXT_SIZE`, `STT_STALL_FRAMES`, `STT_RECYCLE_*`.
- `stt/backend_onnx.py` (new): the `STT_RUNTIME=cpu` backend — encoder+decoder/joint ORT sessions, the
  three-graph cache loop, a numpy-only 128-band Slaney mel, SentencePiece detokenize → cumulative
  transcript; same four callables + reset_turn_state + the stall recycle. Reads `STT_ONNX_MODEL`,
  `STT_QUANT`.
- `stt/server.py` (modified): `STT_RUNTIME` validate + lazy `importlib` backend dispatch; the decode
  body removed (now in backend_nemo); WS/HTTP/lifespan/health/`_gpu_lock`/stall-watchdog/offline
  endpoint unchanged apart from the backend call-through.
- `stt/requirements-cpu.txt` (new): pinned onnxruntime(CPU)/fastapi/uvicorn[standard]/numpy/
  sentencepiece; no onnxruntime-gpu/torch/NeMo/librosa.
- `stt/Dockerfile.cpu` (new): python:3.11-slim, `ARG STT_ONNX_MODEL`/`STT_QUANT` bake, `ENV
  STT_RUNTIME=cpu`, requirements-cpu.txt, server + both backends, EXPOSE 8000, uvicorn CMD, python-urllib
  `/health` HEALTHCHECK.
- `stt/export_onnx.py` (new): operator/build export+quant recipe — `set_export_config(cache_support=
  True)` → encoder + decoder/joint; int8-dynamic (encoder-only, stock `quantize_dynamic`) default +
  int4-kquant stretch branch; single-sourced tags; lazy imports.
- A sandbox stubbed-backend dispatch test (new): `STT_RUNTIME=cpu` → `backend_onnx` import + the
  ready/delta/flush/final/error WS round-trip against a stub (no ORT/NeMo).
- `docker-compose.yml` (modified): `nemo-stt-cpu:` service added (Dockerfile.cpu, STT_RUNTIME=cpu,
  STT_ONNX_MODEL/STT_QUANT single-source, host 8001, no GPU reservation, python-urllib /health, no
  env_file); `nemo-stt` gains explicit `STT_RUNTIME=gpu`; agent `depends_on` nemo-stt `service_healthy`
  → `service_started` (header comment updated).
- `.env.example` (modified): `STT_ONNX_MODEL` (single-source) + `STT_QUANT=int8-dynamic` (int4-kquant
  operator-gated note) documented; STT_RUNTIME per-service note.
- The `STT_RUNTIME` backend contract + the `ws://nemo-stt-cpu:8000/v1/audio/stream` service URL are
  FROZEN here for Wave 2's placement resolver + agent wiring. New Compose service: `nemo-stt-cpu`. New
  env vars: `STT_ONNX_MODEL`, `STT_QUANT` (+ per-service `STT_RUNTIME`).
