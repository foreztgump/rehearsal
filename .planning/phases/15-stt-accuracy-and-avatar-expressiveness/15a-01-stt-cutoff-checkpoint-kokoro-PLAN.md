---
plan: 15a-01
title: STT trailing-word cut-off fix (diagnose + two flag-gated candidates + ONNX parity), post-2026-03-12 Nemotron checkpoint pin, and the free Kokoro VRAM knob + STACK.md correction
phase: 15
sub_phase: 15a
wave: 1
depends_on: []
source: .planning/phases/15-stt-accuracy-and-avatar-expressiveness/15a-DESIGN.md
addresses: 15-BACKLOG.md items 1 (reframed) + 2 + Kokoro-VRAM
autonomous: false
files_modified:
  - stt/backend_common.py
  - stt/backend_nemo.py
  - stt/backend_onnx.py
  - stt/Dockerfile
  - docker-compose.yml
  - .env.example
  - .planning/research/STACK.md
  - .planning/research/PITFALLS.md
  - tests/test_finalize_pad.py
---

# STT Cut-off Fix + Checkpoint Pin + Kokoro VRAM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the trailing-word cut-off on the GPU NeMo STT path (two independently-toggleable, GPU-measured candidate fixes plus a CPU-ONNX parity mirror), pin the running Nemotron weights to the post-2026-03-12 checkpoint so they can never drift, and reclaim the one free Kokoro VRAM knob — while correcting the STACK.md Kokoro estimate.

**Architecture:** The STT service (`stt/`) exposes a frozen four-callable backend seam (`load_model` / `new_stream_state` / `decode_chunk` / `finalize` / `reset_turn_state`) behind a FastAPI websocket; `STT_RUNTIME` selects `backend_nemo` (GPU) or `backend_onnx` (CPU). Item 1 changes live entirely inside that seam: a shared `_stream_step` decode core is factored out so a trailing-silence drain can reuse it without tripping the stall watchdog, and each candidate fix ships **behind an env flag defaulting OFF** so committing it is a no-op until the operator enables and measures it on the GPU box. Item 2a pins the baked weights via `huggingface_hub` revision + offline cache (NeMo's `from_pretrained` has no documented revision arg). Item 3 is a one-line Compose env addition plus a docs correction.

**Tech Stack:** Python 3 (NeMo `conformer_stream_step` cache-aware streaming, onnxruntime CPU port), FastAPI/uvicorn, Docker Compose (6 GPU services), `huggingface_hub`, Kokoro-FastAPI (PyTorch/CUDA 12.8).

## Global Constraints

- **Local-first (hard):** no audio/transcript/KB leaves the LAN; no cloud inference endpoints. — copied from CLAUDE.md.
- **Latency is the design driver:** voice-to-voice **P50 < 1.0s** / **P95 < 1.5s**; never add blocking work to the per-turn hot path without measuring TTFT; named latency budgets (EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms) are constants, never inline numbers. — CLAUDE.md.
- **No magic values:** literals must be named constants (exempt `0`, `1`, `True`, `False`, `''`). Stall/latency thresholds and the new pad/flag knobs are named constants in `backend_common.py`. — CODE_PRINCIPLES §2.
- **Function shape:** ≤40 lines, ≤3 params, ≤3 nesting levels. — CODE_PRINCIPLES §3.
- **No duplication >5 similar lines** — the trailing-silence drain reuses the extracted `_stream_step` core, never a copy of `decode_chunk`. — CODE_PRINCIPLES §6.
- **Heavy imports stay inside functions** so every `stt/` module byte-compiles in the GPU-less / ORT-less sandbox (the real decode is an operator GPU gate). — established `stt/` invariant.
- **No-hardcoded-tag invariant:** the model tag/revision literal lives ONLY in `docker-compose.yml` build.args/environment; server/Dockerfile carry it via env/ARG. — AGENTS.md / existing `stt/` pattern.
- **Single STT contract is frozen:** the WS `ready`/`delta`/`final`/`error` shape and `/health` gate are byte-unchanged; only the *inside* of the backend callables changes. — `stt/server.py` docstring.

## Scope split (from the design's verification matrix — read before starting)

| Work | Sandbox-doable now | GPU / operator-gated |
|---|---|---|
| Task 1 — diagnosis instrumentation | code edit + py_compile | **operator runs the dump on the GPU box** |
| Task 2 — extract `_stream_step` (refactor) | code edit + py_compile | (no behavior change) |
| Task 3 — candidate A: thread `previous_pred_out` | code edit + py_compile | **enable flag, measure tail + WER on GPU** |
| Task 4 — candidate B: trailing-silence drain | code edit + unit test | **enable flag, measure tail + WER on GPU** |
| Task 5 — candidate B: ONNX parity | code edit + py_compile | measure (CPU path, secondary) |
| Task 6 — checkpoint revision pin | env/compose/Dockerfile + `compose config` | **SHA lookup + rebuild + snapshot-match verify** |
| Task 7 — Kokoro `expandable_segments` + STACK fix | compose/docs + `compose config` | `nvidia-smi` before/after re-measure |
| Task 8 — accuracy re-measure / accept gate | — | **live voice pass; operator's accept decision** |

**The candidate fixes (Tasks 3, 4, 5) ship behind flags defaulting OFF.** Committing them changes nothing until the operator flips the flag on the GPU box. Item 1's root cause is a *diagnosis*, not a known fix (15a-DESIGN §"Risks") — the flags exist precisely so the operator can A/B them live without reverting code.

---

### Task 1: Diagnosis instrumentation (env-gated drain logging + encoder config dump)

The design forbids guessing the API: confirm the root cause on the GPU box by dumping `prev_hyps` text/token-count at `finalize` and the encoder's `att_context_style` / `streaming_cfg` at load, **before** judging any candidate. Implemented as an env-gated `logger.info` that is harmless to leave in (default OFF).

**Files:**
- Modify: `stt/backend_common.py` (add `STT_DEBUG_DRAIN` flag constant)
- Modify: `stt/backend_nemo.py` (`load_model` dump; `finalize` drain log)

**Interfaces:**
- Produces: `backend_common.DEBUG_DRAIN: bool` — imported by both backends; gates all diagnosis logging.

- [ ] **Step 1: Add the debug flag constant to `backend_common.py`**

Append after the stall-watchdog block (after line 34, the `RECYCLE_HARD_CHARS` line):

```python
# Diagnosis switch for the Item-1 trailing-word cut-off (15a). When truthy, both
# backends log the drained transcript + held-token count at finalize and the encoder
# streaming config at load, so the operator can confirm the cut-off's root cause on
# the GPU box WITHOUT guessing the API. Default OFF — pure no-op in production.
DEBUG_DRAIN = os.environ.get("STT_DEBUG_DRAIN", "0") == "1"
```

- [ ] **Step 2: Import the flag in `backend_nemo.py`**

In the `from backend_common import (...)` block (lines 33-39), add `DEBUG_DRAIN,` to the imported names (keep alphabetical-ish with the rest):

```python
from backend_common import (
    DEBUG_DRAIN,
    INT16_FULL_SCALE,
    RECYCLE_HARD_CHARS,
    RECYCLE_MIN_CHARS,
    SAMPLE_RATE,
    STALL_FRAMES,
)
```

- [ ] **Step 3: Dump the encoder streaming config at load**

In `load_model` (`backend_nemo.py`), immediately after the existing `logger.info("nemo-stt model loaded: ...")` line (line 103) and before `return model`:

```python
    if DEBUG_DRAIN:
        logger.info(
            "nemo-stt diag: att_context_style=%s streaming_cfg=%s",
            getattr(model.encoder, "att_context_style", "?"),
            getattr(model.encoder, "streaming_cfg", "?"),
        )
```

- [ ] **Step 4: Log the drained tail at finalize**

In `finalize` (`backend_nemo.py:195-200`), after computing `cumulative` and before `return cumulative`:

```python
    if DEBUG_DRAIN:
        held = state["prev_hyps"][0] if state["prev_hyps"] else None
        token_count = len(getattr(held, "y_sequence", []) or []) if held else 0
        logger.info("nemo-stt diag finalize: text=%r held_tokens=%d", cumulative, token_count)
```

- [ ] **Step 5: Sandbox gate — byte-compile both modules**

Run: `python -m py_compile stt/backend_common.py stt/backend_nemo.py`
Expected: exit 0, no output (the GPU-less sandbox cannot import NeMo; py_compile only compiles).

- [ ] **Step 6: OPERATOR GPU GATE — run the diagnosis**

On the GPU box, bring up the GPU STT and drive a **fixed utterance that ends mid-word**:
```bash
STT_DEBUG_DRAIN=1 docker compose --profile stt-gpu up nemo-stt
```
Confirm in the logs: (a) `att_context_style == "chunked_limited"` and `streaming_cfg` shows the trained `[70,N]` pair; (b) the `diag finalize` line shows whether the held tail is present *before* `finalize` returns. Also confirm the `"nemo-stt RNNT stall recycle…"` log is **not** firing right at the turn boundary (design candidate #3 — stall clearing the tail). Record findings in `15a-VERIFY.md`.

- [ ] **Step 7: Commit**

```bash
git add stt/backend_common.py stt/backend_nemo.py
git commit -m "feat(stt): env-gated drain diagnosis logging for trailing-word cut-off (15a Item 1)"
```

---

### Task 2: Refactor — extract the shared `_stream_step` decode core (no behavior change)

The trailing-silence drain (Task 4) needs the conformer step **without** the stall watchdog (a mid-finalize recycle would clear the very tail it is recovering). Factor the decode core out of `decode_chunk` so both the live path and the drain reuse it. Pure refactor — output is byte-identical.

**Files:**
- Modify: `stt/backend_nemo.py` (`decode_chunk` 144-175 → `_stream_step` + thin `decode_chunk`)

**Interfaces:**
- Produces: `_stream_step(model, state, pcm) -> str` — advances `cache_last_*` + `prev_hyps`, returns the cumulative transcript; does NOT run the stall watchdog. Consumed by `decode_chunk` (Task 2) and `finalize` (Task 4).

- [ ] **Step 1: Replace `decode_chunk` (lines 144-175) with the helper + a thin caller**

Replace the entire current `decode_chunk` function body (lines 144-175) with:

```python
def _stream_step(model, state, pcm) -> str:
    """One cache-aware conformer_stream_step: advance caches + prev_hyps, return cumulative.

    Shared decode core for the live per-chunk path (decode_chunk, which adds the stall
    watchdog) AND the trailing-silence drain (finalize, candidate B). Kept separate from
    _track_stall so the drain can NEVER trigger a mid-finalize recycle that would clear
    the tail it is trying to recover. Native PnC surfaced AS-IS (no strip/lowercase).
    """
    import torch  # noqa: PLC0415 - GPU-only dep

    feats, feat_len = _extract_features(model, pcm)
    with torch.inference_mode():
        # 6-tuple: greedy_predictions, transcribed_texts, cache_last_channel_next,
        # cache_last_time_next, cache_last_channel_next_len, best_hyp (the RNNT
        # Hypothesis list carrying .text, fed back as previous_hypotheses).
        out = model.conformer_stream_step(
            processed_signal=feats,
            processed_signal_length=feat_len,
            cache_last_channel=state["cache_last_channel"],
            cache_last_time=state["cache_last_time"],
            cache_last_channel_len=state["cache_last_channel_len"],
            keep_all_outputs=True,
            previous_hypotheses=state["prev_hyps"],
            return_transcription=True,
        )
    state["cache_last_channel"] = out[2]
    state["cache_last_time"] = out[3]
    state["cache_last_channel_len"] = out[4]
    state["prev_hyps"] = out[5]
    return out[5][0].text if out[5] else ""


def decode_chunk(model, state, pcm) -> str:
    """Run one stream step; return the CUMULATIVE transcript and run the stall watchdog.

    Recycles decoder state on a stall but NEVER emits FINAL (the turn detector owns
    finalize).
    """
    cumulative = _stream_step(model, state, pcm)
    _track_stall(state, cumulative)
    return cumulative
```

- [ ] **Step 2: Sandbox gate — byte-compile**

Run: `python -m py_compile stt/backend_nemo.py`
Expected: exit 0, no output.

- [ ] **Step 3: Sandbox gate — confirm the offline decode path still wires up**

Run: `python -m py_compile stt/server.py`
Expected: exit 0 (server's `_transcribe_wav` calls `backend.decode_chunk` + `backend.finalize` — signatures unchanged).

- [ ] **Step 4: Commit**

```bash
git add stt/backend_nemo.py
git commit -m "refactor(stt): extract _stream_step decode core from decode_chunk (no behavior change, 15a)"
```

---

### Task 3: Candidate A — thread `previous_pred_out` for RNNT decode continuity (flag-gated, default OFF)

NeMo's reference streaming loop threads `previous_pred_out=pred_out_stream` back into each `conformer_stream_step`; the current code omits it. Candidate A (design's highest-confidence/lowest-risk) adds it behind `STT_THREAD_PRED_OUT` (default OFF). **The effect MUST be GPU-measured** — the flag default-OFF keeps the commit a no-op until the operator enables it.

**Files:**
- Modify: `stt/backend_common.py` (add `THREAD_PRED_OUT` flag)
- Modify: `stt/backend_nemo.py` (`new_stream_state`, `_stream_step`, `_track_stall` recycle, `reset_turn_state`)

**Interfaces:**
- Consumes: `_stream_step` (Task 2).
- Produces: `backend_common.THREAD_PRED_OUT: bool`; new state key `prev_pred_out`.

- [ ] **Step 1: Add the flag constant to `backend_common.py`**

Append after the `DEBUG_DRAIN` line from Task 1:

```python
# Item-1 candidate A (15a): thread previous_pred_out back into conformer_stream_step
# for RNNT decode continuity, matching NeMo's reference streaming loop (the current
# decode omits it). Default OFF — GPU-measured before it becomes default; likely the
# permanent default once the GPU gate confirms it restores the tail with no WER regress.
THREAD_PRED_OUT = os.environ.get("STT_THREAD_PRED_OUT", "0") == "1"
```

- [ ] **Step 2: Import the flag in `backend_nemo.py`**

Add `THREAD_PRED_OUT,` to the `from backend_common import (...)` block:

```python
from backend_common import (
    DEBUG_DRAIN,
    INT16_FULL_SCALE,
    RECYCLE_HARD_CHARS,
    RECYCLE_MIN_CHARS,
    SAMPLE_RATE,
    STALL_FRAMES,
    THREAD_PRED_OUT,
)
```

- [ ] **Step 3: Seed `prev_pred_out` in `new_stream_state`**

In `new_stream_state` (`backend_nemo.py:118-128`), add the key to the returned dict (after `"prev_hyps": None,`):

```python
        "prev_hyps": None,
        "prev_pred_out": None,
        "frames_since_growth": 0,
        "last_text_len": 0,
```

- [ ] **Step 4: Thread it through `_stream_step`**

In `_stream_step` (from Task 2), add the `previous_pred_out` kwarg to the `conformer_stream_step(...)` call (after `previous_hypotheses=state["prev_hyps"],`):

```python
            previous_hypotheses=state["prev_hyps"],
            previous_pred_out=state.get("prev_pred_out") if THREAD_PRED_OUT else None,
            return_transcription=True,
```

Then, after `state["prev_hyps"] = out[5]` and before the `return`, store the returned greedy predictions:

```python
    state["prev_hyps"] = out[5]
    if THREAD_PRED_OUT:
        state["prev_pred_out"] = out[0]
    return out[5][0].text if out[5] else ""
```

- [ ] **Step 5: Reset `prev_pred_out` wherever `prev_hyps` is reset**

In `_track_stall` (`backend_nemo.py:178-192`), in the stall-recycle branch, beside `state["prev_hyps"] = None`:

```python
        state["prev_hyps"] = None
        state["prev_pred_out"] = None
        state["frames_since_growth"] = 0
```

In `reset_turn_state` (`backend_nemo.py:203-213`), beside `state["prev_hyps"] = None`:

```python
    state["prev_hyps"] = None
    state["prev_pred_out"] = None
    state["frames_since_growth"] = 0
    state["last_text_len"] = 0
```

- [ ] **Step 6: Sandbox gate — byte-compile**

Run: `python -m py_compile stt/backend_common.py stt/backend_nemo.py`
Expected: exit 0, no output.

- [ ] **Step 7: OPERATOR GPU GATE — enable and measure**

```bash
STT_THREAD_PRED_OUT=1 STT_DEBUG_DRAIN=1 docker compose --profile stt-gpu up nemo-stt
```
On the fixed mid-word utterance, confirm the trailing word(s) now finalize **and** run a short WER check vs the Task-1 baseline (no regression). If candidate A alone restores the tail with no WER regression → **keep `STT_THREAD_PRED_OUT=1`, record in `15a-VERIFY.md`, and you may SKIP Task 4**. If insufficient, leave the flag OFF and proceed to Task 4. Record the decision.

- [ ] **Step 8: Commit**

```bash
git add stt/backend_common.py stt/backend_nemo.py
git commit -m "feat(stt): candidate A — flag-gated previous_pred_out RNNT continuity (15a Item 1, default OFF)"
```

---

### Task 4: Candidate B — trailing-silence drain on finalize (flag-gated, default OFF)

At the hard end-of-speech cutoff the last right-context frames lack the future frames they were trained with, so the RNNT may emit blanks for the final ~480ms. Candidate B feeds one last `_stream_step` of **trailing zero PCM** on `finalize` so those frames get a complete attention window. Behind `STT_FINALIZE_PAD` (default OFF). **Unofficial workaround — gate on a no-WER-regression check** (design caveat).

**Files:**
- Modify: `stt/backend_common.py` (add `FINALIZE_PAD` flag, `FINALIZE_PAD_MS` constant, `finalize_pad_pcm()` helper)
- Modify: `stt/backend_nemo.py` (`finalize` uses the drain when enabled)
- Create: `tests/test_finalize_pad.py` (sandbox unit test for the pad-bytes math)

**Interfaces:**
- Consumes: `_stream_step` (Task 2), `SAMPLE_RATE` (existing in `backend_common`).
- Produces: `backend_common.FINALIZE_PAD: bool`, `FINALIZE_PAD_MS: int`, `finalize_pad_pcm() -> bytes`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_finalize_pad.py`:

```python
"""Sandbox unit test for the Item-1 candidate-B trailing-silence drain math (15a).

Pure-fn, GPU-less: backend_common reads only optional/defaulted env (no STT_MODEL),
so it imports cleanly in the sandbox. Follows the repo's sys.path + __main__ assert
harness convention (tests/test_placement.py, stt/test_dispatch.py).

Run: ``python3 tests/test_finalize_pad.py`` or ``python3 -m pytest tests/test_finalize_pad.py``.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stt"))

import backend_common  # noqa: E402


def test_finalize_pad_pcm_is_silence_of_the_configured_duration():
    # Arrange: 640 ms default at 16 kHz mono int16 = 16000 * 0.640 * 2 bytes.
    expected_samples = backend_common.SAMPLE_RATE * backend_common.FINALIZE_PAD_MS // 1000
    expected_bytes = expected_samples * 2

    # Act
    pcm = backend_common.finalize_pad_pcm()

    # Assert: correct length AND all-zero (true silence, not garbage).
    assert len(pcm) == expected_bytes, (len(pcm), expected_bytes)
    assert pcm == b"\x00" * expected_bytes


if __name__ == "__main__":
    test_finalize_pad_pcm_is_silence_of_the_configured_duration()
    print("ok: finalize_pad_pcm")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_finalize_pad.py`
Expected: FAIL with `AttributeError: module 'backend_common' has no attribute 'finalize_pad_pcm'`.

- [ ] **Step 3: Add the constant + helper to `backend_common.py`**

Append after the `THREAD_PRED_OUT` line from Task 3:

```python
# Item-1 candidate B (15a): trailing-silence drain. On finalize, optionally feed one
# last stream step of silence so the final real speech frames get a complete right-
# context attention window — the hard end-of-speech cutoff otherwise leaves the
# trailing right-context frames without the future frames they were trained with, so
# the RNNT can emit blanks for the last words. Default OFF (GPU-measured, unofficial
# workaround). FINALIZE_PAD_MS is generous on purpose: it covers up to a [70,6] right
# context (6 encoder frames x 80 ms = 480 ms) plus preprocessor/8x-subsampling edge,
# regardless of the configured att_context_size (shipped default is [70,1] = 80 ms).
FINALIZE_PAD = os.environ.get("STT_FINALIZE_PAD", "0") == "1"
FINALIZE_PAD_MS = int(os.environ.get("STT_FINALIZE_PAD_MS", "640"))


def finalize_pad_pcm() -> bytes:
    """Zero int16 mono PCM of FINALIZE_PAD_MS at SAMPLE_RATE — the trailing-silence drain frame."""
    return b"\x00\x00" * (SAMPLE_RATE * FINALIZE_PAD_MS // 1000)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_finalize_pad.py`
Expected: `ok: finalize_pad_pcm`

- [ ] **Step 5: Wire the drain into `backend_nemo.finalize`**

Add the imports to the `from backend_common import (...)` block in `backend_nemo.py`:

```python
from backend_common import (
    DEBUG_DRAIN,
    FINALIZE_PAD,
    INT16_FULL_SCALE,
    RECYCLE_HARD_CHARS,
    RECYCLE_MIN_CHARS,
    SAMPLE_RATE,
    STALL_FRAMES,
    THREAD_PRED_OUT,
    finalize_pad_pcm,
)
```

Replace `finalize` (`backend_nemo.py:195-200`, including the Task-1 diag block) with:

```python
def finalize(model, state) -> str:
    """Drain the stream and return the final transcript (flush→final response).

    Candidate B (15a, flag-gated): when STT_FINALIZE_PAD=1, feed one last stream step
    of trailing silence so the final right-context frames get a complete attention
    window before reading the tail. Uses _stream_step (NOT decode_chunk) so the stall
    watchdog never recycles the tail mid-drain. Advancing the cache here is harmless —
    the server calls reset_turn_state immediately after finalize.
    """
    if FINALIZE_PAD and state["prev_hyps"] is not None:
        cumulative = _stream_step(model, state, finalize_pad_pcm())
    else:
        cumulative = state["prev_hyps"][0].text if state["prev_hyps"] else ""
    if DEBUG_DRAIN:
        held = state["prev_hyps"][0] if state["prev_hyps"] else None
        token_count = len(getattr(held, "y_sequence", []) or []) if held else 0
        logger.info("nemo-stt diag finalize: text=%r held_tokens=%d", cumulative, token_count)
    return cumulative
```

- [ ] **Step 6: Sandbox gate — byte-compile + re-run unit test**

Run: `python -m py_compile stt/backend_common.py stt/backend_nemo.py && python3 tests/test_finalize_pad.py`
Expected: exit 0 then `ok: finalize_pad_pcm`.

- [ ] **Step 7: OPERATOR GPU GATE — enable and measure**

```bash
STT_FINALIZE_PAD=1 STT_DEBUG_DRAIN=1 docker compose --profile stt-gpu up nemo-stt
```
On the fixed mid-word utterance confirm the trailing word(s) return **and** WER does not regress vs baseline. Also check the interaction with the framework's end-of-speech silence (`server.py` autonomous endpoint) — the drain must not double-emit or strand a final. `STT_FINALIZE_PAD_MS` is tunable (480–640) if the tail is partially recovered. Keep whichever of A/B (or both) restores the tail cleanly; leave the rest OFF. Record in `15a-VERIFY.md`.

- [ ] **Step 8: Commit**

```bash
git add stt/backend_common.py stt/backend_nemo.py tests/test_finalize_pad.py
git commit -m "feat(stt): candidate B — flag-gated trailing-silence finalize drain (15a Item 1, default OFF)"
```

---

### Task 5: Candidate B — CPU/ONNX parity (flag-shared, default OFF)

The CPU backend has its own `finalize` (`backend_onnx.py:324`) with a separate three-graph decode. The user's complaint is on the GPU path (fixed first), but the design requires checking ONNX for the same symptom and applying the analogous drain. Mirror candidate B behind the **same** `STT_FINALIZE_PAD` flag, reusing the same `finalize_pad_pcm()`. (Candidate A has no ONNX analog — the ONNX loop already threads `dec_state` forward for decode continuity.)

**Files:**
- Modify: `stt/backend_onnx.py` (extract `_encode_decode_step`; `finalize` drains when enabled)

**Interfaces:**
- Consumes: `finalize_pad_pcm`, `FINALIZE_PAD` (Task 4), existing `_extract_features` / `_greedy_rnnt`.
- Produces: `_encode_decode_step(model, state, pcm) -> str` — ONNX analog of `_stream_step`.

- [ ] **Step 1: Import the shared flag + helper in `backend_onnx.py`**

In the `from backend_common import (...)` block (lines 36-40), add:

```python
from backend_common import (
    FINALIZE_PAD,
    INT16_FULL_SCALE,
    RECYCLE_MIN_CHARS,
    STALL_FRAMES,
    finalize_pad_pcm,
)
```

- [ ] **Step 2: Extract `_encode_decode_step` from `decode_chunk`**

Replace `decode_chunk` (`backend_onnx.py:229-259`) — the body from `mel = _extract_features(...)` through `return text` — with a helper plus a thin caller. The helper is the encoder-run + cache-carry + greedy-RNNT + detokenize, **without** `_track_stall`:

```python
def _encode_decode_step(model, state, pcm) -> str:
    """One encoder step + greedy RNNT loop → cumulative transcript (ONNX analog of
    backend_nemo._stream_step). Advances the encoder cache + dec_state + emitted ids;
    does NOT run the stall watchdog, so the trailing-silence drain (finalize) can reuse
    it without recycling the tail. Native PnC surfaced AS-IS.
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    mel = _extract_features(model, pcm)
    length = np.array([mel.shape[2]], dtype=np.int64)
    enc = model["encoder"].run(None, {
        "audio_signal": mel,
        "length": length,
        "cache_last_channel": state["cache_last_channel"],
        "cache_last_time": state["cache_last_time"],
        "cache_last_channel_len": state["cache_last_channel_len"],
    })
    enc_out = enc[0]
    state["cache_last_channel"] = enc[2]
    state["cache_last_time"] = enc[3]
    state["cache_last_channel_len"] = enc[4]
    _greedy_rnnt(model, state, enc_out)
    return model["tokenizer"].decode(state["emitted_token_ids"])


def decode_chunk(model, state, pcm) -> str:
    """Run one encoder + greedy RNNT step; return the CUMULATIVE transcript + stall watch.

    Recycles decoder state on a stall but NEVER emits FINAL (the turn detector owns
    finalize).
    """
    text = _encode_decode_step(model, state, pcm)
    _track_stall(state, text)
    return text
```

> Note: this preserves the existing decode logic verbatim — the only changes are the function boundary and dropping the now-inlined comments (kept in the new docstrings). Leave `_greedy_rnnt`, `_decode_step`, `_track_stall`, `reset_turn_state` unchanged.

- [ ] **Step 3: Wire the drain into `backend_onnx.finalize`**

Replace `finalize` (`backend_onnx.py:324-326`) with:

```python
def finalize(model, state) -> str:
    """Drain the stream and return the final transcript (flush→final response).

    Candidate-B parity (15a, same STT_FINALIZE_PAD flag as backend_nemo): when enabled,
    feed one last encode/decode step of trailing silence so the final encoder frames get
    a complete window before reading the tail. Uses _encode_decode_step (NOT decode_chunk)
    so the stall watchdog never recycles the tail mid-drain.
    """
    if FINALIZE_PAD and state["emitted_token_ids"]:
        return _encode_decode_step(model, state, finalize_pad_pcm())
    return model["tokenizer"].decode(state["emitted_token_ids"]) if state["emitted_token_ids"] else ""
```

- [ ] **Step 4: Sandbox gate — byte-compile**

Run: `python -m py_compile stt/backend_onnx.py`
Expected: exit 0, no output (the sandbox cannot import onnxruntime; py_compile only compiles).

- [ ] **Step 5: OPERATOR GATE — measure on the CPU path (secondary)**

With the default CPU service: `STT_FINALIZE_PAD=1 docker compose up nemo-stt-cpu`. Confirm the same mid-word tail behavior + no WER regression on the ONNX path. Record in `15a-VERIFY.md`.

- [ ] **Step 6: Commit**

```bash
git add stt/backend_onnx.py
git commit -m "feat(stt): candidate B ONNX parity — flag-shared trailing-silence drain (15a Item 1)"
```

---

### Task 6: Item 2a — pin the post-2026-03-12 Nemotron checkpoint (revision, not model swap)

`STT_MODEL` is not revision-pinned: `stt/Dockerfile:32` bakes whatever was on HF `main` at build time. NeMo's `from_pretrained` has **no documented `revision` argument** (verified via NeMo docs), so pin deterministically with `huggingface_hub.snapshot_download(revision=...)` (stable, documented) into the image's HF cache, then bake offline so the loaded weights can't re-resolve to a newer `main`. The actual March-2026 SHA + the rebuild + the snapshot-match check are operator steps.

**Files:**
- Modify: `.env.example` (add `STT_MODEL_REVISION`)
- Modify: `docker-compose.yml` (both STT services' `build.args`; `nemo-stt` `environment`)
- Modify: `stt/Dockerfile` (ARG + pinned bake + offline runtime)

**Interfaces:**
- Produces: `STT_MODEL_REVISION` env/ARG threaded env → compose → Dockerfile (default `main` = current behavior).

- [ ] **Step 1: Add `STT_MODEL_REVISION` to `.env.example`**

Immediately after the `STT_MODEL=...` line (`.env.example:58`), insert:

```bash
# Revision pin for the baked STT weights (15a Item 2a). The Jan-2026 checkpoint is
# weaker and now lives on branch `nemotron-speech-streaming-jan2026`; `main` is the
# re-trained post-2026-03-12 checkpoint. STT_MODEL is NOT revision-pinned by NeMo's
# from_pretrained (no revision arg), so the bake snapshot-downloads THIS commit and
# the runtime loads offline — weights can never drift. Default `main` = current
# behavior. OPERATOR: read the March-2026 commit SHA from the HF model-card history
# and pin it here, then rebuild and confirm the printed "baked snapshot commit" matches.
STT_MODEL_REVISION=main
```

- [ ] **Step 2: Thread the ARG into both STT services in `docker-compose.yml`**

In `nemo-stt` `build.args` (after `docker-compose.yml:120`, the `STT_MODEL:` line):

```yaml
        STT_MODEL: ${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
        STT_MODEL_REVISION: ${STT_MODEL_REVISION:-main}
```

In `nemo-stt` `environment` (after `docker-compose.yml:136`, the `STT_MODEL=` line) — keep runtime/bake symmetric:

```yaml
      - STT_MODEL=${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
      - STT_MODEL_REVISION=${STT_MODEL_REVISION:-main}
```

In `nemo-stt-cpu` `build.args` (after `docker-compose.yml:188`, the `STT_MODEL:` line — the CPU export builder loads the same source `.nemo`, so pin its source too):

```yaml
        STT_MODEL: ${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
        STT_MODEL_REVISION: ${STT_MODEL_REVISION:-main}
```

- [ ] **Step 3: Pin the bake in `stt/Dockerfile`**

After the existing `ARG STT_MODEL` (line 17), add:

```dockerfile
# Revision pin (15a Item 2a). Default main = prior behavior; operator pins the
# March-2026 commit SHA via STT_MODEL_REVISION so the baked weights never drift.
ARG STT_MODEL_REVISION=main
```

Replace the bake line (`stt/Dockerfile:32`) with a pinned snapshot download (prints the resolved commit for the operator's snapshot-match check) followed by an OFFLINE bake so `from_pretrained` cannot re-resolve `main`:

```dockerfile
# Snapshot-download the EXACT pinned commit into the HF cache (huggingface_hub has a
# documented `revision` arg; NeMo's from_pretrained does not), printing the resolved
# commit so the operator can confirm the baked snapshot matches the intended SHA.
RUN python -c "from huggingface_hub import snapshot_download; p=snapshot_download(repo_id='${STT_MODEL}', revision='${STT_MODEL_REVISION}'); print('baked snapshot commit dir:', p)"
# Bake the .nemo from the pinned cache. HF_HUB_OFFLINE forces resolution from the cache
# populated above instead of re-fetching `main`, so the baked weights == the pinned commit.
RUN HF_HUB_OFFLINE=1 python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"
```

After the existing `ENV STT_MODEL=${STT_MODEL}` (line 35), add the runtime offline pin + the revision env:

```dockerfile
ENV STT_MODEL=${STT_MODEL}
ENV STT_MODEL_REVISION=${STT_MODEL_REVISION}
# Runtime loads ONLY from the baked, pinned cache — never re-resolves a newer main.
ENV HF_HUB_OFFLINE=1
```

- [ ] **Step 4: Sandbox gate — validate Compose still parses**

Run: `docker compose config -q`
Expected: exit 0, no output (validates the YAML + the new build.args/environment interpolation). If the compose plugin is unavailable in the sandbox, fall back to: `python -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml'))"` (expect exit 0).

- [ ] **Step 5: OPERATOR GATE — supply the SHA, rebuild, verify the snapshot matches**

Set `STT_MODEL_REVISION=<March-2026 SHA>` in `.env`, then:
```bash
docker compose --profile stt-gpu build nemo-stt
```
Confirm the build log's `baked snapshot commit dir:` path ends in the pinned SHA. **Fallback if `from_pretrained` mis-resolves offline** (NeMo version-dependent): switch the runtime load to `ASRModel.restore_from(hf_hub_download(repo_id=STT_MODEL, filename="<model>.nemo", revision=STT_MODEL_REVISION))` — documented, deterministic — and rebuild. Record the loaded commit in `15a-VERIFY.md`.

- [ ] **Step 6: Commit**

```bash
git add .env.example docker-compose.yml stt/Dockerfile
git commit -m "feat(stt): pin baked Nemotron weights to STT_MODEL_REVISION (15a Item 2a, default main)"
```

---

### Task 7: Item 3 — Kokoro `expandable_segments` + STACK.md / PITFALLS correction

Kokoro's ~5GB is almost all CUDA context + allocator reserve on the `cu128` image, not the ~0.33GB weights. The one free, zero-latency knob is `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (reclaims fragmentation). Correct the STACK.md estimate (~2.5GB → ~4–5GB on cu128) and cross-reference the per-process CUDA-context overhead PITFALLS C1 already anticipated.

**Files:**
- Modify: `docker-compose.yml` (`kokoro` service — add an `environment:` block)
- Modify: `.planning/research/STACK.md` (VRAM lines 183-184 + Part-E budget lines 303/307)
- Modify: `.planning/research/PITFALLS.md` (note the cross-reference under C1)

**Interfaces:**
- Produces: nothing code-facing; a Compose env addition + corrected docs.

- [ ] **Step 1: Add the `environment:` block to the `kokoro` service**

The `kokoro` service (`docker-compose.yml:214-232`) currently has no `environment:`. Insert it after the `image:` + its comment (between line 218's `image:` line and the existing `# No env_file (M3): ...` comment / `ports:`):

```yaml
    image: ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128
    # 15a Item 3: the one free, zero-latency VRAM knob. Kokoro's ~5GB observed footprint
    # is almost all CUDA context + PyTorch allocator reserve on cu128 (weights are
    # ~0.33GB). expandable_segments reclaims reserved fragmentation (~0.5–1GB, operator
    # to re-measure via nvidia-smi). No latency cost. See PITFALLS.md C1.
    environment:
      - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

- [ ] **Step 2: Sandbox gate — validate Compose still parses**

Run: `docker compose config -q`
Expected: exit 0 (fallback: the `yaml.safe_load` check from Task 6 Step 4).

- [ ] **Step 3: Correct the Kokoro VRAM estimate in `STACK.md`**

In `.planning/research/STACK.md`, replace the two co-residency lines (183-184):

```markdown
- Fast/E2B (3.4GB) + NeMo-GPU (~1.5GB) + Kokoro (~4–5GB on cu128) ≈ **9–10GB** → fits 16GB → **GPU STT** (was mis-estimated at ~2.5GB; the bulk is CUDA context + allocator reserve, not weights — see PITFALLS C1).
- Better/E4B (5.3GB) + NeMo-GPU (~1.5GB) + Kokoro (~4–5GB on cu128) ≈ **11–12GB** → tighter once KV cache grows → **this is the case Part C de-risks** by moving STT to CPU-ONNX.
```

And the Part-E budget lines (303 and 307) — change each `Kokoro (~2.5GB)` to `Kokoro (~4–5GB on cu128)` and re-sum:
- Line 303: `... + Kokoro (~4–5GB on cu128) → ~9–10GB, room for KV cache.`
- Line 307: `... + Kokoro (~4–5GB on cu128) → ~10–11GB VRAM, STT off-GPU.`

- [ ] **Step 4: Cross-reference under PITFALLS C1**

In `.planning/research/PITFALLS.md`, append to the Pitfall C1 body (after line 193, the existing paragraph):

```markdown

> **15a note:** the per-process CUDA-context overhead this pitfall flagged is the
> bulk of Kokoro's footprint — observed ~4–5GB on the cu128 image vs ~0.33GB weights.
> 15a Item 3 reclaims the reducible fragment via `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
> (zero latency); ~2.4–3GB context floor is irreducible and genuinely contends on the shared GPU.
```

- [ ] **Step 5: Sandbox gate — confirm the edits landed**

Run: `grep -n "expandable_segments" docker-compose.yml && grep -n "4–5GB on cu128" .planning/research/STACK.md && grep -n "15a note" .planning/research/PITFALLS.md`
Expected: at least one match per file.

- [ ] **Step 6: OPERATOR GATE — re-measure**

`nvidia-smi` Kokoro process VRAM before/after the env addition; record the reclaimed amount in `15a-VERIFY.md` (estimate ~0.5–1GB, unmeasured).

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .planning/research/STACK.md .planning/research/PITFALLS.md
git commit -m "feat(tts): Kokoro expandable_segments VRAM knob + correct STACK/PITFALLS estimate (15a Item 3)"
```

---

### Task 8: Item 2b + 2c — operator verification gates (no code)

Pure operator/GPU verification closing the design's Items 2b/2c. No sandbox work; record outcomes in `15a-VERIFY.md`.

**Files:** none (verification only).

- [ ] **Step 1: 2b — confirm the RNNT stall-recycle fires correctly**

During a live session (especially a long run-on interview answer), confirm the `"nemo-stt RNNT stall recycle…"` log appears when expected and is **not** firing so eagerly it truncates. Tune `STT_STALL_FRAMES` (`backend_common.py`, default 50) only if measurement shows misbehavior.

- [ ] **Step 2: 2c — re-measure accuracy, then decide**

After Tasks 1–6 (the kept Item-1 fix + the checkpoint pin), run a live voice pass and judge accuracy. **Default (user-stated): accept** — if acceptable, selectable accuracy-mode engines stay a v1.2 nicety (roadmap R3 / `15b-DESIGN.md`), not urgent. **Escalate only if still bad.** Record the accept/escalate decision in `15a-VERIFY.md`.

- [ ] **Step 3: Update the roadmap / docs**

Mark 15a complete in `.planning/ROADMAP.md` once the accept gate passes, noting which Item-1 flag(s) were kept (`STT_THREAD_PRED_OUT` / `STT_FINALIZE_PAD`) and the pinned `STT_MODEL_REVISION`. Per CLAUDE.md, also check `README.md` / `CHANGELOG.md` for any user-facing knob mention (the three new `STT_*` env flags).

---

## Self-Review

**1. Spec coverage (vs `15a-DESIGN.md`):**
- Item 1 candidate #1 (`previous_pred_out`) → Task 3. ✓
- Item 1 candidate #2 (trailing-zero flush) → Tasks 4 (NeMo) + 5 (ONNX parity). ✓
- Item 1 candidate #3 (stall `prev_hyps=None` interaction) → Task 1 Step 6 (diagnosis) + Task 8 Step 1 (2b). ✓
- Item 1 diagnosis procedure ("do NOT guess the API") → Task 1. ✓
- Item 1 ONNX parity (`backend_onnx:324`) → Task 5. ✓
- Item 2a checkpoint revision pin + docs → Task 6. ✓
- Item 2b stall-recycle confirmation → Task 8 Step 1. ✓
- Item 2c re-measure / accept gate → Task 8 Step 2. ✓
- Item 3 `expandable_segments` + STACK.md + PITFALLS C1 → Task 7. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N" — every code step shows the exact code; every verification step shows the exact command + expected output. ✓

**3. Type consistency:** `_stream_step(model, state, pcm) -> str` (Task 2) is consumed by `decode_chunk` (Task 2) and `finalize` (Task 4); `_encode_decode_step` is the ONNX analog (Task 5). `finalize_pad_pcm() -> bytes` defined Task 4, consumed Tasks 4/5. Flags `DEBUG_DRAIN` / `THREAD_PRED_OUT` / `FINALIZE_PAD` and constant `FINALIZE_PAD_MS` defined once in `backend_common.py`, imported by both backends. New state key `prev_pred_out` seeded in `new_stream_state`, reset in `_track_stall` recycle + `reset_turn_state`. ✓

**Notes for the executor:**
- **Discrepancy flagged:** the design's frame-math assumes `att_context_size=[70,6]` (480ms right context), but the shipped default is `[70,1]` (`.env.example:64`, Phase 14 snappiest). `FINALIZE_PAD_MS` defaults to 640 to cover up to [70,6] regardless — generous on purpose; tune down toward 80–120ms if running [70,1] and the drain over-pads.
- **Candidate A vs B are independent and both default OFF** — committing all tasks is a production no-op. The operator enables flags one at a time on the GPU box (Task 3 Step 7 / Task 4 Step 7) and keeps whichever restores the tail without WER regression. If A alone suffices, Tasks 4/5 stay dormant (flag OFF), not reverted.
- **Branch first:** this plan must not be executed on `master` (CLAUDE.md / superpowers). Create `phase-15a-stt-fixes` (or a worktree) before Task 1.
</content>
</invoke>
