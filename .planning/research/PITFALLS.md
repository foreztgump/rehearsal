# Pitfalls Research

**Domain:** v1.1 local-first pipeline swap + optional avatar on a shipped, latency-critical voice agent (LiveKit Agents + two community-GGUF Ollama LLMs + NeMo Nemotron streaming ASR + Kokoro + optional TalkingHead client avatar) on a 16GB-VRAM consumer GPU via `docker compose up`
**Researched:** 2026-06-26
**Confidence:** HIGH (verified against the Nemotron-Speech-Streaming model card + its open HF discussion on RNNT decoder stalls; Ollama/HF GGUF chat-template-drift threads; TalkingHead README rig/blendshape requirements; NVIDIA Container Toolkit issue tracker. Specific VRAM co-residency numbers are estimates flagged inline and MUST be measured per Part C.)

> This is the **v1.1 milestone** pitfalls set — it REPLACES the v1.0 research. The v1.0 pitfalls (latency compounding, first-sentence TTS, KB prefix cache, open-mic VAD/echo, endpointing, 16GB OOM, history TTFT, document parsing, LiveKit HTTPS/WebRTC) are SHIPPED-AND-DEFENDED invariants — they are now *regression surfaces* the v1.1 swaps must not break, not fresh risks. Everything below is specific to ADDING the v1.1 changes (Parts A–D + deployment) on top of that shipped system. The headline metric is unchanged: voice-to-voice **P50 < 1.0s / P95 < 1.5s**, and it must hold for **both** LLM choices, with the avatar adding **zero** server VRAM and **zero** latency regression.

**Phase tags used below** (the roadmap is not yet drawn; these map to the milestone's named parts):
- **A** = LLM swap (two user-selectable community GGUF Ollama models)
- **B** = STT swap (NeMo Nemotron streaming behind a local HTTP server, LiveKit plugin)
- **C** = VRAM-aware STT placement (GPU-NeMo vs CPU-ONNX, resolved at session start)
- **D** = Optional client avatar (TalkingHead Path-A, frontend-only)
- **DEPLOY** = consumer-machine `docker compose up` / GPU passthrough
- **POLISH** = deferred v1.0 Phase-7 work folded into v1.1

---

## Critical Pitfalls

### Pitfall A1: A community GGUF ships a broken/simplified chat template — the model degrades silently

**What goes wrong:**
Both v1.1 models are community re-quants (`evalengine/unbound-e2b`, `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf`). When Ollama imports a third-party GGUF, the embedded/registry-served chat template frequently is NOT the official Gemma-4 renderer — it's a simplified Go `TEMPLATE` string that drops turn markers, mishandles the system block, or emits the wrong BOS/EOS. The model still *runs* and *sounds* coherent, so it passes a smoke test, but it's being fed malformed turns: degraded instruction-following, weaker persona adherence, and — critically here — a frozen-prefix layout whose bytes no longer match what v1.0's KB prefix cache was tuned for.

**Why it happens:**
Ollama uses a hand-written Go renderer for *official* Gemma-4 tags but falls back to the GGUF's bundled (often partial) template for imported community tags. The HF→Ollama compatibility layer is documented to "serve a simplified template for Gemma 4 GGUF despite the full `tokenizer.chat_template` being present in metadata." A partial template "can fix basic chat while still breaking tools, thinking, and parser behavior."

**How to avoid:**
- Per-build, dump and diff the served template: `ollama show <tag> --template` and `ollama show <tag> --modelfile`. Compare against the stock `gemma4:e2b`/`gemma4:e4b` template. Any structural difference (missing `<start_of_turn>`/`<end_of_turn>`, altered system handling) → reject the build or override with a Modelfile `FROM <tag>` + correct `TEMPLATE`.
- Pin BOS/EOS/stop strings explicitly in the Modelfile; don't trust the import.
- This is the trigger for the **stock-fallback ladder** PROJECT.md mandates (`gemma4:e2b`/`gemma4:e4b`).

**Warning signs:**
`ollama show --template` differs from the stock tag; persona instructions followed worse than v1.0 E4B; KB turn-2 TTFT no longer drops (prefix bytes shifted).

**Phase to address:** A (per-build template verification before wiring the picker).

---

### Pitfall A2: "Thinking off" is set but reasoning artifacts still leak into the spoken reply

**What goes wrong:**
v1.0 disabled Gemma reasoning via `with_ollama(reasoning_effort="none")`. A community abliterated finetune can ignore that — the abliteration/finetune may have baked a reasoning scaffold into the weights, or the broken template (A1) doesn't honor the think-suppression path. Result: stray `<think>`, `<|think|>`, `<|channel|>`, `<|start|>assistant`, `analysis`/`final` channel markers, or a visible chain-of-thought preamble appear in the token stream. Because v1.0 starts TTS on the **first completed sentence**, the very first thing Kokoro speaks can be a literal "`<think>`" or a rambling reasoning sentence — audible, latency-inflating, and persona-breaking.

**Why it happens:**
`reasoning_effort="none"` maps to Ollama's internal `Think=false`, but that only works if the model+template actually gate reasoning on it. Abliterated/uncensored finetunes are trained to *not* gate behavior, and a simplified template (A1) often omits the conditional that strips the think block. The artifact then flows straight into the first-sentence splitter.

**How to avoid — concrete pre-commit artifact check (the A.5 gate the downstream consumer asked for):**
Ship a scripted, non-interactive gate run per build, BEFORE the model is selectable:
1. Fire N≥20 prompts through the **exact** v1.1 request path (same `reasoning_effort="none"`, same frozen-prefix system block, same `num_predict` cap), including reasoning-bait prompts ("think step by step", "show your work", multi-constraint persona turns).
2. Capture the raw streamed tokens (not the cleaned UI text).
3. **FAIL** if any output contains the artifact regex set: `</?think>`, `<\|?(think|channel|analysis|final|start|end|message)\|?>`, `<\|assistant\|>`, leading "Let me think"/"Reasoning:" preambles, or any non-printable control-token text.
4. **FAIL** if first-sentence-boundary content is a reasoning sentence rather than a direct answer (assert sentence 1 has no meta-cognition markers).
5. PASS requires 0 artifacts across all N for BOTH models; any FAIL → fall back to the stock tag and re-run the gate on the fallback.
Wire this as a CI/preflight script keyed off the model tag so it re-runs on every build bump (community tags mutate under the same name — see A4).
- Defense in depth: keep a token-stream sanitizer that drops known artifact tokens before the sentence splitter, so a regression degrades gracefully instead of speaking `<think>`. But the sanitizer is a backstop, not the gate — the gate must pass on raw output.

**Warning signs:**
Kokoro speaks "think" or a meandering preamble; first-sentence TTS TTFB climbs vs v1.0; transcript shows bracketed tokens; P50 regresses only on the new models.

**Phase to address:** A (the A.5 verification gate; blocks making either model selectable).

---

### Pitfall A3: The abliterated model removes the only refusal — persona prompt is now the SOLE content guardrail, and a swap can silently weaken it

**What goes wrong:**
v1.0's stock Gemma had model-level safety. The v1.1 models are uncensored/abliterated — those refusals are gone by design. The persona prompt's ethical boundary ("security at interview-appropriate level, not step-by-step attack instructions") is now the ONLY guardrail. The pitfall: during the LLM swap it's easy to (a) treat the guardrail as still partly model-enforced, (b) let A1's template drift mangle the system block so the boundary clause is malformed, or (c) tune the persona prose for one model and assume it transfers to the other — abliterated models follow boundary instructions less reliably, so the same prompt can hold on E4B and leak on E2B.

**Why it happens:**
The guardrail moved from weights to prompt without anyone re-validating it against an adversarial bar, because "the persona didn't change." But the *enforcer* changed completely.

**How to avoid:**
- Treat the persona's ethical-boundary clause as a tested artifact, not prose: a scripted red-team suite of boundary-probing prompts ("give me a working exploit for…", "walk me through attacking…") run against BOTH selectable models, asserting interview-appropriate deflection. Run it in the same A-gate harness as A2.
- Verify the boundary clause survives A1's template byte-for-byte (it lives in the frozen prefix).
- Keep the persona prompt **unchanged** in wording (PROJECT mandates it) but re-validate its *effect* per model. Persona text identical ≠ guardrail equivalent across two abliterated backends.

**Warning signs:**
A model complies with an attack-instruction probe; the Fast model leaks where the Better one holds; boundary clause text differs after template rendering.

**Phase to address:** A (boundary red-team in the same per-build gate as A2; this is the content-guardrail acceptance bar).

---

### Pitfall A4: Community tags are mutable `:latest` — a re-push silently changes the model under you

**What goes wrong:**
Both tags end in `:latest` and are owned by third parties. The author can re-push different weights/template under the same name. A `docker compose up` weeks later pulls a changed model that never went through the A1/A2/A3 gate — broken template or leaked reasoning ships to the user with no code change.

**Why it happens:**
`:latest` on a community namespace is not immutable; there's no pin to a digest by default.

**How to avoid:**
- Pin by manifest digest, not `:latest`, in the pull script (record the digest that passed the gate).
- Make the A-gate a hard precondition: the agent refuses to mark a model selectable unless the resident digest matches a gate-passed digest manifest. On digest mismatch → fall back to stock.
- Vendor/cache the gate-passed GGUF locally (privacy-aligned, local-first) rather than re-pulling.

**Warning signs:**
Pull size/digest changes between deploys; a previously-passing model starts leaking artifacts; no commit explains a behavior change.

**Phase to address:** A (pin + digest-gate) and DEPLOY (the pull happens at `compose up`).

---

### Pitfall B1: NeMo + torch bloats the container to several GB and a ~10-minute first build/start

**What goes wrong:**
Replacing faster-whisper with NeMo pulls in `nemo_toolkit[asr]` + a full torch/CUDA stack — multi-GB image layers and a slow first install/download. On a consumer machine doing `docker compose up` for the first time, this looks like a hang, blows past any healthcheck/start_period, and can wedge the whole stack if the agent depends on STT being ready.

**Why it happens:**
NeMo is a research toolkit, not a lean inference runtime; naive `pip install nemo_toolkit[all]` drags in training deps. The model checkpoint also downloads at first run if not baked.

**How to avoid:**
- Install the **minimal** ASR extra (`nemo_toolkit[asr]`), not `[all]`; prune training-only deps; multi-stage build so build tooling isn't in the runtime image.
- **Bake the checkpoint into the image** (or a pre-pulled volume) at build time — no first-run model download (mirrors v1.0's "bake turn-detector weights offline" decision for offline startup).
- Run NeMo behind its **own** local HTTP server container with a real healthcheck + generous `start_period`; gate the agent on STT-healthy via `depends_on: condition: service_healthy`.
- Pin torch/CUDA wheels to the consumer-GPU CUDA target (see DEPLOY1) so install is deterministic, not resolver-roulette.

**Warning signs:**
`compose up` appears to hang on first run; image is many GB larger than v1.0; healthcheck flaps; CI build times balloon.

**Phase to address:** B (NeMo server container + image diet) and DEPLOY (first-run UX).

---

### Pitfall B2: The RNNT decoder stalls after a sentence boundary — transcript freezes and speech is lost

**What goes wrong:**
A documented, open issue on `nvidia/nemotron-speech-streaming-en-0.6b`: in cache-aware streaming, the RNNT decoder can **stall after sentence boundaries**, returning the same frozen transcript for ~2–3s while the user keeps talking — and the content spoken during the stall is **lost**. In Adept this is catastrophic: the agent endpoints on stale text, replies to half an utterance, or never sees the user's actual question.

**Why it happens:**
Cache-aware RNNT maintains per-layer caches across non-overlapping chunks; certain decoder states after end-punctuation can wedge, especially with naive chunk loops copied from the tutorial. It's a model/inference-loop interaction, not just your bug.

**How to avoid:**
- Reproduce explicitly with long, multi-sentence, run-on speech (interview-style answers — exactly Adept's slow-speech profile). Assert the growing transcript never freezes for >X ms while VAD shows active speech.
- Couple finalize to LiveKit's VAD/semantic endpoint, not solely to the decoder emitting end-punctuation, so a stalled decoder can't strand a turn.
- Add a watchdog: if the partial transcript is byte-identical across K consecutive chunks while VAD is active, force a finalize/reset of decoder cache state for the next utterance.
- Track the upstream HF discussion; pin a NeMo version where it's mitigated. If unresolved, the **CPU-ONNX port (Part C) becomes the safer default** — fold this into the Part C fallback decision.

**Warning signs:**
Transcript stuck mid-sentence while the user clearly continues; agent answers a truncated question; lost words on long answers; same partial repeated in logs.

**Phase to address:** B (streaming correctness gate; feeds the C fallback decision).

---

### Pitfall B3: Streaming finalize latency / punctuation tuning regresses the STT leg instead of improving it

**What goes wrong:**
The whole point of the swap is sub-100ms finalize. But `att_context_size` (e.g. `[56,3]` vs larger right-context) trades latency against accuracy: too small right-context → worse WER/punctuation; too large → finalize latency climbs back toward (or past) faster-whisper, killing the win. Naive HTTP-server framing (large request buffers, re-running the encoder on overlapping windows like the old "buffered" approach) silently reintroduces the latency the cache-aware model exists to avoid.

**Why it happens:**
Cache-aware streaming only pays off if you feed strictly non-overlapping chunks and reuse cache state; people copy buffered-inference patterns and lose it. `att_context_size` is an under-documented knob with a real latency/accuracy curve.

**How to avoid:**
- Make `att_context_size` a config knob (PROJECT requires it) and **measure** finalize latency AND WER/punctuation at each setting against a fixed dev-set; pick the sub-100ms point that holds caps/punctuation.
- Implement the chunk loop as strictly non-overlapping with cache reuse (per the model card's cache-state API); never re-encode overlapping windows.
- Instrument the STT leg with the existing v1.0 per-stage metric (speech_id-keyed) so a finalize regression shows up in P50/P95 decomposition immediately, not as a vague "feels slower."
- Verify native punctuation/caps so you don't bolt on a separate punctuation pass (added latency) — the model provides it.

**Warning signs:**
STT stage in the per-turn metric ≥ v1.0 faster-whisper; lowercase/no-punctuation transcripts; finalize latency varies wildly with utterance length (= buffered, not streaming).

**Phase to address:** B (latency/accuracy tuning, gated by the per-stage metric).

---

### Pitfall B4: The LiveKit STT plugin contract is broken by a custom HTTP wrapper (interim vs final, timing, threading)

**What goes wrong:**
Wiring NeMo "behind a local HTTP server as the LiveKit STT plugin" means implementing LiveKit's STT/streaming interface yourself. Easy mistakes: never emitting `INTERIM_TRANSCRIPT` events (so the UI's live transcript and any partial-driven logic die), emitting final-only after a big buffer (re-adds latency), mis-timestamping so the v1.0 metric buffer mis-attributes latency, or blocking the agent event loop on a synchronous HTTP call. Any of these regress the shipped streaming UX even if STT itself is fast.

**Why it happens:**
LiveKit's built-in plugins hide this contract; a hand-rolled HTTP bridge has to replicate interim/final emission, end-of-utterance signaling, and async I/O exactly.

**How to avoid:**
- Follow LiveKit's Nemotron voice-agent example as the reference plugin shape (PROJECT cites it).
- Emit growing interim transcripts during speech + a single final within ~100ms of endpoint; map NeMo's streaming partials to LiveKit interim events.
- Use async HTTP (no blocking the agent loop); stream audio frames to the NeMo server, don't batch whole utterances.
- Validate against the existing v1.0 instruments: live two-sided transcript still grows while speaking; speech_id-keyed e2e metric still attributes the STT leg correctly; barge-in still fires.

**Warning signs:**
Transcript only appears after the user stops; metric buffer shows 0ms or implausible STT durations; agent loop stalls; barge-in lag.

**Phase to address:** B (plugin integration), regression-checked against v1.0 Phase-2 instruments.

---

### Pitfall C1: VRAM miscalculation OOMs with E4B + GPU-NeMo + Kokoro on 16GB (static param math lies)

**What goes wrong:**
The naive budget (E4B-Q4 ~5GB + NeMo-0.6B ~2GB + Kokoro ~2–3GB ≈ ~10GB) "fits 16GB" — but it ignores exactly what bit v1.0: Ollama **pre-allocates the full `num_ctx` KV cache upfront** (the `num_ctx=8192` pin), per-process CUDA context overhead (~0.5–1GB each, now THREE GPU processes minimum + NeMo's torch runtime), NeMo/torch's own allocator reserve, and fragmentation. With the heavier E4B selected, E4B + GPU-STT + Kokoro can quietly exceed 16GB → Ollama partial CPU offload (latency cliff) or OOM crash, most likely at the KB-load prefill peak.

**Why it happens:**
Adding a torch-based GPU STT process to a budget that v1.0 already called "the floor with no headroom" removes the slack. Param-size math omits KV pre-alloc + multi-process CUDA overhead — the same trap as v1.0 Pitfall 9, now worse because there's a fourth GPU resident.

**How to avoid — concrete co-residency measurement (the Part C bar the downstream consumer asked for):**
Extend the existing `scripts/vram-validate.sh` (already warms 3 models, asserts peak < 16384MB with 1GB headroom, greps for q8_0-not-F16 fallback, asserts exactly N GPU procs) into a **Part-C co-residency matrix**:
1. For each cell **{E2B, E4B} × {GPU-NeMo, CPU-ONNX} × Kokoro-resident**, at the **KB-load prefill peak** (the worst moment), with `num_ctx` pinned and Flash-Attn + q8_0 KV on:
2. Warm all residents, fire a max-context turn, sample `nvidia-smi --query-gpu=memory.used` at peak.
3. **PASS** a cell only if peak used-VRAM < (GPU_total − 1GB headroom) AND ollama logs show q8_0 engaged (not silent F16 fallback) AND no partial CPU offload in ollama logs.
4. The decision rule: if **E4B × GPU-NeMo × Kokoro** FAILS on the 16GB target → adopt PROJECT's "simplest-robust fallback": **global CPU-ONNX STT for both LLM choices** (the ONNX port is ~0.67GB, >6× realtime, negligible WER loss). If it PASSES → GPU-NeMo allowed only in the E2B cell, CPU-ONNX forced in the E4B cell.
5. Record the measured peak per cell in STATE.md (this discharges the existing "VRAM co-residency operator gate" blocker). This is an **operator gate** — the sandbox has no GPU/Docker; the matrix must be captured on the real consumer GPU.

**Warning signs:**
Latency cliffs mid-session (CPU offload); `nvidia-smi` near 100%; ollama "unable to allocate"/partial offload; OOM on first turn after KB load; q8_0 silently F16.

**Phase to address:** C (co-residency matrix is the gate that picks GPU-vs-CPU-vs-global-CPU), re-checked at the KB-load peak.

> **15a note:** the per-process CUDA-context overhead this pitfall flagged is the
> bulk of Kokoro's footprint — observed ~4–5GB on the cu128 image vs ~0.33GB weights.
> 15a Item 3 reclaims the reducible fragment via `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
> (zero latency); ~2.4–3GB context floor is irreducible and genuinely contends on the shared GPU.

---

### Pitfall C2: Mid-session GPU↔CPU STT thrashing (the failure PROJECT explicitly forbids)

**What goes wrong:**
A "smart" placement that re-evaluates VRAM during the session and migrates NeMo between GPU and CPU on the fly → model reload stalls (multi-second), cache loss, a latency spike mid-conversation, and possible OOM during the overlap when both copies are briefly resident.

**Why it happens:**
It feels efficient to free GPU "when idle." But STT must be hot every turn; reloading it is never free, and the overlap window is a VRAM spike.

**How to avoid:**
- Resolve placement **exactly once at session start**, coupled to the selected LLM, then freeze it for the session (PROJECT decision). No runtime migration. This is also listed in Out of Scope — treat any mid-session migration code as a scope violation.
- The LLM picker switching is **next-turn** and must NOT trigger STT replacement mid-session; if the user changes LLM, the placement consequence applies to the **next session**, or simply pin global CPU-ONNX so the picker is VRAM-safe with zero switching (the simplest-robust fallback).

**Warning signs:**
STT reloads in logs mid-session; a one-off multi-second stall after a quiet stretch; VRAM spike when placement "rebalances."

**Phase to address:** C (placement resolved once; assert no migration path exists).

---

### Pitfall C3: The CPU-ONNX STT port can't keep up with realtime / drifts in WER, breaking the fallback

**What goes wrong:**
The whole fallback safety net assumes the 4-bit ONNX CPU port runs >6× realtime with negligible WER loss. On a weak consumer CPU (or a busy one also running the web/agent containers), it may not hold realtime → finalize latency climbs, partials lag, the sub-100ms goal evaporates exactly when you fell back to protect VRAM. Or quantization shifts punctuation/caps enough to feed the LLM degraded turns.

**Why it happens:**
"6× realtime" is a benchmark-class-CPU figure; consumer CPUs under container contention vary widely. 4-bit quant has *some* accuracy cost.

**How to avoid:**
- Benchmark the CPU-ONNX port on the **actual target CPU under load** (agent+web+Kokoro running), not in isolation; assert realtime factor and finalize latency budgets hold.
- Reserve CPU threads for ONNX STT (set thread count / cpuset) so it isn't starved by the rest of the stack.
- Validate WER/punctuation parity against the GPU model on the dev-set; if it degrades LLM turn quality, that's a signal the global-CPU fallback isn't acceptable on this machine → surface a clear "this machine needs more VRAM/CPU" message rather than shipping a degraded experience.

**Warning signs:**
STT leg slower on CPU fallback than v1.0 GPU faster-whisper; realtime factor <1 under load; degraded transcripts only in fallback mode.

**Phase to address:** C (benchmark the fallback on target hardware, under contention).

---

### Pitfall D1: The avatar quietly touches the server pipeline (the cardinal Part-D violation)

**What goes wrong:**
"Frontend-only" erodes: someone adds a viseme/timestamp endpoint to the agent, routes TTS through a new server path to get phonemes, changes the Kokoro stream to feed lip-sync, or adds an avatar-state RPC that the pipeline awaits. Any of these makes voice-only mode no longer byte-for-byte identical, adds server cost, and risks latency regression — violating the hard Part-D constraint.

**Why it happens:**
Lip-sync "wants" phoneme/timestamp data, and the easiest place to get it is server-side. Path A exists precisely to avoid this (audio-driven visemes in the browser), but under pressure people reach for the server.

**How to avoid — concrete server-isolation guard (the Part-D guard the downstream consumer asked for):**
1. **Diff guard:** the avatar work must produce **zero diff** in the agent/server pipeline dirs (agent code, Ollama config, STT, TTS, LiveKit room logic). Add a CI check: when the avatar feature branch touches any path under the server pipeline, FAIL. Concretely — `git diff --stat <base>..HEAD -- agent/ <stt>/ <tts>/` MUST be empty for any avatar-tagged change.
2. **Byte-for-byte voice-only proof:** capture the full set of outbound server artifacts for a fixed scripted session (per-turn metrics line, LLM request bytes, TTS request/stream, frozen prefix) with avatar OFF before the avatar work and after; assert identical. Voice-only mode = pre-avatar bytes exactly.
3. **Latency non-regression:** run the v1.0 P50/P95 harness in voice-only mode after the avatar lands; assert no change vs the pre-avatar baseline.
4. **VRAM proof:** `nvidia-smi` server-side with avatar ON vs OFF must be identical (rendering is client WebGL).
The avatar consumes only the **inbound** Kokoro WebRTC audio already flowing to the browser — it is a pure subscriber.

**Warning signs:**
Any server-side file in an avatar PR; voice-only metrics differ ON vs OFF; a new TTS/viseme endpoint appears; server VRAM rises with avatar on.

**Phase to address:** D (isolation guard is the acceptance gate for the whole part).

---

### Pitfall D2: A second VAD is added for the avatar instead of reusing the LiveKit interrupt

**What goes wrong:**
To make the avatar "stop talking when the user speaks," someone wires a browser-side VAD/mic listener into the avatar component. Now there are two turn-taking sources of truth — they disagree, the avatar keeps lip-syncing after the server already barged-in (or vice versa), and the second mic tap can re-introduce echo/AEC complications the server pipeline already solved.

**Why it happens:**
The avatar feels like it needs its own sense of "is the user talking." But the server already detects user-speech-start and interrupts.

**How to avoid:**
- Drive avatar barge-in from the **existing** LiveKit user-speech-start interrupt / `streamInterrupt()` — one turn-taking source of truth (PROJECT decision). The avatar reacts to the same interrupt event that stops Kokoro; when inbound audio stops, lip-sync stops.
- No new `getUserMedia`/VAD instance for the avatar. The avatar never listens to the mic; it only consumes inbound TTS audio.

**Warning signs:**
A `getUserMedia`/VAD call in avatar code; avatar mouth keeps moving after barge-in; echo/AEC regressions appear only with avatar on; two interrupt paths in logs.

**Phase to address:** D (barge-in reuses the existing interrupt; assert no second VAD).

---

### Pitfall D3: GLB assets lack the required Mixamo rig + ARKit(52)/Oculus(15) viseme blendshapes — lip-sync silently does nothing

**What goes wrong:**
TalkingHead **requires** the GLB to have a Mixamo-compatible rig (root named "Armature") AND both ARKit (52) and Oculus (15) viseme blendshapes. A GLB from RPM/Avaturn/Sketchfab that's missing the Oculus visemes (or has a non-Mixamo skeleton) loads and renders fine but the mouth doesn't move, or animations break — a "looks done" failure that surfaces only when the avatar tries to speak.

**Why it happens:**
Many avatar exporters ship ARKit blendshapes but not Oculus visemes (or vice versa), or a different rig. The model displaying ≠ the model being lip-sync-capable. HeadAudio (Path A) specifically outputs **Oculus** viseme blendshape values — if those targets are absent, audio-driven lip-sync has nothing to drive.

**How to avoid:**
- Validate every persona's GLB at build/load: assert root "Armature" (or configured `modelRoot`), assert presence of the ARKit-52 set AND the Oculus-15 viseme morph targets by name before allowing the avatar to be selected for that persona.
- Use TalkingHead's reference models (`brunette.glb`) to confirm the pipeline before custom GLBs.
- Make the validator part of the persona↔avatar GLB mapping step, so a bad asset fails loudly at config time, not silently at speak time.

**Warning signs:**
Avatar renders but mouth is static; console errors about missing morph targets; animations don't play; works with the reference GLB, breaks with a persona's GLB.

**Phase to address:** D (GLB asset validation in the persona↔avatar mapping).

---

### Pitfall D4: Client GPU/CPU overload tanks frame rate (or fries laptops) — avatar must degrade gracefully

**What goes wrong:**
A heavy GLB + un-optimized Three.js render loop on a consumer laptop drops well below the ~30fps target, stutters lip-sync, spins fans, and on a shared-GPU machine (where the LLM/STT also use the GPU server-side, but the browser shares the *client* GPU) competes for client resources. Worst case the avatar makes the whole experience feel worse than voice-only.

**Why it happens:**
WebGL avatars are deceptively expensive; default GLBs are high-poly/uncompressed; no frame-rate floor or quality fallback is wired.

**How to avoid:**
- Compress assets (Meshopt/Draco), cap polygon/texture budgets per PROJECT's guidance.
- Target ~30fps with **graceful degradation**: detect sustained low FPS and reduce render quality / disable secondary animations / fall back to voice-only with a notice. Never let avatar rendering starve the audio path.
- Because rendering is **client-side WebGL with zero server VRAM**, the failure is local UX, not server OOM — but still measure FPS on a representative consumer laptop, not just the dev workstation.

**Warning signs:**
FPS < 30 sustained; audio stutter when avatar on; laptop thermal throttle; battery drain; jank during lip-sync.

**Phase to address:** D (performance budget + degradation path), validated on a representative client.

---

### Pitfall D5: GLB licensing forbids redistribution in a public/downloadable web app

**What goes wrong:**
Many avatar sources (Ready Player Me, Avaturn, CC BY-NC Sketchfab models) prohibit redistribution or commercial/public bundling. Baking such a GLB into a `docker compose up`-shippable app that others download = license violation, even though Adept itself is free/local.

**Why it happens:**
"It's just my avatar" — but shipping the GLB inside a distributable image redistributes the asset under whatever license it carries.

**How to avoid:**
- PROJECT already scopes this: **personal/internal use only for v1.1**; public redistribution of GLBs is Out of Scope unless licensing is re-confirmed.
- Don't bundle non-redistributable GLBs into the shipped image. Ship the reference/own-rights avatar; have users supply their own GLB for other personas, or load from a user-provided path.
- Record each persona-avatar's license + redistribution rights alongside the mapping.

**Warning signs:**
A bundled GLB from RPM/Avaturn/CC-BY-NC; no recorded license for a persona avatar; "redistribution" in the asset's terms.

**Phase to address:** D (license check gates any bundled asset) and DEPLOY (what ships in the image).

---

### Pitfall DEPLOY1: Host driver / container CUDA mismatch breaks `--gpus all` on the user's consumer machine

**What goes wrong:**
Dropping Proxmox PCIe passthrough for consumer-machine `docker compose up` exposes the classic NVIDIA Container Toolkit failures: `could not select device driver` (toolkit not installed), `nvml error: driver/library version mismatch` (host driver updated, not rebooted), or `CUDA driver version is insufficient for CUDA runtime version` (container CUDA newer than the host driver supports). On a heterogeneous consumer-GPU population this is the single most likely "it won't even start" failure — and it now affects NeMo/torch too, not just Ollama.

**Why it happens:**
The container's CUDA runtime must be ≤ the host driver's max CUDA; consumer machines have arbitrary driver versions; toolkit install/`nvidia-ctk runtime configure` + Docker restart is an easy-to-miss step; a host driver update without reboot mismatches the loaded module.

**How to avoid:**
- Pin container CUDA to a conservative version that a broad consumer driver range supports; document the minimum driver version.
- Ship a **preflight doctor**: before `compose up` proper, run `docker run --rm --gpus all nvidia/cuda:<pinned>-base nvidia-smi` and parse the result; on failure emit the exact remedy (install toolkit, `nvidia-ctk runtime configure --runtime=docker`, restart Docker, reboot after driver update).
- In compose, set the GPU reservation correctly (`deploy.resources.reservations.devices` with `driver: nvidia`, `capabilities: [gpu]`); note the known gotcha that some docker/compose versions need `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES`/`NVIDIA_DRIVER_CAPABILITIES` env to work under `compose up` even when `docker run --gpus` works.
- Detect "no GPU"/insufficient VRAM and route to the global CPU-ONNX STT fallback + smallest LLM rather than crashing.

**Warning signs:**
`could not select device driver`; `driver/library version mismatch`; works with `docker run --gpus` but not `docker compose up`; `nvidia-smi` fine on host, fails in container.

**Phase to address:** DEPLOY (GPU preflight doctor + pinned CUDA + correct compose GPU block).

---

### Pitfall DEPLOY2: Consumer machine has < 16GB VRAM (or a non-NVIDIA GPU) — the silent assumption breaks

**What goes wrong:**
v1.0 assumed a homelab RTX on a Proxmox VM. Consumer machines include 8–12GB cards, laptop GPUs, and AMD/Intel GPUs. The stack assumes 16GB NVIDIA; on smaller/non-NVIDIA hardware it OOMs, falls back to CPU silently (latency collapse), or fails GPU init entirely.

**Why it happens:**
Dropping the controlled VM removes the hardware guarantee, but the VRAM math and GPU assumptions didn't change.

**How to avoid:**
- At startup, detect GPU vendor + VRAM; branch placement: <16GB or non-NVIDIA → force global CPU-ONNX STT and the Fast/E2B LLM; surface capabilities clearly ("running CPU STT — needs ≥16GB NVIDIA for GPU STT").
- Make the C co-residency matrix (C1) parametric on detected VRAM, not hardcoded to 16GB.
- Document the minimum spec; fail with a clear message, not an OOM stack trace.

**Warning signs:**
OOM on first turn on a smaller card; CPU fallback "for no reason"; non-NVIDIA users report GPU init errors; latency far worse than spec on some machines.

**Phase to address:** DEPLOY (hardware detection → placement/model branch) feeding C.

---

### Pitfall POLISH1: Session reset / "end session" doesn't fully clear ephemeral state with the new pipeline

**What goes wrong:**
The deferred SESS-01/02/03 controls must clear ephemeral state — but v1.1 added new resident state: the selected-LLM session preference, NeMo decoder cache state, the avatar GLB/mood, and any session-pinned STT placement. A reset that only clears the v1.0 KB/transcript leaves the new state dangling → next session inherits a stale model choice, a wedged decoder cache (B2), or a mismatched avatar.

**Why it happens:**
The teardown was written for v1.0 state; v1.1 added state the teardown doesn't know about.

**How to avoid:**
- Extend the session-teardown audit to the v1.1 additions: reset LLM selection to default (Fast), reset/clear NeMo decoder cache, clear avatar selection, re-resolve STT placement next session. Keep v1.0's KB+transcript+KV-cache eviction.
- Verify ephemeral promise still holds (privacy): no transcript/audio/KB to disk or logs — re-check now that a NeMo HTTP server and avatar are in the loop (don't let the STT server log audio/transcripts).

**Warning signs:**
New session keeps the prior model/avatar; decoder stall persists across sessions; STT placement from a prior LLM choice lingers; NeMo server logs contain transcript/audio.

**Phase to address:** POLISH (extend teardown to v1.1 state) with a privacy re-audit of the NeMo server.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Trust the community GGUF's served chat template | Skip per-build verification | Silent degradation + KB-prefix byte drift; abliterated leak | Never — run the A1/A2 gate per build |
| `reasoning_effort="none"` and assume thinking is off | One config line | Reasoning artifacts spoken aloud on first sentence | Never — prove with the A2 artifact gate on raw tokens |
| Pin community models at `:latest` | Easiest pull | A re-push ships an ungated model to users | Never — pin by digest |
| `pip install nemo_toolkit[all]` | Fewest install errors | Multi-GB image, slow first start | Never — `[asr]` + multi-stage + baked checkpoint |
| Copy the buffered-inference chunk loop for NeMo | Works in a demo | Loses cache-aware latency win; re-encodes overlaps | Never — strict non-overlapping + cache reuse |
| Re-evaluate STT placement mid-session | "Frees VRAM when idle" | Reload stall + VRAM spike + OOM (forbidden) | Never — resolve once at session start |
| Static VRAM param-math ("fits 16GB") | No measurement needed | OOM from KV pre-alloc + 4th CUDA proc | Never — run the C1 co-residency matrix |
| Get visemes/timestamps from the server for lip-sync | Easy phoneme data | Breaks Part-D isolation; voice-only no longer byte-identical | Never — Path A audio-driven only |
| Add a browser VAD for avatar barge-in | "Avatar knows when to stop" | Two turn-taking truths; echo regressions | Never — reuse LiveKit interrupt |
| Bundle an RPM/Avaturn/CC-BY-NC GLB in the image | Nice default avatars | License violation on a downloadable app | Only assets cleared for redistribution |
| Hardcode 16GB / NVIDIA in placement | Simpler code | Breaks on consumer 8–12GB/AMD machines | Never — detect VRAM/vendor at startup |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Ollama + community GGUF | Trust imported template / `:latest` | `ollama show --template` diff vs stock; pin digest; Modelfile override |
| Ollama thinking-off on abliterated model | Assume `reasoning_effort=none` suppresses it | Raw-token artifact gate (A2) + sanitizer backstop |
| Abliterated model guardrail | Persona prose unchanged ⇒ guardrail unchanged | Red-team boundary probes per model (A3) |
| NeMo image build | `[all]` extra + first-run download | `[asr]` extra, multi-stage, bake checkpoint, healthcheck |
| NeMo RNNT streaming | Decoder stall strands turns | Couple finalize to LiveKit endpoint + stall watchdog (B2) |
| NeMo as LiveKit STT plugin | No interim events / blocking HTTP | Async streaming plugin per LiveKit Nemotron example; emit interims |
| `att_context_size` tuning | Guess the value | Measure finalize latency + WER per setting; pick sub-100ms |
| STT placement | Mid-session GPU↔CPU migration | Resolve once at session start, coupled to LLM |
| 16GB co-residency | Static param math | C1 nvidia-smi peak-at-KB-load matrix; q8_0-engaged assert |
| TalkingHead GLB | Render-OK ⇒ lip-sync-OK | Assert Mixamo rig + ARKit-52 + Oculus-15 morphs before select |
| TalkingHead Path A | Pull phonemes from server | HeadAudio worklet on inbound Kokoro WebRTC audio only |
| Avatar barge-in | New browser VAD | Reuse LiveKit `streamInterrupt()` user-speech-start |
| NVIDIA Container Toolkit | Container CUDA > host driver; toolkit not configured | Pin CUDA ≤ host max; `nvidia-ctk runtime configure`; preflight `nvidia-smi` |
| docker compose GPU | `--gpus` works, `compose up` doesn't | Add `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES`/`_DRIVER_CAPABILITIES` env |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Reasoning artifact spoken first | First TTS chunk says "think"; P50 up on new models | Raw-token A2 gate + sanitizer | Any abliterated build that ignores think-off |
| Buffered (not cache-aware) NeMo loop | STT leg ≥ faster-whisper; latency scales with utterance | Non-overlapping chunks + cache reuse | Whenever the tutorial loop is copied naively |
| RNNT decoder stall | Transcript frozen mid-sentence; lost words | Endpoint-coupled finalize + watchdog | Long multi-sentence (interview) speech |
| KV pre-alloc + 4th GPU proc OOM | Latency cliff to CPU offload; OOM at KB load | C1 matrix; global CPU-ONNX fallback | E4B × GPU-NeMo × Kokoro on 16GB |
| CPU-ONNX can't hold realtime | Finalize slow only in fallback; RTF<1 under load | Benchmark on target CPU under contention; reserve threads | Weak/contended consumer CPU |
| Avatar FPS collapse | <30fps, audio stutter, thermal throttle | Meshopt/Draco + FPS floor + degrade to voice-only | Heavy GLB on consumer laptop |
| Avatar adds server latency | Voice-only metrics differ ON vs OFF | Part-D isolation guard (D1) | Any server-side avatar coupling |

## Security / Privacy Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Abliterated model with weak persona guardrail | Step-by-step attack instructions to the user | Red-team boundary probes per model (A3); persona clause is the sole guardrail |
| Community `:latest` re-push | Ungated/leaky model silently ships | Pin by digest; gate on gate-passed digest; vendor locally |
| NeMo HTTP server logs audio/transcripts | Private practice content leaks to disk | Disable request/transcript logging on the STT server; in-memory only |
| Avatar feature opens a server endpoint | New attack surface + breaks isolation | Path A only; no new server endpoint (D1 diff guard) |
| Non-redistributable GLB bundled | License violation in a downloadable app | Personal-use only for v1.1; ship only redistribution-cleared assets |
| GPU/STT server bound beyond LAN on consumer machine | Local models reachable externally | Bind LAN/localhost; consumer firewall; no WAN forward |
| Session reset misses new v1.1 ephemeral state | Stale model/avatar/decoder cache + leak | Extend teardown audit to v1.1 state (POLISH1) |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No feedback during NeMo first-run download | "App is hung" on first `compose up` | Bake checkpoint; show "preparing speech model…" with progress |
| LLM picker switch feels instant but isn't byte-stable | Next turn slow / artifacts after switch | Default Fast; switch next-turn; re-run A-gate per model so neither leaks |
| Avatar on by default | Latency/FPS surprise; not byte-for-byte voice-only | Default Voice-only; avatar opt-in toggle |
| Avatar mouth static (missing Oculus visemes) | "It's broken" | Validate GLB blendshapes at config; fail loudly there |
| GPU-mismatch crash on `compose up` | Wall of CUDA errors, no path forward | Preflight GPU doctor with exact remedy text |
| Garbled/empty NeMo transcript answered as a turn | Agent replies to noise (REL-02) | Reprompt on empty/low-confidence finalize |
| Mic-permission denial unhandled (REL-01) | Blank app, no audio | Detect getUserMedia failure; clear message + secure-context hint (v1.0 invariant) |

## "Looks Done But Isn't" Checklist

- [ ] **LLM template:** Often missing the per-build diff — verify `ollama show --template` matches stock Gemma-4 structure for BOTH models.
- [ ] **Thinking-off:** Often missing the raw-token check — verify 0 reasoning artifacts across ≥20 reasoning-bait prompts on RAW streamed tokens, both models (A2 gate).
- [ ] **Guardrail:** Often missing the per-model red-team — verify both abliterated models deflect attack-instruction probes with the unchanged persona clause.
- [ ] **Model pin:** Often missing digest pinning — verify the selectable model's digest equals a gate-passed digest, not floating `:latest`.
- [ ] **NeMo image:** Often missing the cold-machine first-run test — verify `compose up` on a clean machine doesn't hang and the checkpoint is baked, not downloaded.
- [ ] **RNNT stall:** Often missing the long-speech test — verify the transcript never freezes during a 30s+ run-on interview answer.
- [ ] **STT latency:** Often missing the per-stage decomposition — verify the NeMo STT leg ≤ v1.0 faster-whisper at the chosen `att_context_size`, with caps/punctuation intact.
- [ ] **STT plugin:** Often missing interim emission — verify the live transcript grows while speaking and the metric buffer attributes STT correctly.
- [ ] **VRAM co-residency:** Often missing the KB-load peak measurement — verify the C1 matrix passes (q8_0 engaged, <16GB−1GB) for the chosen placement, recorded in STATE.md.
- [ ] **No thrash:** Often missing the no-migration assertion — verify there is no mid-session GPU↔CPU STT code path.
- [ ] **CPU fallback:** Often missing the under-contention benchmark — verify CPU-ONNX holds realtime with agent+web+Kokoro running.
- [ ] **Avatar isolation:** Often missing the server-diff guard — verify zero server-pipeline diff + byte-for-byte voice-only + identical server VRAM ON vs OFF (D1).
- [ ] **Avatar barge-in:** Often missing the no-second-VAD check — verify avatar stop is driven by the existing LiveKit interrupt, no new getUserMedia.
- [ ] **GLB rig:** Often missing the blendshape assert — verify Mixamo rig + ARKit-52 + Oculus-15 present before a persona's avatar is selectable.
- [ ] **Avatar FPS:** Often missing the consumer-laptop test — verify ~30fps with graceful degradation, no audio stutter.
- [ ] **GLB license:** Often missing the redistribution check — verify no non-redistributable GLB is bundled in the shipped image.
- [ ] **GPU passthrough:** Often missing the clean-machine + compose-vs-run test — verify `docker compose up` (not just `docker run --gpus`) gets the GPU, with a preflight doctor.
- [ ] **Session reset:** Often missing the v1.1-state teardown — verify reset clears LLM choice, decoder cache, avatar, and re-resolves placement.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Broken community template (A1) | LOW | Modelfile `FROM <tag>` + correct `TEMPLATE`, or fall back to stock gemma4 tag |
| Leaked reasoning artifacts (A2) | LOW–MEDIUM | Fall back to stock tag; enable token sanitizer backstop; re-run gate |
| Weak guardrail on abliterated model (A3) | MEDIUM | Strengthen persona boundary clause; re-red-team; drop the failing model from the picker |
| Mutable-tag drift (A4) | LOW | Re-pin to last gate-passed digest; vendor the GGUF locally |
| NeMo image bloat / slow start (B1) | MEDIUM | Switch to `[asr]` extra; multi-stage; bake checkpoint; add healthcheck |
| RNNT decoder stall (B2) | MEDIUM–HIGH | Endpoint-coupled finalize + stall watchdog; if unresolved, default to CPU-ONNX |
| STT latency regression (B3) | LOW–MEDIUM | Re-tune `att_context_size`; fix chunk loop to non-overlapping cache reuse |
| Plugin contract broken (B4) | MEDIUM | Re-implement interim/final emission + async per LiveKit Nemotron example |
| 16GB co-residency OOM (C1) | MEDIUM | Adopt global CPU-ONNX fallback; tighten num_ctx; confirm q8_0 KV |
| Mid-session thrash (C2) | LOW | Remove migration path; freeze placement at session start |
| CPU-ONNX too slow (C3) | MEDIUM | Reserve CPU threads; or require more VRAM and surface a clear message |
| Avatar touched server (D1) | MEDIUM–HIGH | Revert server changes; move lip-sync to Path A audio-driven; re-prove byte-for-byte |
| Second VAD added (D2) | LOW | Delete browser VAD; drive barge-in from LiveKit interrupt |
| GLB missing visemes (D3) | LOW–MEDIUM | Re-export with ARKit+Oculus blendshapes or pick a compliant GLB |
| Avatar FPS collapse (D4) | MEDIUM | Compress (Meshopt/Draco); add FPS floor + degrade-to-voice |
| GLB license violation (D5) | LOW | Remove bundled asset; ship only cleared/own-rights GLBs |
| GPU passthrough broken (DEPLOY1) | LOW–MEDIUM | Pin container CUDA; `nvidia-ctk runtime configure` + restart; preflight doctor |
| Sub-spec consumer GPU (DEPLOY2) | LOW | Detect VRAM/vendor → force CPU-ONNX + Fast LLM; clear capability message |
| Reset misses v1.1 state (POLISH1) | LOW | Extend teardown to LLM/decoder/avatar/placement; privacy re-audit |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| A1 Broken chat template | A | `ollama show --template` diff vs stock passes for both models |
| A2 Leaked reasoning (thinking-off real) | A | Raw-token artifact gate: 0 artifacts / ≥20 bait prompts, both models |
| A3 Abliterated guardrail is sole guard | A | Per-model red-team boundary probes deflect attack instructions |
| A4 Mutable `:latest` drift | A + DEPLOY | Selectable model digest == gate-passed digest |
| B1 NeMo image/startup bloat | B + DEPLOY | Clean-machine `compose up` doesn't hang; checkpoint baked |
| B2 RNNT decoder stall | B | 30s+ run-on speech never freezes; lost-word test passes |
| B3 Finalize latency/punct regression | B | STT leg ≤ v1.0 at chosen `att_context_size`; caps/punct intact |
| B4 LiveKit plugin contract | B | Interim transcript grows; metric attributes STT; barge-in fires |
| C1 16GB co-residency OOM | C | C1 nvidia-smi matrix passes (q8_0 on, <16GB−1GB) — recorded in STATE.md |
| C2 Mid-session thrash | C | No GPU↔CPU migration code path exists |
| C3 CPU-ONNX too slow | C | CPU-ONNX holds realtime under agent+web+Kokoro contention |
| D1 Avatar touches server | D | Zero server diff + byte-for-byte voice-only + identical server VRAM |
| D2 Second VAD | D | Barge-in driven by LiveKit interrupt; no new getUserMedia |
| D3 GLB rig/blendshapes | D | Mixamo rig + ARKit-52 + Oculus-15 asserted before select |
| D4 Client FPS overload | D | ~30fps + graceful degradation on a consumer laptop |
| D5 GLB license | D + DEPLOY | No non-redistributable GLB bundled in the image |
| DEPLOY1 CUDA/driver mismatch | DEPLOY | Preflight `nvidia-smi` in container passes; pinned CUDA ≤ host |
| DEPLOY2 Sub-spec consumer GPU | DEPLOY | VRAM/vendor detection routes to CPU-ONNX + Fast LLM |
| POLISH1 Reset misses v1.1 state | POLISH | Teardown clears LLM/decoder/avatar/placement; privacy re-audit |

## Sources

- nvidia/nemotron-speech-streaming-en-0.6b model card (Cache-Aware FastConformer-RNNT, 24 layers, native punctuation/caps, cache-state streaming API): https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
- nemotron-speech-streaming-en-0.6b HF discussion #5 — **RNNT decoder stalls after sentence boundaries in streaming mode** (transcript freezes ~2.7s, content lost; uses the official cache-aware tutorial loop): https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/discussions/5
- nvidia/nemotron-3.5-asr-streaming-0.6b model card (latency-vs-concurrency, 80ms setting, buffered-vs-cache-aware): https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b
- NeMo Framework — cache-aware streaming ASR; ONNX export needs `cache_support=True`: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/models.html
- HF discuss — Ollama registry serves a **simplified Gemma-4 chat template** despite full `tokenizer.chat_template` in GGUF (official tags use a Go renderer; imports fall back): https://discuss.huggingface.co/t/ollama-model-registry-provides-wrong-chat-template/176139
- HF discuss — GGUF vs Ollama: template/stop-token/context drift makes "same weights, different results"; template is high-impact: https://discuss.huggingface.co/t/gguf-vs-ollama-direct-pull-which-one-actually-performs-better-need-guidance/175181
- Netclaw / llama.cpp troubleshooting — buggy GGUF templates ship broken; reasoning/`<think>` leakage without correct `--jinja`/`--reasoning-format`; serve corrected templates: https://netclaw.dev/troubleshooting/llama-cpp
- Unsloth — wrong chat template / wrong EOS → gibberish; must match training template: https://unsloth.ai/docs/basics/inference-and-deployment/saving-to-gguf
- met4citizen/TalkingHead README — requires Mixamo-compatible rig (root "Armature") + ARKit and Oculus viseme blendshapes; ThreeJS/WebGL; HeadAudio = audio-driven Oculus-viseme worklet (Path A): https://github.com/met4citizen/talkinghead
- VRChat lip-sync docs — Oculus viseme indices 0–14 (the 15-viseme set): https://vrcreators.net/docs/vrchat/avatar-creation/lip-sync
- NVIDIA Container Toolkit issue #394 — `nvml error: driver/library version mismatch`: https://github.com/NVIDIA/nvidia-container-toolkit/issues/394
- NVIDIA dev forums — nvidia runtime works under `docker run --gpus` but breaks under `docker compose up`; fix via `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES`/`NVIDIA_DRIVER_CAPABILITIES`: https://forums.developer.nvidia.com/t/nvidia-docker-runtime-does-not-seem-to-work-with-docker-compose/307879
- Docker GPU setup + common errors (`could not select device driver`, `no CUDA-capable device`, compose GPU block): https://oneuptime.com/blog/post/2026-01-16-docker-nvidia-gpu-ai-ml/view
- CUDA driver-insufficient errors (container CUDA > host driver): https://www.rightnowai.co/guides/cuda-errors/cuda-error-insufficient-driver
- PROJECT.md / STATE.md (Adept) — v1.1 milestone scope, Parts A–D, 16GB floor, `reasoning_effort="none"`, vram-validate.sh operator gate, frozen-prefix/KB-cache invariants, Out-of-Scope no-thrash/no-server-touch/no-redistribution

---
*Pitfalls research for: v1.1 local-first pipeline swap + optional avatar (Adept)*
*Researched: 2026-06-26*
