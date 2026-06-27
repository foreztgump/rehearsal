---
phase: 14
plan: 14-09
slug: latency-verification-release-gate
depends_on: [14-01, 14-04]
status: ready
kind: operator runbook
files_modified:
  - .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-VERIFY.md  # NEW — consolidated sign-off
requirements: [PERF-04]
---

# Plan 14-09 — Latency Verification + Release Gate

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. This is the **final, operator-gated** plan.
> Most steps run on the **RTX 5090** (marked **OPERATOR**); the self-checkable audits
> (server-diff, metrics mechanism, vram-validate dry-run) are signed in-plan. This
> plan **produces no product code** — it produces the signed `14-VERIFY.md` and
> discharges the pending Phase 9/10/11 operator gates.

**Goal:** Sign PERF-04 (P50<1.0s / P95<1.5s for both LLMs on the retuned STT leg;
STT finalize trending sub-100ms; Avatar adds no latency regression and zero server
VRAM; voice-only byte-for-byte), and discharge the pending 9/10/11 operator gates — or
re-defer any with a recorded reason.

**Architecture:** Latency is read from `agent/metrics.py`'s `emit_rolling_summary()`
(every 10 turns → JSON to stdout); VRAM from `scripts/vram-validate.sh`; voice-only
isolation from a server-diff + a data-channel audit (the 14-04 gate makes this true).

**Tech Stack:** the running 7-service stack on the RTX 5090; `agent/metrics.py`,
`scripts/vram-validate.sh`, the Phase 9/10/11 `*-VERIFY.md` runbooks.

**Current state:** `emit_rolling_summary()` and `rolling_percentiles()` exist (read-only
here). The 9/10/11 runbooks list **all** operator gates as PENDING (sandbox-verifiable
parts already PASS). 14-01 (retuned feel) and 14-04 (the voice-only gate) must be
merged before this plan can sign their dependent gates.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: PERF-03 local-first — metrics are stdout-only, no
external telemetry. PERF-04 thresholds are the release bar: **e2e P50 < 1000 ms, P95 <
1500 ms** for *both* LLM choices. Do not weaken a gate to pass it — re-defer with a
written reason instead.

---

## Task 1: Self-checkable audits (sign in-plan, no GPU)

**Files:** none.

- [ ] **Step 1: Voice-only server-diff is empty except the documented avatar path**

Confirm the 14-04 gate holds in code: with Avatar OFF, the agent requests no timestamps
and publishes nothing.
```bash
grep -n "_avatar_enabled" agent/captioned_tts.py        # flag default False, gates publish
python3 tests/test_captioned_gate.py                    # ok: avatar-off suppresses timestamps
git grep -n "lk.avatar" agent/                          # only captioned_tts publishes, gated
```
Expected: the only server-side `lk.avatar.*` publisher is `captioned_tts.py`, gated on
`_avatar_enabled`. Record PASS.

- [ ] **Step 2: Metrics readout mechanism works**

```bash
python3 agent/metrics.py                                 # the module self-check
```
Expected: the self-check passes; confirm `rolling_percentiles` returns `p50`/`p95` and
`emit_rolling_summary` emits the `eou/stt/llm_ttft/tts_ttfb/e2e` keys.

- [ ] **Step 3: All Phase-14 pure tests green**

```bash
python3 tests/test_endpointing.py
python3 tests/test_captioned_gate.py
python3 tests/test_transcript_gate.py
python3 tests/test_placement.py        # pre-existing, must still pass
```
Expected: `ok:` from each. Record PASS.

---

## Task 2: PERF-04 latency — both LLMs (OPERATOR, RTX 5090)

**Files:** none (records into `14-VERIFY.md`, Task 6).

- [ ] **Step 1: Boot the retuned stack**

On the RTX 5090: `./up.sh -d` with the 14-01 retune merged (mode-aware endpointing,
named VAD/interrupt knobs, trained `STT_ATT_CONTEXT_SIZE=[70,1]`).

- [ ] **Step 2: Fast LLM — drive ≥30 Converse turns, read percentiles**

Hold a natural conversation (≥30 turns) in Converse mode with the **Fast** model, then:
```bash
docker compose logs agent | grep rolling_summary | tail -3
```
Expected: `rolling_summary.e2e.p50 < 1000` and `e2e.p95 < 1500`; `stt.p50` trending
**< ~100 ms** (the STT-04 finalize leg). Record the JSON line.

- [ ] **Step 3: Better LLM — repeat**

Switch to the **Better** model (Settings → Model, or `OLLAMA_MODEL` env), drive ≥30
turns, read again. Expected: same e2e P50<1000 / P95<1500 bar holds. Record.

- [ ] **Step 4: Interview mode sanity**

Switch to Interview mode and confirm the *intended* deliberate floor: `eou` flags
`over_budget` (0.7s > 300 ms budget) — this is **expected**, not a regression (per
`agent/main.py` METRICS INTERPRETATION). e2e still within the release bar for replies.

- [ ] **Step 5: Record PERF-04 latency verdict** — PASS/FAIL + the JSON evidence for
  both LLMs into `14-VERIFY.md`.

---

## Task 3: Avatar no-regression + zero server VRAM (OPERATOR)

**Files:** none.

- [ ] **Step 1: Voice-only VRAM baseline**

With Avatar OFF, run:
```bash
./scripts/vram-validate.sh
```
Record peak VRAM (must stay under the 15360 MB ceiling).

- [ ] **Step 2: Avatar-ON VRAM delta is ~zero**

Toggle Avatar ON (captioned TTS active), hold a conversation, re-run
`./scripts/vram-validate.sh`. Expected: peak VRAM is **unchanged** vs Step 1 — captioned
TTS reuses the Kokoro service and adds no model/VRAM. Record the delta (target 0).

- [ ] **Step 3: Avatar adds no latency regression**

Compare `rolling_summary` Avatar-OFF vs Avatar-ON over comparable turn counts. Expected:
`e2e` and `tts_ttfb` P50/P95 are within noise (the only addition is a post-audio
data-channel publish, off the first-audio path). Record.

- [ ] **Step 4: Voice-only emits no lip-sync channel**

Avatar OFF, full conversation: confirm zero `lk.avatar.lipsync` frames (room-level
`DataReceived` audit, or agent logs). Avatar ON: frames present, lip-sync tracks words;
drop the channel for one utterance → Path-A fallback, no breakage. Record.

---

## Task 4: Discharge Phase 9 — STT correctness/finalize (OPERATOR)

**Files:** `.planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md` (sign).

- [ ] **Step 1: Run the six Phase-9 gates on the RTX 5090**

Execute the runbook's PENDING gates: (1) `conformer_stream_step` decodes growing text,
(2) Blackwell sm_120 torch runs, (3) growing interim + native PnC + ~100 ms finalize +
`stt_ms` non-null, (4) voice-to-voice P50<1.0s both LLMs (shares Task 2 evidence),
(5) RNNT stall watchdog recycles without a premature FINAL, (6) VRAM co-residency 3
procs under 16 GB.

- [ ] **Step 2: Sign or re-defer**

Fill the runbook's operator sign-off line (`Operator / Date / GPU: RTX 5090`). For any
gate not passed, record the reason and a re-defer note. Commit:
```bash
git add .planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md
git commit -m "test(14-09): discharge Phase-9 STT operator gates on RTX 5090"
```

---

## Task 5: Discharge Phase 10 + Phase 11 gates (OPERATOR)

**Files:**
- `.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md`
- `.planning/phases/11-consumer-gpu-deployment-part-e/11-DEPLOY-VERIFY.md`

- [ ] **Step 1: Phase 10 — placement co-residency matrix**

Run the 8 PENDING gates, especially the 4-cell {E2B,E4B}×{GPU,CPU} co-residency matrix
(peak < 15360, 3 vs 2 GPU procs), resolve-once/no-thrash on Fast↔Better swap, and the
`STT_FORCE_CPU` global pin. Decide the safe-default flip (`STT_FORCE_CPU=1→0` +
`STT_HEADROOM_MEASURED=1`) **only** if Gates 1–5 pass. Sign the runbook.

- [ ] **Step 2: Phase 11 — deployment doctor + boot**

Run the 7 PENDING gates: default CPU-STT boot healthy; GPU-STT opt-in
(`--profile stt-gpu`); `gpu-doctor.sh` on all-OK / toolkit-missing / sub-spec hosts;
no-hung-`up`. Also exercise the **new** `./install.sh` on a clean machine (14-07) and
`./down.sh`. Sign the runbook.

- [ ] **Step 3: Commit the signed runbooks**

```bash
git add .planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md \
        .planning/phases/11-consumer-gpu-deployment-part-e/11-DEPLOY-VERIFY.md
git commit -m "test(14-09): discharge Phase-10 placement + Phase-11 deploy operator gates"
```

---

## Task 6: Consolidated release UAT + `14-VERIFY.md` sign-off

**Files:**
- Create: `.planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-VERIFY.md`

- [ ] **Step 1: Run the cross-plan UAT**

Aggregate the per-plan manual checks into one pass:
- **Feel A/B (14-01):** Converse feels Whisper-era snappy vs the pre-retune build;
  interrupts cut TTS; openings transcribed; Interview keeps patience. Use the 14-01
  operator tuning table to settle final values; record them.
- **Themes (14-02) / Orbs (14-08):** six themes switch + persist; reduced-motion; orb
  audio+state reactive; no console errors.
- **Avatar (14-03/14-04):** idle reads engaged; framing reflows; lip-sync tracks words
  Avatar-ON; voice-only emits no schedule channel.
- **Presets (14-05):** pick → edit → start; voice/mood applied; default GLB reused.
- **Lifecycle (14-06):** new/reset/end teardown leaves no residue; transcript export
  txt/md; mic-denied prompt; garbled reprompt.
- **Install (14-07):** clean-machine `install.sh` → run → `down.sh`.

- [ ] **Step 2: Write `14-VERIFY.md`**

One gate table: each Phase-14 requirement (FEEL-01/02, UI-01/02/03, AVTR-09..13,
DEPLOY-06/07, SESS-01..04, REL-01/02, PERF-04) → PASS / FAIL / RE-DEFERRED(reason), with
evidence links (the per-plan verification records + the metric JSON + the signed 9/10/11
runbooks). Include the final tuned feel values (resolving PRD §10's open question) and an
operator sign-off line (`Operator / Date / GPU: RTX 5090`).

- [ ] **Step 3: Commit**

```bash
git add .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-VERIFY.md
git commit -m "docs(14-09): consolidated Phase-14 release verification + PERF-04 sign-off"
```

## Verification
**Self-checkable (signed in-plan):** Task 1 — server-diff audit, metrics mechanism,
all pure tests green.
**OPERATOR (RTX 5090):** PERF-04 both LLMs (e2e P50<1000/P95<1500); STT finalize
sub-100ms; avatar zero-VRAM + no latency regression; voice-only no-schedule; Phase
9/10/11 runbooks signed or re-deferred with reason.

## Artifacts this plan produces
- **NEW** `14-VERIFY.md` — the consolidated Phase-14 release gate + PERF-04 sign-off.
- **Signed** `09-STT-VERIFY.md`, `10-PLACEMENT-VERIFY.md`, `11-DEPLOY-VERIFY.md`
  (operator gates discharged or re-deferred with reason).
