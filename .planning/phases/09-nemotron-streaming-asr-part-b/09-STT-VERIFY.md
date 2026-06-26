---
status: pending-operator
phase: 09-nemotron-streaming-asr-part-b
plan: 09-02
requirement_ids: [STT-01, STT-02, STT-03, STT-04]
verifies: [STT-01, STT-02, STT-03, STT-04, "conformer_stream_step signature", "Blackwell sm_120 torch", "stt_ms finalize-latency emission", "voice-to-voice P50<1.0s with new STT leg", "RNNT stall watchdog no-premature-FINAL", "VRAM co-residency (3 procs)"]
harness_note: >
  Every gate below needs the live GPU stack (Docker daemon + RTX 5090 + NeMo/torch +
  browser + LAN mic). The execution sandbox has NO GPU, NO Docker daemon, and CANNOT
  import NeMo/torch, so the entire NeMo decode path, the Blackwell sm_120 kernels, the
  ~2.4 GB model bake/build, and the live voice loop are all deferred operator gates,
  mirroring the Phase-1 VRAM gate and the Phase-2..8 operator deferrals. NONE are marked
  passed by the executor — the operator fills each result table with measured
  observations on the real GPU. What ships sandbox-verified (already green, not
  re-proven here): py_compile of agent/nemo_stt.py + agent/main.py + ollama/warmup.py,
  bash -n scripts/vram-validate.sh, NemoSTT instantiation (capabilities.streaming /
  interim_results True against livekit-agents==1.6.4), and a fake-WS unit test driving
  delta->INTERIM / final->FINAL + an explicit STTMetrics with a non-null measured
  duration that populates stt_ms through the READ-ONLY metrics scaffold.
---

# Phase 09 — Nemotron Streaming ASR (Part B): OPERATOR VERIFICATION (NeMo decode + Blackwell sm_120 + live interim/finalize + voice-to-voice P50 + RNNT stall watchdog + VRAM co-residency)

**Status:** PENDING OPERATOR — run on the Proxmox VM (Docker daemon + RTX 5090 + NeMo/torch +
browser + LAN mic). The sandbox has **no** GPU/Docker daemon and **cannot import NeMo/torch**, so
every gate below is a deferred operator gate. **None are marked passed by the executor.**

**Owns:**
- **STT-01** — faster-whisper is replaced by `nvidia/nemotron-speech-streaming-en-0.6b` served via
  NeMo behind a local websocket (`nemo-stt`), wired into the agent as a custom streaming `NemoSTT`
  plugin; faster-whisper is fully removed from agent code + host scripts + README.
- **STT-02** — a GROWING interim transcript streams while the user speaks and FINAL fires within
  ~100 ms of end-of-speech, triggered by the turn-detector flush; long run-on answers are not
  stranded (the RNNT stall watchdog recovers without a premature FINAL).
- **STT-03** — native punctuation + capitalization are surfaced AS-IS to both the transcript and
  the LLM (zero client-side post-processing).
- **STT-04** — `att_context_size` is the config knob (`STT_ATT_CONTEXT_SIZE`, default `[56,3]`); the
  cyber-vocabulary fine-tune is a documented HOOK only, NOT implemented.

---

## Frozen-contract notes (read before running any gate)

- **Endpoint authority is UNCHANGED.** Silero VAD + the local `MultilingualModel` turn detector
  remain the SOLE endpoint authority. The `turn_handling` dict in `build_session` is untouched. NeMo
  does **not** own turn-taking — the turn detector decides end-of-utterance, AgentSession calls
  `end_input()`/`flush()`, the plugin forwards `{"type":"flush"}`, and only THEN does the server
  emit `final`. This preserves the single-turn-source invariant from v1.0.
- **The server NEVER auto-finalizes.** The RNNT stall watchdog recycles decoder state (resets
  `prev_hyps`, carries the encoder cache forward) while audio is still arriving — it logs the
  recycle and continues; it does **not** emit a premature FINAL. FINAL is emitted ONLY in response
  to a `flush` control frame.
- **Native PnC surfaced as-is.** The model emits punctuation + capitalization natively; the plugin
  passes `delta`/`final` text through verbatim — no lowercase/strip/recapitalize anywhere.
- **`agent/metrics.py` is READ-ONLY.** The plugin FEEDS it via an explicit `metrics_collected` emit;
  the per-turn JSON shape is frozen. No metrics.py edit this phase (verify `git diff agent/metrics.py`
  is empty).
- **Single-source model tag, no hardcoded literal in code.** `STT_MODEL` (build ARG + Compose env)
  is the single source for the model; `STT_ATT_CONTEXT_SIZE` (default `[56,3]`) is the knob. There
  is no `nvidia/nemotron-speech-streaming` literal in `stt/server.py` or agent code — the model
  string in `agent/nemo_stt.py` is a metrics **label** only, not a behaviour driver.

---

## PINNED: `stt_ms` semantics (RESEARCH §5 — the load-bearing gotcha)

**`stt_ms` = FINALIZE LATENCY (flush → final wall-clock seconds).** Measured in
`NemoSpeechStream._emit_final` as `time.perf_counter() - self._flush_started`, where
`_flush_started` is stamped the instant the flush sentinel is sent over the websocket, and the
delta is taken when the server's `final` message is received. It is emitted as
`STTMetrics(duration=<that delta>, streamed=True, ...)` and read by `metrics._on_stt_metrics`
(`buffer.stt_ms = _seconds_to_ms(metric.duration)`).

This is the **load-bearing line**: the LiveKit streaming path does NOT auto-emit a timed
`STTMetrics` (the base monitor hardcodes `duration=0.0` for `streamed=True`). Without the explicit
emit, `stt_ms` would stay **NULL forever**. The faster-whisper `openai.STT` worked only because it
is non-streaming and emitted a real `duration`.

`stt_ms` (finalize latency) is compared against **`BUDGET_MS["stt"]=150`** (`agent/metrics.py:34`)
and should tighten toward the ~100 ms target (STT-02 / PERF-04). The `e2e` line is gated by
`BUDGET_MS["e2e"]=1200`. **State for the record:** the P50 STT gate below is the FINALIZE leg, not
full transcription latency — pick-one is pinned here so the gate is unambiguous.

---

## 0. Build / deploy BEFORE verifying (stale-deploy / baked-image guard)

The stack runs from **baked images** — a code edit is NOT live until the image is rebuilt. The
`nemo-stt` image bakes the ~2.4 GB `.nemo` at build time (offline-capable) and loads it resident at
container start, so the build is multi-GB and the first `up` waits on a generous healthcheck
`start_period`. Always rebuild + restart, with `nemo-stt` healthy BEFORE the agent, before any live
gate:

```bash
# from the repo root on the VM
set -a && . ./.env && set +a
docker compose build nemo-stt agent
docker compose up -d
docker compose ps              # nemo-stt: healthy; agent: Up (started after nemo-stt healthy)
```

If `agent` comes up before `nemo-stt` is healthy, the `depends_on: { nemo-stt: { condition:
service_healthy } }` gate is misconfigured — fix before proceeding.

---

## Gate 1 — `conformer_stream_step` signature confirmation (RESEARCH §1 ⚠️, Risk 1)

**Goal:** the NeMo cache-aware decode call matches the in-container `nemo.collections.asr` source
for the pinned NeMo version (the signature drifts across minors), and the server decodes a real
clip to growing text.

**Steps (in-container — target the SAME NeMo the server runs):**

```bash
# confirm the call signature against the installed NeMo source
docker compose exec nemo-stt python -c "
import inspect, nemo.collections.asr as a
import nemo; print('NeMo version:', nemo.__version__)
from nemo.collections.asr.models import EncDecRNNTModel
print(inspect.signature(EncDecRNNTModel.conformer_stream_step))"

# decode a real clip through the server's own offline path (or the WS) and confirm growing text
docker compose logs nemo-stt | tail -40
```

**ASSERT:** the printed `conformer_stream_step` signature includes the params the server passes
(`processed_signal`, `processed_signal_length`, `cache_last_channel`, `cache_last_time`,
`cache_last_channel_len`, `keep_all_outputs`, `previous_hypotheses`, `return_transcription`); a real
clip produces a cumulative growing transcript; no signature `TypeError` in the logs.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| NeMo version pinned in image | (record) | |
| `conformer_stream_step` signature matches server call | yes | |
| real clip → growing cumulative text | yes | |
| **Gate 1 verdict** | PASS | **PENDING** |

---

## Gate 2 — Blackwell sm_120 torch execution (RESEARCH Risk 2 — the Kokoro-class gate)

**Goal:** the `nemo-stt` image runs sm_120 kernels on the RTX 5090 — no *"no kernel image is
available for execution on the device"* crash (the precedent: Kokoro's stock image bundled
sm_50..sm_90 torch and crashed on Blackwell until a CUDA-12.8 build).

**Steps:**

```bash
docker compose exec nemo-stt python -c "
import torch
print('torch:', torch.__version__, 'cuda:', torch.version.cuda)
print('device:', torch.cuda.get_device_name(0))
print('sm capabilities:', torch.cuda.get_arch_list())
x = torch.randn(1024, 1024, device='cuda'); y = (x @ x).sum().item()
print('matmul on cuda OK:', y is not None)"
docker compose logs nemo-stt | grep -i 'no kernel image' || echo 'no sm_120 kernel crash'
```

**ASSERT:** `get_arch_list()` includes `sm_120` (or the build runs the matmul without error); no
*"no kernel image is available"* line in the logs; the model actually loaded resident.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| torch CUDA build (sm_120 present / matmul runs) | yes | |
| no "no kernel image is available" crash | yes | |
| model loaded resident (/health 200) | yes | |
| **Gate 2 verdict** | PASS | **PENDING** |

---

## Gate 3 — interim + final stream with ~100 ms finalize + native PnC (STT-02 / STT-03)

**Goal:** speaking yields a GROWING interim transcript in the existing panel; native
punctuation/casing is surfaced as-is; the turn-detector flush finalizes within ~100 ms; final
replaces the interim in place; `stt_ms` is NON-NULL in the agent metrics line (the §5 gotcha is
closed).

**Steps:** start a live browser session, speak a multi-clause sentence ("Okay, so the SOC analyst
triages the alert, then escalates."), watch the transcript panel, and tail the agent metrics:

```bash
docker compose logs agent | grep -E '"stt_ms"|delta|final' | tail -40
```

**ASSERT:**
- the interim transcript GROWS token-by-token while speaking (cumulative re-emit), styled as the
  panel already distinguishes interim from final (no web/ change required);
- punctuation + capitalization appear natively (commas, periods, capital S in "SOC") — NOT
  lowercased/stripped;
- on end-of-speech the turn-detector flush yields a FINAL that replaces the interim in place,
  measured finalize ~100 ms;
- the per-turn metrics line shows `stt_ms` **NON-NULL** and within / near `BUDGET_MS["stt"]=150`.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| growing interim while speaking | yes | |
| native PnC surfaced as-is | yes | |
| flush → FINAL finalize latency | ~100 ms | |
| final replaces interim in place | yes | |
| `stt_ms` non-null in metrics line | yes (non-null) | |
| **Gate 3 verdict** | PASS | **PENDING** |

---

## Gate 4 — voice-to-voice P50 < 1.0s with the new STT leg (PERF-04, the headline)

**Goal:** with the NeMo STT leg swapped in, rolling voice-to-voice latency holds the headline gate;
the STT finalize leg tightens toward sub-100 ms; `e2e` stays under `BUDGET_MS["e2e"]=1200`.

**Steps:** run ~20+ real turns across both LLM choices (Fast, then Better), then read the rolling
summary emitted every `SUMMARY_EVERY_TURNS=10` turns:

```bash
docker compose logs agent | grep -E 'rolling_summary' | tail -8
```

**ASSERT:** `rolling_summary.e2e.p50` < 1000 ms (target P50 < 1.0s) and < 1500 ms P95 for BOTH LLM
choices; `rolling_summary.stt.p50` trends toward / under ~100 ms; no stage chronically `over_budget`.

**Results capture:**

| LLM choice | e2e P50 | e2e P95 | stt P50 (finalize) | PASS/FAIL |
|------------|---------|---------|--------------------|-----------|
| Fast | | | | **PENDING** |
| Better | | | | **PENDING** |

- **Gate 4 verdict: PENDING**

---

## Gate 5 — RNNT stall watchdog: no premature FINAL on a run-on answer (STT-02)

**Goal:** an interview-mode, pause-heavy, run-on answer is NOT stranded — the server recycles
decoder state and continues; it does NOT emit a premature FINAL mid-utterance (the turn detector is
the sole finalize authority).

**Steps:** enter Interview mode, give a long deliberate answer with several mid-thought pauses
("Well… let me think… so first you'd enumerate… and then… you'd pivot to lateral movement…"), and
watch both logs:

```bash
docker compose logs nemo-stt | grep -iE 'recycle|stall' | tail -20
docker compose logs agent    | grep -E 'final'         | tail -20
```

**ASSERT:** the server logs a state recycle during the run-on (text stopped growing while audio
still arrived) but emits **no** `final` until the turn-detector flush at true end-of-speech; the
agent records exactly one FINAL for the turn; the interim kept growing across the pauses.

**Results capture:**

| Check | Expected | Observed |
|-------|----------|----------|
| server recycles decoder state on stall | yes (logged) | |
| NO premature FINAL mid-utterance | yes (none) | |
| exactly one FINAL at true end-of-speech | yes | |
| **Gate 5 verdict** | PASS | **PENDING** |

---

## Gate 6 — VRAM co-residency re-check (RESEARCH Risk 4)

**Goal:** the 3 GPU processes (ollama, nemo-stt, kokoro) co-reside under the 16 GB floor with the
+2.4 GB NeMo model resident; q8_0 KV did not silently fall back to F16.

**Steps:** run the existing script (note: it now names the 3 procs ollama/nemo-stt/kokoro,
`EXPECTED_GPU_PROCS=3` unchanged):

```bash
set -a && . ./.env && set +a
./scripts/vram-validate.sh            # default
./scripts/vram-validate.sh --with-kb  # KB-load peak-memory re-check
```

**ASSERT:** the script prints `PASS` — q8_0 KV engaged (no F16 fallback), peak VRAM under the
16 GB-with-headroom ceiling WITH the NeMo model resident, exactly 3 GPU processes (ollama, nemo-stt,
kokoro — no embedder/vector store).

**Results capture:**

| Mode | q8_0 KV engaged? | peak VRAM < ceiling? | 3 GPU procs (ollama, nemo-stt, kokoro)? | PASS/FAIL |
|------|------------------|----------------------|------------------------------------------|-----------|
| no-KB | | | | **PENDING** |
| KB-loaded (`--with-kb`) | | | | **PENDING** |

- **Gate 6 verdict: PENDING**

---

## Cyber-vocabulary fine-tune HOOK (STT-04 / RESEARCH §10) — NOT IMPLEMENTED

A cyber-vocab fine-tune is a **documented seam only**; it is **NOT implemented** in Phase 9. The
single-source `STT_MODEL` build ARG + Compose env is the hook: point `STT_MODEL` at a future
fine-tuned `.nemo` checkpoint (a custom cybersecurity-vocabulary model) and `docker compose build
nemo-stt` — **ZERO code change** in `stt/server.py` or the agent (the model string in
`agent/nemo_stt.py` is a metrics label only). No fine-tune code, data, or scripts exist in this
phase. Revisit in a later phase (REQUIREMENTS STT-F1).

---

## Overall Phase-9 sign-off

| Gate | What it proves | Verdict |
|------|----------------|---------|
| 1 | `conformer_stream_step` signature matches in-container NeMo; real clip decodes to growing text | **PENDING** |
| 2 | Blackwell sm_120 torch runs on the RTX 5090 (no "no kernel image" crash) | **PENDING** |
| 3 | growing interim + native PnC + ~100 ms finalize + `stt_ms` non-null | **PENDING** |
| 4 | voice-to-voice P50 < 1.0s with the new STT leg, both LLM choices | **PENDING** |
| 5 | RNNT stall watchdog recycles without a premature FINAL on a run-on answer | **PENDING** |
| 6 | VRAM co-residency: 3 procs (ollama, nemo-stt, kokoro), q8_0 KV engaged, under 16 GB | **PENDING** |

**Operator:** _______________  **Date:** _______________  **VM/GPU:** RTX 5090

**Net posture (to be filled by the operator):** the sandbox-verifiable plugin wiring + metrics
emission are GREEN (py_compile, NemoSTT capabilities, fake-WS interim/final + non-null `stt_ms`);
the NeMo decode, Blackwell sm_120 execution, live interim/finalize, voice-to-voice P50, stall
watchdog, and VRAM co-residency are all deferred to this operator gate and **unsigned** until run on
the real consumer GPU.
