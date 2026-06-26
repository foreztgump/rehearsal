---
status: pending-operator
phase: 10-vram-aware-stt-placement-part-c
plan: 10-02
requirement_ids: [STT-05, STT-06, STT-07]
verifies: [STT-05, STT-06, STT-07, "ONNX export cache_support=True + int8/int4 quant + size", "mel-preprocessor parity (baked filterbank vs NeMo preprocessor)", ">6x realtime CPU-ONNX under contention", "WS contract byte-identical GPU vs CPU", "placement resolves once / no mid-session thrash on Fast↔Better swap", "STT_FORCE_CPU global pin both LLMs", "4-cell {E2B,E4B}×{GPU,CPU} co-residency matrix peak < total−1GB", "Kokoro KOKORO_MB placeholder measurement", "safe-default flip after matrix"]
harness_note: >
  Every gate below needs the live GPU stack (Docker daemon + RTX 5090 + NeMo/torch at
  export time + onnxruntime at serve time + browser + LAN mic). The execution sandbox
  has NO GPU, NO Docker daemon, and CANNOT import NeMo/torch/onnxruntime, so the real
  ONNX export + int8/int4 quant, the CPU-ONNX image build + model bake, the mel-parity
  numerics, the >6× realtime + WER-under-contention measurements, the 4-cell
  co-residency matrix, and the live placement/no-thrash behaviour are ALL deferred
  operator gates. NONE are marked passed by the executor — the operator fills each
  result table with measured observations on the real GPU host. What ships
  sandbox-verified (already green, not re-proven here): agent/placement.py pure-fn
  _self_check + tests/test_placement.py full truth-table matrix (force-cpu-first,
  default-CPU-when-unmeasured, worst-case-LLM lock, unknown-choice CPU-safe,
  no-exception invariant), py_compile of agent/placement.py + agent/main.py +
  stt/server.py + stt/backend_nemo.py + stt/backend_onnx.py, the stubbed STT_RUNTIME
  dispatch round-trip (stt/test_dispatch.py), bash -n scripts/vram-validate.sh, and
  docker compose config validity (both STT services, no GPU reservation on the CPU one).
---

# Phase 10 — VRAM-Aware STT Placement (Part C): OPERATOR VERIFICATION (ONNX export + quant + size, mel-parity, >6× realtime + WER, 4-cell co-residency matrix, Kokoro measurement, resolve-once/no-thrash, STT_FORCE_CPU pin, safe-default flip)

**Status:** PENDING OPERATOR — run on the Proxmox VM (Docker daemon + RTX 5090 + NeMo/torch +
onnxruntime + browser + LAN mic). The sandbox has **no** GPU/Docker daemon and **cannot import
NeMo/torch/onnxruntime**, so every gate below is a deferred operator gate. **None are marked passed
by the executor.**

**Owns:**
- **STT-05** — an off-GPU CPU-ONNX STT runtime (`nemo-stt-cpu`, `STT_RUNTIME=cpu`) serves the
  byte-identical Phase-9 WS contract via an int8-dynamic (~0.88 GB) ONNX encoder, with int4-kquant
  (~0.67 GB) as an operator-gated stretch; >6× realtime on CPU with negligible WER loss under
  contention.
- **STT-06** — STT placement is resolved EXACTLY ONCE at session start by the pure
  `resolve_stt_placement(llm_choice, env)` from a STATIC measured-headroom table (no live
  `nvidia-smi` probe), using worst-case-LLM (E4B/Better) math so a mid-session Fast↔Better LLM swap
  never thrashes the STT runtime.
- **STT-07** — `STT_FORCE_CPU` is the FIRST check in the resolver and short-circuits to CPU for BOTH
  LLM choices before any headroom logic — the global pin that makes the LLM picker VRAM-safe.

---

## Frozen-contract notes (read before running any gate)

- **The WS contract is byte-unchanged.** The CPU-ONNX backend reproduces the SAME cumulative growing
  transcript the GPU path emits, so the server's `ready`/`delta`/`final`/`error` framing, the
  flush→final reset, and the stall watchdog are identical at the WS layer. `agent/nemo_stt.py` is
  untouched — only the `ws_url` it is handed changes.
- **Placement is resolved ONCE.** `resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)` is called
  exactly once in `build_session` at session start and NEVER re-consulted on an LLM swap (STT-06).
  `grep -n "resolve_stt_placement" agent/main.py` shows it ONLY in `build_session`, never in
  `handle_model_update`.
- **`handle_model_update` / VAD-turn-detector / `agent/metrics.py` are untouched.** The `model.update`
  LLM-swap RPC stays LLM-only (no placement re-check/guard added); the `turn_handling` dict +
  `MultilingualModel` turn detector keep sole endpoint authority; `agent/metrics.py` is READ-ONLY
  (verify `git diff agent/metrics.py` is empty). The CPU backend emits the same `delta`/`final`, so
  `stt_ms` still populates unchanged.
- **Single-source ONNX tag.** `STT_ONNX_MODEL` (build ARG + Compose env) is the single source for the
  CPU ONNX bundle — no hardcoded ONNX tag in `stt/server.py`, the backends, or the agent.

---

## PINNED: the placement semantics (RESEARCH §3 — the locked resolution order)

- **`STT_FORCE_CPU` is checked FIRST** — truthy (`{"1","true","yes","on"}`, normalized) → `"cpu"`
  immediately, before any headroom logic (STT-07). It pins CPU for BOTH LLM choices.
- **The default is CPU until `STT_HEADROOM_MEASURED=1`** — the GPU branch is LOCKED OFF until the
  operator measures the real Kokoro footprint + runs the 4-cell matrix and flips the measured flag
  (the default-CPU-when-unmeasured lock; `KOKORO_MB=2048` is an unmeasured placeholder).
- **The GPU branch uses worst-case-LLM (E4B) math** — `max(LLM_PEAK_MB) + KOKORO_MB + STT_GPU_MB <=
  VRAM_TOTAL_MB − VRAM_HEADROOM_MB`. Because it keys off the HEAVIEST LLM, the decision is identical
  for Fast and Better, so a mid-session swap is always VRAM-safe.
- **The shipped `.env.example` carries `STT_FORCE_CPU=1`** so the picker is VRAM-safe out of the box
  regardless of the table arithmetic.

---

## 0. Build / deploy BEFORE verifying (stale-deploy / baked-image guard)

The stack runs from **baked images** — a code edit is NOT live until the image is rebuilt. The
`nemo-stt-cpu` image bakes the ONNX bundle (`STT_ONNX_MODEL`) at build time (offline-capable) and
loads it resident at container start. Always rebuild + restart BEFORE any live gate:

```bash
# from the repo root on the VM
set -a && . ./.env && set +a
docker compose build nemo-stt-cpu agent
docker compose up -d
docker compose ps              # nemo-stt-cpu: healthy on host 8001; agent: Up
```

The agent no longer hard-depends on either STT service's `service_healthy` (Wave-1 10-01 dropped the
gate) — the plugin's WS connect-retry is the readiness point, so a CPU-default deploy
(`STT_FORCE_CPU=1`) does NOT wait on a GPU STT image it never uses. The resolved service simply must
be up.

---

## Gate 1 — ONNX export (cache_support=True) + int8/int4 quant + size (STT-05, RESEARCH §1.1/§5)

**Goal:** `stt/export_onnx.py` runs the official cache-aware export → encoder + decoder/joint graphs;
int8-dynamic encoder lands ~0.88 GB on disk (the CI/Docker-reproducible default); the int4-kquant
~0.67 GB stretch is a SEPARATE operator build (custom k-quant + MHA-fusion tooling, NOT stock
`quantize_dynamic`).

**Steps (operator host with NeMo+torch+onnxruntime):**

```bash
# export from the ORIGINAL NeMo checkpoint WITH cache support, then quantize:
STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b \
STT_QUANT=int8-dynamic python stt/export_onnx.py
ls -lh encoder_int8.onnx decoder_model.onnx   # record on-disk sizes
# (STRETCH, operator) int4 k-quant + MHA fusion per arXiv 2604.14493 → ~0.67 GB:
STT_QUANT=int4-kquant python stt/export_onnx.py
```

**ASSERT:** the export emits the encoder + decoder/joint graphs with cache I/O (cache_support=True);
the int8-dynamic encoder is ~0.88 GB; the **int4-kquant ~0.67 GB is the operator-gated STT-05
stretch** (NOT the int8 default); the decoder/joint + cache tensors stay FP32.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| cache_support=True export → encoder + decoder/joint | yes | |
| int8-dynamic encoder on-disk size | ~0.88 GB | |
| int4-kquant stretch on-disk size (operator) | ~0.67 GB | |
| decoder/joint + cache tensors FP32 | yes | |
| **Gate 1 verdict** | PASS | **PENDING** |

---

## Gate 2 — mel-preprocessor parity (RESEARCH §1.3, HIGHEST RISK)

**Goal:** the CPU backend's self-computed 128-band Slaney mel (baked `filterbank.bin` + numpy STFT)
matches the NeMo `AudioToMelSpectrogramPreprocessor` numerically — a mismatch silently tanks WER
because the mel features leave the exported ONNX graph and must be recomputed host-side.

**Steps:** run a fixed clip through both the NeMo preprocessor and the CPU backend's
`_extract_features`; compare the feature tensors and the resulting WER on the same clip.

```bash
docker compose exec nemo-stt-cpu python - <<'PY'
# compare backend_onnx._extract_features(pcm) vs NeMo preprocessor features on a fixed clip
# (max abs diff per mel band; WER on the decoded transcript)
PY
```

**ASSERT:** the per-band feature max-abs-diff is within numerical tolerance (sample-rate 16000,
pre-emphasis 0.97, FFT 512 / hop 160 / win 400 Hann, 128 Slaney bands, band-major); the decoded WER
on the clip is within ~0.17% abs of the FP32/NeMo baseline.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| mel feature max-abs-diff vs NeMo preprocessor | within tolerance | |
| WER delta on the fixed clip | within ~0.17% abs | |
| **Gate 2 verdict** | PASS | **PENDING** |

---

## Gate 3 — CPU-ONNX contract parity + >6× realtime + WER-under-contention (STT-05)

**Goal:** `nemo-stt-cpu` serves the byte-identical `ready`/`delta`/`final`/`error`; a real clip
streams growing deltas + a flush FINAL; measured CPU throughput is >6× realtime; WER is within target
vs the FP32/NeMo baseline under concurrent LLM+TTS load.

**Steps:** stream a real clip through the CPU service WS (host 8001) while the LLM+TTS load runs;
measure decode wall-clock vs audio duration; compare the transcript against the NeMo baseline.

```bash
docker compose logs nemo-stt-cpu | grep -iE 'ready|delta|final|error' | tail -40
# time a clip decode: realtime_factor = audio_seconds / decode_seconds  (target > 6)
```

**ASSERT:** the WS framing is byte-identical to the GPU path (ready→growing deltas→one flush FINAL,
native PnC surfaced as-is); realtime factor > 6× on the host CPU (VNNI/AMX dependent — RESEARCH
§1.4); WER within target vs FP32/NeMo under contention.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| WS contract byte-identical (ready/delta/final/error) | yes | |
| growing deltas + single flush FINAL | yes | |
| CPU realtime factor | > 6× | |
| WER under contention vs FP32/NeMo | within target | |
| **Gate 3 verdict** | PASS | **PENDING** |

---

## Gate 4 — 4-cell {E2B,E4B}×{GPU,CPU} co-residency matrix (STT-06, RESEARCH §7)

**Goal:** at the `--with-kb` KB-load prefill peak, every cell fits under the 16 GB-with-headroom
ceiling (peak < 15360 MB); GPU-STT cells show 3 GPU procs (ollama, nemo-stt, kokoro) and CPU-STT
cells show 2 (ollama, kokoro). The **GPU-STT × E4B cell is LOAD-BEARING**: if its peak ≥ ceiling, the
safe default stays `STT_FORCE_CPU=1` and the resolver returns CPU for E4B.

**Steps:** sweep `OLLAMA_MODEL` over E2B (Fast) / E4B (Better) × `--stt-runtime gpu|cpu`, restarting
ollama between tags to clear `keep_alive=-1` (Gate D):

```bash
set -a && . ./.env && set +a
OLLAMA_MODEL="$OLLAMA_MODEL_FAST"   ./scripts/vram-validate.sh --stt-runtime gpu --with-kb
OLLAMA_MODEL="$OLLAMA_MODEL_BETTER" ./scripts/vram-validate.sh --stt-runtime gpu --with-kb   # LOAD-BEARING
OLLAMA_MODEL="$OLLAMA_MODEL_FAST"   ./scripts/vram-validate.sh --stt-runtime cpu --with-kb
OLLAMA_MODEL="$OLLAMA_MODEL_BETTER" ./scripts/vram-validate.sh --stt-runtime cpu --with-kb
```

**ASSERT:** each cell prints `PASS` — q8_0 KV engaged (no F16 fallback), peak < 15360 MB, the
expected GPU-proc count (3 for GPU-STT / 2 for CPU-STT). The CPU-STT cells show a LOWER peak (no +2.4
GB STT on GPU) — that is the headroom the placement table banks on.

**Results capture:**

| Cell | OLLAMA_MODEL | --stt-runtime | expected procs | peak VRAM | < 15360? | PASS/FAIL |
|------|--------------|---------------|----------------|-----------|----------|-----------|
| E2B × GPU-STT | Fast | gpu | 3 | | | **PENDING** |
| E4B × GPU-STT (LOAD-BEARING) | Better | gpu | 3 | | | **PENDING** |
| E2B × CPU-STT | Fast | cpu | 2 | | | **PENDING** |
| E4B × CPU-STT | Better | cpu | 2 | | | **PENDING** |

- **Gate 4 verdict: PENDING**

---

## Gate 5 — Kokoro VRAM measurement (RESEARCH §3 — the KOKORO_MB placeholder)

**Goal:** measure the real Kokoro-82M GPU footprint to replace the `KOKORO_MB=2048` placeholder in
`agent/placement.py`, then sanity-check the headroom table against the measured number.

**Steps:** with only Kokoro resident (or by differencing nvidia-smi with/without Kokoro), record its
GPU footprint; recompute `worst_llm + KOKORO_real + STT_GPU_MB` against the 15360 ceiling.

**ASSERT:** the measured Kokoro footprint is recorded; the worst-case (E4B) sum with the REAL Kokoro
number is consistent with the Gate 4 GPU-STT × E4B peak — if it exceeds the ceiling, the GPU branch
must stay disabled (`STT_FORCE_CPU=1`).

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| measured Kokoro-82M GPU footprint (MB) | (record) | |
| E4B + Kokoro(real) + STT_GPU_MB vs 15360 | ≤ ceiling to allow GPU | |
| placeholder KOKORO_MB=2048 vs measured | (record delta) | |
| **Gate 5 verdict** | PASS | **PENDING** |

---

## Gate 6 — placement resolves once / no mid-session thrash on Fast↔Better swap (STT-06)

**Goal:** with the measured flag set, a live Fast↔Better `model.update` swap does NOT change the STT
runtime — STT stays on the session-start URL; `handle_model_update` never re-resolves placement.

**Steps:** start a live session, note the STT URL the agent connected to, then send `model.update`
swaps (Fast→Better→Fast) and confirm the STT connection is unchanged:

```bash
docker compose logs agent | grep -iE 'nemo-stt|ws_url|placement' | tail -20
# perform Fast↔Better swaps via the browser ModelPanel during the session
```

**ASSERT:** the agent logs show STT connected to the session-start URL ONCE; no STT reconnect /
runtime switch on any `model.update`; the LLM tag swaps in place (the existing LLM-only behaviour).

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| STT resolves once at session start | yes | |
| no STT runtime switch on Fast↔Better swap | yes (none) | |
| LLM tag swaps in place (LLM-only) | yes | |
| **Gate 6 verdict** | PASS | **PENDING** |

---

## Gate 7 — STT_FORCE_CPU global pin (STT-07)

**Goal:** `STT_FORCE_CPU=1` pins CPU for BOTH LLM choices regardless of headroom/measured; the agent
connects to `nemo-stt-cpu`.

**Steps:** with `STT_FORCE_CPU=1` (the shipped default), start a session with Fast, then with Better,
and confirm STT routes to `nemo-stt-cpu` both times — even if `STT_HEADROOM_MEASURED=1`.

```bash
docker compose logs agent | grep -iE 'nemo-stt-cpu|placement' | tail -10
```

**ASSERT:** with `STT_FORCE_CPU=1`, STT connects to `ws://nemo-stt-cpu:8000/...` for BOTH Fast and
Better, and the force-pin wins even when `STT_HEADROOM_MEASURED=1` (force is checked first).

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| STT_FORCE_CPU=1 → CPU for Fast | yes (nemo-stt-cpu) | |
| STT_FORCE_CPU=1 → CPU for Better | yes (nemo-stt-cpu) | |
| force beats STT_HEADROOM_MEASURED=1 | yes | |
| **Gate 7 verdict** | PASS | **PENDING** |

---

## Gate 8 — safe-default flip (ONLY after Gates 1–5 pass)

**Goal:** ONLY after the export/quant/size, mel-parity, >6× realtime + WER, the 4-cell matrix, and
the Kokoro measurement all pass, flip `STT_FORCE_CPU=1`→`0` + `STT_HEADROOM_MEASURED=1` and confirm
E2B/E4B route per the matrix.

**Steps:** set `STT_FORCE_CPU=0` and `STT_HEADROOM_MEASURED=1` in `.env`, restart the agent, and
verify routing: E4B → CPU if its GPU-STT cell (Gate 4) failed; GPU otherwise.

```bash
# .env: STT_FORCE_CPU=0  STT_HEADROOM_MEASURED=1   (ONLY after Gates 1–5 PASS)
docker compose up -d agent
docker compose logs agent | grep -iE 'nemo-stt|placement' | tail -10
```

**ASSERT:** with the flag flipped, placement routes per the matrix — GPU when the worst-case (E4B)
cell fit under the ceiling, CPU when it did not. The flip is performed ONLY after Gates 1–5 PASS.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| Gates 1–5 all PASS before flip | yes | |
| E2B/E4B route per the matrix after flip | yes | |
| GPU only if E4B GPU-STT cell fit | yes | |
| **Gate 8 verdict** | PASS | **PENDING** |

---

## Overall Phase-10 (placement) sign-off

| Gate | What it proves | Verdict |
|------|----------------|---------|
| 1 | ONNX export (cache_support=True) + int8 ~0.88 GB / int4-kquant ~0.67 GB stretch + size | **PENDING** |
| 2 | mel-preprocessor parity (baked filterbank vs NeMo) — WER within ~0.17% abs | **PENDING** |
| 3 | CPU-ONNX byte-identical WS contract + >6× realtime + WER-under-contention | **PENDING** |
| 4 | 4-cell {E2B,E4B}×{GPU,CPU} co-residency matrix, peak < 15360, 3 vs 2 procs (E4B×GPU load-bearing) | **PENDING** |
| 5 | Kokoro KOKORO_MB placeholder measured + table sanity-checked | **PENDING** |
| 6 | placement resolves once / no mid-session thrash on Fast↔Better swap | **PENDING** |
| 7 | STT_FORCE_CPU pins CPU for BOTH LLM choices (force-first, STT-07) | **PENDING** |
| 8 | safe-default flip (STT_FORCE_CPU=1→0 + STT_HEADROOM_MEASURED=1) after the matrix | **PENDING** |

**Operator:** _______________  **Date:** _______________  **VM/GPU:** RTX 5090

**Net posture (to be filled by the operator):** the sandbox-verifiable placement resolver + agent
wiring are GREEN (placement.py _self_check + the full truth-table matrix in tests/test_placement.py,
py_compile of placement.py/main.py/server.py/backend_nemo.py/backend_onnx.py, the stubbed
STT_RUNTIME dispatch, bash -n vram-validate.sh, docker compose config); the real ONNX export + quant
+ size, mel-parity, >6× realtime + WER, the 4-cell co-residency matrix, the Kokoro measurement, the
resolve-once/no-thrash behaviour, the STT_FORCE_CPU pin, and the safe-default flip are all deferred
to this operator gate and **unsigned** until run on the real consumer GPU host.
