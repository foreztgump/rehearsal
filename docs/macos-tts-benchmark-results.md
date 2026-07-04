# macOS Kokoro TTS benchmark — results

Measures whether native Kokoro is worth adding to the macOS topology. Method +
rationale: `scripts/bench-kokoro-macos.md`, `docs/adr/0001-*`, `docs/adr/0002-*`.
Deciding metric: short-sentence synthesis **latency P50** through
`/dev/captioned_speech`; RTF is the hardware-comparable secondary.

## Environment

- **Machine:** MacBook Air M5, macOS 26.5.2 (arm64), on AC power. Docker Desktop
  29.6.1. Each arm run alone (other arms stopped) so nothing competed for CPU/GPU.
- **Date:** 2026-07-04. Benchmark commit: this branch.
- **Backend reality:** upstream Kokoro-FastAPI v0.6.x dropped the ONNX runtime, so
  both native arms run **PyTorch** (`start-cpu.sh` → torch CPU; `start-gpu_mac.sh` →
  torch MPS). Docker baseline is the pinned v0.5.0 CPU image. See ADR 0001.
- **Corpus:** 4 short persona openers × 10 = 40 warm samples per arm (3 warmups
  discarded after one cold-start call). Voice `af_bella`, speed 1.0, avatar OFF.

## Results

| Arm | Backend | Cold-start (ms) | Latency P50 (ms) | Latency P95 (ms) | RTF P50 | Δ P50 vs prev rung |
|-----|---------|-----------------|------------------|------------------|---------|--------------------|
| docker-cpu (baseline) | PyTorch CPU, v0.5.0 | 824 | **799.1** | 864.3 | 0.202 | — |
| native-cpu | PyTorch CPU, v0.6.0-rc1 | 1364 | **433.3** | 465.8 | 0.110 | −365.8 / −45.8% |
| native-metal | PyTorch/MPS | 2141 | **257.1** | 784.7 | 0.064 | −176.2 / −40.7% |

### Confirmation on the pinned tag (v0.5.0)

The native arms above ran on upstream `master` (version string `v0.6.0-rc1`, never a git
tag). Re-ran both on the **`v0.5.0`** tag we plan to pin (same tag as the Docker baseline
image, so this also removes the version-skew confound) — medians reproduce within ~2 ms:

| Arm | v0.5.0 P50 | v0.5.0 P95 | v0.5.0 cold-start | RTF |
|-----|-----------|-----------|-------------------|-----|
| native-cpu (v0.5.0) | 431.0 | 464.1 | 1354 | 0.109 |
| native-metal (v0.5.0) | 255.8 | 310.3 | 1125 | 0.063 |

The pin is safe. (On this v0.5.0 run Metal's tail was tighter — P95 310 ms, cold-start
1125 ms — than the earlier master run's P95 785 / cold 2141 ms; one 40-sample run each, so
treat that as noise, not a reversal. native-CPU stays the recommended default regardless.)

Prior in-stack reference (agent metrics on M5, full pipeline): `tts_ttfb` P50 ~1752 ms.
**The isolated docker-cpu baseline (799 ms) is already ~2× faster than that in-stack
number** — so most of the in-stack TTS cost is pipeline co-residency contention, not
Docker-VM overhead. Numbers here are Kokoro-alone; the full stack will land higher.

Raw JSON lines from `bench_kokoro_tts.py` (one per arm):

```
{"arm": "docker-cpu", "base_url": "http://localhost:8880", "samples": 40, "cold_start_ms": 823.9, "latency": {"p50_ms": 799.1, "p95_ms": 864.3, "min_ms": 707.9, "mean_ms": 794.0}, "rtf_p50": 0.202}
{"arm": "native-cpu", "base_url": "http://localhost:8880", "samples": 40, "cold_start_ms": 1363.9, "latency": {"p50_ms": 433.3, "p95_ms": 465.8, "min_ms": 381.8, "mean_ms": 428.8}, "rtf_p50": 0.11}
{"arm": "native-metal", "base_url": "http://localhost:8880", "samples": 40, "cold_start_ms": 2140.8, "latency": {"p50_ms": 257.1, "p95_ms": 784.7, "min_ms": 218.3, "mean_ms": 290.0}, "rtf_p50": 0.064}
```

## GPU-contention test (the number the isolated bench couldn't give)

On macOS the LLM (Ollama) already runs on Metal, so Metal-TTS shares the GPU with it
while CPU-TTS does not. Isolated numbers can't see that. A full voice turn can't be
driven headless (no mic over SSH), but GPU contention lives below LiveKit, so we
reproduced it directly: a background Ollama-on-Metal generation loop running flat-out
while the SAME 40-sample Kokoro bench runs (v0.5.0, P50):

| TTS backend | Ollama idle | Ollama saturating Metal | Degradation |
|-------------|-------------|-------------------------|-------------|
| Metal-TTS | 256 ms | **344 ms** | +88 ms / +34% |
| CPU-TTS | 433 ms | **485 ms** | +52 ms / +12% |

**Metal-TTS wins in BOTH conditions** — 344 ms under contention still beats CPU-TTS's
485 ms by ~140 ms. Metal degrades more (it fights for the GPU); CPU degrades less (it
only shares memory bandwidth) — but Metal never loses its lead.

> Two honest caveats: (1) the probe pins Ollama at 100% continuously; a real turn
> interleaves LLM + TTS rather than saturating, so +34% is closer to a worst-case
> ceiling than typical — which only favours Metal further. (2) Fanless-M5 thermal
> throttling over a long session is unmeasured (this was a ~90 s test).

## Verdict

Applying the pre-registered ADR-0002 rule to the deciding metric (short-sentence P50):

- native-cpu vs docker-cpu: −365.8 ms / −45.8% → clears ≥300 ms **and** ≥25% → **adopt**.
- native-metal vs native-cpu: −40.7% → clears ≥25% → **adopt**.

**Decision: adopt native-metal as the default.** On the pinned v0.5.0 tag it beats
native-cpu on P50 (256 vs 433 ms), P95 (310 vs 464 ms), AND cold-start (1125 vs 1354 ms)
— the earlier "fatter tail / worse cold-start" reading came from a single noisy run on
untagged `master` (P95 785 / cold 2141) that did **not** reproduce on v0.5.0. The
contention test then confirmed Metal keeps its lead even while Ollama saturates the GPU.
Install cost is identical to CPU (same clone, venv, and `torch==2.8.0` wheel — MPS is
built in), and the choice is a single env-var flag, so it is cheap to reverse.

Keep **native-cpu as a documented one-flag fallback** for anyone who hits MPS trouble
(upstream Mac issues remsky/Kokoro-FastAPI#270) — not the default.

> Correction note: an earlier revision of this doc recommended native-cpu as default on
> a tail/cold-start argument. That argument was based on the master run and was retracted
> once v0.5.0 re-measurement + the contention test showed Metal wins across the board.

**Follow-up:**
1. Flip the INSTALLATION.md macOS note from "native Kokoro is unmeasured" to the
   measured outcome (native-metal ~256 ms P50 isolated / ~344 ms under LLM contention,
   vs 799 ms Docker CPU; native-cpu ~433 ms as the fallback).
2. Open a scoped change to add native-host Kokoro (a second native service beside
   Ollama: installer detect/guide + a `docker-compose` override that points
   `KOKORO_BASE_URL` at `host.docker.internal:8880` + validation-checklist steps),
   mirroring the native-Ollama pattern. Default `--metal`, document the CPU fallback.
3. Separately investigate the in-stack contention (799 ms alone vs 1752 ms in-stack) —
   the bigger latency lever may be pipeline scheduling, independent of native TTS.
