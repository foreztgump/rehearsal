---
phase: 15
kind: backlog
status: draft
source: Phase-14 release UAT on the RTX 5090 (2026-06-27)
---

# Phase 15 — Backlog (from Phase-14 UAT)

Items surfaced while live-testing the Phase-14 release. Each records **what**, **why**
(which test/review surfaced it), **where** in code, and **current state**. This is the
raw candidate list — not yet scoped into plans. Two themes dominate: **STT accuracy**
and **avatar expressiveness / word-accurate lip-sync**.

---

## 1. STT — research a faster-*and*-more-accurate streaming model  *(P1)*

- **Why:** the live 0.6B NeMo streaming model (`nvidia/nemotron-speech-streaming-en-0.6b`)
  is noticeably less accurate than the early-phase faster-whisper-large-v3 (1.5B,
  full-context). The user accepts it for now ("very fast, good enough") but wants better.
- **Constraint:** must stay **streaming** (live partials + ~100ms finalize) to hold the
  voice-to-voice **P50 < 1.0s** budget — do NOT revert the streaming architecture.
- **Direction:** evaluate larger cache-aware-streaming variants (NeMo/Parakeet). A swap
  needs a new ONNX export for the CPU path + VRAM re-verification (4-cell matrix).
- **Separately:** faster-whisper is to be reintroduced on a **different setup** (not the
  streaming path).
- **Where:** `.env` (`STT_MODEL`), `stt/backend_nemo.py`, `stt/export_onnx.py`, `docker-compose.yml`.

## 2. STT — fix `finalize()` lookahead-tail drop (trailing words)  *(P1, real bug)*

- **Why:** the user saw transcripts **drop trailing words**. Root cause: `stt/backend_nemo.py`
  `finalize()` claims to "drain the stream" but just returns already-decoded text. With
  cache-aware streaming + `att_context_size=[70,N]`, the last N frames' tokens are held back
  until N *future* frames arrive; at end-of-speech none come, so the lookahead-delayed tail
  is never emitted. Drop scales with N (`[70,6]`≈480ms, `[70,13]`≈1040ms).
- **Current state:** mitigated by reverting `[70,13]→[70,6]` (halves the drop). `[70,6]` still
  drops ~480ms — the finalize fix is the real cure for any lookahead.
- **Fix (needs NeMo research + GPU test, do NOT guess the API):** on flush, pad the
  audio/encoder with ~right-context frames of trailing silence (or use NeMo
  `CacheAwareStreamingAudioBuffer` keep_all_outputs / a final stream step) so the held-back
  tail emits before reading `prev_hyps`.
- **Where:** `stt/backend_nemo.py:195` (`finalize`), `stt/server.py:147-150` (flush), `_drain_buffer` (server.py:195).

## 3. Lip-sync — word-accurate Path-B reliability + multi-sentence anchoring  *(P3 — deferred, accepted)*

- **Status:** the user **accepted the current tuned Path-A lip-sync as good-enough** (2026-06-27)
  and explicitly deferred this — low urgency, not blocking. The word-accurate upgrade below stays on the Phase-15 list.
- **Why:** Phase-14 only **tuned the Path-A formant fallback** for naturalness (capped
  mouth-open 0.6, softer attack, viseme intensity 0.7×). The real upgrade is the
  **word-accurate Path-B** (captioned-TTS `lk.avatar.lipsync` schedule).
- **Two parts:**
  - (a) Confirm Path-B actually fires when avatar is ON (the `avatar.update` gate + the
    bounded retry in `ApplyAvatarMode.tsx`).
  - (b) **Bug (code review #7):** Path-B only anchors the **first sentence** — a new
    schedule is popped only on a silence→sound edge (`AvatarStage.tsx` ~line 580,
    `audible && !wasAudibleRef.current`); continuous multi-sentence playout never dips below
    `RMS_LO`, so later sentences never anchor and fall back to rough Path-A. Fix: anchor each
    sentence's schedule by seq/timing, not only on a silence gap.
- **Where:** `web/app/AvatarStage.tsx`, `web/app/ApplyAvatarMode.tsx`, `agent/captioned_tts.py`.

## 4. Avatar — emotion + body movement  *(P2)*

- **Why:** the 3D avatar has **no facial emotion and no body motion** yet, which makes
  full-body framing read unnatural. Phase-14 worked around this: default to **upper**
  (head-and-shoulders) framing, with a "Show full body" opt-in and a full-screen toggle.
- **Direction:** add mood/expression (TalkingHead `setMood`/morphs, driven by conversation
  state or sentiment) and idle + speaking body motion. Once expressiveness exists, full-body
  framing becomes a reasonable default.
- **Where:** `web/app/AvatarStage.tsx`, `web/app/TalkingScreen.tsx`, `web/public/vendor/talkinghead/talkinghead.mjs`.

## 5. TTS — streaming first-audio on the captioned path  *(P3, verify-then-fix)*

- **Why (code review #1):** `agent/captioned_tts.py` buffers the whole sentence
  (`resp.json()` → full base64 WAV) before the first `output_emitter.push`, so first-audio
  waits for the complete synthesis. May regress voice-to-voice **P50** on longer first
  sentences. Pre-existing (predates Phase-14) but this branch makes captioned TTS the path.
- **Action:** measure first-audio latency (14-09 B1) avatar ON vs OFF; if it regresses,
  stream the Kokoro `/dev/captioned_speech` response incrementally.
- **Where:** `agent/captioned_tts.py`.

---

## Phase-14 close-out still pending (NOT Phase-15 — finish first)

These are the Phase-14 release gate, deferred to the operator runbook
(`.planning/phases/14-.../14-VERIFY.md` PART B). They need real-voice / GPU measurement:

- **B1** — voice-to-voice **P50<1.0s / P95<1.5s** over ~30 turns, both LLMs (`rolling_summary.e2e`).
- **B2** — avatar zero-VRAM (VRAM done: 11.7GB < ceiling) + live "no `lk.avatar.*` when avatar OFF" audit.
- **B3/B4** — discharge the Phase 9/10/11 operator gates (`09-STT-VERIFY.md`, `10-PLACEMENT-VERIFY.md`, `11-DEPLOY-VERIFY.md`).
- **#8 (review)** — VAD/interrupt margins (0.65→0.60 / 0.30→0.25s) A/B for speaker echo; revert only if it misfires.
