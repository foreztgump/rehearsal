# Pitfalls Research

**Domain:** Near-real-time local voice AI agent (LiveKit Agents + faster-whisper turbo + Gemma E4B via Ollama + Kokoro) on a 16GB-VRAM homelab GPU
**Researched:** 2026-06-24
**Confidence:** HIGH (stack-specific behaviors verified against LiveKit docs, Ollama prompt-caching internals, faster-whisper streaming guidance, MDN getUserMedia; some VRAM numbers are estimates flagged inline)

> Extends the risk surface implied by PROJECT.md (Context, Constraints, Key Decisions). PROJECT.md has no §13 risk list in the current revision; the pitfalls below sharpen the latency/VRAM/KB/open-mic decisions already logged there. Sub-second voice-to-voice (P50 < 1.0s) is the metric every pitfall is measured against — a pitfall here is anything that silently adds 100–500ms or breaks the "feels live" illusion.

---

## Critical Pitfalls

### Pitfall 1: Latency compounds silently across un-instrumented stages

**What goes wrong:**
Voice-to-voice latency is a *sum* of seven stages — capture/network buffering → VAD endpoint delay → STT → LLM TTFT → first-sentence detection → TTS first-chunk → playback buffering. Each looks "fast enough" alone (80ms here, 150ms there) but they stack to 1.5–2.5s. Without per-stage timing you'll chase the wrong stage for days.

**Why it happens:**
Developers measure the LLM (the "obvious" cost) and ignore the silent additives: Silero's `min_endpointing_delay` (default 500ms) alone is half the entire P50 budget; client/jitter playout buffers add 100–200ms; a non-streamed TTS adds the full synthesis time of the whole first sentence.

**How to avoid:**
- Instrument every stage from day one. LiveKit Agents emits per-turn metrics (`EOUMetrics`/end-of-utterance delay, STT duration, LLM TTFT, TTS TTFB). Log them as a single structured line per turn and compute P50/P95 over a rolling window.
- Set an explicit per-stage budget: e.g. endpoint ≤300ms, STT ≤150ms, LLM TTFT ≤300ms, TTS TTFB ≤150ms, playout ≤100ms. Any stage over budget is the bug.
- Treat the 500ms default endpoint delay as the single biggest knob — see Pitfall 6.

**Warning signs:**
"It feels laggy" with no number attached; only one timer in the codebase (around the LLM); P95 you can't decompose.

**Phase to address:** Phase 0 (env: wire up metric logging scaffold) → Phase 1 (voice loop: enforce per-stage budgets as success criteria).

---

### Pitfall 2: Not streaming TTS on the first sentence (full-response buffering)

**What goes wrong:**
The agent waits for the *entire* LLM response before starting TTS, or waits for the *entire* TTS audio before playback. Either turns a 300ms TTFT win into a 2s wait, because Gemma generates a 3-sentence answer faster than it's spoken but you've blocked on the whole thing.

**Why it happens:**
Naive pipelines are request/response: `text = llm(); audio = tts(text); play(audio)`. Sentence-boundary streaming requires extra plumbing (token stream → sentence splitter → incremental TTS calls) that's easy to skip in a first cut.

**How to avoid:**
- Stream LLM tokens, split on the first sentence boundary (`. ! ?` + abbreviation guard), and fire TTS the instant sentence 1 is complete. Pipeline sentence N+1 synthesis while sentence N plays. PROJECT.md already mandates this ("start TTS on first completed sentence") — make it a Phase 1 gate, not a later optimization.
- Use Kokoro's streaming/chunked output; play audio frames as they arrive, don't buffer the whole utterance.
- Guard the sentence splitter against decimals, "e.g.", "Mr.", URLs, and code — a bad split mid-number produces audible glitches.

**Warning signs:**
First audio only after the agent's full text appears in the transcript; latency that scales with *response length* rather than staying flat.

**Phase to address:** Phase 1 (voice loop) — non-negotiable for the core value prop.

---

### Pitfall 3: Cold starts / keep-alive eviction (the first turn after idle is brutal)

**What goes wrong:**
After a pause, the first turn takes 5–30s because Ollama unloaded the model (default 5-minute idle unload) and must reload weights *and* re-prefill the KB prefix from scratch. The KV cache is gone too, so prefix caching gives zero benefit on that turn.

**Why it happens:**
Ollama's default `keep_alive` is 5 minutes; the cache and weights are dumped from VRAM on idle. A practice session with thinking pauses easily exceeds that.

**How to avoid:**
- Set `OLLAMA_KEEP_ALIVE=-1` (or `60m`) / pass `keep_alive: -1` per request to pin Gemma resident for the whole session.
- Warm all three models at session start (Phase 0/1 startup sequence): issue a tiny dummy inference to Gemma, faster-whisper, and Kokoro before the user's first word so weights are resident and CUDA kernels are JIT-compiled.
- After loading the KB, fire one priming turn to force the KB-prefix prefill while the user is still reading the "ready" indicator — so turn 1 is warm, not cold.
- Note the keep-alive vs. VRAM tension: pinning all three resident forever is what makes the 16GB budget tight (see Pitfall 9). This is a deliberate trade, not an accident.

**Warning signs:**
First question after a pause is dramatically slower than mid-conversation; Ollama logs show "loading model" mid-session; VRAM drops between turns.

**Phase to address:** Phase 0 (env: keep-alive config) + Phase 1 (warmup sequence) + Phase 3 (KB priming turn).

---

### Pitfall 4: Open-mic VAD false triggers on background noise (the PTT-vs-VAD decision's cost)

**What goes wrong:**
With open-mic VAD (PROJECT.md decided VAD over push-to-talk), Silero VAD fires on a cough, keyboard, fan, a door, or a roommate. This either (a) triggers a spurious turn that interrupts the agent, or (b) keeps the "user is speaking" state latched so semantic endpointing never commits — making the agent feel deaf/sluggish.

**Why it happens:**
VAD detects *audio energy resembling speech*, not *intentional speech directed at the agent*. Open-mic removes the explicit "I'm talking now" signal that PTT gives for free. AssemblyAI's comparison explicitly flags LiveKit/VAD as "Poor" noise robustness.

**How to avoid:**
- Enable browser-side noise suppression in `getUserMedia` constraints: `{ audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true } }` — on by default in Chrome/Firefox but set explicitly.
- Tune Silero VAD `threshold` upward (e.g. 0.5 → 0.6–0.7) for noisy rooms; raise `min_silence_duration_ms` so brief noise blips don't register as speech.
- Pair VAD with the LiveKit semantic turn-detector model so a noise blip that produces no coherent transcript never commits a turn.
- Consider LiveKit's noise-cancellation / ai-coustics filter (its VAD adapter runs inside the denoiser) as a stronger open-mic path.
- Keep PTT as a documented fallback toggle for genuinely noisy environments — cheap insurance even though v1 defaults to open-mic.

**Warning signs:**
Agent starts "thinking" when nobody spoke; transcript shows empty/garbage user turns; agent cuts itself off when a noise occurs.

**Phase to address:** Phase 1 (voice loop / VAD config) — explicitly, because the open-mic decision concentrates risk here.

---

### Pitfall 5: The agent hears itself (echo / acoustic feedback loop)

**What goes wrong:**
With open mic + speakers (no headphones), the mic picks up Kokoro's own output. VAD treats the agent's voice as user speech → the agent interrupts itself (barge-in on its own audio), or transcribes its own TTS as a user turn, producing a feedback spiral.

**Why it happens:**
Echo cancellation must run *client-side at the speaker/mic*, where the reference signal exists. Server-side it's nearly impossible. Speaker output physically re-enters the mic on any open-mic, no-headphones setup.

**How to avoid:**
- Rely on browser AEC: `echoCancellation: true` in `getUserMedia` — the WebRTC AEC uses the playback signal as reference and is the primary defense.
- During agent speech, gate/attenuate barge-in sensitivity: require a higher VAD confidence or a minimum user-speech duration before canceling TTS, so the agent's own tail doesn't trigger barge-in (LiveKit keeps turn detection active during playback — tune the interruption threshold).
- Recommend headphones in the UI as the clean path; if the agent self-interrupts, that's the #1 sign headphones (or stronger AEC) are needed.
- Test the worst case explicitly: laptop speakers + built-in mic in a small room.

**Warning signs:**
Agent interrupts itself mid-sentence; user turns in the transcript that are verbatim fragments of the agent's last reply; runaway interruptions with no human present.

**Phase to address:** Phase 1 (voice loop) — barge-in + echo must be validated together, not separately.

---

### Pitfall 6: Semantic endpointing cuts in on pauses (or feels sluggish)

**What goes wrong:**
Two failure modes (LiveKit names both): endpoint *too early* → agent interrupts the user mid-thought on a natural pause ("I think the answer is… [agent jumps in]"); endpoint *too late* → dead air after the user clearly finished, killing the "feels live" feel.

**Why it happens:**
Pure VAD endpointing keys off silence duration alone — it can't tell "I went to the store…" (incomplete) from "…and bought milk." (complete). A fixed timer is wrong in both directions. PROJECT.md correctly requires *semantic* endpointing, but it still needs tuning.

**How to avoid:**
- Use LiveKit's turn-detector transformer model (Qwen2.5-0.5B-based, INT8, CPU-friendly) on top of Silero VAD: VAD triggers, the model decides if the utterance is semantically complete before committing.
- Tune `min_endpointing_delay` (default 500ms): lower it (~250–350ms) for snappier turns since the semantic model now guards against premature cutoff; the model lets you be faster *and* safer simultaneously.
- Budget-check: the endpoint delay is the largest single contributor to P50 — every 100ms here is 10% of the latency budget.
- Test on slow, deliberate speech (interview-style "let me think… the answer is…") — exactly the speech pattern Interview Mode produces.

**Warning signs:**
Users say "it keeps interrupting me" or "it waits too long"; complaints cluster on thoughtful/hesitant answers (interview mode).

**Phase to address:** Phase 1 (turn detection); re-tune in the phase that ships Interview Mode (slow-speech profile differs).

---

### Pitfall 7: KB-as-cached-prefix cache invalidation (any prefix change re-prefills everything)

**What goes wrong:**
The whole "inline-and-cache, no RAG" strategy depends on Ollama reusing the KV cache for the KB prefix so it costs prefill only on turn 1. But Ollama's prefix cache requires the prefix to be **byte-identical** to the previous request. Any change anywhere before the new tokens busts the cache and forces a full re-prefill of the entire KB brief — turning "free after turn 1" into "expensive every turn."

**Why it happens:**
Common silent cache-busters at the *front* of the prompt:
- A dynamic timestamp, turn counter, or "current time" in the system prompt.
- Live persona edits (PROJECT.md allows in-session persona editing) — changing role/instructions mid-session rewrites the system block, invalidating the cache from that point.
- History summarization/sliding-window that rewrites earlier turns (rewriting the middle invalidates everything after it).
- Non-deterministic prompt assembly (dict ordering, trailing whitespace, re-tokenized JSON).

**How to avoid:**
- Layout the prompt as **[static persona] + [static KB brief] + [rolling history] + [new user turn]**. Keep everything before the history *frozen* for the session. Put any volatile data (timestamps) at the very end, never in the prefix.
- When the user edits the persona live, accept that turn 1 after the edit re-prefills — show "applying…" briefly. Don't edit persona on every turn.
- For history management, only *append* and *truncate from the front past the cached prefix*; if you must summarize, do it as a discrete event the user sees, not silently every turn.
- Verify cache hits empirically: compare turn-2 TTFT with the model warm vs. cold — a large KB that doesn't speed up after turn 1 means the cache isn't hitting.
- Keep model resident (`keep_alive`, Pitfall 3) — eviction also dumps the prefix cache.

**Warning signs:**
TTFT is high and *constant* across turns (no turn-1 vs turn-2 drop); TTFT scales with KB size on every turn; Ollama logs show full prompt eval count each turn instead of a small "new tokens" count.

**Phase to address:** Phase 3 (KB) — design the prompt layout for cache stability before building distillation.

---

### Pitfall 8: KB distillation drops detail needed for credible coaching

**What goes wrong:**
To keep the brief compact (so prefill is cheap and it fits the context window), distillation over-compresses and discards specifics — exact CVE numbers, command flags, config values, the nuance that makes the trainer sound like a practitioner. The agent then gives generic, confidently-wrong answers about the user's own uploaded material.

**Why it happens:**
Distillation optimizes for size, and the latency design *wants* a small brief. But "compact" and "faithful" pull in opposite directions, and a small LLM doing the distillation can hallucinate or smooth over technical specifics.

**How to avoid:**
- Distill at *setup time* where latency is invisible — so you can afford a careful, higher-quality pass (bigger model, multi-pass, or extractive+abstractive hybrid) without hurting conversation latency.
- Preserve verbatim "fact anchors": extract exact identifiers, numbers, commands into a structured facts section that is *not* paraphrased, alongside the prose brief.
- Set a size guard with a *quality* fallback, not just a hard cutoff: if the doc exceeds the brief budget, that's the signal to fall back to real RAG (PROJECT.md reserves RAG for oversized KBs) rather than crushing it into a lossy brief.
- Spot-check distilled briefs against source on the default Cybersecurity KB before trusting it.

**Warning signs:**
Agent gives correct-sounding but vague answers about uploaded docs; specifics from the doc never surface; user says "that's not what my notes say."

**Phase to address:** Phase 3 (KB distillation) — define the size/quality threshold and fact-anchor extraction here.

---

### Pitfall 9: Three models co-resident + KV cache growth → OOM on 16GB under load

**What goes wrong:**
The 16GB budget assumes Gemma E4B Q4 (~5GB) + faster-whisper turbo int8 (~2GB) + Kokoro (~2–3GB) ≈ ~10GB. But that ignores: (a) Ollama **pre-allocates the full `num_ctx` KV cache upfront** — a large `num_ctx` to fit the KB brief reserves GB even when the prompt is short; (b) CUDA context/runtime overhead per process (~0.5–1GB each); (c) fragmentation. Under a real session the three resident models + a big KV cache blow past 16GB and Ollama OOMs (silently falls back to partial CPU offload → latency collapses, or crashes).

**Why it happens:**
Static parameter-size math ignores KV-cache pre-allocation and per-process CUDA overhead. The KB-as-prefix strategy *requires* a large `num_ctx`, which *requires* a large pre-allocated KV cache — the very thing that breaks the budget. These two design decisions are in direct tension on 16GB.

**How to avoid:**
- Size `num_ctx` to the *actual* worst case (KB brief + max history + headroom), not a round 32k. Every extra 1k of `num_ctx` is pre-allocated VRAM you may not have. Measure the distilled brief's real token count and set `num_ctx` tightly.
- Enable Flash Attention (`OLLAMA_FLASH_ATTENTION=1`) — reduces KV memory to O(n) and unlocks KV-cache quantization. On Gemma it's safe; Ollama warns and falls back to F16 if unsupported.
- Quantize the KV cache: `OLLAMA_KV_CACHE_TYPE=q8_0` (requires Flash Attention) roughly halves KV memory with negligible quality loss. q4_0 halves again but risks quality on long context — q8_0 is the sweet spot. (Note: high-attention-head models can be KV-quant-sensitive; verify Gemma E4B behaves.)
- Account for per-process CUDA overhead in the budget: plan ~12–13GB of usable headroom on a 16GB card, not 16.
- Add a VRAM watchdog: log `nvidia-smi` used-VRAM per turn; alarm before OOM. If it climbs across turns, KV cache or history isn't being bounded.
- 16GB is the *floor with no headroom* — treat it as the constraint that forbids a larger model, not a comfortable budget.

**Warning signs:**
Latency suddenly cliffs mid-session (CPU offload); `nvidia-smi` near 100%; Ollama logs "unable to allocate" / partial offload; OOM crash on the first turn after KB load (peak prefill memory).

**Phase to address:** Phase 0 (env: Flash Attention + KV quant + num_ctx sizing) → re-validate in Phase 3 (KB load is the peak-memory moment).

---

### Pitfall 10: Growing conversation history inflates per-turn TTFT

**What goes wrong:**
Even with KB cached, the *conversation history* grows every turn. Past some length, prefill of the new history tail (plus any cache miss from history rewrites) inflates TTFT turn over turn, and the context can exceed `num_ctx`, which evicts the cache (Ollama: cache lost "if context exceeds num_ctx") — re-prefilling the whole KB.

**Why it happens:**
Append-only history is the simplest implementation and works fine for 5 turns; it degrades at 30. PROJECT.md flags this ("sliding-window / summarize older turns") but it's easy to defer until it hurts.

**How to avoid:**
- Sliding window: keep the last N turns verbatim; drop or summarize older ones. Ensure summarization happens *behind* the frozen KB prefix so it doesn't bust the KB cache (tension with Pitfall 7 — summarize the history region only).
- Cap total context well under `num_ctx` so you never trigger eviction mid-session.
- Track tokens-in-context per turn as a logged metric; it should plateau, not grow unbounded.

**Warning signs:**
TTFT creeps up over a long session; a sudden TTFT spike when context wraps `num_ctx`; long sessions feel progressively slower.

**Phase to address:** Phase 1 (basic window) → Phase 3+ (summarization once KB + history coexist).

---

### Pitfall 11: Gemma E4B is too small for nuanced interview feedback

**What goes wrong:**
A 4B-class model gives shallow, generic, or subtly wrong critique in Interview Mode — misjudges a strong answer, gives textbook-bland "model answers," misses domain nuance, or fails to track multi-constraint persona instructions (difficulty + verbosity + correction-aggressiveness simultaneously). The latency is great but the *coaching value* is thin.

**Why it happens:**
The model was chosen for VRAM fit and speed ("generates faster than speech is spoken"), not reasoning depth. Nuanced evaluation/feedback is exactly where small models are weakest.

**How to avoid:**
- Lean hard on prompt engineering: give the persona an explicit rubric/structure for critique (what to assess, a scoring frame, a "model answer" template) rather than open-ended "give feedback" — structure compensates for model size.
- Define a quality bar on the default Cybersecurity interview flow; if E4B can't meet it, that's the trigger to fall back to a larger model on a 24GB card (PROJECT.md names Gemma 26B-A4B MoE or Qwen3 8B). Keep the LLM swap behind LiveKit's interface so it's a config change.
- Consider model-by-mode: E4B for fast Converse mode, larger model for Interview critique turns where depth matters more than the sub-second target (a 1.5s critique is acceptable; a 1.5s conversational reply isn't).
- Don't fine-tune (out of scope) — prompt-engineer or swap up.

**Warning signs:**
Interview feedback feels generic/interchangeable across answers; the agent praises weak answers; persona knobs (difficulty/verbosity) don't visibly change behavior; user trusts the critique less over time.

**Phase to address:** Phase where Interview Mode ships — gate it on a feedback-quality check; document the 24GB fallback path.

---

### Pitfall 12: LiveKit self-hosting — WebRTC/TURN/HTTPS breaks mic on LAN

**What goes wrong:**
Self-hosting LiveKit from day one (PROJECT.md decision) means owning WebRTC's hard parts. Common breakages: (a) browser refuses mic access because the page isn't a secure context; (b) WebRTC can't establish a media path across the Proxmox VM / LAN NAT without proper STUN/TURN; (c) ICE candidates advertise the wrong (container/internal) IP so audio never flows even though signaling "connects."

**Why it happens:**
- `getUserMedia` **only works in a secure context** — HTTPS, `localhost`, or `file://`. A homelab app served over plain `http://192.168.x.x` has `navigator.mediaDevices === undefined` and mic access throws `TypeError`. This bites every LAN deployment that isn't `localhost`.
- LiveKit needs correct `node_ip` / external IP and UDP port ranges open for media; behind the Proxmox VM's NAT, default config often advertises an unreachable address.

**How to avoid:**
- Serve the UI over HTTPS even on LAN: a self-signed cert or local CA (mkcert), or access via `localhost`/SSH-tunnel for single-user dev. Plan this in Phase 0 — it blocks the entire voice loop.
- Configure LiveKit's `rtc.node_ip` / use-external-ip and open the UDP media port range to the VM; verify ICE picks the LAN-reachable address.
- For single-user same-machine use, STUN/TURN may be unnecessary (host candidates work); but cross-device (phone on LAN → server) needs correct host-candidate IPs at minimum, TURN as fallback.
- Test mic on the *actual* deployment URL/device early, not just on `localhost` where the secure-context rule is silently satisfied.

**Warning signs:**
`navigator.mediaDevices` is undefined; mic permission prompt never appears; LiveKit room connects but no audio frames flow (ICE connected, media dead); works on `localhost`, breaks on the LAN IP.

**Phase to address:** Phase 0 (env: HTTPS + LiveKit network config) — this is a hard blocker for Phase 1.

---

### Pitfall 13: faster-whisper streaming mis-configuration (it's not built for streaming)

**What goes wrong:**
faster-whisper expects *complete* audio; naively feeding it tiny chunks gives garbled partials, or feeding it whole utterances adds full-utterance latency. Worse defaults: `condition_on_previous_text=True` makes streaming hallucinate/repeat; auto language detection adds ~50ms/segment; beam search adds latency you don't need for live STT.

**Why it happens:**
The README and most tutorials show batch/file transcription. Real-time needs a VAD-aware sliding-window wrapper and specific non-default settings.

**How to avoid:**
- Let LiveKit's STT plugin manage segmentation (VAD-gated utterances) rather than hand-rolling chunking.
- Streaming-tuned settings: `beam_size=1`, `condition_on_previous_text=False` (critical — prevents cross-segment hallucination), `vad_filter=True`, `language="en"` set explicitly (skip detection, faster + more accurate when language is known).
- Use large-v3-turbo int8 (the chosen model) — good latency/accuracy; expect ~50–80ms per 4s chunk on a decent GPU.
- Don't enable word timestamps unless needed (adds 5–10%).

**Warning signs:**
Transcripts repeat phrases or hallucinate during pauses; STT latency spikes from language detection; partials thrash/rewrite excessively.

**Phase to address:** Phase 1 (STT config in the voice loop).

---

### Pitfall 14: Document parsing quality (PDF/DOCX/encoding) garbles the KB at the source

**What goes wrong:**
Bad text extraction poisons the entire KB pipeline: scanned/image PDFs yield empty or OCR-garbage text; multi-column PDFs interleave columns into nonsense; DOCX tables/headers extract out of order; encoding errors (mojibake, smart quotes, BOM) inject noise. The distillation then faithfully distills garbage, and the agent confidently coaches from it.

**Why it happens:**
"Upload a PDF" sounds trivial; PDF is a layout format, not a text format. Different extractors handle columns, tables, ligatures, and scanned pages very differently. Encoding is assumed UTF-8 and isn't always.

**How to avoid:**
- Pick extractors deliberately: a layout-aware PDF library (e.g. PyMuPDF/pdfplumber) over the lowest-common-denominator; handle DOCX via python-docx with explicit table/heading handling; normalize encoding to UTF-8 and strip BOM/smart-quote artifacts.
- Detect the failure mode: if extracted text is near-empty or has a very low alpha-character ratio, flag it as likely scanned/image PDF and surface a clear error ("this looks like a scanned document — text couldn't be extracted") instead of silently proceeding. PROJECT.md requires "graceful handling of KB upload failure" — this is where it lives.
- Show the user a short preview of extracted text (or word count) before distillation so garbage is caught by a human at upload time (latency is free here).
- Set the size guard on *extracted token count*, not file bytes (a 200-page scanned PDF is 0 useful tokens; a dense 10-page MD is many).

**Warning signs:**
KB brief is empty or nonsense for some uploads; agent has no knowledge of a doc the user definitely uploaded; weird characters in the transcript/brief.

**Phase to address:** Phase 3 (KB upload/parse) — extraction quality gate before distillation.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| No per-stage latency instrumentation (one timer round the LLM) | Faster to build the loop | Can't decompose P95; chase wrong stage for days | Never — instrument in Phase 0, it's cheap |
| Append-only history, no window | Trivial; fine early | TTFT creep + cache eviction at `num_ctx` in long sessions | MVP only, with a turn cap; fix before real practice sessions |
| Full-response then TTS (no sentence streaming) | Simplest pipeline | Breaks the core sub-second value prop | Never — Phase 1 gate |
| Round `num_ctx=32768` "to be safe" | One less thing to size | Pre-allocates VRAM you don't have → OOM | Never on 16GB; size to real worst case |
| Persona timestamp/turn-counter in system prompt | Convenient context | Busts KB prefix cache every turn → constant high TTFT | Never — keep prefix byte-stable |
| Skip HTTPS on LAN (`http://192.168…`) | No cert hassle | `getUserMedia` undefined → no mic at all off-localhost | Only on `localhost` single-machine dev |
| KV cache q4_0 to save VRAM | More headroom | Quality degradation on long KB context | Only if q8_0 still OOMs and quality verified acceptable |
| Open-mic with no AEC/noise-suppression config | Works in a quiet room | Self-interruption + false triggers in the real world | Never ship without AEC; quiet-room demo only |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Ollama keep-alive | Default 5-min unload dumps model + KV cache | `keep_alive=-1`/`60m`; warm at session start |
| Ollama prefix cache | Volatile data at prompt front busts byte-identical match | Freeze [persona+KB] prefix; volatile data at the end only |
| Ollama Flash Attention | Left off → no KV quant, F16 KV cache eats VRAM | `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` |
| Ollama `num_ctx` | Set large "to be safe" → full KV pre-allocated upfront | Size tightly to brief+history+headroom; measure tokens |
| LiveKit + browser mic | App served over plain HTTP off-localhost → no `mediaDevices` | Serve over HTTPS (mkcert/self-signed) or `localhost`/tunnel |
| LiveKit WebRTC on Proxmox VM | Advertises internal/container IP → media never flows | Set external/node IP; open UDP media port range to VM |
| LiveKit turn detection | VAD-only → cuts in on pauses / latches on noise | Silero VAD + semantic turn-detector model; tune delay/threshold |
| faster-whisper streaming | `condition_on_previous_text=True` → hallucinated repeats | `=False`, `beam_size=1`, `vad_filter=True`, explicit `language` |
| Kokoro TTS | Wait for full audio before playback | Stream chunks; play first sentence while synthesizing the rest |
| Client echo cancellation | Expect server to cancel echo | AEC is client-side: `echoCancellation: true` in getUserMedia |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Endpoint delay dominates P50 | Snappy STT/LLM but slow "feel" | Lower `min_endpointing_delay` under semantic-model guard | Always present; it's ~500ms of a 1000ms budget |
| KB prefix re-prefill every turn | TTFT high and flat, scales with KB size | Byte-stable prefix; verify turn-2 TTFT drops | When prefix changes per turn |
| History TTFT creep / `num_ctx` eviction | Session slows over time; spike when context wraps | Sliding window; cap under `num_ctx` | ~20–40 turns depending on verbosity |
| KV cache pre-allocation OOM | Latency cliff to CPU offload; OOM at KB load | Tight `num_ctx` + Flash Attn + q8_0 KV | At session/KB-load peak on 16GB |
| Cold start after idle pause | First post-pause turn 5–30s | `keep_alive=-1` + warmup + KB priming turn | Any pause > keep-alive window |
| Non-streamed TTS | Latency scales with response length | Sentence-boundary streaming | Every multi-sentence reply |

## Security / Privacy Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| KB not actually cleared at session end | Sensitive employer/study material persists; violates ephemeral promise | Explicit teardown: drop KB from context, clear distilled brief from disk/RAM, evict KV cache; verify nothing written to logs |
| Transcripts/audio written to disk or logs | Private practice content leaks; breaks local-first guarantee | Keep transcript in-memory; only persist on explicit user export; scrub prompt/brief from debug logs |
| Self-signed HTTPS cert reused/leaked | LAN MITM of audio stream | Per-deployment cert; restrict to LAN; document the trust step |
| Uploaded doc path traversal / unsanitized filename | Arbitrary file write on the homelab host | Sanitize filenames; store in a sandboxed ephemeral dir; size/type validate before parse |
| Distillation/parse runs untrusted file content | Malicious PDF exploits parser | Use maintained extractors; run parse in the container's least-privilege context; cap resource use |
| Ollama/LiveKit ports exposed beyond LAN | External access to local models / rooms | Bind to LAN interface; firewall; no port-forward to WAN |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No visible agent state (listening/thinking/speaking) | User talks over the agent or waits awkwardly, unsure if heard | The PROJECT.md state indicator — make it instant and unambiguous; it masks latency psychologically |
| Silent VAD false-trigger | Agent "thinks" with no input; user confused | Show the detected user transcript live; empty turn = visible nothing, not a hidden LLM call |
| No "KB ready / priming" feedback | User asks about a doc before it's loaded → agent says it doesn't know | KB active indicator + "preparing knowledge…" until primed (Pitfall 3 priming turn) |
| Mic-permission denial unhandled | Blank app, no audio, no explanation | Detect `getUserMedia` failure; clear message + retry + secure-context hint |
| Garbled transcription shown raw | User loses trust on a single STT slip | Allow the agent to ask for clarification; show low-confidence gracefully (PROJECT.md requires this) |
| Barge-in too aggressive | Agent stops on the user's "mm-hmm" backchannel | Require minimum user-speech duration/confidence before canceling TTS |
| Persona edit with no feedback during re-prefill | Edit feels broken (slow next turn) | "Applying persona…" indicator on the post-edit turn |

## "Looks Done But Isn't" Checklist

- [ ] **Voice loop:** Often missing first-sentence TTS streaming — verify first audio starts before the full text is generated (latency flat vs. response length).
- [ ] **Latency:** Often missing per-stage breakdown — verify you can produce P50/P95 *per stage*, not just end-to-end.
- [ ] **KB caching:** Often missing actual cache-hit verification — verify turn-2 TTFT is dramatically lower than turn-1 with a large KB loaded.
- [ ] **Keep-alive:** Often missing the post-idle test — verify the first turn after a 6-minute pause is still fast.
- [ ] **Open-mic:** Often missing the noisy-room + speakers test — verify no self-interruption and no false triggers with laptop speakers, no headphones.
- [ ] **Echo:** Often missing AEC verification — verify the agent never transcribes its own voice as a user turn.
- [ ] **HTTPS:** Often missing the non-localhost test — verify mic works on the real LAN URL/device, not just `localhost`.
- [ ] **VRAM:** Often missing the peak-load test — verify no OOM at the KB-load moment with all three models resident and `nvidia-smi` headroom logged.
- [ ] **KB ephemeral:** Often missing the teardown audit — verify brief + transcript + KV cache are actually gone after session end (check disk and logs).
- [ ] **Document parsing:** Often missing the bad-input test — verify a scanned/image PDF and a non-UTF-8 file produce a clear error, not silent garbage.
- [ ] **Interview feedback:** Often missing a quality bar — verify E4B critique distinguishes a strong from a weak answer on the default KB.
- [ ] **Endpointing:** Often missing the slow-speech test — verify the agent doesn't cut in on deliberate "let me think…" interview answers.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Latency compounding, un-instrumented | LOW | Add per-stage logging; find the over-budget stage; fix that one |
| Cold start / keep-alive eviction | LOW | Set `keep_alive=-1`; add warmup + KB priming turn |
| KB prefix cache busting | MEDIUM | Refactor prompt to frozen-prefix layout; move volatile data to the end; re-verify cache hits |
| VRAM OOM | MEDIUM | Shrink `num_ctx`; enable Flash Attn + q8_0 KV; if still tight, drop to a smaller Whisper or move it to CPU |
| Open-mic false triggers / echo | MEDIUM | Enforce AEC + noise-suppression constraints; raise VAD threshold; recommend headphones; expose PTT fallback |
| Endpointing cutting in | LOW–MEDIUM | Add/tune semantic turn-detector; adjust `min_endpointing_delay`; re-test on slow speech |
| E4B feedback too shallow | MEDIUM–HIGH | Add rubric-structured prompts; swap to larger model on 24GB behind the LiveKit interface |
| HTTPS/mic broken on LAN | LOW | Add mkcert/self-signed HTTPS or serve via localhost/tunnel |
| Bad document parsing | MEDIUM | Swap to layout-aware extractor; add empty/low-alpha detection + user preview; reject scanned PDFs clearly |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Latency compounding | Phase 0 (metrics) + Phase 1 | Per-stage P50/P95 dashboard exists and decomposes |
| 2. No first-sentence TTS | Phase 1 | First audio precedes full text; latency flat vs. length |
| 3. Cold start / keep-alive | Phase 0 + 1 + 3 | Post-6-min-pause turn still fast |
| 4. Open-mic false triggers | Phase 1 | No spurious turns in a noisy-room test |
| 5. Agent hears itself / echo | Phase 1 | No self-transcription with speakers + open mic |
| 6. Endpointing cuts in | Phase 1 (+ Interview phase) | No cutoff on deliberate slow speech |
| 7. KB prefix cache busting | Phase 3 | Turn-2 TTFT ≪ turn-1 with large KB |
| 8. Distillation drops detail | Phase 3 | Distilled brief preserves fact anchors vs. source |
| 9. VRAM OOM on 16GB | Phase 0 (+ re-check Phase 3) | No OOM at KB-load peak; logged headroom |
| 10. History TTFT creep | Phase 1 (+ Phase 3 summarization) | Tokens-in-context plateaus; no `num_ctx` eviction |
| 11. E4B feedback too shallow | Interview Mode phase | Critique distinguishes strong vs. weak answers |
| 12. LiveKit HTTPS/WebRTC/LAN | Phase 0 | Mic + media work on the real LAN URL/device |
| 13. faster-whisper streaming | Phase 1 | No hallucinated repeats; explicit-language STT |
| 14. Document parsing quality | Phase 3 | Scanned PDF / bad encoding → clear error, not garbage |

## Sources

- LiveKit — Turn detection for voice agents (VAD, endpointing, model-based); barge-in & client-side echo cancellation: https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection
- LiveKit — Transformer-based end-of-turn detection; `min_endpointing_delay` default 500ms: https://livekit.com/blog/using-a-transformer-to-improve-end-of-turn-detection
- LiveKit Docs — Turns overview; turnDetection modes (vad / stt / model): https://docs.livekit.io/agents/logic/turns
- LiveKit Docs — Noise & echo cancellation (ai-coustics VAD adapter): https://docs.livekit.io/transport/media/noise-cancellation
- livekit/turn-detector model card (Qwen2.5-0.5B, INT8 ONNX, CPU): https://huggingface.co/livekit/turn-detector
- AssemblyAI — turn detection / endpointing comparison (VAD noise robustness "Poor"): https://www.assemblyai.com/blog/turn-detection-endpointing-voice-agent
- Ollama prompt prefix caching, keep-alive, byte-identical-prefix rule, `num_ctx` pre-allocation, Flash Attention: https://leanpub.com/read/ollama/prompt-caching ; https://vijay.eu/co-authored/llm-inference-internals-apple-silicon
- Ollama issue #16635 — cache_prompt / context-shift coupling: https://github.com/ollama/ollama/issues/16635
- KV cache quantization (q8_0/q4_0) requires Flash Attention; high-attention-head sensitivity: https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama
- faster-whisper streaming settings (`condition_on_previous_text=False`, `beam_size=1`, `vad_filter`, explicit language) and turbo int8 VRAM/latency: https://www.spheron.network/blog/faster-whisper-gpu-cloud-production-deployment-guide ; https://github.com/SYSTRAN/faster-whisper
- MDN — getUserMedia secure-context requirement (HTTPS/localhost/file), `mediaDevices` undefined otherwise: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- getUserMedia audio constraints (echoCancellation/noiseSuppression/autoGainControl defaults): https://blog.addpipe.com/getusermedia-audio-constraints
- PROJECT.md (Adept) — stack, latency target, KB-inline-and-cache, open-mic VAD decision, 16GB floor

---
*Pitfalls research for: near-real-time local voice AI agent (Adept)*
*Researched: 2026-06-24*
