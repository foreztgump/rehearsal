---
status: partially-signed
phase: 14-release-polish-conversation-feel-ui-avatar-lifecycle
plan: 14-09
requirement_ids: [PERF-04, FEEL-01, FEEL-02, UI-01, UI-02, UI-03, AVTR-09, AVTR-10, AVTR-11, AVTR-12, AVTR-13, DEPLOY-06, DEPLOY-07, SESS-01, SESS-02, SESS-03, SESS-04, REL-01, REL-02]
harness_note: >
  This file has TWO parts. PART A (Self-checkable results) is SIGNED in-sandbox:
  build-green (web + py_compile), the Phase-14 stdlib gate tests, the metrics
  self-check, and the voice-only server-diff static audit — all run with real
  output recorded below. PART B (OPERATOR runbook) is PENDING HARDWARE: every
  latency / VRAM / live voice-to-voice gate needs the RTX 5090 + the running
  7-service stack, which the sandbox has NO GPU and NO Docker daemon to provide.
  NONE of the operator gates are marked passed by the executor. Latency budgets
  are referenced by their named constants (agent/metrics.py:BUDGET_MS,
  agent/endpointing.py, agent/main.py) — never inlined.
---

# Phase 14 — Release Verification + PERF-04 Sign-off (plan 14-09)

**Status:** PART A SIGNED (self-checkable, sandbox) · PART B PENDING OPERATOR (RTX 5090).

Branch verified: `phase-14-release-polish`.

The named latency budgets this gate asserts against live in code, not in this doc:

| Budget | Named constant | Source |
|--------|----------------|--------|
| EOU | `BUDGET_MS["eou"]` | `agent/metrics.py:33` |
| STT finalize | `BUDGET_MS["stt"]` | `agent/metrics.py:34` |
| LLM TTFT | `BUDGET_MS["llm_ttft"]` | `agent/metrics.py:35` |
| TTS TTFB | `BUDGET_MS["tts_ttfb"]` | `agent/metrics.py:36` |
| e2e per-line over_budget flag | `BUDGET_MS["e2e"]` | `agent/metrics.py:38` |

> **PERF-04 release bar vs `BUDGET_MS["e2e"]`.** The per-turn `over_budget`
> flag fires off `BUDGET_MS["e2e"]` (the looser Phase-2 e2e gate). PERF-04's
> **release** bar is stricter — voice-to-voice **P50 < 1.0s, P95 < 1.5s** for
> *both* LLM choices — and is defined in plan `14-09 §Global Constraints`, not
> as a `BUDGET_MS` entry. The operator asserts the stricter PERF-04 bar against
> `rolling_summary.e2e.{p50,p95}`; a turn may flag `over_budget:["e2e"]` on a
> single slow turn yet the rolling P50/P95 still pass the release bar.

---

## PART A — Self-checkable results (SIGNED, sandbox, no GPU)

These discharge plan 14-09 **Task 1** in full, plus the prompt's build-green
requirement. All commands were run on this branch; output is recorded verbatim.

### A1 — Voice-only server-diff is empty except the documented avatar path (AVTR-12) · PASS

The 14-04 OFF-gate holds in code: with Avatar OFF the agent requests no
timestamps and publishes nothing on `lk.avatar.*`.

```
$ grep -n "_avatar_enabled" agent/captioned_tts.py
111:        self._avatar_enabled = False          # default OFF — voice-only isolated
131:    def set_avatar_enabled(self, on: bool) -> None:
133:        self._avatar_enabled = bool(on)
178:        self._avatar_enabled = tts._avatar_enabled   # snapshot per utterance
188:            avatar_enabled=self._avatar_enabled,      # gates return_timestamps
230:        if self._avatar_enabled:                      # gates the publish

$ git grep -n "lk.avatar" agent/
agent/main.py:589:    # lk.avatar.lipsync frames (the voice-only auditable invariant) ... (comment)
# LIPSYNC_TOPIC = "lk.avatar.lipsync" is defined once, in agent/captioned_tts.py:62,
# and published only inside _publish_schedule, reached only when self._avatar_enabled.
```

The single server-side `lk.avatar.*` publisher is `captioned_tts.py`, gated on
`_avatar_enabled` (default `False`). The `avatar.update {on: bool}` RPC
(`agent/main.py:591-608`) is the only flip path and validates the payload type
at the untrusted boundary before calling `session.tts.set_avatar_enabled(on)`.
**Voice-only invariant holds. PASS.**

### A2 — Metrics readout mechanism works · PASS

```
$ python3 agent/metrics.py
{"eou_ms": 200.0, "stt_ms": 120.0, "llm_ttft_ms": 250.0, "tts_ttfb_ms": 130.0, "e2e_ms": 900.0, "over_budget": []}
{"eou_ms": 200.0, "stt_ms": 120.0, "llm_ttft_ms": 250.0, "tts_ttfb_ms": 130.0, "e2e_ms": 1100.0, "over_budget": []}
{"eou_ms": 200.0, "stt_ms": 120.0, "llm_ttft_ms": 250.0, "tts_ttfb_ms": 130.0, "e2e_ms": 1000.0, "over_budget": []}
{"eou_ms": 200.0, "stt_ms": 120.0, "llm_ttft_ms": 250.0, "tts_ttfb_ms": 130.0, "e2e_ms": 1300.0, "over_budget": ["e2e"]}
{"rolling_summary": {"eou": {"p50": 200.0, "p95": 200.0}, "stt": {"p50": 120.0, "p95": 120.0}, "llm_ttft": {"p50": 250.0, "p95": 250.0}, "tts_ttfb": {"p50": 130.0, "p95": 130.0}, "e2e": {"p50": 1000.0, "p95": 1260.0}}, "window": 100}
_self_check OK: e2e p50=1050.0 p95=1270.0
```

`rolling_percentiles` returns `p50`/`p95`; `emit_rolling_summary` emits the
`eou/stt/llm_ttft/tts_ttfb/e2e` keys; the per-turn line flags `over_budget`
correctly (the 1300 ms turn trips `["e2e"]` against `BUDGET_MS["e2e"]`). **PASS.**

### A3 — All Phase-14 pure tests green · PASS

```
$ python3 tests/test_endpointing.py
ok: endpointing selector truth table
$ python3 tests/test_captioned_gate.py
ok: captioned gate truth table
$ python3 tests/test_transcript_gate.py
ok: transcript gate truth table
$ python3 tests/test_placement.py        # pre-existing, still green
test_placement OK — full llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED matrix
```

All four exit 0. **PASS.**

### A4 — Build green (web + py_compile) · PASS

```
$ python3 -m py_compile agent/*.py        → PY_COMPILE agent OK
$ python3 -m py_compile tests/*.py stt/*.py → PY_COMPILE tests+stt OK

$ (cd web && npx --no-install tsc --noEmit)   → exit 0 (no type errors)
$ (cd web && npm run build)
  ▲ Next.js 16.2.9 (Turbopack)
  ✓ Compiled successfully in 2.0s
  Finished TypeScript in 1553ms
  ✓ Generating static pages using 5 workers (3/3)
  Route (app):  ○ /   ○ /_not-found   ƒ /api/token
```

Python byte-compile clean across `agent/`, `stt/`, `tests/`; web typecheck +
production build clean. **PASS.**

### PART A verdict — SIGNED GREEN

| Self-checkable gate | Evidence | Verdict |
|---------------------|----------|---------|
| Voice-only server-diff empty except gated avatar path (AVTR-12) | A1 | **PASS** |
| Metrics readout mechanism (`rolling_percentiles`/`emit_rolling_summary`) | A2 | **PASS** |
| Phase-14 stdlib gate tests (endpointing, captioned_gate, transcript_gate, placement) | A3 | **PASS** |
| Build green — py_compile (agent/stt/tests) + web tsc + next build | A4 | **PASS** |

The branch is **self-checkable-green** and ready for the operator pass.

---

## PART A2 — Browser UAT (SIGNED, no GPU — dev server on :3001)

Driven against `npm run dev` (no LiveKit backend needed for the setup-screen
surface) via Chrome DevTools. These cover the client-only slice of B5; the
talking-screen items (orb pulse, avatar idle/lip-sync, Reset/Export) still need
the live stack and remain in B5.

| Check | Requirement | Evidence | Verdict |
|-------|-------------|----------|---------|
| Setup screen renders; console clean | UI-01 | first paint + `list_console_messages` empty across the whole session | **PASS** |
| Theme switch | UI-01 | Prism Wave → `data-theme=prism-wave`, `--accent=#8775cc` | **PASS** |
| Theme persists across reload | UI-02 | reload → `data-theme` + `localStorage["adept.theme"]` both `prism-wave` | **PASS** |
| Preset pre-fill | 14-05 (AVTR presets) | SOC Analyst Coach → Display Name `SOC Analyst Coach`, Voice `am_michael` | **PASS** |
| Prefilled fields stay editable | 14-05 | injected edit persisted; a later preset pick overrode it | **PASS** |
| Mic-denied prompt | **REL-01** | stubbed `getUserMedia` NotAllowedError + Start → "Microphone access is blocked. Click the mic/camera icon… press Start again."; stayed on setup | **PASS** |

---

## PART B — OPERATOR runbook (PENDING HARDWARE — RTX 5090)

> **OPERATOR-ONLY.** Every gate below needs the running 7-service stack on the
> RTX 5090 (Docker daemon + GPU + NeMo/torch + Kokoro + Ollama + browser + LAN
> mic). The sandbox has no GPU and no Docker daemon, so these are deferred and
> **unsigned**. Run top-to-bottom on the GPU host; fill each PASS/FAIL line.
> Do **not** weaken a gate to pass it — re-defer with a written reason.

### Pre-req — boot the retuned stack (14-01 + 14-04 merged)

```bash
# repo root on the RTX 5090 host
set -a && . ./.env && set +a
./up.sh -d                         # runs gpu-doctor then `docker compose up -d`
docker compose ps                  # all services healthy/running before any gate
```

The retune under test is the shipped default of the named feel constants
(operator A/B-tunes around these — see the Final tuned feel values table):

| Knob | Named constant | Shipped default | Source |
|------|----------------|-----------------|--------|
| Converse min/max endpointing delay | `CONVERSE_MIN_DELAY` / `CONVERSE_MAX_DELAY` | 0.3s / 3.0s | `agent/endpointing.py:14-15` |
| Interview min/max endpointing delay | `INTERVIEW_MIN_DELAY` / `INTERVIEW_MAX_DELAY` | 0.7s / 5.0s | `agent/endpointing.py:18-19` |
| VAD speech-onset bar | `VAD_ACTIVATION_THRESHOLD` | 0.6 | `agent/main.py:108` |
| Barge-in min speech | `INTERRUPT_MIN_DURATION_S` | 0.25s | `agent/main.py:114` |
| False-interrupt resume window | `FALSE_INTERRUPT_TIMEOUT_S` | 2.0s | `agent/main.py:115` |

---

### B1 — PERF-04 latency, both LLMs (plan 14-09 Task 2)

```bash
# Fast LLM: hold a natural Converse conversation (>=30 turns), then:
docker compose logs agent | grep rolling_summary | tail -3
# Switch to the Better model (Settings -> Model, or OLLAMA_MODEL), >=30 turns, repeat:
docker compose logs agent | grep rolling_summary | tail -3
```

- **Assert (both LLMs):** `rolling_summary.e2e.p50` < PERF-04 P50 bar (1.0s) and
  `rolling_summary.e2e.p95` < PERF-04 P95 bar (1.5s) — the stricter release bar
  from 14-09 §Global Constraints, not `BUDGET_MS["e2e"]`.
- **Assert:** `rolling_summary.stt.p50` (the STT-04 finalize leg) trends toward /
  under ~100 ms, comfortably inside `BUDGET_MS["stt"]`.

| LLM | e2e P50 | e2e P95 | stt P50 (finalize) | record rolling_summary JSON | PASS/FAIL |
|-----|---------|---------|--------------------|------------------------------|-----------|
| Fast | | | | | **PENDING** |
| Better | | | | | **PENDING** |

**Interview-mode sanity (Task 2 Step 4):** switch to Interview, confirm the
*intended* deliberate floor — `eou` flags `over_budget:["eou"]` because
`INTERVIEW_MIN_DELAY` (0.7s) deliberately exceeds `BUDGET_MS["eou"]`. This is
**expected, not a regression** (see the METRICS INTERPRETATION note,
`agent/main.py:98-101`). Reply e2e still within the PERF-04 bar. → ☐ confirmed.

**PERF-04 latency verdict:** ☐ PASS  ☐ FAIL/RE-DEFER (reason: __________)

---

### B2 — Avatar no-regression + zero server VRAM (plan 14-09 Task 3)

```bash
# Voice-only VRAM baseline (Avatar OFF):
./scripts/vram-validate.sh
# Toggle Avatar ON (captioned TTS active), hold a conversation, re-run:
./scripts/vram-validate.sh
```

- **Assert:** Avatar-OFF peak VRAM under the 15360 MB ceiling (script prints PASS).
- **Assert:** Avatar-ON peak VRAM **unchanged** vs OFF (captioned TTS reuses the
  Kokoro service — target delta 0).
- **Assert:** `rolling_summary` `e2e`/`tts_ttfb` P50/P95 Avatar-ON vs OFF within
  noise (the only addition is a post-audio data-channel publish, off the
  first-audio path — `captioned_tts.py:225-233`).
- **Assert (voice-only no-schedule):** Avatar OFF, full conversation → zero
  `lk.avatar.lipsync` frames (room `DataReceived` audit or agent logs). Avatar ON
  → frames present, lip-sync tracks words. Drop the channel for one utterance →
  Path-A fallback, no breakage.

| Check | Target | Observed | PASS/FAIL |
|-------|--------|----------|-----------|
| Avatar-OFF peak VRAM < 15360 MB | yes | | **PENDING** |
| Avatar-ON VRAM delta | ~0 | | **PENDING** |
| e2e/tts_ttfb P50/P95 OFF vs ON within noise | yes | | **PENDING** |
| Voice-only emits no `lk.avatar.lipsync` | 0 frames | | **PENDING** |
| Avatar-ON lip-sync tracks words / Path-A fallback on drop | yes | | **PENDING** |

**Avatar verdict:** ☐ PASS  ☐ FAIL/RE-DEFER (reason: __________)

---

### B3 — Discharge Phase 9 STT operator gates (plan 14-09 Task 4)

Run the six PENDING gates in
`.planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md`:
(1) `conformer_stream_step` decodes growing text, (2) Blackwell sm_120 torch
runs, (3) growing interim + native PnC + ~100 ms finalize + `stt_ms` non-null,
(4) voice-to-voice P50<1.0s both LLMs (shares B1 evidence), (5) RNNT stall
watchdog recycles without a premature FINAL, (6) VRAM co-residency 3 procs under
16 GB. Fill that runbook's result tables and its operator sign-off line, then:

```bash
git add .planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md
git commit -m "test(14-09): discharge Phase-9 STT operator gates on RTX 5090"
```

**Phase-9 verdict:** ☐ all PASS  ☐ gaps/re-defer recorded in 09-STT-VERIFY.md

---

### B4 — Discharge Phase 10 placement + Phase 11 deploy gates (plan 14-09 Task 5)

**Phase 10** — `.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md`:
run the 8 PENDING gates, especially the 4-cell {E2B,E4B}×{GPU,CPU} co-residency
matrix (peak < 15360, 3 vs 2 GPU procs), resolve-once/no-thrash on Fast↔Better
swap, and the `STT_FORCE_CPU` global pin. Flip the safe default
(`STT_FORCE_CPU=1→0` + `STT_HEADROOM_MEASURED=1`) **only** if Gates 1–5 pass.

**Phase 11** — `.planning/phases/11-consumer-gpu-deployment-part-e/11-DEPLOY-VERIFY.md`:
run the 7 PENDING gates (default CPU-STT boot healthy; GPU-STT opt-in
`--profile stt-gpu`; `gpu-doctor.sh` on all-OK / toolkit-missing / sub-spec
hosts; no-hung-`up`). Also exercise the new `./install.sh` on a clean machine
(14-07) and `./down.sh`.

```bash
git add .planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md \
        .planning/phases/11-consumer-gpu-deployment-part-e/11-DEPLOY-VERIFY.md
git commit -m "test(14-09): discharge Phase-10 placement + Phase-11 deploy operator gates"
```

**Phase-10 verdict:** ☐ all PASS  ☐ gaps/re-defer recorded in 10-PLACEMENT-VERIFY.md
**Phase-11 verdict:** ☐ all PASS  ☐ gaps/re-defer recorded in 11-DEPLOY-VERIFY.md

---

### B5 — Consolidated release UAT (plan 14-09 Task 6 Step 1)

Aggregate the per-plan manual checks into one browser pass on the running stack:

- **Feel A/B (14-01):** Converse feels Whisper-era snappy vs the pre-retune
  build; interrupts cut TTS; openings transcribed; Interview keeps patience.
  Settle final feel values into the table below. → ☐
- **Themes (14-02) / Orbs (14-08):** six themes switch + persist (`adept.theme`
  in localStorage); reduced-motion static frame; orb audio + state reactive; no
  console errors setup→talk. → ☐
- **Avatar (14-03/14-04):** idle reads engaged (idle micro-expressions resume);
  framing reflows by breakpoint; lip-sync tracks words Avatar-ON; voice-only
  emits no schedule channel (cross-ref B2). → ☐
- **Presets (14-05):** pick → edit → start; voice/mood applied; default GLB
  reused. → ☐
- **Lifecycle (14-06):** new/reset/end teardown leaves no residue; transcript
  export txt/md; mic-denied prompt; garbled reprompt. → ☐
- **Install (14-07):** clean-machine `./install.sh` → run → `./down.sh`. → ☐

---

## Consolidated Phase-14 gate table

Legend: **SIGNED** = proven in PART A (sandbox) · **OPERATOR** = pending RTX 5090
(see PART B / the linked runbook) · **CODE-COMPLETE** = landed + build-green in
its wave plan, live UAT deferred to B5.

| Requirement | What it gates | Verdict |
|-------------|---------------|---------|
| PERF-04 | voice-to-voice P50<1.0s / P95<1.5s both LLMs; STT finalize sub-100ms; avatar zero-VRAM + no latency regression; voice-only byte-for-byte | **OPERATOR** (B1, B2) |
| FEEL-01 | mode-aware endpointing (`endpointing_for_mode`) | SIGNED selector (A3) · feel UAT **OPERATOR** (B1, B5) |
| FEEL-02 | VAD onset + barge-in retune | code-complete (14-01) · UAT **OPERATOR** (B1, B5) |
| UI-01/02/03 | v4 themes + persistence + reduced-motion | CODE-COMPLETE (14-02) · UAT **OPERATOR** (B5) |
| AVTR-09 | audio-reactive orb | CODE-COMPLETE (14-02/14-08) · UAT **OPERATOR** (B5) |
| AVTR-10/11 | avatar idle-fix + responsive framing | CODE-COMPLETE (14-03) · UAT **OPERATOR** (B5) |
| AVTR-12 | voice-only lip-sync OFF-gate (no `lk.avatar.*`) | **SIGNED** static audit (A1) · live no-schedule **OPERATOR** (B2) |
| AVTR-13 | word-accurate lip-sync Avatar-ON / Path-A fallback | code-complete (14-04) · UAT **OPERATOR** (B2) |
| DEPLOY-06/07 | `install.sh` + `down.sh` | bash-n/PATH-shim SIGNED (14-07) · clean-machine run **OPERATOR** (B4/B5) |
| SESS-01..04 | session lifecycle teardown + transcript export | CODE-COMPLETE (14-06); `test_transcript_gate` **SIGNED** (A3) · UAT **OPERATOR** (B5) |
| REL-01/02 | mic-denied prompt + garbled reprompt | CODE-COMPLETE (14-06); `test_transcript_gate` **SIGNED** (A3) · UAT **OPERATOR** (B5) |
| Phase-9 STT gates | NeMo decode / sm_120 / finalize / watchdog / co-residency | **OPERATOR** (B3 → 09-STT-VERIFY.md) |
| Phase-10 placement gates | ONNX export / mel-parity / co-residency matrix / pin / flip | **OPERATOR** (B4 → 10-PLACEMENT-VERIFY.md) |
| Phase-11 deploy gates | toolkit / boot / doctor / no-hung-up | **OPERATOR** (B4 → 11-DEPLOY-VERIFY.md) |

---

## Final tuned feel values (resolving PRD §10's open question)

Shipped defaults below are the documented starting points; the operator records
the final A/B-settled values in B1/B5. Values are the named constants — never
inline literals in code.

| Constant | Source | Shipped default | Final (operator) |
|----------|--------|-----------------|------------------|
| `CONVERSE_MIN_DELAY` | `agent/endpointing.py:14` | 0.3s | |
| `CONVERSE_MAX_DELAY` | `agent/endpointing.py:15` | 3.0s | |
| `INTERVIEW_MIN_DELAY` | `agent/endpointing.py:18` | 0.7s | |
| `INTERVIEW_MAX_DELAY` | `agent/endpointing.py:19` | 5.0s | |
| `VAD_ACTIVATION_THRESHOLD` | `agent/main.py:108` | 0.6 | |
| `INTERRUPT_MIN_DURATION_S` | `agent/main.py:114` | 0.25s | |
| `FALSE_INTERRUPT_TIMEOUT_S` | `agent/main.py:115` | 2.0s | |

---

## Sign-off

**PART A (self-checkable):** SIGNED GREEN by the executor (sandbox, no GPU) —
evidence recorded in §A1–A4.

**PART B (operator):** PENDING.

**Operator:** _______________  **Date:** _______________  **GPU: RTX 5090**

**Release decision:** ☐ all PERF-04 + Phase 9/10/11 gates PASS → ship  ☐ gaps re-deferred (reasons recorded above + in the linked runbooks)
