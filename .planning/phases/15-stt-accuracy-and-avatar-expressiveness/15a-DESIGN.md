---
phase: 15
sub_phase: 15a
kind: design
status: draft
source: Phase-15 brainstorming (2026-06-27), research-grounded
addresses: 15-BACKLOG.md items 1 (reframed), 2, and a new Kokoro-VRAM item
build_order: first (before 15b)
---

# Phase 15a — STT cut-off fix, accuracy verification, Kokoro VRAM

The **surgical** track: fix the trailing-word cut-off, verify (not swap) the STT model is
on its best checkpoint, reclaim what Kokoro VRAM is cheap to reclaim. Small, low-risk,
ships before the bigger selectable-engines work (`15b-DESIGN.md`).

## Goal

After 15a, an operator on the 16GB target should hear **no dropped trailing words**, be
**provably on the post-2026-03-12 Nemotron checkpoint**, and be able to **re-judge live
accuracy** to decide whether 15b is even needed. Kokoro's VRAM line is reduced by the one
free knob and its STACK.md estimate corrected.

> **Forward note (v1.2):** the "16GB target" framing here is current-release. A later release
> (v1.2 roadmap **R2 — model lifecycle**) retargets to a **~6GB budget with lazy/on-demand model
> loading and a single resident LLM**, superseding the two-resident-LLM / `keep_alive=-1`
> assumption. Nothing in 15a conflicts with that — the Kokoro knob and checkpoint pin help under
> *any* budget — but treat 15a's 16GB co-residency framing as not-final. See `.planning/ROADMAP.md` → v1.2.

## Non-goals (explicitly out of scope here)

- **No STT model swap.** Research (Phase-15) confirmed `parakeet-tdt-0.6b-v2` is offline-only
  (no trained limited-right-context settings → cache-aware streaming does not apply) and that
  the current `nemotron-speech-streaming-en-0.6b` is the **strongest streaming-English model
  available**. Swapping would break P50<1.0s or downgrade accuracy. Alternative engines are a
  *selectable option*, designed in `15b-DESIGN.md`, not a replacement.
- **No CPU-Kokoro / unload-between-sessions.** Both reclaim real VRAM but risk P50<1.0s.
- **Chatterbox** — parked for the next release (operator's call).

---

## Item 1 — Trailing-word cut-off: diagnose + apply candidate fix  *(P1)*

**Reframed from backlog #2.** The backlog assumed `finalize()` fails to drain the held-back
lookahead tail. Source review of NeMo (`v2.7.3`, identical on the 2.8.x line) shows the
canonical drain is `keep_all_outputs=True` on the final `conformer_stream_step`, and
`backend_nemo.py:164` **already passes `keep_all_outputs=True` on every chunk** — so the
documented output-truncation path is already defeated. The cut-off therefore has a *different*
root cause, to be confirmed on the GPU box.

### Candidate causes & concrete fixes (try in this order; all GPU-gated)

1. **Missing `previous_pred_out` (highest confidence, lowest risk).**
   NeMo's official streaming example
   (`examples/asr/asr_cache_aware_streaming/speech_to_text_cache_aware_streaming_infer.py:273`)
   threads `previous_pred_out=pred_out_stream` back into each `conformer_stream_step` for RNNT
   decode continuity. The current `decode_chunk` (`backend_nemo.py:158-167`) **omits it**. Add
   it (carry `pred_out_stream` in `new_stream_state`, pass it in, store the returned value).
   This matches the reference loop exactly. **Effect must be GPU-measured.**

2. **Ragged-edge feature degradation at hard cutoff (empirical workaround).**
   The last `right`-context frames were *trained* with future frames present; at end-of-speech
   none exist, so those frames' mel features are degraded and the RNNT may emit blanks for the
   last ~480ms. Fix: on `finalize`, feed one final `conformer_stream_step` of **trailing zero
   PCM** so the last real frames get a complete attention window.
   - Frame math (verified against the streaming yaml): 1 encoder frame = `subsampling(8) ×
     window_stride(0.01s)` = **80ms**; `right=6` → **480ms**. At 16kHz mono int16 that is
     **7 680 samples / 15 360 bytes** of zeros. Round **up** to ~500–640ms to absorb
     preprocessor + 8× subsampling edge effects (exact frame yield confirmed in-container).
   - **Caveat:** NOT a documented NeMo step — the official buffer pads only the *left*
     pre-encode cache, never a trailing tail. Validate empirically that trailing words return
     **and WER does not regress**. Also check interaction with the endpoint silence the
     pipeline already pushes (`server.py:79-83,234-235`: livekit-agents pushes silence rather
     than a `flush` frame on end-of-speech — some trailing silence may already reach the stream).

3. **`_track_stall` mid-stream `prev_hyps=None` reset (interaction check).**
   `backend_nemo.py:178-192` resets `prev_hyps` on a stall; confirm this isn't firing right at
   the turn boundary and clearing the tail before `finalize` reads it.

### Diagnosis procedure (operator, GPU box — backlog #2 "do NOT guess the API")

Print `prev_hyps[0].text` (and the held tokens) **before vs. after** each candidate, on a
fixed utterance that ends mid-word. Confirm `model.encoder.att_context_style ==
"chunked_limited"` and dump `model.encoder.streaming_cfg` for `[70,6]`. Keep whichever
candidate restores the tail without WER regression; revert the others.

### Parity note — CPU/ONNX backend

`stt/backend_onnx.py:324` has its own `finalize` with a different (custom-STFT) decode path.
The user's complaint is on the GPU NeMo path, so fix `backend_nemo` first. **Check ONNX for the
same symptom and apply the analogous fix**, but treat it as secondary (CPU fallback).

### Where
`stt/backend_nemo.py` (`decode_chunk` 144-175, `finalize` 195-200, `new_stream_state` 118-128),
`stt/server.py` (flush/finalize 133-155, `_drain_buffer` 195), `stt/backend_onnx.py:324`.

---

## Item 2 — Accuracy: verify the checkpoint, don't swap the model  *(P1)*

Since no better streaming model exists, "accuracy" here is **verification + re-measurement**,
not a swap.

### 2a. Pin / verify the post-2026-03-12 checkpoint
`STT_MODEL` is **not revision-pinned** (`docker-compose.yml:120,136,188`;
`stt/Dockerfile:32` bakes weights at *build* time via `from_pretrained('${STT_MODEL}')`).
So the running weights are whatever was on HF `main` **when the image was built**. The Jan-2026
weights are weaker and now live on branch `nemotron-speech-streaming-jan2026`; `main` is the
re-trained March checkpoint.
- **Action:** pin `STT_MODEL` to the **March-2026 checkpoint commit SHA** (operator reads it
  from the HF model-card history) in `.env.example` + the compose default, so weights can never
  drift. Verify the baked image's HF snapshot commit matches. *(Sandbox-doable: the pin + docs;
  the SHA + rebuild are operator steps.)*

### 2b. Confirm the RNNT stall-recycle actually fires
The documented Nemotron "RNNT stalls after sentence boundaries" issue degrades real-world
quality more than raw WER does; `_track_stall` (`backend_nemo.py:178`) is the mitigation.
- **Action (operator):** during a live session, confirm the `"nemo-stt RNNT stall recycle…"`
  log appears when expected (and is *not* firing so eagerly it truncates). Tune `STALL_FRAMES`
  (`stt/backend_common.py`) only if measurement shows it misbehaving.

### 2c. Re-measure, then decide
After Item 1 + 2a, run a live voice pass and judge accuracy.
- **Default (user-stated): accept.** If acceptable, selectable accuracy-mode engines stay a
  hardware-choice nicety, not urgent.
- **Escalate only if still bad** → the deferred engine-selection work (v1.2 roadmap **R3 —
  hardware-aware engines + models**, where `15b-DESIGN.md` now lives). Not a Phase-15 step.

---

## Item 3 — Kokoro VRAM: the one free knob + doc correction  *(P3)*

Kokoro-82M weights are ~0.33GB; the observed ~5GB is **almost all CUDA context + PyTorch
allocator reserve** on the `cu128` image (upstream's own benchmark: ~2.37GB context floor →
~4GB loaded on cu121; ~1GB more on cu128/Blackwell). ~2.4–3GB is irreducible and genuinely
contends on the shared GPU.

- **Action (sandbox-doable):** add to the `kokoro` service in `docker-compose.yml:214-232`
  (currently no `environment:` block):
  ```yaml
  environment:
    - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
  ```
  Reclaims reserved fragmentation (~0.5–1GB, to verify), **zero latency cost**.
- **Action (operator):** re-measure `nvidia-smi` before/after.
- **Docs (sandbox-doable):** correct the Kokoro estimate in `.planning/research/STACK.md`
  (~2.5GB → **~4–5GB on cu128**); cross-reference `PITFALLS.md` C1, which already anticipated
  per-process CUDA-context overhead.

---

## Verification matrix (what's sandbox vs GPU/operator)

| Work | Sandbox-doable | GPU / operator-gated |
|---|---|---|
| Item 1 — add `previous_pred_out` | code edit | **effect measured on GPU** |
| Item 1 — trailing-zero flush | code edit | **validate tail returns, no WER regress** |
| Item 1 — ONNX parity | code edit | measure |
| Item 2a — revision pin + docs | yes | SHA lookup + rebuild |
| Item 2b — stall-recycle | — | live log inspection |
| Item 2c — re-measure / accept gate | — | live voice pass |
| Item 3 — `expandable_segments` + STACK fix | yes | `nvidia-smi` re-measure |

## Risks / uncertainties

- **Item 1 cause is not yet confirmed** — it's a diagnosis, not a known fix. Budget a focused
  GPU session to try the candidates. If none fully fixes it, the partial improvement + user's
  stated willingness to accept still closes the cut-off as "mitigated."
- Trailing-zero padding is an **unofficial** workaround; gate it on a no-WER-regression check.
- `expandable_segments` payoff magnitude is unmeasured (estimate ~0.5–1GB).

## References (Phase-15 research, 2026-06-27)

- NeMo `keep_all_outputs` drain + `previous_pred_out`: `speech_to_text_cache_aware_streaming_infer.py`
  L249-281, `conformer_stream_step` docstring `mixins.py:616`, truncation `conformer_encoder.py:542-544`
  (NeMo v2.7.3). Frame math: `fastconformer_hybrid_transducer_ctc_bpe_streaming.yaml` L72,97,111,116,119.
- Parakeet offline-only / Nemotron streaming-SOTA: HF model cards + maintainer threads, April-2026
  on-device benchmark (`arXiv 2604.14493`).
- Kokoro VRAM: remsky/Kokoro-FastAPI README VRAM table + `config.py` (no fp16 toggle); STACK.md, PITFALLS.md C1.
