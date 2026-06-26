---
phase: 04-knowledge-base-layer
plan: 04-04
subsystem: infra
tags: [num_ctx, ollama, context-length, distill, facts-anchor, kb-grounding, persona, cite-nudge, whisper-warmup, uat-gap-closure]

requires:
  - phase: 04-knowledge-base-layer
    provides: distill.py BRIEF_TOKEN_BUDGET + render_prompt(persona, kb_brief) KB_SLOT seam + 04-KB-VERIFY.md operator runbook + 04-UAT.md live-stack gaps
provides:
  - docker-compose.yml ollama service pins OLLAMA_NUM_PARALLEL=1 + OLLAMA_CONTEXT_LENGTH=8192 (effective 8192-token context, single source of truth for /v1 and /api/generate)
  - distill() FACTS-anchor post-validation with one off-hot-path repair call + DistillError boundary mapping (KB-04 grounding)
  - persona render_prompt KB_CITE_NUDGE prepended only when a brief is present (empty-KB render byte-identical to EXPECTED_DEFAULT)
  - warmup.py WHISPER_MODEL default aligned to large-v3 (matches agent/main.py offline cache)
  - 04-UAT.md gaps_resolved + 04-KB-VERIFY.md verified-proxy (Proof A/C/D re-run on live stack)
affects: [phase-05-and-beyond]

tech-stack:
  added: []
  patterns:
    - "Effective-context pinning: OLLAMA_NUM_PARALLEL=1 + OLLAMA_CONTEXT_LENGTH=8192 on the service is the runtime source of truth — Modelfile num_ctx never reaches the base tag the agent/distiller actually load"
    - "FACTS-anchor contract enforcement: post-validate the model output, repair ONCE off-hot-path, append only verbatim content (never a fabricated empty anchor), else raise DistillError"
    - "Brief-gated persona nudge: KB_CITE_NUDGE renders only when kb_brief is non-empty, keeping the empty-KB prefix byte-identical to the golden EXPECTED_DEFAULT (Pitfall 7 byte-stability)"

key-files:
  created: []
  modified:
    - docker-compose.yml
    - ollama/Modelfile
    - agent/kb/distill.py
    - agent/persona.py
    - ollama/warmup.py
    - .planning/phases/04-knowledge-base-layer/04-UAT.md
    - .planning/phases/04-knowledge-base-layer/04-KB-VERIFY.md

key-decisions:
  - "Pin effective context via service env, not Modelfile: the agent and distiller load the base gemma3:4b-it-qat tag (not adept-gemma), so Modelfile num_ctx never reached the runtime; OLLAMA_NUM_PARALLEL=1 + OLLAMA_CONTEXT_LENGTH=8192 is VRAM-neutral (8192x1 == 4096x2 KV) and applies to both /v1 and /api/generate"
  - "Repair distill output once, off the hot path, and only append a FACTS anchor that carries real verbatim content — never fabricate an empty anchor; if repair fails, raise DistillError (REL-03 continue-without-KB preserved by main.ingest_kb)"
  - "KB_CITE_NUDGE is brief-gated so the empty-KB render stays byte-identical to EXPECTED_DEFAULT — the golden seam and Pitfall-7 byte-stability are both intact"
  - "warmup.py default aligned to large-v3 to match agent/main.py and the offline HF cache; env override seam preserved"
  - "No format=json (#15260-safe), no hardcoded tag, no livekit import, no bare except; agent/metrics.py left byte-identical (frozen per-turn key set)"

patterns-established:
  - "Gap-closure plan: minimal targeted edits closing UAT-found HIGH gaps, re-running the SAME UAT proxies against the rebuilt live stack as the verification step"

requirements-completed: [KB-04, KB-05]

duration: 17 min
completed: 2026-06-25
status: complete
---

# Phase 4 Plan 04-04: Close the two HIGH UAT gaps (effective context 8192 + FACTS-anchor distill) Summary

**The Phase-4 gap-closure slice: after live-stack UAT surfaced 2 HIGH gaps, pinned the effective Ollama context to 8192 via service env (was a silently-truncated 4096), made `distill()` honor the FACTS-anchor contract with a one-shot off-hot-path repair (KB-04 grounding), added a brief-gated persona cite-nudge, aligned the whisper-warmup default to large-v3, then rebuilt + force-recreated the stack and re-ran the UAT proxies — GAP-1 and GAP-2 RESOLVED, Proofs A/C/D verified-proxy, `agent/metrics.py` untouched.**

## Performance

- **Duration:** ~17 min
- **Completed:** 2026-06-25
- **Tasks:** 5 (4 targeted fixes + 1 live-stack re-verification)
- **Files modified:** 7 (5 code/config, 2 verification docs)

## Accomplishments

- **GAP-1 — effective context 4096 → 8192 (`docker-compose.yml`, `ollama/Modelfile`):** the runner loaded `--ctx-size 8192 --parallel 2` (4096 effective), silently truncating real KB prompts (`truncating input prompt limit=4096`). Pinned `OLLAMA_NUM_PARALLEL=1` + `OLLAMA_CONTEXT_LENGTH=8192` on the `ollama` service as the single runtime source of truth for both `/v1` and `/api/generate`; VRAM-neutral (8192×1 == 4096×2 KV). Modelfile `num_ctx` retained with a hot-path note.
- **GAP-2a — distill honors the FACTS-anchor contract (`agent/kb/distill.py`):** `DISTILL_INSTRUCTION` now forbids critique/quality-commentary and adds a neutral few-shot showing the literal `FACTS:` prefix; `distill()` post-validates the anchor, runs ONE focused off-hot-path repair when absent, and appends the line only when it carries real verbatim content (else raises `DistillError`). Both network calls route through `_generate()`, mapping `httpx.HTTPError` → `DistillError` so the REL-03 continue-without-KB boundary holds.
- **GAP-2b — persona KB cite-nudge (`agent/persona.py`):** added a frozen `KB_CITE_NUDGE` that `render_prompt` prepends to the KB segment ONLY when `kb_brief` is non-empty, so the empty-KB render stays byte-identical to `EXPECTED_DEFAULT` (golden seam intact) and the nudge is byte-stable across turns (Pitfall 7).
- **Warmup alignment (`ollama/warmup.py`):** `WHISPER_MODEL` default changed from `faster-whisper-large-v3-turbo` to `large-v3` to match `agent/main.py` and the offline HF cache (a bare `--with-kb` validate had 500'd on whisper warmup); env override seam preserved.

## Task Commits

1. **Task 04-04-1: pin effective Ollama context to 8192 via service env (GAP-1)** - `46b2857` (fix)
2. **Task 04-04-2: make distill honor the FACTS-anchor contract (GAP-2a)** - `d579297` (fix)
3. **Task 04-04-3: persona KB cite-nudge when a brief is present (GAP-2b)** - `69605b9` (fix)
4. **Task 04-04-4: align warmup.py WHISPER_MODEL default to large-v3** - `afaac74` (fix)
5. **Task 04-04-5: record GAP-1/GAP-2 closure + Proof A/C/D re-verification** - `d60d5a0` (docs)

## Files Created/Modified

- `docker-compose.yml` - `ollama` service `OLLAMA_NUM_PARALLEL=1` + `OLLAMA_CONTEXT_LENGTH=8192` (effective-context pin)
- `ollama/Modelfile` - `num_ctx` retained with a hot-path note (base tag is what actually loads)
- `agent/kb/distill.py` - FACTS-anchor instruction + post-validation + one off-hot-path repair + `DistillError` boundary mapping
- `agent/persona.py` - brief-gated `KB_CITE_NUDGE`; `EXPECTED_DEFAULT`/`DEFAULT_PERSONA`/`KB_SLOT`/knob tables/`render_persona` unchanged
- `ollama/warmup.py` - `WHISPER_MODEL` default `large-v3`
- `.planning/phases/04-knowledge-base-layer/04-UAT.md` - status `gaps_found` → `gaps_resolved` (passed 4→6, issues 2→0)
- `.planning/phases/04-knowledge-base-layer/04-KB-VERIFY.md` - status pending-operator → verified-proxy; result tables filled

## Decisions Made

- **Service-env pin, not Modelfile:** the agent/distiller load the base `gemma3:4b-it-qat` tag, so `Modelfile num_ctx` never reached the runtime; the service env is the real source of truth and is VRAM-neutral.
- **Repair once, off the hot path, verbatim-only:** never fabricate an empty FACTS anchor; on repair failure raise `DistillError` and let `main.ingest_kb` continue without KB (REL-03).
- **Brief-gated nudge:** keeps the empty-KB render byte-identical to the golden `EXPECTED_DEFAULT` and byte-stable across turns.
- **`agent/metrics.py` untouched:** the frozen per-turn key set is the Phase-3 contract.

## Deviations from Plan

None - the four targeted fixes and the live-stack re-verification ran as planned.

## Issues Encountered

- A bare `./scripts/vram-validate.sh --with-kb` 500'd on whisper warmup until `WHISPER_MODEL` was aligned (closed by Task 04-04-4).
- Ollama service env only applies on container **recreate** — the re-verification step force-recreated `ollama` (not just restart) so the new context pin took effect.

## Live-Stack Re-Verification (Proxy)

Rebuilt agent+web, force-recreated `ollama`, re-ran the UAT proxies against the live RTX 5090 stack:

- **GAP-1 RESOLVED:** runner now `ctx-size 8192 --parallel 1` (8192 effective, was 4096); **0** `truncating input prompt` lines across distill + hot path (was 2).
- **GAP-2 RESOLVED:** brief emits a verbatim `FACTS:` anchor; trainer cites supplied facts **3/3**; no-KB path still does not invent. KB-04 grounding demonstrated.
- **Proof A (flat-TTFT, KB-05):** turn-2 222.7ms ≪ turn-1 394.5ms; KB/no-KB turn-2 ratio 0.95.
- **Proof C (brief tokens → num_ctx):** worst_total 6713 ≤ 8192, FACTS anchor present.
- **Proof D (KB-load VRAM):** bare `--with-kb` peak 10070MB < 15360, q8_0 engaged, 3 GPU procs.

## Next Phase Readiness

- **Phase 04 (knowledge-base-layer) is complete (4/4 plans).** The inline-and-cache KB design is implemented end-to-end (04-01 parse/upload/panel, 04-02 distill/inject-once/compose, 04-03 num_ctx pin + flat-TTFT runbook) and the two HIGH live-stack gaps are closed and proxy-verified (04-04).
- KB-04 grounding and KB-05 flat-TTFT are demonstrated on the live stack; PERF-02 VRAM ceiling holds with a KB loaded.
- Ready for Phase 05 (history-management).

---
*Phase: 04-knowledge-base-layer*
*Completed: 2026-06-25*
