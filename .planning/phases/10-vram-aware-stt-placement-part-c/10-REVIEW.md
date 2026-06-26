# Phase 10 — VRAM-Aware STT Placement (Part C) — Code Review

**Scope:** Waves 1+2 source changes (stt/backend_nemo.py, stt/backend_onnx.py,
stt/server.py, stt/export_onnx.py, stt/Dockerfile.cpu, stt/requirements-cpu.txt,
stt/test_dispatch.py, agent/placement.py, agent/main.py, tests/test_placement.py,
docker-compose.yml, .env.example, scripts/vram-validate.sh).

**Method:** static read of every changed file; `git diff` of server.py vs the frozen
Phase-9 body and of agent/main.py around the `model.update` handler; sandbox execution
of `py_compile`, `placement._self_check`, `tests/test_placement.py`,
`stt/test_dispatch.py`, `bash -n scripts/vram-validate.sh`; reproduction of the CPU
import path. GPU/ONNX/Docker *runtime* behaviour is operator-gated and intentionally
NOT flagged as "untested"; only code-visible defects are reported.

---

## Verdict

The placement resolver, the WS-contract preservation, and the `model.update` handler
are correct and well-tested: `resolve_stt_placement` is pure, force-CPU-first,
default-CPU-when-unmeasured, returns an identical decision for fast/better (no-thrash
lock holds), never raises, the worst-case headroom math is right, it is read exactly
once in `build_session`, `agent/metrics.py` is untouched, and the Phase-9
ready/delta/final/error + /health-503 + flush-only-FINAL + stall-never-emits-FINAL
contract in `server.py` is byte-for-byte the Phase-9 body behind a thin
`backend.*(_model, …)` indirection. However, the off-GPU CPU runtime — the entire
point of the phase — **cannot start as shipped**: `backend_onnx` imports `backend_nemo`
at module top, whose body hard-requires `STT_MODEL`, which the CPU image deliberately
does not set, so the server SystemExits at import (the stubbed dispatch test masks
this). The mel-parity recompute also omits NeMo's per-feature normalization and
diverges on the log-guard, window periodicity, and STFT centering — each a silent WER
sink. Block on the Critical import coupling and the High normalization gap; the
remaining mel items are operator-WER-gate verification points.

**Findings:** Critical 1 · High 1 · Medium 5 · Low 3

---

## Critical

### C1 — CPU backend SystemExits at import: `backend_onnx` → `backend_nemo` top-level coupling requires `STT_MODEL`, which the CPU image never sets
`stt/backend_onnx.py:34-39` does `from backend_nemo import (INT16_FULL_SCALE,
RECYCLE_MIN_CHARS, SAMPLE_RATE, STALL_FRAMES)`. Importing `backend_nemo` runs its module
body, which at `stt/backend_nemo.py:36-39` does `os.environ["STT_MODEL"]` →
`SystemExit("STT_MODEL is not set …")` when unset. The CPU image sets `STT_MODEL` ONLY
in the export-builder stage (`stt/Dockerfile.cpu:21,25`); the runtime stage and the
`nemo-stt-cpu` compose service set only `STT_ONNX_MODEL`/`STT_QUANT`/`STT_RUNTIME=cpu`
(`Dockerfile.cpu:34-54`, `docker-compose.yml:165-168`). So at `STT_RUNTIME=cpu`,
`server.py:61 importlib.import_module("backend_onnx")` transitively imports
`backend_nemo`, which exits the process before the server can serve. The CPU STT server
never starts — Phase 10's whole deliverable is dead on arrival under the shipped config.

Reproduced in-sandbox:
```
$ env -u STT_MODEL STT_ONNX_MODEL=x STT_QUANT=int8-dynamic STT_RUNTIME=cpu \
    python3 -c "import sys; sys.path.insert(0,'stt'); import backend_onnx"
STT_MODEL is not set — supplied by docker-compose build/env
exit=1
```
`stt/test_dispatch.py` does NOT catch this: it installs a *stub* `backend_onnx` into
`sys.modules` before importing `server`, so the real module (and its `backend_nemo`
import) is never executed (see L2).

**Fix (pick one, prefer the first):** move the four shared constants
(`INT16_FULL_SCALE`, `SAMPLE_RATE`, `STALL_FRAMES`, `RECYCLE_MIN_CHARS`) into a tiny
tag-free `stt/stt_constants.py` that both backends import — so neither backend depends
on the other and neither pulls the `STT_MODEL` gate; OR make `STT_MODEL` lazy inside
`backend_nemo.load_model()` instead of at module scope; OR set `STT_MODEL` in the CPU
runtime ENV (worst option — re-introduces a tag the CPU path does not use).

---

## High

### H1 — Mel parity: per-feature normalization is missing entirely
`stt/backend_onnx.py:137-158` returns the raw `log(clip(mel))` with **no normalization**.
NeMo's `AudioToMelSpectrogramPreprocessor` defaults to `normalize="per_feature"` (mean/std
per mel bin), and that normalization lives in the preprocessor — which, per the file's own
header (L141-149), is NOT in the exported encoder graph and therefore must be recomputed
here. The FastConformer encoder was trained on per-feature-normalized features; feeding
un-normalized log-mel shifts the entire input distribution and will silently tank WER far
more than any of the Medium items. The `_write_parity_assets` export
(`stt/export_onnx.py:83-97`) bakes the filterbank and tokenizer but emits no
normalization statistics, so even a fix needs the export to surface the
normalization mode (and, for streaming, the per-feature running stats / fixed scale NeMo
uses on cache-aware chunks).

**Fix:** replicate the preprocessor's `normalize` step (per-feature mean/var over the
chunk, matching NeMo's streaming normalization) and verify against a reference feature
dump at the operator WER gate; have `export_onnx.py` record the normalize mode.

---

## Medium

### M1 — Mel parity: log zero-guard type and epsilon both differ from NeMo defaults
`stt/backend_onnx.py:157` uses `np.log(np.clip(mel, a_min=1e-9, …))` — a *clamp* guard
with eps `1e-9`. NeMo's preprocessor default is `log_zero_guard_type="add"` with
`log_zero_guard_value=2**-24` (≈5.96e-8), i.e. `log(mel + 2**-24)`. Both the guard
*type* (clamp vs add) and the *value* differ; for low-energy bands the two produce
materially different log values. Confirm the export's actual `log_zero_guard_*` config
and match it exactly.

### M2 — Mel parity: no `center=True` reflect padding in the STFT
`stt/backend_onnx.py:161-171` frames from `signal[i*hop : i*hop+win]` with leading pad
only when `len(signal) < win`. `torch.stft` (which NeMo wraps) defaults to `center=True`
with reflect padding of `n_fft//2`, shifting every frame's center and changing the frame
count. Unless the export was produced with `center=False`/`stft_conv` semantics, frame
alignment diverges from the trained preprocessor. Verify the export's STFT centering and
match (add `n_fft//2` reflect pad, or confirm center=False).

### M3 — Mel parity: Hann window periodicity unverified (`np.hanning` is symmetric)
`stt/backend_onnx.py:165` uses `np.hanning(_WIN)`, the *symmetric* (periodic=False) Hann
window. `torch.hann_window` defaults to `periodic=True`. NeMo's `FilterbankFeatures`
typically builds the window with `periodic=False` (which would match `np.hanning`), but
this is config-dependent and a mismatch subtly changes spectral leakage on every frame.
Confirm the window periodicity used at export and align.

### M4 — Mel parity: filterbank orientation is a hard-coded reshape trap
`stt/backend_onnx.py:100` reads `filterbank.bin` and forces `.reshape(1, _N_MELS,
_N_FFT//2+1)` = `(1,128,257)`, while `export_onnx.py:94` writes it dynamically as
`reshape(1, fb.shape[-2], fb.shape[-1])`. If `model.preprocessor.featurizer.filter_banks`
is freq-major (`[257,128]`) rather than band-major (`[128,257]`), the export writes a
`[1,257,128]` buffer that the loader silently re-interprets as `[1,128,257]`, scrambling
the mel projection with no error. The matmul orientation (`power @ filterbank[0].T`,
L156) is correct *given* `[128,257]`, but nothing asserts the on-disk shape. Add a shape
assert in `load_model` (and/or have the export validate `fb.shape == (128, 257)` before
writing).

### M5 — Compose topology defeats the headroom the placement table banks on
There are no `profiles:` on the STT services, and the agent's `depends_on`
(`docker-compose.yml:48-55`) references `nemo-stt` (GPU) only — not `nemo-stt-cpu`. A
default `docker compose up` therefore starts `nemo-stt`, which loads the NeMo model
**resident on the GPU (~2.4 GB, keep-forever)** even though the shipped default
(`STT_FORCE_CPU=1`) routes every session to `nemo-stt-cpu`. The 2.4 GB the placement
math assumes is freed by CPU-STT (`STT_GPU_MB=2400` in `agent/placement.py:49`) is still
consumed by the always-on GPU service. The `service_healthy`→`service_started`
relaxation is correct and the WS connect-retry readiness story is sound, but without a
`profiles`/explicit-up gate the GPU STT service should not be brought up in a CPU-default
deploy. Recommend `profiles: ["stt-gpu"]` on `nemo-stt` (and/or `["stt-cpu"]` on
`nemo-stt-cpu`) and document the operator selecting the cell, so the default deploy
realizes the VRAM it is designed to save.

---

## Low

### L1 — Dispatch test gives false confidence; it cannot catch C1
`stt/test_dispatch.py:46-71` stubs `backend_onnx` into `sys.modules` before importing
`server`, so the real `backend_onnx`→`backend_nemo` import (C1) is never exercised. The
test proves the WS framing round-trips against a stub but asserts nothing about the real
backend importing cleanly without `STT_MODEL`. Consider an additional sandbox check that
imports the *real* `backend_onnx` with only `STT_ONNX_MODEL` set and asserts it does not
SystemExit (it would fail today — and should, until C1 is fixed).

### L2 — Dead/unused state in `backend_onnx`
`SAMPLE_RATE` is imported (L37) but never used in the module. `state["prev_text"]` is
written (L131, L190, L268) but never read — the cumulative string is recomputed from
`emitted_token_ids` each time. Harmless, but trim to reduce parity-surface confusion.

### L3 — `resolve_stt_placement(llm_choice, …)` ignores `llm_choice` (by design — note only)
`agent/placement.py:80-94` never uses `llm_choice`; the decision keys off
`max(LLM_PEAK_MB)` (the worst-case-LLM no-thrash lock, STT-06). This is correct and
deliberate and the docstring says so, but the unused parameter can read as a bug to a
future maintainer. Optionally keep the signature (it documents the call site's intent)
but add an explicit one-line note at the use site, or accept as-is.

---

## Invariants verified (no violation)

- **placement.py logic** — `STT_FORCE_CPU` short-circuits FIRST (L87-88), before the
  `STT_HEADROOM_MEASURED` gate (L90-91) and the headroom math (L94); identical decision
  for fast/better (worst-case lock, verified by `tests/test_placement.py:61-68` and the
  full matrix at L107-114); defaults `"cpu"` when unmeasured; never raises on garbage
  choice/env; truthy normalization (strip/lower) correct. Headroom math correct:
  `max(7408,8912)+2048+2400 = 13360 ≤ 15360` ceiling.
- **resolve-once** — read exactly once in `build_session` (`agent/main.py:210`); the
  `model.update` handler (`agent/main.py:550-564`) is byte-unchanged and never re-consults
  placement.
- **agent/metrics.py** — not in the diff (`git diff --stat` confirms).
- **Phase-9 WS contract** — `server.py` WS/HTTP layer diffs only docstrings + the
  `backend.*(_model, …)` indirection; ready/delta/final/error, /health 503-until-ready,
  flush-only-FINAL with per-turn `reset_turn_state`, and the stall watchdog (which logs,
  never emits FINAL) are intact in both backends.
- **No hardcoded model tag** — `rg` finds `nvidia/nemotron…` only in `docker-compose.yml`
  (build.args/environment) and `.env.example`; no tag literal in any backend/server/
  Dockerfile.cpu body or in `agent/*`.
- **Dispatch validation** — `STT_RUNTIME not in ("gpu","cpu")` → SystemExit
  (`server.py:59-60`); backend imports lazy (py_compile passes without NeMo/ORT, verified).
- **Healthchecks** — python-urllib, not curl, in both `Dockerfile.cpu:60-61` and the
  `nemo-stt-cpu` compose service (`docker-compose.yml:178-183`).
- **Security** — no secrets logged; `nemo-stt-cpu` carries no `env_file`/LiveKit secret;
  host port LAN-bound via `${LAN_BIND_IP:-127.0.0.1}:8001:8000`; `vram-validate.sh`
  `--stt-runtime` is validated against `gpu|cpu` (`parse_args` L225-229) and is never
  interpolated into a command string (no injection); WS bad-frame/JSON guards
  (`server.py:155-165`) unchanged from Phase 9.
- **Function limits** — all reviewed functions ≤40 lines, ≤3 params, ≤3 nesting
  (`_greedy_rnnt` is exactly 3 levels: for/for/if).

## Sandbox evidence
```
py_compile (all 7 py files) ............ OK
agent/placement.py _self_check ......... OK
tests/test_placement.py ................ OK (full force×measured×choice matrix)
stt/test_dispatch.py ................... OK (ready→delta→final→error)  [masks C1]
bash -n scripts/vram-validate.sh ....... OK
repro: import backend_onnx w/o STT_MODEL  SystemExit (C1)
```
