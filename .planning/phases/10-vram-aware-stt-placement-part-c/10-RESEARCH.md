# Phase 10 — VRAM-Aware STT Placement (Part C): Implementation Research

**Question answered:** *What do I need to know to PLAN this phase well?*
**Scope:** Ship the mechanism to run STT either as full GPU NeMo (`nemo-stt`,
`STT_RUNTIME=gpu`) or as an off-GPU 4-bit/int8 ONNX CPU port (`nemo-stt-cpu`,
`STT_RUNTIME=cpu`), behind the **frozen Phase 9 WS contract**, with placement
resolved **once at session start** from the selected LLM + a static measured-headroom
table, plus a single env-flagged global-CPU fallback (`STT_FORCE_CPU`).

This doc researches **HOW** to implement the locked decisions in `10-CONTEXT.md`. It
does NOT relitigate them. Every API/number below is pinned to what the repo actually
runs (Phase 9 `stt/server.py`, NeMo 25.11, `onnxruntime` CPU EP) or flagged as an
operator-gate placeholder.

> **The load-bearing unknown is RESOLVED (§1):** 4-bit ONNX at ~0.67 GB for THIS exact
> model is real and published — but it requires custom **int4 k-quant + operator fusion**
> tooling, NOT a stock one-line `quantize_dynamic` call. The realistic, Docker-reproducible
> target is **int8 dynamic quantization (~0.88 GB on-disk / encoder ~0.8 GB)**; int4 k-quant
> (~0.67 GB) is the stretch goal and is an operator-gated build. The streaming contract IS
> preservable under ONNX Runtime via the three-graph (encoder + decoder/joint) cache-fed
> decode loop. See §1 for the honest 4-bit-vs-int8 split.

---

## 0. Source-of-truth references (fetched/verified this phase)

| Reference | What it gives us | Trust |
|---|---|---|
| NeMo Framework User Guide — *Models* (ASR export section) | Official ONNX export path for cache-aware streaming Conformer/Transducer: `model.set_export_config({'cache_support':'True'})` then `model.export(...)` / `scripts/export.py --export-config cache_support=True`; Hybrid exports as **RNNT (encoder + decoder+joint)** by default | Canonical (vendor) |
| `danielbodart/nemotron-speech-600m-onnx` (HF) | A **direct ONNX export of `nvidia/nemotron-speech-streaming-en-0.6b`** (our exact model) with fp32/fp16/int8-dynamic/int8-static variants, full runtime `config.json`, cache tensor shapes, mel preprocessing params, and reproducible export+quant scripts | High (independent, from-NeMo export, sizes given) |
| arXiv 2604.14493 *"Pushing the Limits of On-Device Streaming ASR"* (+ Microsoft Research listing) | The **0.67 GB / int4 k-quant** result for Nemotron Speech Streaming: 2.47 GB → 0.67 GB, WER within ~0.17% abs of FP32, **>realtime on CPU**, three-graph decomposition, encoder-only quant, FP32 decoder/joiner + FP32 cache tensors | High (the source of the STT-05 0.67 GB number) |
| `tonythethompson/Nemotron-3.5-...-ONNX` (HF) | A second ONNX bundle (multilingual 3.5 sibling): `encoder.onnx` + `decoder_joint.onnx` + `tokenizer.model` — confirms the two-graph packaging shape | Medium (multilingual sibling, not our en-0.6b) |
| `onnxruntime.ai` quantization docs | `quantize_dynamic` recommended for transformer/RNN; S8S8 QDQ default; CPU int8 needs VNNI/AMX to be FAST (else can be SLOWER than fp32) | Canonical (vendor) |
| Phase 9 `stt/server.py` / `Dockerfile` / `09-RESEARCH.md` | The frozen WS contract, the `load_model`/`decode_chunk`/`finalize`/`new_stream_state` split to factor behind `STT_RUNTIME`, the bake/single-source pattern | Repo HEAD |
| Phase 8 Gate D (STATE.md:114) | Measured per-LLM VRAM at the q8_0 KB-load prefill peak: **Fast/E2B = 7408 MB, Better/E4B = 8912 MB**, 3 GPU procs | Repo measurement (operator-signed) |

> **Note on the reference ONNX repos:** they are CPU/edge bundles. We reuse the *export
> recipe + runtime config + decode-loop shape*, not necessarily the artifact (CONTEXT:
> bake our own at build via `STT_ONNX_MODEL`, do NOT commit the `.onnx`). The
> `danielbodart` `config.json` + scripts are the working template for our `STT_RUNTIME=cpu`
> backend.

---

## 1. The runtime split — GPU-NeMo vs CPU-ONNX decode (the load-bearing research)

Phase 9's GPU path is `conformer_stream_step` (one NeMo call that does encoder + RNNT
greedy decode + cumulative-text assembly, carrying `cache_last_channel/time/channel_len`
+ `prev_hyps`). The CPU-ONNX path must reproduce the **same cumulative-text output** so
the WS `delta`/`final` contract is byte-identical to the agent. Here is exactly how.

### 1.1 Is 4-bit ONNX achievable, or is int8 the realistic target? (HONEST ANSWER)

**Both are real for this exact model — but at different cost/risk tiers:**

| Tier | Method | On-disk size | WER vs FP32 | CPU realtime | Toolchain | Verdict for Phase 10 |
|---|---|---|---|---|---|---|
| **int8 dynamic** | `onnxruntime.quantization.quantize_dynamic` (encoder MatMul weights → int8, decoder/joint FP32) | ~0.88 GB (enc ~0.80 GB) | ~matches FP32 (paper: int8 k-quant 8.01% vs 8.03% fp32) | >realtime on VNNI/AMX CPU | **Stock ORT, one script** | **Realistic baseline / default build target** |
| **int4 k-quant** | importance-weighted k-quant on encoder + operator (MHA) fusion (arXiv 2604.14493 recommended config) | **~0.67 GB** | within ~0.17% abs (8.20% vs 8.03%) | "comfortably faster than realtime", 0.56 s algo latency | **Custom k-quant + fusion (paper scripts)** | **Stretch / operator-gated build** — hits the literal STT-05 0.67 GB |

**Recommendation for the PLAN:** target **int8 dynamic as the shipped/CI default** (`STT_QUANT=int8-dynamic`), and make **int4 k-quant an env-selectable build profile**
(`STT_QUANT=int4-kquant`) that is an **operator-gated build** (multi-GB, needs the paper's
custom tooling). State plainly in the runbook: the **~0.67 GB figure is the int4 k-quant
target**; int8 dynamic lands ~0.88 GB on disk (still trivially co-resident off-GPU and
RAM-cheap). Do **not** claim 0.67 GB for the int8 default. The STT-05 contract numbers
(~0.67 GB, >6× realtime, negligible WER loss under contention) are the **int4 k-quant
operator-benchmark acceptance targets**, measured on the real consumer GPU host CPU.

> **Why not 4-bit on the decoder/joiner?** The paper + the danielbodart export both keep
> the **RNNT decoder (LSTM prediction net) + joiner FP32** (combined <35 MB) and keep the
> **streaming cache tensors FP32** — the joiner runs at every encoder time-step inside the
> greedy loop, and the cache must stay numerically stable across chunk boundaries.
> Quantizing them risks decode-loop collapse for ~zero size win. Encoder = >95% of params,
> so encoder-only quant captures essentially all the savings.

### 1.2 Can the streaming contract be preserved under ORT? YES — three-graph cache loop

The NeMo export (per the official guide) decomposes the model into:
- `encoder_model.onnx` — cache-aware FastConformer (24 layers, dim 1024).
- `decoder_model.onnx` — RNNT decoder **+ joint** (LSTM 2×640 prediction net + joiner).

The ORT decode loop replaces the single `conformer_stream_step` with an explicit
encoder-then-greedy-RNNT loop that carries the **same cache state**. Verified shapes from
the danielbodart `config.json`:

```
# Per connection (init zeros) — the CPU analog of get_initial_cache_state(batch_size=1):
cache_last_channel : [1, 24, 70, 1024]  float32
cache_last_time    : [1, 24, 1024, 8]   float32
cache_last_channel_len : [1]            int64
dec_state_1/2      : [2, 1, 640]        float32  (RNNT LSTM h/c)

# Per chunk (56 mel frames = 560 ms audio + 9 pre-encode cache frames = 65 input frames):
enc_out, cache_last_channel, cache_last_time, cache_last_channel_len =
    encoder.run(mel_chunk, cache_last_channel, cache_last_time, cache_last_channel_len)
# Greedy RNNT over enc_out frames: for each frame feed [1,1024,1] to decoder, argmax over
# 1025 vocab (blank=1024), emit token if not blank and loop (≤10 symbols/frame), else
# advance frame. Feed dec_state back. Accumulate SentencePiece tokens → detokenize.
growing_text = sp.decode(emitted_token_ids)   # CUMULATIVE — same as prev_hyps[0].text
```

This produces the **identical cumulative growing transcript** the GPU path emits, so the
server's existing `delta`/`final`/`ready`/`error` framing, the flush→final reset, and the
stall watchdog are all **unchanged at the WS layer**. The only difference is *inside*
`decode_chunk`/`finalize`/`new_stream_state`.

> **Streaming chunk size already matches.** The server's offline window is
> `OFFLINE_CHUNK_MS=560` and the att-context default is `[56,3]` — the ONNX export's
> 56-mel-frame / 560 ms chunk is the **same cadence**. No re-tuning of chunk size needed.

### 1.3 The ONE preprocessing gotcha — mel features leave the graph

The NeMo GPU path calls `_model.preprocessor(input_signal=...)` (the
`AudioToMelSpectrogramPreprocessor`) to turn int16 PCM → mel features. **That preprocessor
is NOT in the exported ONNX encoder graph.** The CPU backend must compute the 128-band mel
spectrogram itself before the encoder session. Verified params from the export `config.json`:

| Param | Value |
|---|---|
| sample rate | 16000, S16_LE int16 |
| pre-emphasis | 0.97 |
| FFT size | 512 · hop 160 (10 ms) · win 400 (25 ms) · Hann |
| mel bands | 128, Slaney norm, **band-major** `[n_mels, n_frames]` |
| filterbank | provided as `filterbank.bin` `[1,128,257]` |

Implementation options for the CPU backend's `_extract_features` (pick one in the PLAN):
- **librosa/numpy** mel (add `librosa` to the CPU requirements), or
- a **baked filterbank** (`filterbank.bin`) + numpy STFT (no librosa dep), mirroring the
  export bundle. **Preferred:** the baked filterbank keeps deps lean (numpy-only) and is
  numerically matched to the export.

This is the single largest piece of *new* code in the CPU backend and the highest-risk
parity item (operator WER gate catches a mel mismatch).

### 1.4 CPU base image + pinned deps

- Base: a **plain CPU Python** image (e.g. `python:3.11-slim`) — **NO CUDA, NO NeMo, NO
  torch** in the runtime image (that is the whole point of the off-GPU port). NeMo/torch
  are needed ONLY at *export time* (a separate builder stage or an operator-run export
  script), not at serve time.
- Runtime deps: `onnxruntime` (the **CPU** wheel, NOT `onnxruntime-gpu`), `fastapi`,
  `uvicorn[standard]`, `numpy`, `sentencepiece` (detokenize the RNNT tokens), and the mel
  dep (`librosa` OR numpy-only baked filterbank). Pin all (mirror `stt/requirements.txt`
  posture).
- Result: a small image (~hundreds of MB + ~0.67–0.88 GB model) that loads with
  `ort.InferenceSession(..., providers=["CPUExecutionProvider"])`.

> **CPU int8 speed caveat (ORT docs):** int8 is only *fast* on x86-64 with **VNNI/AMX** (or
> Arm dot-product). On an old CPU int8 can be SLOWER than fp32 (quant/dequant overhead). The
> target consumer host has a modern CPU, so this is fine — but the **>6× realtime claim is
> CPU-dependent and is an operator gate**, not a sandbox fact.

---

## 2. `STT_RUNTIME=gpu|cpu` switch inside `stt/server.py`

The frozen contract functions (`load_model`, `new_stream_state`, `decode_chunk`,
`finalize`, `reset_turn_state`) already exist and are the **exact seam** to factor behind a
backend dispatch. Keep ≤40 lines / ≤3 params / ≤3 nesting.

**Recommended factoring (planner discretion, within these invariants):**
- Add a module const `RUNTIME = os.environ.get("STT_RUNTIME", "gpu")` (validated to
  `{"gpu","cpu"}`, SystemExit on bad value — same posture as `_parse_att_context_size`).
- Split the two backends into **two small modules** imported lazily (so the GPU-less,
  ONNX-less sandbox still `py_compile`s both): `stt/backend_nemo.py` (the current NeMo body)
  and `stt/backend_onnx.py` (the ORT body). Each exposes the SAME four callables:
  `load_model() -> Any`, `new_stream_state(model) -> dict`, `decode_chunk(model, state, pcm)
  -> str`, `finalize(model, state) -> str`.
- `server.py` keeps the WS/HTTP layer **unchanged** and dispatches:
  `backend = importlib.import_module("backend_nemo" if RUNTIME=="gpu" else "backend_onnx")`.
  `load_model`/`decode_chunk`/`finalize`/`new_stream_state`/`reset_turn_state` call through
  `backend`. The lifespan, `/health` 503-gate, `_gpu_lock`, flush→final reset, stall
  watchdog, and the `ws_stream`/`_stream_loop` body all stay as-is.
- The `_gpu_lock` serialize-decode discipline still applies to the CPU backend (it
  serializes the single ONNX session per connection); rename intent in a comment but keep
  the lock (single-user, one active stream).
- The stall watchdog (`_track_stall`) is **backend-agnostic** — it operates on the
  cumulative string, so it stays in `server.py` (or shared) and works for both. The CPU
  backend's "recycle decoder state" = reset the RNNT `dec_state` + emitted-token list,
  carry encoder cache forward (exact analog of `prev_hyps=None` + cache carry).

**Invariant preserved:** the agent plugin (`agent/nemo_stt.py`) is **untouched** — it
speaks the WS contract; GPU vs CPU is purely a server-side `STT_RUNTIME` + a different URL.

---

## 3. `agent/placement.py` — the pure resolver + VRAM table constants

**Signature (locked):** `resolve_stt_placement(llm_choice: str, env: Mapping[str,str]) ->
str` returning `"gpu"` or `"cpu"`. Pure function, no `nvidia-smi`, called **once** in
`build_session`/entrypoint, never re-consulted on a mid-session LLM swap.

**Resolution order (locked by CONTEXT):**
1. **`STT_FORCE_CPU` FIRST** — if truthy (`{"1","true","yes","on"}`, normalized) → return
   `"cpu"` immediately, before any headroom logic (STT-07). This is the global pin for
   both LLMs.
2. **Static measured-headroom table** (no live probe). Compute against the **worst-case
   LLM** so a mid-session Fast↔Better swap is always safe (STT-06): if the heaviest LLM
   that could be selected this session (E4B/Better) + Kokoro + GPU-NeMo does **not** fit
   under the ceiling, return `"cpu"` for the WHOLE session.
3. **Default when unmeasured → `"cpu"`** (VRAM-safe for both LLMs) until the operator
   co-residency gate proves E4B + GPU-STT + Kokoro co-fit.

**The table constants (cite + flag each):**

```python
# All MB. The literal LLM peaks are MEASURED (Phase 8 Gate D, STATE.md:114) at the
# q8_0 KB-load prefill peak — grounded, not guessed.
VRAM_TOTAL_MB      = 16384   # 16 GB consumer-GPU floor (PERF-02 target)
VRAM_HEADROOM_MB   = 1024    # peak must stay < total − 1 GB (vram-validate ceiling)
LLM_PEAK_MB = {
    "fast":   7408,          # E2B, MEASURED Phase 8 Gate D
    "better": 8912,          # E4B, MEASURED Phase 8 Gate D
}
STT_GPU_MB         = 2400    # GPU-NeMo .nemo + activations (~2.4 GB, Phase 9)
STT_CPU_GPU_MB     = 0       # CPU-ONNX uses NO VRAM (runs off-GPU; ~0.67–0.88 GB RAM)
KOKORO_MB          = 2048    # ⚠️ PLACEHOLDER — Kokoro-82M GPU footprint is UNMEASURED;
                             #    operator co-residency gate pins the real number.
```

**The decision math (worst-case-LLM, STT-06):**

```python
ceiling = VRAM_TOTAL_MB - VRAM_HEADROOM_MB                 # 15360
worst_llm = max(LLM_PEAK_MB.values())                      # 8912 (E4B)
gpu_fits = worst_llm + KOKORO_MB + STT_GPU_MB <= ceiling   # 8912+2048+2400=13360 ≤ 15360
# → with the PLACEHOLDER Kokoro number gpu_fits is True, BUT the default is still CPU
#   until the operator MEASURES Kokoro and the 4-cell matrix proves the real peak fits.
```

> **Why a "measured" flag and not just the arithmetic?** The arithmetic with the placeholder
> *says* GPU fits, but Kokoro is unmeasured and the LLM peaks were measured **without** a
> co-resident GPU-STT. So gate the GPU branch behind an explicit
> `STT_HEADROOM_MEASURED` (or equivalent) signal that the operator sets to `1` ONLY after
> the 4-cell matrix passes. Until then → CPU. This is the "default CPU when unmeasured"
> lock. The PLAN should represent this as: `if not measured: return "cpu"`. The shipped
> `.env.example` carries `STT_FORCE_CPU=1` so the picker is VRAM-safe out of the box
> regardless.

**Inputs validated at the boundary** (Phase 6/8 discipline): `llm_choice` normalized
against `MODEL_CHOICES`; unknown → treat as worst-case (CPU-safe). `env` booleans parsed
with a single helper. No exceptions escape the resolver — it always returns `"gpu"`/`"cpu"`.

**Wiring (`agent/main.py`):** add `NEMO_STT_CPU_URL` const beside `NEMO_STT_URL`; in
`build_session`, call `resolve_stt_placement(current_model[0], os.environ)` once, pick the
URL, and construct `NemoSTT(ws_url=<resolved>, language="en")`. **Do NOT touch
`handle_model_update`** (the LLM-swap RPC stays LLM-only; placement is read once).

---

## 4. `nemo-stt-cpu` Compose service

Clone the `nemo-stt` block (docker-compose.yml:101-139) **minus the GPU reservation**, set
`STT_RUNTIME=cpu`, add the `STT_ONNX_MODEL` build ARG (single-source, mirrors `STT_MODEL`),
and a python-urllib `/health` healthcheck.

**Key compose decisions:**
- **Distinct service name `nemo-stt-cpu`** on the `adept` network; both services keep the
  **same internal port 8000**. The agent reaches each by service DNS
  (`ws://nemo-stt:8000/...` vs `ws://nemo-stt-cpu:8000/...`) — internal ports needn't differ.
  For host debugging, bind a **distinct host port** (e.g. `8001:8000`) so both can be probed
  from the host without collision.
- **Build target / image:** a separate `stt/Dockerfile.cpu` (CPU base, ORT, no CUDA) OR a
  multi-stage `target:` in the existing Dockerfile. Recommend a **separate `Dockerfile.cpu`**
  for clarity (the bases are entirely different — `python:slim` vs `nvcr.io/nvidia/nemo`).
- **depends_on (the cleanest pattern — researched):** the agent should **NOT** hard-depend
  `service_healthy` on **both** STT services, because only the placement-resolved one is used
  and forcing both healthy would (a) make a CPU-only deploy wait on a GPU service it never
  uses and (b) couple startup to a service the session won't touch. Cleanest options:
  - **(Recommended) Gate the agent on neither STT service's health**, drop STT to
    `condition: service_started` (or remove from `depends_on`), and let the **plugin's WS
    connect** be the readiness point (it already retries via `conn_options`). The agent's
    `service_healthy` gate on STT is then removed; the resolved service simply must be up.
  - **(Alternative)** Keep `nemo-stt: service_healthy` for the GPU-default deploy and add
    `nemo-stt-cpu: service_started`, accepting that the GPU service must be healthy even when
    `STT_FORCE_CPU=1`. **Rejected** — contradicts the shipped CPU-safe default (you'd boot a
    GPU image you're not using).
  - Decide in the PLAN; the recommended path keeps the CPU-default deploy from requiring the
    GPU STT image at all. Note this is a change to the Phase 9 `service_healthy` gate — call
    it out explicitly.
- **No `env_file`** (M3 — no LiveKit secret), `restart: unless-stopped`, `networks:[adept]`,
  LAN-bound port.

---

## 5. Dockerfile + ONNX export/quantize recipe (`stt/Dockerfile.cpu` + a script)

**The export is a TWO-PHASE thing** (CONTEXT: author the recipe; the multi-GB build +
accuracy check are operator-gated; do NOT commit the `.onnx`):

**Phase A — export + quantize (needs NeMo+torch; builder stage or operator script):**
```bash
# 1. Export from the ORIGINAL NeMo checkpoint WITH cache support (official path):
python - <<'PY'
import nemo.collections.asr as nemo_asr
m = nemo_asr.models.ASRModel.from_pretrained(os.environ["STT_MODEL"])
m.set_export_config({'cache_support': 'True'})    # REQUIRED for streaming cache I/O
m.export("stt.onnx")                              # → encoder + decoder/joint graphs
PY
# 2. int8 dynamic (DEFAULT, stock ORT — encoder only, decoder/joint stay FP32):
python -c "from onnxruntime.quantization import quantize_dynamic, QuantType; \
  quantize_dynamic('encoder_model.onnx','encoder_int8.onnx',weight_type=QuantType.QInt8)"
# 3. (STRETCH, operator) int4 k-quant + MHA fusion per arXiv 2604.14493 → ~0.67 GB.
```
The `danielbodart/nemotron-speech-600m-onnx` repo's scripts (`nemo_export_onnx.py`,
`onnx_int8_quantize.py`, `onnx_int8_calibration.py` — **warm-cache streaming calibration**,
which avoids the blank-token collapse that breaks naive static quant of cache-stateful
streaming models) are the working template. The PLAN should author an
`stt/export_onnx.py` mirroring these.

**Phase B — the lean CPU runtime image (`stt/Dockerfile.cpu`):**
- `FROM python:3.11-slim` (no CUDA).
- `ARG STT_ONNX_MODEL` (single-source, no hardcoded tag — the Compose `build.args` supplies
  it from env; mirrors `STT_MODEL`). `ENV STT_ONNX_MODEL=${STT_ONNX_MODEL}`,
  `ENV STT_RUNTIME=cpu`.
- pip install pinned `onnxruntime`, `fastapi`, `uvicorn[standard]`, `numpy`,
  `sentencepiece` (+ mel dep).
- **Bake the model:** either run the export in a multi-stage builder (heavy — NeMo+torch in
  the builder only, copy the `.onnx` into the slim final stage) OR `hf download` a pre-built
  ONNX bundle keyed by `STT_ONNX_MODEL` at build (no first-run download; offline/local-first
  — same intent as Phase 9's `.nemo` bake). The PLAN picks one; the multi-GB build is an
  operator gate either way.
- python-urllib `/health` HEALTHCHECK (NOT curl), generous `start_period` (ONNX load is far
  faster than NeMo — a shorter start_period than 180 s is fine, but keep python-urllib for
  parity).
- `EXPOSE 8000`; `CMD uvicorn server:app ...` (the SAME `server.py`, `STT_RUNTIME=cpu`
  routes it to the ORT backend).

---

## 6. Env surface (`.env.example`)

Add, mirroring the existing STT/OLLAMA single-source comment style:
- `STT_ONNX_MODEL=...` — single-sourced ONNX artifact tag/path (the CPU analog of
  `STT_MODEL`); literal default lives ONLY in compose `build.args`/`environment`.
- `STT_QUANT=int8-dynamic` — quant profile selector (`int8-dynamic` default; `int4-kquant`
  stretch/operator). Document that `int4-kquant` is the ~0.67 GB STT-05 target and is an
  operator-gated build.
- `NEMO_STT_CPU_URL` — note the code default `ws://nemo-stt-cpu:8000/v1/audio/stream` (or
  add it explicitly, parity with `NEMO_STT_URL` which is code-default only today).
- **`STT_FORCE_CPU=1`** — ship as the **documented SAFE DEFAULT** (CONTEXT) until the
  operator co-residency gate flips it. Comment: pins CPU-ONNX for BOTH LLMs; the picker is
  VRAM-safe out of the box; the operator sets `STT_FORCE_CPU=0` (and the measured flag) only
  after the 4-cell matrix proves E4B + GPU-STT + Kokoro co-fit.
- (Server-only) `STT_RUNTIME` is set per-service in compose, not in `.env.example`.

---

## 7. `vram-validate.sh` 4-cell matrix `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}`

Parametrize the existing harness. Per-cell variables:
- **`OLLAMA_MODEL`** swept over the Fast (E2B) and Better (E4B) tags (the script already
  reads `OLLAMA_MODEL`; restart ollama between tags to clear `keep_alive=-1`, per Gate D).
- **`EXPECTED_GPU_PROCS`** is **no longer a constant 3** — it becomes a per-cell value:
  - **GPU-STT cells → 3** procs (ollama, nemo-stt, kokoro).
  - **CPU-STT cells → 2** procs (ollama, kokoro) — `nemo-stt-cpu` runs on CPU, NOT a GPU
    process, so it must NOT be counted/expected. Add a `--stt-runtime gpu|cpu` flag (or
    `STT_RUNTIME_UNDER_TEST` env) that sets `EXPECTED_GPU_PROCS` to 3 or 2.
- **Peak assertion unchanged:** `peak < total − 1 GB` (15360 MB) at the **KB-load prefill
  peak** (`--with-kb`), per cell. The CPU-STT cells will show a LOWER peak (no +2.4 GB STT on
  GPU) — that is the headroom the placement table banks on.
- The base URL/health probe for the STT under test points at `nemo-stt` (8000) or
  `nemo-stt-cpu` (host 8001) per cell.
- Keep the q8_0-engaged grep (already 0.30.x-aware).

Output: a 4-row pass/fail table the operator signs in `10-PLACEMENT-VERIFY.md`. The
**GPU-STT × E4B cell is the load-bearing one** — if its peak ≥ ceiling, the safe default
stays `STT_FORCE_CPU=1` and the resolver returns CPU for E4B sessions.

---

## 8. Exact files to CREATE / MODIFY

### CREATE
| File | Purpose |
|---|---|
| `agent/placement.py` | `resolve_stt_placement(llm_choice, env) -> "gpu"|"cpu"` pure resolver + the static headroom table constants (§3). |
| `stt/backend_onnx.py` | ORT CPU backend: `load_model`/`new_stream_state`/`decode_chunk`/`finalize` over encoder+decoder ONNX sessions with the cache loop + mel preprocessing (§1). |
| `stt/backend_nemo.py` | The current `stt/server.py` NeMo decode body moved behind the `STT_RUNTIME=gpu` dispatch (§2). |
| `stt/Dockerfile.cpu` | Lean CPU base (python:slim, onnxruntime, no CUDA), `STT_ONNX_MODEL` bake, `STT_RUNTIME=cpu` (§5). |
| `stt/requirements-cpu.txt` | `onnxruntime`, `fastapi`, `uvicorn[standard]`, `numpy`, `sentencepiece` (+ mel dep) — pinned, no `onnxruntime-gpu`. |
| `stt/export_onnx.py` | Operator/build export+quant recipe (NeMo export with `cache_support=True` → int8-dynamic / int4-kquant) (§5). |
| `tests/test_placement.py` (or repo test convention) | Pure-fn unit tests: `llm_choice × STT_FORCE_CPU × measured/headroom → gpu/cpu`. |
| `.planning/phases/10-.../10-PLACEMENT-VERIFY.md` | Operator GPU-gate runbook: real ONNX export+build, >6× realtime, WER-under-contention, the 4-cell matrix, safe-default flip. |

### MODIFY
| File | Change |
|---|---|
| `stt/server.py` | Add `STT_RUNTIME` const + lazy backend dispatch; move the NeMo body to `backend_nemo.py`; keep WS/HTTP/lifespan/health/lock/stall-watchdog as-is. |
| `agent/main.py` | Add `NEMO_STT_CPU_URL`; import + call `resolve_stt_placement(current_model[0], os.environ)` once in `build_session`; construct `NemoSTT(ws_url=<resolved>)`. Do NOT touch `handle_model_update`. |
| `docker-compose.yml` | Add `nemo-stt-cpu:` service (clone of `nemo-stt` minus GPU reservation, `Dockerfile.cpu`, `STT_RUNTIME=cpu`, `STT_ONNX_MODEL` build ARG, host port 8001); adjust agent `depends_on` per §4 (recommended: drop STT `service_healthy` hard-gate). |
| `.env.example` | Add `STT_ONNX_MODEL`, `STT_QUANT`, `NEMO_STT_CPU_URL` note, and **`STT_FORCE_CPU=1` safe default** (§6). |
| `scripts/vram-validate.sh` | Parametrize `EXPECTED_GPU_PROCS` (3 GPU-STT / 2 CPU-STT) via `--stt-runtime`; sweep `OLLAMA_MODEL` over E2B/E4B; per-cell peak assertion (§7). |
| `README.md` | Note the two STT runtimes + the placement/`STT_FORCE_CPU` default. |

### NO CHANGE (validated)
- `agent/nemo_stt.py` — runtime-agnostic; only the URL it is handed changes (CONTEXT).
- `agent/metrics.py` — READ-ONLY; the CPU backend emits the same `delta`/`final` so
  `_emit_final`'s `STTMetrics` still populates `stt_ms`.
- The `model.update` LLM-swap RPC handler — placement is read once, never re-consulted.

---

## 9. Sandbox-verifiable vs operator-GPU-gated split

| Item | Where |
|---|---|
| `agent/placement.py` pure-fn unit tests (`llm_choice × STT_FORCE_CPU × measured/headroom → gpu/cpu`; worst-case-LLM lock; default-CPU-when-unmeasured) | **Sandbox** (pure python, no GPU). |
| `STT_FORCE_CPU` parse/normalize + first-check short-circuit | **Sandbox**. |
| `py_compile stt/server.py`, `backend_nemo.py`, `backend_onnx.py` (heavy imports lazy/inside functions) | **Sandbox**. |
| `STT_RUNTIME` dispatch path with a **stubbed** backend (no ORT/NeMo download) — WS framing/flush/delta/final/error against the stub | **Sandbox** (mock backend echoes text). |
| `docker compose config` validity (both STT services, no GPU reservation on CPU one) | **Sandbox** if a compose binary is present (no daemon needed for `config`). |
| `agent/main.py` wiring compiles; resolved URL flows into `NemoSTT` | **Sandbox** (`py_compile` + a unit test of the URL pick). |
| **Real ONNX export** (`model.export` cache_support=True) + int8/int4 quant | **Operator** (needs NeMo+torch; multi-GB). |
| **CPU-ONNX image build** + model bake | **Operator** (no Docker daemon in sandbox). |
| **>6× realtime on CPU** + **WER-under-contention** vs FP32/NeMo baseline | **Operator GPU/host gate**. |
| **int4 k-quant ~0.67 GB** size + WER-within-1% | **Operator** (custom k-quant tooling). |
| **4-cell `{E2B,E4B}×{GPU,CPU}` co-residency matrix** (peak < total−1 GB, 3 vs 2 GPU procs) | **Operator GPU gate**. |
| **Kokoro VRAM footprint** measurement (the `KOKORO_MB` placeholder) | **Operator GPU gate**. |
| **Safe-default flip** (`STT_FORCE_CPU=1` → `0` + measured flag) | **Operator** (only after the matrix passes). |
| mel-preprocessing numerical parity (filterbank/STFT vs NeMo preprocessor) | **Operator** (caught by the WER gate). |

---

## 10. Risks / open items the PLAN must address

1. **4-bit vs int8 honesty (HIGH).** The literal ~0.67 GB is int4 k-quant from arXiv
   2604.14493, requiring **custom k-quant + MHA-fusion tooling**, NOT stock `quantize_dynamic`.
   Ship int8-dynamic (~0.88 GB) as the default build; make int4-kquant an operator-gated
   profile. Do not claim 0.67 GB for the int8 default. (§1.1)
2. **mel preprocessing leaves the ONNX graph (HIGH).** The CPU backend must recompute the
   128-band Slaney mel itself (baked `filterbank.bin` + numpy, or librosa). A mismatch
   silently tanks WER. Highest-risk parity item; operator WER gate is the catch. (§1.3)
3. **`conformer_stream_step` ≠ ORT loop (MED).** The CPU path reimplements encoder + greedy
   RNNT + detokenize to reproduce the cumulative string. Token/blank handling (blank=1024,
   ≤10 symbols/frame, dec_state feedback) must match exactly or `delta`/`final` text drifts.
   Use the danielbodart `config.json` shapes verbatim. (§1.2)
4. **CPU int8 speed is hardware-dependent (MED).** Fast only with VNNI/AMX; the >6× realtime
   claim is an operator host-CPU gate, not a given. (§1.4)
5. **Kokoro footprint is a placeholder (MED).** `KOKORO_MB=2048` is unmeasured; the whole GPU
   branch of the resolver hinges on the real number + the 4-cell matrix. Default stays CPU
   until measured. (§3)
6. **depends_on coupling (MED).** Forcing both STT services `service_healthy` contradicts the
   CPU-safe default (would boot an unused GPU image). Recommended: drop STT to
   `service_started` / rely on the plugin WS retry. This *changes* the Phase 9 gate — call it
   out. (§4)
7. **`EXPECTED_GPU_PROCS` is no longer constant (LOW).** Must be 3 (GPU-STT) or 2 (CPU-STT)
   per cell, or the matrix false-fails. (§7)
8. **Export reproducibility / no-commit-artifact (LOW).** The `.onnx` must NOT be committed
   (multi-GB); bake at build via `STT_ONNX_MODEL`. The export script + a pinned NeMo version
   are the reproducibility seam (operator). (§5)
9. **ONNX opset / ORT version drift (LOW).** Pin `onnxruntime` and the export opset; a newer
   ORT may reject an older quantized graph. Operator build catches it.

---

## 11. Hooks / seams (noted, NOT built this phase)

- **int4 k-quant build profile** — `STT_QUANT=int4-kquant` is wired as a selector but the
  custom k-quant tooling + the ~0.67 GB benchmark are operator-gated (§1.1). The seam lets a
  future build hit the literal STT-05 number with zero placement-code change.
- **GPU-ONNX variant** — the danielbodart export ships `int8-static` (QDQ, CUDA EP) and
  `fp16`; a future "ONNX-on-GPU" middle option is a `STT_RUNTIME`/provider seam, NOT in scope
  (Phase 10 is GPU-NeMo vs CPU-ONNX only).
- **Live VRAM probe** — explicitly out of scope (CONTEXT): placement is static-table-driven;
  a future `nvidia-smi`-informed resolver is a Phase 11 (deployment doctor) seam.
- **Cyber-vocab fine-tune** — `STT_MODEL` / `STT_ONNX_MODEL` single-source tags already let a
  future fine-tuned checkpoint be exported + swapped in with no code change (Phase 9 §10 hook
  carried forward).

---

RESEARCH COMPLETE
