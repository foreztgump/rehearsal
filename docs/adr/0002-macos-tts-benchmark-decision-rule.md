# macOS TTS benchmark: pre-registered decision rule

The benchmark exists to decide whether to add native Kokoro to the macOS topology, so
the adoption thresholds are fixed **before** any numbers are seen — pre-registration
prevents motivated reading of the results.

The arms sit on a complexity ladder: **Docker-CPU** (shipped status quo) < **native-CPU**
(adds a second native host service beside Ollama, plus installer/doc changes) <
**native-Metal** (all of that *plus* PyTorch/MPS via upstream `start-gpu_mac.sh`, which
has open Mac issues — remsky/Kokoro-FastAPI#270 — and is the most fragile rung). Each rung
up must earn its complexity with a real latency win, judged on short-sentence P50:

- **Adopt native-CPU over Docker-CPU** only if it cuts short-sentence P50 by **≥300 ms or
  ≥25%** (whichever is more meaningful at the observed magnitude).
- **Adopt native-Metal over native-CPU** only if Metal beats native-CPU by a *further*
  **≥25%**. A tie or marginal win → prefer native-CPU (simpler, ONNX, no MPS fragility).
- **If nothing beats Docker-CPU meaningfully** → keep the status quo; the only deliverable
  is flipping the INSTALLATION.md macOS note from "native Kokoro is unmeasured" to
  "measured — not worth it."

## Consequences

Adopting a rung is not just a config flip — it pulls in a new native host service, an
installer detect/guide path, and macOS validation-checklist steps, mirroring the existing
native-host-Ollama pattern. The thresholds are deliberately high because that recurring
operator and maintenance cost, not the one-time benchmark, is what a latency win must repay.

## Outcome (2026-07-04)

Both rungs cleared their thresholds: native-CPU beat Docker-CPU by −365.8 ms / −45.8%, and
native-Metal beat native-CPU by a further −40.7%. **Adopted native-Metal as the default.**

The rule judged P50 only; two extra tests settled the tail question the rule left open:
(1) on the pinned v0.5.0 tag, native-Metal also wins P95 (310 vs 464 ms) and cold-start
(1125 vs 1354 ms) — the "fatter tail" seen once on untagged `master` did not reproduce;
(2) a GPU-contention probe (Ollama saturating Metal while Kokoro benches) showed Metal-TTS
degrades to 344 ms but still beats CPU-TTS's 485 ms, so Metal keeps its lead even sharing
the GPU with the LLM. native-CPU is retained as a documented one-flag fallback for MPS
trouble, not the default. Full numbers: `docs/macos-tts-benchmark-results.md`.
