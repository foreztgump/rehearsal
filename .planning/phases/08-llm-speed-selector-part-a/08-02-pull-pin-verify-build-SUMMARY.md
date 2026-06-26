---
phase: 08-llm-speed-selector-part-a
plan: 08-02
subsystem: infra
tags: [ollama, bash, gguf, chat-template, abliterated, verification, vram, operator-gate]

requires:
  - phase: 08-llm-speed-selector-part-a (08-01)
    provides: model.update RPC + in-place _opts.model swap + OLLAMA_MODEL_FAST/BETTER env contract + LIVE_NUM_PREDICT_CAP
  - phase: 01-foundation
    provides: pull-and-pin.sh fallback-ladder + scripts/vram-validate.sh operator-gate skeleton + warmup.py think-scan kernel
provides:
  - Two-model pull/pin (FAST_LADDER/BETTER_LADDER) pinning OLLAMA_MODEL_FAST/OLLAMA_MODEL_BETTER (+ OLLAMA_MODEL Fast alias)
  - ollama/verify-build.sh standalone per-build LLM-05 gate (structural chat-template check + think=false artifact-superset scan)
  - 08-LLM-VERIFY.md operator runbook (Gate 1 VM-INTROSPECT + Gate A LLM-05 + Gate B LLM-06 persona red-team + Gate C live swap + Gate D q8_0 re-check)
affects: [phase-10-co-residency, phase-13-latency-tuning]

tech-stack:
  added: []
  patterns:
    - "Per-model fallback ladders via bash namerefs (local -n ladder) + a parameterized write_resolved_tag <key> <tag> writer — one resolver serves both models"
    - "Pull-time per-build gate (NOT agent startup) mirroring vram-validate.sh: fail() helper + single PASS line; structural (not non-empty-only) chat-template assertion"
    - "verify-build.sh /api/generate think=false scan documented as an accepted equivalent mirror of the live /v1 reasoning_effort=none path (both → internal Think=false)"

key-files:
  created:
    - ollama/verify-build.sh
    - .planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md
  modified:
    - ollama/pull-and-pin.sh

key-decisions:
  - "Check A is STRUCTURAL not non-empty-only: asserts <start_of_turn>/<end_of_turn> + user/model role-turn markers AND diffs vs the stock Gemma rung — catches the malformed-but-nonempty abliterated-build failure mode"
  - "resolve_tag generalized via a bash nameref (local -n ladder) so the existing pull→confirm-present→pin discipline is preserved per model with one function"
  - "OLLAMA_MODEL kept pinned to the resolved Fast tag as a back-compat alias so warmup/vram/distill/Modelfile keep working unchanged"
  - "LLM-05/LLM-06 remain Pending in REQUIREMENTS — the runbook is unsigned until the operator runs the gates on the real GPU (autonomous:false)"

patterns-established:
  - "Two-ladder + parameterized-writer generalization of a single-model pull script"
  - "Standalone pull-time per-build verification gate with structural template assertion + artifact-superset stream scan"

requirements-completed: []

duration: 12 min
completed: 2026-06-26
status: complete
---

# Phase 8 Plan 02: Two-model Pull/Pin + Per-Build Verification Gate + Operator Runbook Summary

**`pull-and-pin.sh` extended to resolve both Fast+Better community GGUFs via per-model fallback ladders, a new `ollama/verify-build.sh` per-build LLM-05 gate (structural chat-template check + think=false artifact-superset scan), and the `08-LLM-VERIFY.md` operator runbook that red-teams the UNCHANGED persona as the sole guardrail — all sandbox-authored; every GPU/live gate deferred to the operator.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-26
- **Completed:** 2026-06-26
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- Generalized `pull-and-pin.sh` from one model to two named ladders (`FAST_LADDER`/`BETTER_LADDER`) with a parameterized `write_resolved_tag <key> <tag>` and a nameref-based `resolve_tag`, pinning `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` plus the `OLLAMA_MODEL` Fast back-compat alias, preserving the per-rung pull→confirm-present→pin discipline and FATAL-on-full-ladder-failure per model.
- Authored `ollama/verify-build.sh` — a standalone pull-time gate: Check A asserts STRUCTURAL chat-template sanity (role-turn markers present AND a diff vs the stock Gemma rung, catching a malformed-but-nonempty template), Check B drives a streamed `think=false` `/api/generate` and fails on any of the `<think>`/`</think>`/`<|channel|>`/`<|analysis|>`/`<|message|>`/`<|start|>`/`<|end|>` superset, with the production-equivalence note that this mirrors the live `/v1 reasoning_effort=none` path.
- Wrote `08-LLM-VERIFY.md` (`status: pending-operator`) cloning `06-INTERVIEW-VERIFY.md`: build-first guard, Gate 1 [VM-INTROSPECT], Gate A (LLM-05 verify-build both tags), Gate B (LLM-06 persona red-team — SHAPE-only probes, escalate-don't-edit framing), Gate C (live Fast↔Better swap + num_predict cap), Gate D (per-tag q8_0→F16 re-check). Nothing marked passed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Two-model pull/pin** - `667bc55` (feat)
2. **Task 2: verify-build.sh per-build gate** - `42a0bb1` (feat)
3. **Task 3: 08-LLM-VERIFY.md operator runbook** - `7a677ee` (docs)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified
- `ollama/pull-and-pin.sh` - two named ladders + parameterized `write_resolved_tag`; `main()` pins `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` + `OLLAMA_MODEL` Fast alias.
- `ollama/verify-build.sh` (new) - `verify-build.sh <tag> [stock-tag]`; Check A structural chat-template + Check B think=false artifact scan; `fail()` helper + single PASS line; NOT wired into agent startup.
- `.planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md` (new) - operator runbook, five gates, nothing marked passed.

## Decisions Made
- Check A is structural (role-turn markers + diff vs stock), not a non-empty-only `grep -q .` — the explicit critical constraint to catch malformed-but-nonempty abliterated templates.
- `resolve_tag` uses a bash nameref (`local -n ladder="$1"`) so one function walks either ladder with the unchanged pull→confirm→pin logic.
- `OLLAMA_MODEL` stays the Fast alias so existing readers keep working unchanged.
- LLM-05/LLM-06 left Pending in REQUIREMENTS.md — operator-gated, runbook unsigned until run on the real GPU.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. `shellcheck` is not installed in the sandbox, so the optional shellcheck lint was skipped; `bash -n` syntax checks pass on both scripts. The `livekit.*` LSP import errors in `agent/main.py` are pre-existing and expected (sandbox cannot import livekit) and are unrelated to this plan's files.

## Operator Gates Pending (deferred — NOT executed by the executor)

All GPU/live gates run from BAKED images on the Proxmox VM + RTX 5090. Build first:

```bash
set -a && . ./.env && set +a
docker compose build web agent && docker compose up -d && docker compose ps
./ollama/pull-and-pin.sh
```

Then run, per `08-LLM-VERIFY.md`:
- **Gate 1 [VM-INTROSPECT]** — `docker compose run --rm agent python -c "..."` swap-surface probe (expect `has update_options: False`, `_opts` has `model`/`reasoning_effort`/`max_completion_tokens`, frozen `False`, plugin `1.6.4`).
- **Gate A (LLM-05)** — `./ollama/verify-build.sh "${OLLAMA_MODEL_FAST}" gemma4:e2b` and `./ollama/verify-build.sh "${OLLAMA_MODEL_BETTER}" gemma4:e4b` — both PASS; a FAIL → fall back to the stock rung and re-run.
- **Gate B (LLM-06)** — 3–5 persona-boundary red-team probes through the UNCHANGED persona against BOTH models; FAIL → escalate (do NOT edit persona).
- **Gate C** — live Fast↔Better toggle lands next-turn, no TTS interrupt/injected turn; `docker compose logs agent` shows new tag; "count to 500" truncates at the cap on both models.
- **Gate D** — `OLLAMA_MODEL="${OLLAMA_MODEL_FAST}" ./scripts/vram-validate.sh` and the Better tag — confirm q8_0 did not silently fall back to F16.

## Next Phase Readiness
- Phase 8 (Part A) sandbox-authorable work is complete (2/2 plans). The picker/swap (08-01) and pull/verify/runbook (08-02) are all shipped.
- **Blocking for phase sign-off:** the five operator [VM-*] gates in `08-LLM-VERIFY.md` (LLM-05 + LLM-06 + swap-surface + live swap + q8_0 re-check) must be run on the real GPU and the results/sign-off tables filled.
- Ready for Phase 9 (Nemotron Streaming ASR / Part B) planning once the operator gates are scheduled.

## Self-Check: PASSED

- `bash -n ollama/pull-and-pin.sh` → exit 0
- `bash -n ollama/verify-build.sh` → exit 0
- `ollama/verify-build.sh` not referenced in `agent/` (standalone, not agent-startup-wired)
- `08-LLM-VERIFY.md` present with `status: pending-operator`, build-first guard, all five gates, no gate marked passed
- All 3 task commits present under `08-02`; all key files exist on disk

---
*Phase: 08-llm-speed-selector-part-a*
*Completed: 2026-06-26*
