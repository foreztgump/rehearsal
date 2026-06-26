---
status: gaps_resolved
phase: 04-knowledge-base-layer
source: [04-VERIFICATION.md]
started: 2026-06-25T22:30:00Z
updated: 2026-06-26T00:20:00Z
harness: scriptable proxies run locally against the live Docker stack (RTX 5090 + Ollama gemma3:4b-it-qat + rebuilt agent image). Voice-I/O-bound items deferred (headless fake-media yields no STT transcript).
---

## Current Test

number: done
name: both HIGH gaps closed + re-verified on rebuilt stack (task plan 04-04); 1 voice-gated deferral remains
awaiting: nothing — GAP-1 (num_ctx/parallel) and GAP-2 (distill FACTS-anchor + cite-nudge) both resolved and re-proven

## Tests

### 1. Upload matrix — PDF/TXT/MD/DOCX each parse to ready, failures surface clearly
expected: Each of PDF/TXT/MD/DOCX → indicator reaches `ready (n docs)`; scanned/empty PDF → "looks scanned" error + loop continues; unsupported type → clear error; oversize doc → guard fires (oversize). Session never breaks on a bad upload.
result: [pass] (parse-layer) — Drove kb.parse.parse() inside the REBUILT agent container against real fixtures (fitz-generated PDF, python-docx DOCX incl. table cells, TXT, MD) + all 4 failure fixtures. ALL_PASS: PDF/TXT/MD/DOCX extract correctly (codename verbatim; DOCX cell-B-9931 captured); scanned/empty PDF→reason=scanned "Couldn't extract text (looks scanned)"; unsupported→reason=unsupported; corrupt PDF→reason=corrupt; oversize→reason=oversize. Typed KbParseError, never raises. NOTE: browser upload→KbPanel state-pill transitions (idle→uploading→parsing→distilling→ready) NOT exercised (no CDP-driven LiveKit upload); parse/distill contract behind the pill is proven.

### 2. KB-04 live grounding — agent references the user's material; no-KB does not invent it
expected: Upload a doc containing a distinctive fact → ask about that fact by voice → the trainer references the user's own material. With NO KB loaded, the agent does not invent that fact. Editing the persona AFTER a KB load preserves grounding (compose, not clobber).
result: [pass] (RESOLVED 04-04, was issue:HIGH) — Re-ran the grounding proxy against the REBUILT agent after closing GAP-2 (distill FACTS-anchor post-validate/repair + persona conditional KB_CITE_NUDGE). The brief now carries the verbatim anchor `FACTS: BLUE-OTTER-7714, 4242, adept rollback --to 7714, AUD-9931-X` (brief_has_FACTS_line=true), and on realistic learner phrasings the trainer cites the supplied material 3/3: "the codename is BLUE-OTTER-7714 and the audit identifier is AUD-9931-X", "The command is `adept rollback --to 7714`", and quizzes back on the throughput target. no-KB still does NOT invent the fact (safety direction holds). The earlier deflection was reproduced ONLY under an adversarial probe phrased like the coach quizzing the student ("What is the project codename?") — that IS correct Socratic behaviour, not a grounding failure. KB-04 grounding now demonstrably works on gemma3:4b-it-qat. Compose-not-clobber persona-edit-after-KB sub-case still NOT separately exercised (needs live update_instructions ordering).

### 3. KB-05 flat-TTFT keystone (Proof A) — turn-2 TTFT ≪ turn-1, ≈ no-KB turn-2
expected: Per 04-KB-VERIFY.md Proof A. With a LARGE KB loaded: turn-1 `llm_ttft_ms` is elevated (cold prefill, `over_budget:["llm_ttft"]`, the one sanctioned re-prefill) and turn-2/turn-3 `llm_ttft_ms` ≪ turn-1. turn-2(KB) ≈ turn-2(no-KB) — flat. metrics.py read-only; turn-1 spike expected, not a regression.
result: [pass] — Drove the real frozen prefix (persona.render_prompt(brief)) across 3 KB turns + 2 no-KB turns on live Ollama, measured TTFT-to-first-content-token. KB: turn1=1300.1ms (cold prefill spike — the sanctioned re-prefill), turn2=310.3ms, turn3=305.9ms → turn2 ≪ turn1 (4.2× collapse ✓). no-KB turn2=203.6ms; KB-turn2/noKB-turn2 ratio=1.52 (flat-ish, same ballpark; the ~107ms delta tracks the larger resident KB prefix, well within the per-turn budget). Cache-hit collapse after turn-1 is unambiguous. NOTE: measured via /v1 stream timing in a harness, not the agent's own metrics.py emit (live mic turns deferred); metrics.py untouched (git diff clean).

### 4. KB-05 Ollama prefix-cache-hit (Proof B) — turn-2 prompt-eval is small, not a brief re-eval
expected: Per 04-KB-VERIFY.md Proof B. Ollama logs show turn-2 prompt-eval / "new tokens" count is SMALL (only the new turn tokens), not a full re-eval of the brief. A turn-2 prompt-eval ≈ brief size = cache BUST = FAIL (investigate prefix byte-drift).
result: [pass-with-caveat] — The TTFT collapse in Test 3 (1300→310ms with the prefix held constant) is the cache-hit signature; the frozen prefix bytes are stable across turns (render_prompt is deterministic, brief is an opaque frozen string), so NO byte-drift cache-bust. Caveat: Ollama is NOT in debug mode (OLLAMA_DEBUG=false), so native per-request `prompt eval count`/`n_past` "new tokens" lines are not emitted — could not read the exact small-vs-full token count directly; cache-hit is inferred from the unambiguous TTFT collapse + byte-stable prefix rather than the raw n_past log. To capture the literal number, set OLLAMA_DEBUG=1 and re-grep (optional hardening).

### 5. num_ctx pin confirmation (Proof C) — measured brief tokens covered by num_ctx 8192
expected: Per 04-KB-VERIFY.md Proof C. Measure the REAL distilled-brief token count for a representative KB. Confirm the pinned `num_ctx 8192` is the smallest value covering persona + measured brief + history + headroom (bump only to a measured value if it does not fit).
result: [pass] (RESOLVED 04-04, was issue:HIGH) — Closed GAP-1 by pinning `OLLAMA_NUM_PARALLEL=1` + `OLLAMA_CONTEXT_LENGTH=8192` in the compose ollama service env and force-recreating the container (env-var changes don't apply on a plain restart). Re-verified end-to-end on the rebuilt stack: in-container env now shows OLLAMA_NUM_PARALLEL=1, OLLAMA_CONTEXT_LENGTH=8192, OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0; the live runner cmdline is `ctx-size 8192 --batch-size 512 --n-gpu-layers 35 --threads 24 --flash-attn --kv-cache-type q8_0 --parallel 1` → effective per-slot context = 8192/1 = 8192 (was 4096). PROOF of truncation elimination: **0** `truncating input prompt` lines after the fix (was 2 before), across both `/api/generate` (distill) and `/v1/chat` (hot path) calls. Proof-C arithmetic re-confirmed: worst_total 6713 ≤ 8192, has_FACTS_anchor=true. num_ctx 8192 IS now in effect end-to-end.

### 6. KB-load VRAM re-check (Proof D / PERF-02) — peak < 16GB, q8_0 engaged, 3 GPU procs
expected: Per 04-KB-VERIFY.md Proof D. Run `./scripts/vram-validate.sh --with-kb` (or KB_FIXTURE) AND a real-KB-loaded `nvidia-smi` peak sample. Peak used-VRAM < 16384 MB (with 1GB headroom), q8_0 KV engaged (FAIL LOUDLY on F16 fallback), exactly 3 GPU procs (no embedder/vector store).
result: [pass] — Re-ran on the rebuilt stack: a BARE `./scripts/vram-validate.sh --with-kb` (NO WHISPER_MODEL override needed — the 04-04-4 warmup.py default→large-v3 alignment is verified) → peak used-VRAM 10070 MB < 15360 ceiling (well under the 16384 floor), q8_0 KV engaged (no F16 fallback), exactly 3 GPU procs (ollama+whisper+kokoro, no embedder/vector store). Independently confirmed live: runner cmd shows `--flash-attn --kv-cache-type q8_0`. PERF-02 re-validated at the KB-loaded peak; VRAM-neutral vs the prior 10196 MB sample. MINOR HARNESS BUG from the first run (warmup.py defaulting to `faster-whisper-large-v3-turbo` while the app pins `large-v3`) is FIXED in 04-04-4 and confirmed by the override-free run above.

### 7. Ephemeral teardown (KB-06) — KB cleared at session end
expected: After a session with a KB loaded, end the session / disconnect the room → no KB persistence on disk or db; a fresh session starts with no KB (indicator idle, 0 docs). The KB lived only in the in-memory _SessionKb for the job lifetime.
result: [blocked] — Requires a live LiveKit room join + disconnect lifecycle (voice). Headless chromium with fake-media can reach the web UI but cannot produce a real STT transcript to drive a session to teardown, and the MCP browser cannot attach to the existing CDP (it hardcodes /opt/google/chrome). Static reasoning is favorable (KB held only in in-memory _SessionKb for the job lifetime, no disk/db writer in the kb path), but the live no-persistence-after-disconnect assertion is unproven. Needs operator voice session OR a LiveKit token-based headless client harness.

### 8. [VM-INTROSPECT] live SDK signatures
expected: Confirm on the installed stack: `register_byte_stream_handler` / `reader.info` (.name/.mimeType/.size) / `local_participant.set_attributes` on the rtc SDK; `sendFile(file,{topic})` + participant-attribute-change event on livekit-client@2.20.0; `agent.update_instructions` is a coroutine; silent/internal `generate_reply` prime works; `pymupdf4llm.to_markdown(doc)` signature. (Client types statically verified — live flow is the gate.)
result: [pass] — Introspected the REBUILT agent image (livekit-agents 1.6.4): rtc.Room.register_byte_stream_handler=True, rtc.LocalParticipant.set_attributes=True, ByteStreamReader importable, Agent.update_instructions is a coroutine (iscoroutinefunction=True), pymupdf4llm.to_markdown present (sig (*args,**kwargs) — meta-package wrapper), fitz/PyMuPDF 1.27.2.3, python-docx 1.2.0. Python/server SDK surface CONFIRMED. NOT exercised live here: browser-side sendFile(file,{topic}) + participant-attribute-change event on livekit-client@2.20.0 (needs CDP-driven upload), and the silent generate_reply prime in a real room (needs voice). Server half proven; client-event half deferred.

## Summary

total: 8
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 1
notes: After 04-04 gap closure + re-verification on the rebuilt stack — 6 pass (1,2,3,5,6,8; Tests 2 & 5 RESOLVED from issue:HIGH), 1 pass-with-caveat (Test 4), 1 blocked (7 ephemeral teardown — voice lifecycle, legitimately voice-gated). Both HIGH gaps closed: GAP-1 (effective context 8192, 0 truncations) and GAP-2 (FACTS-anchor + cite-nudge, grounding 3/3).

## Gaps

### GAP-1 [HIGH] — RESOLVED (04-04) — Effective Ollama context was 4096, half the pinned num_ctx 8192 (Test 5)
- **Symptom (original):** live runner loaded `--ctx-size 8192 --parallel 2` → 4096 tokens per slot. Real KB distill prompts logged `truncating input prompt limit=4096 prompt=6077 keep=4 new=4096` (×2) — the frozen prefix the num_ctx pin was meant to protect was being silently truncated.
- **Fix applied:** pinned `OLLAMA_NUM_PARALLEL=1` + `OLLAMA_CONTEXT_LENGTH=8192` in the compose ollama service env (Modelfile note added for the adept-gemma path) and force-recreated the ollama container so the env actually applies.
- **Re-verified:** in-container env confirms both vars; runner cmdline now `ctx-size 8192 ... --parallel 1` → 8192 effective; **0** `truncating input prompt` lines across `/api/generate` + `/v1/chat` (was 2). KB-05 frozen-prefix budget now enforced end-to-end. Proof A flat-TTFT and Proof C arithmetic both re-pass.

### GAP-2 [HIGH] — RESOLVED (04-04) — Distill output ignored the FACTS-anchor contract; KB-04 grounding now demonstrated (Tests 2, 5)
- **Symptom (original):** `distill()` on `gemma3:4b-it-qat` returned meta-commentary ("This is a good, comprehensive specification…") instead of the mandated `DOMAIN BRIEF` + `FACTS:` verbatim-anchor line; the trainer deflected rather than citing BLUE-OTTER-7714 / AUD-9931-X.
- **Fix applied:** (a) hardened `DISTILL_INSTRUCTION` with an anti-critique / few-shot framing; (b) post-validate the brief and repair/append a verbatim `FACTS:` anchor line when absent; (c) added a conditional `KB_CITE_NUDGE` in `persona.render_prompt` that nudges the trainer to cite supplied material — rendered ONLY when a brief is present so the empty-KB render stays byte-identical to EXPECTED_DEFAULT (golden seam intact; persona `_self_check` green).
- **Re-verified:** brief now emits `FACTS: BLUE-OTTER-7714, 4242, adept rollback --to 7714, AUD-9931-X`; grounding proxy cites supplied facts 3/3 on realistic learner phrasings; no-KB still does not invent the fact. KB-04 grounding demonstrably works.

### Deferred (operator voice session — legitimately VM/voice-gated, not implementation gaps)
- **Test 7** (ephemeral teardown): needs a real LiveKit join+disconnect; no headless STT transcript path available. MCP browser can't attach to the running CDP (hardcoded /opt/google/chrome); raw CDP on :9222 is up if a token-based headless LiveKit client is built later.
- **Client-event half of Test 8**: browser `sendFile(file,{topic})` + participant-attribute-change on livekit-client@2.20.0 — needs CDP-driven upload.
- **metrics.py-emitted** turn metrics for Test 3 (vs the harness /v1 timing used here) — needs live mic turns. `git diff --stat agent/metrics.py` = no change (read-only contract honored).

### Environment fix applied during this run (stale-deploy guard, runbook §0)
- The deployed agent image (built 14:07) PREDATED the KB-deps commit 772993e (15:46) — `pymupdf4llm`/`fitz`/`python-docx` were MISSING from the running container (would have failed all KB-01 parsing live). Rebuilt `agent`+`web` images and `docker compose up -d`; deps now present (fitz 1.27.2.3, python-docx 1.2.0, pymupdf4llm). This is exactly the Phase-3 stale-deploy trap the runbook warns about.
