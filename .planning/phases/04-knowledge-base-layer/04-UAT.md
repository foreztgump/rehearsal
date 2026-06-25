---
status: testing
phase: 04-knowledge-base-layer
source: [04-VERIFICATION.md]
started: 2026-06-25T22:30:00Z
updated: 2026-06-25T22:30:00Z
---

## Current Test

number: 1
name: Upload matrix — PDF/TXT/MD/DOCX each parse to ready, failures surface clearly
expected: |
  Upload one each of PDF/TXT/MD/DOCX at session start → KbPanel indicator moves
  idle → uploading → parsing → distilling → ready (n docs). A scanned/empty PDF →
  clear "looks scanned" error and the voice loop keeps working. An unsupported type
  → clear "Unsupported file type" error. An oversize doc → the size guard fires
  (oversize). (KB-01, KB-07, KB-08, REL-03 live surfacing)
awaiting: user response

## Tests

### 1. Upload matrix — PDF/TXT/MD/DOCX each parse to ready, failures surface clearly
expected: Each of PDF/TXT/MD/DOCX → indicator reaches `ready (n docs)`; scanned/empty PDF → "looks scanned" error + loop continues; unsupported type → clear error; oversize doc → guard fires (oversize). Session never breaks on a bad upload.
result: [pending]

### 2. KB-04 live grounding — agent references the user's material; no-KB does not invent it
expected: Upload a doc containing a distinctive fact → ask about that fact by voice → the trainer references the user's own material. With NO KB loaded, the agent does not invent that fact. Editing the persona AFTER a KB load preserves grounding (compose, not clobber).
result: [pending]

### 3. KB-05 flat-TTFT keystone (Proof A) — turn-2 TTFT ≪ turn-1, ≈ no-KB turn-2
expected: Per 04-KB-VERIFY.md Proof A. With a LARGE KB loaded: turn-1 `llm_ttft_ms` is elevated (cold prefill, `over_budget:["llm_ttft"]`, the one sanctioned re-prefill) and turn-2/turn-3 `llm_ttft_ms` ≪ turn-1. turn-2(KB) ≈ turn-2(no-KB) — flat. metrics.py read-only; turn-1 spike expected, not a regression.
result: [pending]

### 4. KB-05 Ollama prefix-cache-hit (Proof B) — turn-2 prompt-eval is small, not a brief re-eval
expected: Per 04-KB-VERIFY.md Proof B. Ollama logs show turn-2 prompt-eval / "new tokens" count is SMALL (only the new turn tokens), not a full re-eval of the brief. A turn-2 prompt-eval ≈ brief size = cache BUST = FAIL (investigate prefix byte-drift).
result: [pending]

### 5. num_ctx pin confirmation (Proof C) — measured brief tokens covered by num_ctx 8192
expected: Per 04-KB-VERIFY.md Proof C. Measure the REAL distilled-brief token count for a representative KB. Confirm the pinned `num_ctx 8192` is the smallest value covering persona + measured brief + history + headroom (bump only to a measured value if it does not fit).
result: [pending]

### 6. KB-load VRAM re-check (Proof D / PERF-02) — peak < 16GB, q8_0 engaged, 3 GPU procs
expected: Per 04-KB-VERIFY.md Proof D. Run `./scripts/vram-validate.sh --with-kb` (or KB_FIXTURE) AND a real-KB-loaded `nvidia-smi` peak sample. Peak used-VRAM < 16384 MB (with 1GB headroom), q8_0 KV engaged (FAIL LOUDLY on F16 fallback), exactly 3 GPU procs (no embedder/vector store).
result: [pending]

### 7. Ephemeral teardown (KB-06) — KB cleared at session end
expected: After a session with a KB loaded, end the session / disconnect the room → no KB persistence on disk or db; a fresh session starts with no KB (indicator idle, 0 docs). The KB lived only in the in-memory _SessionKb for the job lifetime.
result: [pending]

### 8. [VM-INTROSPECT] live SDK signatures
expected: Confirm on the installed stack: `register_byte_stream_handler` / `reader.info` (.name/.mimeType/.size) / `local_participant.set_attributes` on the rtc SDK; `sendFile(file,{topic})` + participant-attribute-change event on livekit-client@2.20.0; `agent.update_instructions` is a coroutine; silent/internal `generate_reply` prime works; `pymupdf4llm.to_markdown(doc)` signature. (Client types statically verified — live flow is the gate.)
result: [pending]

## Summary

total: 8
passed: 0
issues: 0
pending: 8
skipped: 0
blocked: 0

## Gaps
