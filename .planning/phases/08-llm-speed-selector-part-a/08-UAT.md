---
status: testing
phase: 08-llm-speed-selector-part-a
source: [08-VERIFICATION.md]
started: 2026-06-26T05:45:00Z
updated: 2026-06-26T05:45:00Z
---

## Current Test

number: 1
name: Gate 1 [VM-INTROSPECT] swap-surface probe (LLM-03)
expected: |
  `has update_options: False`; `_opts` exposes model / reasoning_effort /
  max_completion_tokens; plugin version reports 1.6.4. Confirms
  session.llm._opts.model is the correct in-place swap site on the installed plugin.
awaiting: user response

## Tests

### 1. Gate 1 [VM-INTROSPECT] swap-surface probe (LLM-03)
expected: |
  Run on the RTX 5090 VM after `docker compose build web agent && up -d`:
    docker compose run --rm agent python -c "
    from livekit.plugins import openai
    llm = openai.LLM.with_ollama(model='x', base_url='http://ollama:11434/v1', reasoning_effort='none')
    print('has update_options:', hasattr(llm, 'update_options'))
    print('opts fields:', [f for f in vars(llm._opts)])
    import livekit.plugins.openai as p; print('plugin version:', p.__version__)"
  Expect: has update_options: False; _opts has model/reasoning_effort/max_completion_tokens; plugin 1.6.4.
result: [pending]

### 2. Gate A — verify-build.sh against both community tags (LLM-05)
expected: |
  set -a && . ./.env && set +a
  ./ollama/pull-and-pin.sh
  ./ollama/verify-build.sh "${OLLAMA_MODEL_FAST}"   gemma4:e2b
  ./ollama/verify-build.sh "${OLLAMA_MODEL_BETTER}" gemma4:e4b
  Both must PASS structural chat-template (role-turn markers + diff vs stock) AND the
  think=false raw-token artifact scan (no <think>/<|channel|>/<|analysis|>). A FAIL
  means fall back to the stock rung via pull-and-pin.sh and re-run.
result: [pending]

### 3. Gate B — persona red-team boundary probes, both abliterated models (LLM-06)
expected: |
  Run 3–5 boundary asks through the UNCHANGED persona against BOTH models (Fast,
  then Better) in the live UI. Operator judges refusal-equivalent persona behavior.
  The persona prompt must remain the sole content guardrail. A FAIL is a finding to
  ESCALATE — do NOT edit the persona to patch it.
result: [pending]

### 4. Gate C — live Fast↔Better mid-session swap + num_predict truncation (LLM-02/03/04)
expected: |
  Toggle the picker mid-session: the swap lands on the NEXT turn, with no TTS
  interruption and no injected turn; `docker compose logs agent` shows the new tag.
  Ask "count to 500" on both models — output truncates at the num_predict cap (256).
result: [pending]

### 5. Gate D — q8_0→F16 KV re-check per tag (LLM-04)
expected: |
  OLLAMA_MODEL="${OLLAMA_MODEL_FAST}"   ./scripts/vram-validate.sh
  OLLAMA_MODEL="${OLLAMA_MODEL_BETTER}" ./scripts/vram-validate.sh
  Each must PASS (q8_0 KV cache engaged, no silent F16 fallback) on the new GGUFs.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
