---
phase: 04-knowledge-base-layer
plan: 04-03
subsystem: infra
tags: [num_ctx, kv-cache, vram, flat-ttft, prefix-cache, ollama, modelfile, operator-gate]

requires:
  - phase: 04-knowledge-base-layer
    provides: distill.py BRIEF_TOKEN_BUDGET + render_prompt(persona, kb_brief) KB_SLOT seam + inject-once/compose/priming in main.py
provides:
  - ollama/Modelfile num_ctx pinned at 8192 with documented persona+brief+history+headroom accounting (coupled to BRIEF_TOKEN_BUDGET/KB_MAX_TOKENS)
  - scripts/vram-validate.sh additive KB-loaded peak-VRAM re-check mode (--with-kb / KB_FIXTURE) with all four assertions intact
  - 04-KB-VERIFY.md operator runbook with proofs A (flat-TTFT KB-05), B (Ollama cache-hit), C (brief-token→num_ctx), D (KB-load VRAM re-check)
affects: [phase-05-and-beyond]

tech-stack:
  added: []
  patterns:
    - "num_ctx ↔ brief-budget coupling: num_ctx is pre-allocated VRAM, sized to persona+BRIEF_TOKEN_BUDGET+history+headroom; kept at 8192 since the worst case fits"
    - "Additive operator-script mode: --with-kb/KB_FIXTURE drives a brief-sized prefix at the peak-memory moment without rewriting the default no-KB path"
    - "Deferred operator-gate runbook: VM-only proofs captured as numbered steps + results-capture tables, never marked passed by the executor"

key-files:
  created:
    - .planning/phases/04-knowledge-base-layer/04-KB-VERIFY.md
  modified:
    - ollama/Modelfile
    - scripts/vram-validate.sh

key-decisions:
  - "Kept num_ctx at 8192: the documented worst case (persona ~250 + brief ~1500 + history ~5000 + headroom ~1440 ≈ 8190) fits, and Ollama pre-allocates the full num_ctx as VRAM — no inflation"
  - "KB-loaded VRAM mode is additive (--with-kb flag / KB_FIXTURE env), default no-KB path byte-unchanged; synthetic brief-sized prefix is the repeatable proxy, real KB via UI is authoritative"
  - "json_string helper (python3 json.dumps) safely encodes the large brief prefix into the generate prompt — avoids shell-quoting a multi-KB payload"
  - "agent/metrics.py left byte-identical (frozen per-turn key set); 04-03 only READS llm_ttft_ms for the flat-TTFT proof"

patterns-established:
  - "Operator-verification doc mirrors 01-VERIFICATION.md style: numbered steps, exact commands, fill-in results tables, explicit pending-operator status"

requirements-completed: [KB-05]

duration: 8 min
completed: 2026-06-25
status: complete
---

# Phase 4 Plan 04-03: Flat-TTFT proof + num_ctx pin + KB-load VRAM re-check Summary

**The keystone verification slice: pinned `ollama/Modelfile` `num_ctx` at 8192 with explicit persona+brief+history+headroom accounting (coupled to `BRIEF_TOKEN_BUDGET`/`KB_MAX_TOKENS`), added an additive `--with-kb`/`KB_FIXTURE` peak-VRAM re-check mode to `scripts/vram-validate.sh`, and authored `04-KB-VERIFY.md` — the operator runbook proving turn-2 `llm_ttft_ms` ≪ turn-1 with a large KB (KB-05), the Ollama prefix-cache hit, the brief-token→num_ctx measurement, and three-models-under-16GB with q8_0 engaged — all deferred VM gates, `agent/metrics.py` untouched.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-25T23:00:00Z
- **Completed:** 2026-06-25T23:08:00Z
- **Tasks:** 3 (all sandbox-verifiable work)
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- **`ollama/Modelfile`:** replaced the "grows in Phase 4" future-tense forecast with the ACTUAL Phase-4 accounting (persona ~250 + brief ~1500 + history ~5000 + headroom ~1440 ≈ 8190 → 8192 covers it); documented num_ctx ↔ `BRIEF_TOKEN_BUDGET`/`KB_MAX_TOKENS` coupling and the q8_0+flash-attn KV-halving that makes it affordable. `FROM`, sampling params, and the #15260 note are unchanged.
- **`scripts/vram-validate.sh`:** added an opt-in KB-loaded mode (`--with-kb` flag or `KB_FIXTURE` env) that prepends a `BRIEF_TOKEN_BUDGET`-sized prefix to the concurrent generate load so peak VRAM is sampled with the KB-loaded KV footprint resident. All four existing assertions (VRAM ceiling, q8_0 FAIL-LOUD, 3 GPU procs, `OLLAMA_MODEL` tag) still fire; the default no-KB path is unchanged.
- **`04-KB-VERIFY.md`:** new operator runbook with the build/deploy-before-verify reminder + proofs A (flat-TTFT KB-05: turn-1 vs turn-2 vs no-KB turn-2), B (Ollama prompt-eval cache-hit + cache-bust signature), C (brief token measurement → num_ctx pin), D (KB-load VRAM re-check), each with exact commands and fill-in results tables. States `agent/metrics.py` is read-only and the turn-1 spike is the sanctioned, expected re-prefill.

## Task Commits

1. **Task 04-03-1: pin num_ctx 8192 with Phase-4 brief-budget accounting** - `c92607c` (docs)
2. **Task 04-03-2: add KB-loaded peak-VRAM re-check mode to vram-validate.sh** - `5ba5f27` (feat)
3. **Task 04-03-3: add 04-KB-VERIFY.md operator runbook** - `2760aac` (docs)

## Files Created/Modified

- `ollama/Modelfile` - num_ctx 8192 with documented persona+brief+history+headroom accounting + coupling note
- `scripts/vram-validate.sh` - additive `--with-kb`/`KB_FIXTURE` KB-loaded mode + `kb_prefix`/`json_string` helpers; default path intact
- `.planning/phases/04-knowledge-base-layer/04-KB-VERIFY.md` - operator runbook, proofs A–D, results-capture tables

## Decisions Made

- **Kept num_ctx at 8192:** the documented worst case (~8190 tok) fits; Ollama pre-allocates the full num_ctx as VRAM, so no inflation. A bump is gated on the operator's Proof-C measurement.
- **Additive KB mode, not a rewrite:** `--with-kb`/`KB_FIXTURE` is opt-in; the no-flag invocation runs exactly as before. Synthetic prefix is the repeatable proxy; real KB via the agent UI is the authoritative check.
- **`json_string` helper** (python3 `json.dumps`) safely encodes the large brief prefix into the generate payload — avoids shell-quoting a multi-KB string.
- **`agent/metrics.py` untouched:** the frozen per-turn key set is the Phase-3 contract; 04-03 only READS `llm_ttft_ms`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. LSP flagged unresolved `livekit`/`fitz`/`pymupdf4llm`/`docx` imports in `agent/main.py` and `agent/kb/parse.py` — pre-existing sandbox dependency gaps, unrelated to this plan's edits.

## Deferred / Operator Gates (NOT marked passed)

All four proofs in `04-KB-VERIFY.md` are **OPERATOR-VERIFICATION / `[VM-INTROSPECT]`** steps requiring the Proxmox VM (Docker + RTX 5090 + Ollama + browser + LAN device). The sandbox has none of these. Recorded as **pending operator verification — NOT a blocking checkpoint and NOT marked passed**:

- **Proof A (flat-TTFT, KB-05):** load a large KB; assert turn-2 `llm_ttft_ms` ≪ turn-1 and turn-2(KB) ≈ turn-2(no-KB). Only turn-1 carries `over_budget: ["llm_ttft"]`.
- **Proof B (Ollama prefix-cache hit):** turn-2 prompt-eval shows a small new-token count, not a full brief re-eval (cache-bust = Pitfall 7 byte-drift).
- **Proof C (brief tokens → num_ctx):** measure the real distilled-brief token count; confirm 8192 is the smallest covering value (bump only to a measured value).
- **Proof D (KB-load VRAM re-check, PERF-02):** run `./scripts/vram-validate.sh --with-kb` AND a real-KB `nvidia-smi` peak sample; assert peak < 16384 MB (with headroom), q8_0 engaged, 3 GPU procs.

## Next Phase Readiness

- **Phase 04 (knowledge-base-layer) plans are all complete (3/3).** The inline-and-cache KB design is fully implemented (04-01 parse/upload/panel, 04-02 distill/inject-once/compose) and its keystone invariant is captured as a runnable operator runbook (04-03).
- **Operator gate before relying on KB-05:** run the four proofs in `04-KB-VERIFY.md` on the VM and fill the results tables. Until then, KB-05 / PERF-02 re-validation are pending, not proven.
- Ready for phase verification (`/gsd-verify-work 04`).

---
*Phase: 04-knowledge-base-layer*
*Completed: 2026-06-25*

## Self-Check: PASSED

- `bash -n scripts/vram-validate.sh` → exit 0 (syntax valid)
- `grep` acceptance: `KB_FIXTURE\|with-kb\|BRIEF\|kb` present; `VRAM_CEILING_MB\|q8_0\|EXPECTED_GPU_PROCS\|OLLAMA_MODEL` assertions intact; `git diff --stat scripts/vram-validate.sh` = additive (80 ins / 5 del)
- `ollama/Modelfile`: `num_ctx 8192` justified by documented accounting; `grep "grows in Phase 4"` returns nothing; `git diff` shows only the num_ctx comment changed (FROM/sampling/#15260 unchanged)
- `04-KB-VERIFY.md` exists with proofs A–D, exact commands, results tables; states metrics.py read-only + turn-1 spike expected; includes build/deploy reminder — all acceptance greps non-zero
- `git diff --stat agent/metrics.py` → empty (frozen key set untouched)
- All three task commits present (`c92607c`, `5ba5f27`, `2760aac`); key-files.created exists on disk
- OPERATOR-VERIFICATION proofs A–D recorded as deferred/pending — NOT marked passed
