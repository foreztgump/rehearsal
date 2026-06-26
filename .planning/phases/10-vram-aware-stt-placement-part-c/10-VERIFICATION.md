---
phase: 10-vram-aware-stt-placement-part-c
verifier: goal-backward analysis
requirement_ids: [STT-05, STT-06, STT-07]
verdict: CODE-COMPLETE — operator gate pending (analogous to Phases 8/9)
sandbox_constraint: NO GPU, NO Docker daemon, CANNOT import NeMo/torch/onnxruntime
date: 2025
---

# Phase 10 — VRAM-Aware STT Placement (Part C): GOAL-BACKWARD VERIFICATION

## Phase goal (restated)

> Ship the mechanism to run STT either as full GPU NeMo or as the off-GPU 4-bit ONNX
> CPU port, resolved ONCE at session start from VRAM headroom coupled to the selected
> LLM, with a single env-flagged global-CPU-ONNX fallback (`STT_FORCE_CPU`) that makes
> the picker VRAM-safe with zero runtime switching — gated on an operator co-residency
> measurement.

**Verdict: CODE-COMPLETE with operator gate pending.** The CODE delivers the whole
mechanism the phase promised; the placement decision logic is correct and
resolve-once/no-thrash; the fallback flag short-circuits first; and the operator
deferral is correctly structured (runbook exists, 8 gates enumerated, status
`pending-operator`, nothing falsely passed). The GPU-only items (real ONNX
export+build, int8/int4 quant + on-disk size, mel-parity/WER, >6× realtime,
byte-identical GPU-vs-CPU contract, 4-cell co-residency matrix, Kokoro measurement)
are legitimately operator-gated, exactly as Phases 8 and 9 shipped.

---

## Goal-backward decomposition

Working backward from the goal, the phase is achieved iff ALL of these hold. Each is
assessed as **CODE-MET** (delivered + sandbox-verifiable) or **OPERATOR-GATED**
(mechanism in code, numeric proof deferred to 10-PLACEMENT-VERIFY.md).

| # | Goal sub-claim | Status | Evidence |
|---|----------------|--------|----------|
| G1 | STT can run as full GPU NeMo OR off-GPU CPU-ONNX behind ONE WS contract | CODE-MET | `server.py` lazy importlib dispatch on `STT_RUNTIME`; both backends expose the same 5-callable seam |
| G2 | Placement resolved ONCE at session start from VRAM headroom | CODE-MET | `resolve_stt_placement` called once in `build_session` (main.py:210), nowhere else |
| G3 | Headroom math coupled to the selected LLM, worst-case-locked so no mid-session thrash | CODE-MET | `_gpu_fits()` keys off `max(LLM_PEAK_MB)`; identical decision for fast/better proven in tests |
| G4 | Single env-flagged global CPU-ONNX fallback (`STT_FORCE_CPU`) | CODE-MET | First check in resolver, before any headroom logic; short-circuits to `"cpu"` |
| G5 | Zero runtime switching | CODE-MET | `handle_model_update` is LLM-only; no placement re-read on swap |
| G6 | Gated on an operator co-residency measurement | CORRECTLY DEFERRED | `STT_HEADROOM_MEASURED` locks GPU branch off; 10-PLACEMENT-VERIFY Gate 4 enumerated, unsigned |
| G7 | The "4-bit ONNX" / >6× realtime / size / WER reality | OPERATOR-GATED | export recipe + quant tiers in code; int8 ~0.88GB default reproducible, int4 ~0.67GB stretch literal-only |

---

## Per-requirement assessment

### STT-05 — CPU-ONNX alt runtime behind the same WS contract

**Status: SATISFIED-IN-CODE for the mechanism; numeric proofs operator-gated.**

What the code delivers (sandbox-verified):
- `stt/server.py` selects the backend by `STT_RUNTIME` via `importlib.import_module`
  (server.py:58-61), validate-or-`SystemExit` on a bad value. The WS/HTTP layer below
  (lines 90-200) is byte-unchanged from Phase 9 — `ready`/`delta`/`final`/`error`,
  the flush→final+reset, `/health` gate, `_gpu_lock` serialize, offline transcribe path.
- `stt/backend_onnx.py` reproduces the GPU path's cumulative growing transcript over
  ORT: explicit three-graph cache loop (`encoder.onnx` → greedy RNNT over
  `decoder_joint.onnx` with LSTM `dec_state` fed back, blank=1024, ≤10 symbols/frame →
  SentencePiece detokenize), numpy-only 128-band Slaney mel with NeMo per-feature
  normalization + add-offset log guard. Same 5-callable seam, same stall-watchdog
  semantics (shared via `backend_common`).
- `stt/test_dispatch.py` PROVES (without ORT/NeMo/fastapi) that `STT_RUNTIME=cpu`
  imports `backend_onnx` and the frozen WS framing round-trips config→ready, PCM→delta,
  flush→final, bad-frame→error against a stub backend. **Ran green in sandbox.**
- `stt/export_onnx.py` is the export recipe: `set_export_config({'cache_support':'True'})`
  for streaming cache I/O; **int8-dynamic encoder-only `quantize_dynamic` is the
  reproducible DEFAULT (~0.88 GB)**; **int4-kquant (~0.67 GB, the literal STT-05 number)
  is an explicit OPERATOR-GATED stretch** that `SystemExit`s with a clear "not stock
  ORT" message rather than pretending to work (export_onnx.py:78-80). Also emits
  `filterbank.bin` + `tokenizer.model` + `mel_parity.json` for the parity gate.
- `stt/Dockerfile.cpu` (python:3.11-slim, no CUDA/NeMo/torch in runtime stage;
  multi-stage export builder), `requirements-cpu.txt` (onnxruntime CPU, no torch/NeMo/
  librosa), python-urllib `/health`.

Honestly operator-gated (10-PLACEMENT-VERIFY Gates 1-3):
- Real ONNX export + int8/int4 quant + **on-disk size** (Gate 1).
- **Mel-preprocessor parity** baked filterbank vs NeMo preprocessor — HIGHEST RISK,
  WER within ~0.17% (Gate 2). M2 (STFT centering) / M3 (Hann periodicity) sub-items are
  explicitly flagged in `_stft_power` for the operator to confirm against the actual
  export config.
- **>6× realtime** + WER-under-contention + byte-identical GPU-vs-CPU contract (Gate 3).

These deferrals are legitimate: the sandbox cannot download or run ORT/NeMo. Code
delivers the mechanism; the numbers are gated. **No deferred item is falsely marked
passed.**

### STT-06 — resolve once at session start, no mid-session thrash

**Status: SATISFIED-IN-CODE; the no-thrash property is proven, not asserted.**

- `resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)` is called EXACTLY ONCE in
  `build_session` (main.py:210). `grep` confirms it appears in main.py only at the import
  (line 33), a comment (line 59), and the single call site (line 210) — **never** in
  `handle_model_update` or any per-turn path.
- The worst-case-LLM lock: `_gpu_fits()` computes `max(LLM_PEAK_MB) + KOKORO_MB +
  STT_GPU_MB <= ceiling` (placement.py:71-77). Because it keys off the HEAVIEST LLM
  (E4B/Better, 8912 MB), the decision is **identical for fast and better**. A mid-session
  Fast↔Better swap therefore can never strand placement.
- `tests/test_placement.py::test_worst_case_llm_lock_identical_fast_better` asserts the
  decision is identical for fast/better across the whole `force × measured` matrix, and
  `test_tightened_table_pins_cpu_for_both` proves a tightened table pins BOTH to CPU.
  **Ran green in sandbox.**
- `handle_model_update` (main.py:550-564) is verified LLM-only: validates the choice,
  mutates `session.llm._opts.model` in place, no placement re-check, no STT reconnect.

Operator-gated: the LIVE confirmation that a browser Fast↔Better swap does not reconnect
STT (Gate 6). The code makes this structurally impossible; the runtime observation is
deferred.

### STT-07 — STT_FORCE_CPU global fallback pins CPU for both LLMs

**Status: SATISFIED-IN-CODE; short-circuit-first verified.**

- `STT_FORCE_CPU` is the FIRST check in `resolve_stt_placement` (placement.py:92-93),
  returning `"cpu"` immediately before any headroom or measured-gate logic.
- `tests/test_placement.py::test_force_cpu_first_beats_measured` proves force-cpu pins
  CPU for both fast and better **even when `STT_HEADROOM_MEASURED=1` and the math would
  fit GPU**, across truthy normalizations (`1/true/TRUE/yes/on`). **Ran green.**
- Shipped as the safe default: `.env.example` carries `STT_FORCE_CPU=1` +
  `STT_HEADROOM_MEASURED=0`, so the picker is VRAM-safe out of the box regardless of the
  table arithmetic.

Operator-gated: the LIVE confirmation that the agent connects to `nemo-stt-cpu` for both
choices (Gate 7). Logic is sandbox-proven; runtime observation deferred.

---

## Invariants — all hold

| Invariant | Status | Evidence |
|-----------|--------|----------|
| C1 fix: CPU backend imports WITHOUT `STT_MODEL` | ✅ HOLDS | `backend_onnx` imports shared constants from tag-free `backend_common`, never `backend_nemo`; `test_dispatch._assert_cpu_import_needs_no_stt_model` subprocess-imports `backend_onnx` with `STT_MODEL` unset and asserts rc=0. Ran green. |
| No-hardcoded-tag single-source | ✅ HOLDS | `backend_onnx` reads `STT_ONNX_MODEL` (KeyError→SystemExit); `backend_nemo` reads `STT_MODEL`; literal defaults live ONLY in docker-compose.yml build.args/environment + .env.example |
| `metrics.py` untouched | ✅ HOLDS | `git diff --stat 85d95cc~1 HEAD -- agent/metrics.py` is EMPTY across the whole phase |
| `model.update` handler untouched (LLM-only) | ✅ HOLDS | `handle_model_update` validates choice → mutates `_opts.model` in place; no placement logic added |
| Phase-9 WS contract byte-unchanged | ✅ HOLDS | server.py WS/HTTP layer (ready/delta/final/error, flush→final+reset, /health) is the Phase-9 body; `agent/nemo_stt.py` untouched (only the `ws_url` handed to it differs) |
| VAD / turn detector untouched | ✅ HOLDS | `turn_handling` dict + `MultilingualModel` unchanged in build_session |
| Resolver never raises | ✅ HOLDS | `_self_check` + `test_no_exception_return_membership_invariant` cover the full matrix incl. unknown/empty choice → always in {gpu,cpu} |
| Default-CPU-when-unmeasured lock | ✅ HOLDS | `STT_HEADROOM_MEASURED` gates the GPU branch; default CPU even with `STT_FORCE_CPU=0` |
| Compose: CPU STT default, GPU behind profile, no GPU reservation on CPU | ✅ HOLDS | `nemo-stt-cpu` always-on (no profile), `nemo-stt` behind `stt-gpu` profile, agent `depends_on: nemo-stt-cpu`, service_healthy hard-gate dropped |

---

## Sandbox-verifiable evidence (re-run green this verification)

```
python3 agent/placement.py        → placement _self_check OK
python3 tests/test_placement.py   → test_placement OK — full llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED matrix
python3 stt/test_dispatch.py      → dispatch _self_check OK — frames: ['ready','delta','final','error']
py_compile placement/main/server/backend_common/backend_nemo/backend_onnx/export_onnx → OK
bash -n scripts/vram-validate.sh  → OK
git diff agent/metrics.py (whole phase) → empty (untouched)
grep resolve_stt_placement agent/main.py → import + comment + single call site (build_session) only
```

---

## Honest notes on the operator deferral

- **int4 (~0.67 GB literal) is operator-gated; int8 (~0.88 GB) is the reproducible
  default.** `export_onnx._quantize_encoder` ships stock `quantize_dynamic` for int8 and
  a documented-seam `SystemExit` for int4-kquant ("custom k-quant + MHA fusion, arXiv
  …; not stock ORT") — it does NOT claim 4-bit works out of the box. The phase goal's
  "4-bit ONNX CPU port" is therefore delivered as a *recipe + selector*, with the int8
  tier as the working default. This is the correct, honest posture.
- **`KOKORO_MB=2048` is an explicit unmeasured placeholder.** The arithmetic *says* GPU
  fits, but the LLM peaks were measured WITHOUT a co-resident GPU-STT and Kokoro is a
  guess — which is exactly why the GPU branch stays locked behind
  `STT_HEADROOM_MEASURED` until the operator measures Kokoro (Gate 5) and runs the 4-cell
  matrix (Gate 4). The code is conservative by construction.
- **10-PLACEMENT-VERIFY.md is correctly structured:** front-matter `status:
  pending-operator`, 8 gates each with a results table and a **PENDING** verdict, the
  E4B×GPU-STT cell flagged LOAD-BEARING, the safe-default flip (Gate 8) explicitly gated
  on Gates 1-5, and a `harness_note` enumerating what ships sandbox-green vs deferred.
  Nothing is falsely signed.
- **10-REVIEW.md findings resolved:** C1 + H1 fixed (verified in code), plus
  M1/M4/M5 + L1/L2/L3; M2/M3 mel sub-items correctly flagged for operator Gate 2 rather
  than silently closed.

---

## Overall verdict

**CODE-COMPLETE — operator gate pending (analogous to Phases 8/9).**

Every line of the mechanism the phase promised is present, byte-compiles, and is proven
to the limit the GPU-less/Docker-less/ORT-less sandbox allows:
- The dual-runtime STT dispatch behind one frozen WS contract is in place and round-trips
  against a stub (STT-05 mechanism).
- The placement resolver is pure, never-raises, resolve-once, worst-case-LLM-locked, and
  its truth table is exhaustively unit-tested (STT-06).
- `STT_FORCE_CPU` short-circuits first and is the shipped safe default (STT-07).
- All required invariants (C1, no-hardcoded-tag, metrics/model.update/WS-contract
  untouched) hold.

The remaining proofs — real export+quant+size, mel-parity/WER, >6× realtime,
byte-identical GPU-vs-CPU, and the 4-cell co-residency matrix + Kokoro measurement — are
legitimately operator-gated and correctly deferred to 10-PLACEMENT-VERIFY.md (status
pending-operator, 8 gates enumerated and UNSIGNED). This is the established Phase-8/9
pattern and is **not** a phase failure.

**No blocking gaps.** Phase 10 ships code-complete with the operator co-residency gate
pending.
