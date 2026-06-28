---
phase: 15
sub_phase: 15a
kind: verify
status: complete
operator_uat: 2026-06-27 (RTX 5090 Laptop GPU)
source: 15a-01-stt-cutoff-checkpoint-kokoro-PLAN.md
---

# Phase 15a — operator UAT outcome

Live voice-pass on the GPU NeMo path (`STT_FORCE_CPU=0`, `STT_HEADROOM_MEASURED=1`,
`--profile stt-gpu`). GPU STT image rebuilt from the 15a code for each candidate.

## Item 1 — trailing-word cut-off: BOTH surgical candidates FAILED → escalate

| Probe | Setting | Operator verdict |
|---|---|---|
| Baseline | flags OFF, `[70,6]` | the original cut-off (reference point) |
| Candidate A | `STT_THREAD_PRED_OUT=1` | **worse** than baseline |
| Candidate B | `STT_FINALIZE_PAD=1` (560ms drain) | **as bad as A, and less accurate** (silence-injected RNNT junk) |
| Lookahead dial | `STT_ATT_CONTEXT_SIZE=[70,13]` (max trained) | **a little better** on the cut-off but **slightly less accurate** than `[70,6]`; latency still felt fast |

Two distinct mechanisms (decode-continuity and trailing-silence drain) both regressing
means the cut-off's root cause is NOT what either candidate addressed — the drain/
decode-continuity approach is a dead end on this model (per the project "stop after 2
attempts" rule). `[70,13]` is the **maximum trained right-context**; the four trained
settings are `[70,0] [70,1] [70,6] [70,13]`, so there is nothing higher to tune to
without going untrained (which degrades accuracy further — declined).

### Decision
- **Locked in `STT_ATT_CONTEXT_SIZE=[70,13]`** (`.env`) — best trailing-word capture of
  the trained settings; the residual cut-off is accepted as **mitigated** (design's
  fallback for "no candidate fully fixes it").
- **Accuracy axis escalated to v1.2 R3** (hardware-aware *selectable STT engines* /
  `15b-DESIGN.md`) — a stronger/different engine, not more att_context tuning.
- The flag-gated drain code (candidates A/B) stays **dormant (default OFF)** on `master`
  — proven no-op; left in place in case R3 revisits it. Strip later if R3 doesn't.

## Item 2a — checkpoint revision pin: VERIFIED
Offline-bake pin works end-to-end (build exit 0; no runtime fetch). Model restored from
the pinned snapshot `models--nvidia--nemotron-speech-streaming-en-0.6b/snapshots/`**`7b176baa37b4692ca5e4f671edbcbfd6541fe52b`**`/...nemo`
— the resolved `main` commit. **To pin the March-2026 checkpoint:** set
`STT_MODEL_REVISION=<SHA>` in `.env`, rebuild `nemo-stt` (and `nemo-stt-cpu`), and confirm
this snapshot hash changes to the pinned SHA. Resolves review finding F5 (offline export
fails loud at build, not silently at runtime).

## Item 2b — RNNT stall-recycle: NOT verified (blocked)
The `nemo-stt` app logger does not emit INFO to stdout, so neither the "RNNT stall recycle"
log (Phase 9) nor the new `STT_DEBUG_DRAIN` diagnostic is visible in `docker logs`. This is
a **pre-existing logging-config gap**, not a 15a regression. Follow-up: add a logging
config so these surface (one-liner + rebuild) before relying on either for diagnosis.

## Item 3 — Kokoro expandable_segments: deployed, not yet measured
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is on the kokoro service. `nvidia-smi`
before/after re-measure still outstanding (estimate ~0.5–1GB reclaimed).

## Net
v1.2 backlog gains: **R3 must carry the STT accuracy + trailing-word work** (the surgical
track could not). Item 2a pin + Item 3 knob shipped and stand. `[70,13]` is the operating
default for this deploy.
