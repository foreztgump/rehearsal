---
phase: 08-llm-speed-selector-part-a
verified: 2026-06-26
verifier: phase-verification
phase_goal: >
  Replace the single stock LLM with two user-selectable Ollama models (Fast E2B
  default / Better E4B) via a plain-language UI picker, session-persisted, switchable
  on the next turn without session teardown — preserving the latency optimizations
  and verifying per-build that the abliterated community GGUFs have a sane chat
  template, leak no reasoning artifacts, and leave the persona prompt as the sole
  intact content guardrail.
requirement_ids: [LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06]
plans: [08-01, 08-02]
status: passed
human_verification_resolved: 2026-06-26
human_verification:
  - gate: "Gate 1 [VM-INTROSPECT] swap-surface probe"
    requirement: LLM-03
    expected: "has update_options: False; _opts exposes model/reasoning_effort/max_completion_tokens; plugin 1.6.4"
  - gate: "Gate A — verify-build.sh against both community tags (Fast + Better)"
    requirement: LLM-05
    expected: "Both tags PASS structural chat-template (role-turn markers + diff vs stock) and think=false artifact scan; FAIL → fall back to stock rung"
  - gate: "Gate B — persona red-team boundary probes against both abliterated models"
    requirement: LLM-06
    expected: "Unchanged persona holds refusal-equivalent boundary on Fast and Better; a FAIL is a finding to escalate, NOT a persona edit"
  - gate: "Gate C — live Fast↔Better mid-session swap + num_predict truncation"
    requirement: LLM-02/03/04
    expected: "Swap lands next-turn, no TTS interrupt, no injected turn, agent log shows new tag; 'count to 500' truncates at cap on both models"
  - gate: "Gate D — q8_0→F16 KV re-check per tag"
    requirement: LLM-04
    expected: "vram-validate.sh PASS for both tags (q8_0 KV engaged, no F16 fallback)"
---

# Phase 08 — LLM Speed Selector (Part A): VERIFICATION

**Phase goal:** Replace the single stock LLM with two user-selectable Ollama models (Fast E2B default / Better E4B) via a plain-language UI picker, session-persisted, switchable on the next turn without session teardown — preserving the latency optimizations and verifying per-build that the abliterated community GGUFs have a sane chat template, leak no reasoning artifacts, and leave the persona prompt as the sole content guardrail.

**Verified:** 2026-06-26
**Verdict:** PASS (sandbox-verifiable scope) — 5 operator/VM gates correctly deferred (human_needed), 0 failures.

---

## Requirement ID cross-reference (PLAN frontmatter ↔ REQUIREMENTS.md)

| Req ID | In PLAN frontmatter | In REQUIREMENTS.md | Code/deliverable present | Status |
|--------|---------------------|--------------------|--------------------------|--------|
| LLM-01 | 08-01 | yes (`[x]`) | ModelPanel outcome-label picker + agent `MODEL_CHOICES` validation | PASS (static) |
| LLM-02 | 08-01 | yes (`[x]`) | `DEFAULT_MODEL_CHOICE="fast"`, `current_model` holder, in-place swap | PASS (static) |
| LLM-03 | 08-01 | yes (`[x]`) | `resolved_model_tag`, `_opts.model` retarget, pull-and-pin two ladders | PASS (static) |
| LLM-04 | 08-01 | yes (`[x]`) | `reasoning_effort="none"` + `LIVE_NUM_PREDICT_CAP` + server env untouched | PASS (static) |
| LLM-05 | 08-02 | yes (`[ ]` Pending) | `ollama/verify-build.sh` (Check A + Check B), runbook Gate A | code present; live = human_needed |
| LLM-06 | 08-02 | yes (`[ ]` Pending) | `08-LLM-VERIFY.md` Gate B persona red-team, persona UNCHANGED | runbook present; live = human_needed |

**All 6 phase requirement IDs accounted for.** Every ID in both plan frontmatters maps to a REQUIREMENTS.md entry; no orphan IDs. LLM-01..04 marked Complete `[x]`; LLM-05/06 correctly remain Pending `[ ]` (operator-gated, runbook unsigned).

---

## must_haves verification (static / sandbox-verifiable)

### Plan 08-01 truths

| must_have | Evidence | Status |
|-----------|----------|--------|
| LLM-01 outcome-label picker, never raw tags; agent rejects non-`MODEL_CHOICES` | `ModelPanel.tsx:10,14-17` CHOICE_LABEL; `main.py:549` `choice not in MODEL_CHOICES → "error"` | PASS |
| LLM-02 default Fast, per-session, next-turn no teardown/TTS interrupt | `main.py:143` `DEFAULT_MODEL_CHOICE="fast"`, `:414` `current_model`, `:555` in-place swap, no `generate_reply`/`update_instructions` in handler | PASS |
| LLM-03 both via Ollama, plugin targets selected tag | `main.py:154-163` `resolved_model_tag`, `:555` retargets same instance; `pull-and-pin.sh:29-36` both ladders | PASS |
| LLM-04 thinking-off + streaming + capped num_predict, both models | `main.py:226` `reasoning_effort="none"`, `:387` `max_completion_tokens=LIVE_NUM_PREDICT_CAP` exactly once after `metrics.attach` | PASS |
| In-place swap on same LLM instance ⇒ metrics_collected survives | `main.py:555` mutates `session.llm._opts.model`, no reconstruction | PASS |
| Validate-before-mutate (Phase-6 fix) | `main.py:547-551` validates before `:552-555` mutation | PASS |

### Plan 08-01 prohibitions

| Prohibition | Check | Status |
|-------------|-------|--------|
| No raw tag / latency number in UI | `grep -niE "evalengine\|defyma85\|gemma\|latency\|tokens/s" ModelPanel.tsx` → only a comment, no rendered value | HONORED |
| No hardcoded model tag in code | `main.py` resolves via env with SystemExit-if-unset; no second `with_ollama`/`gemma` literal | HONORED |
| No teardown / LLM recreation / TTS recreation | single `openai.LLM.with_ollama` at `:223`; handler does in-place mutation only | HONORED |
| No `generate_reply`/`update_instructions` in `handle_model_update` | body `:542-556` contains neither | HONORED |
| No thinking back on, no metrics.py change | `reasoning_effort="none"` intact; no Phase-8 commit on `agent/metrics.py` | HONORED |
| No `OLLAMA_MAX_LOADED_MODELS` raise / out-of-band warming | absent | HONORED |
| No `model.get` RPC / agent→UI push (`useParticipantAttributes`) | absent from ModelPanel | HONORED |

### Plan 08-02 truths

| must_have | Evidence | Status |
|-----------|----------|--------|
| LLM-05 Check A structural template + Check B artifact superset | `verify-build.sh:48-74` role-turn markers + diff vs stock; `:76-97` think=false scan of 7-marker superset | PASS (static) |
| LLM-06 persona is sole guardrail, verified via Gate B red-team | `08-LLM-VERIFY.md:159-207`, escalate-don't-edit framing | PASS (runbook present) |
| Both tags pulled/pinned with stock fallback rungs | `pull-and-pin.sh:29-36` FAST/BETTER ladders, `:90-93` pins three vars | PASS |
| LLM-04 q8_0 re-check per GGUF (Gate D) | `08-LLM-VERIFY.md:250-279` reuses `vram-validate.sh` | PASS (runbook present) |
| Pull-time gate, not agent startup | `grep -rn verify-build agent/` → none | HONORED |

### Plan 08-02 prohibitions

| Prohibition | Check | Status |
|-------------|-------|--------|
| Persona UNCHANGED, no other content filter | `git log agent/persona.py` → last commit Phase 4, no Phase-8 edit | HONORED |
| No attack-cookbook fixtures committed | Gate B describes SHAPE only (`08-LLM-VERIFY.md:170-182`) | HONORED |
| No hardcoded picker tag in code | tags live in ladders/env only | HONORED |
| verify-build.sh not wired into agent startup | confirmed absent in `agent/` | HONORED |
| No STT/TTS change, no metrics.py change | `build_session` STT/TTS untouched; no Phase-8 metrics commit | HONORED |

---

## Static gate results

| Check | Result |
|-------|--------|
| `python3 -m py_compile agent/main.py` | exit 0 |
| `agent/requirements.txt` pins `livekit-plugins-openai==1.6.4` | confirmed (line 12) |
| `bash -n ollama/pull-and-pin.sh` | exit 0 |
| `bash -n ollama/verify-build.sh` | exit 0 |
| ModelPanel raw-tag/latency scan | clean (label-only) |
| `.env.example` documents `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` + Fast alias | confirmed (lines 35-40) |
| Server latency env (`OLLAMA_FLASH_ATTENTION`/`OLLAMA_KV_CACHE_TYPE`/`OLLAMA_KEEP_ALIVE`) unchanged | confirmed (lines 27-29) |
| `VoiceRoom.tsx` imports + renders `<ModelPanel />` inside `<LiveKitRoom>` | confirmed (lines 8, 88) |
| `agent/metrics.py` / `agent/persona.py` untouched in Phase 8 | confirmed (git log) |

Note: cap is applied at exactly one site — `main.py:387` `session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP` (after `metrics.attach`, before `session.start`), `LIVE_NUM_PREDICT_CAP=256` (named constant, no magic value).

---

## Deferred to human operator (RTX 5090 VM — NOT failures)

These are correctly `autonomous: false` and documented in `08-LLM-VERIFY.md` (`status: pending-operator`). Code/scripts/runbook are in place and correct; live proof requires the GPU VM.

| Gate | Requirement | Classification |
|------|-------------|----------------|
| Gate 1 [VM-INTROSPECT] swap-surface probe | LLM-03 (confirm `_opts.model` swap site on plugin 1.6.4) | human_needed |
| Gate A: `verify-build.sh` against both community tags | LLM-05 | human_needed |
| Gate B: persona red-team boundary probes, both abliterated models | LLM-06 | human_needed |
| Gate C: live Fast↔Better mid-session swap + num_predict truncation | LLM-02/03/04 cross-check | human_needed |
| Gate D: q8_0→F16 KV re-check per tag | LLM-04 | human_needed |

The runbook carries the build-first guard, all five gates with empty results tables, the escalate-don't-edit framing for LLM-06, and marks nothing passed — matching the v1.0 operator-gate posture.

---

## Conclusion

Phase 08 goal is **ACHIEVED** within the sandbox-verifiable scope:

- **LLM-01..04** — fully implemented and statically verified. The Fast/Better picker, in-place `_opts.model` swap (no teardown, next-turn effective), per-session `current_model` holder, validate-before-mutate `model.update` RPC, and the one-site num_predict cap are all present and correct; thinking-off/streaming/server latency env preserved.
- **LLM-05..06** — all deliverables (`pull-and-pin.sh` two ladders, `verify-build.sh` Check A+B, `08-LLM-VERIFY.md` runbook) are present, syntactically valid, and correctly structured. Their live acceptance is intentionally operator-gated on the GPU VM and remains Pending in REQUIREMENTS.md by design.

All 6 requirement IDs accounted for. All constraints honored (persona unchanged, no raw tags in UI, no hardcoded tags, STT/TTS + metrics.py untouched). No failures. Phase sign-off blocks only on the five human-operator gates.

---

## Operator-gate resolution (2026-06-26 — RTX 5090, status → passed)

The five deferred human gates were run live on the RTX 5090. Full verdicts and
runbook evidence are in `08-LLM-VERIFY.md` and `08-UAT.md`; summary:

| Gate | Requirement | Verdict |
|------|-------------|---------|
| Gate 1 [VM-INTROSPECT] swap-surface probe | LLM-03 | **PASS** — `_opts.model` in-place swap confirmed on livekit-plugins-openai==1.6.4 (no `update_options`). |
| Gate A: `verify-build.sh` both tags | LLM-05 | **PASS** — think=false artifact scan clean on both. Required Ollama engine bump 0.6.8→0.30.10 to load the gemma4 GGUFs; Check A rewritten as a behavioral 3-turn `/v1` recall probe. |
| Gate B: persona red-team | LLM-06 | **FAIL → RISK ACCEPTED** (operator-approved, document-only). Persona insufficient as sole guardrail vs abliterated models; persona NOT edited. Tracked accepted limitation, not an open action item. |
| Gate C: live Fast↔Better mid-session swap + cap | LLM-02/03/04 | **PASS** — operator confirmed mid-TTS toggle did not interrupt speech nor inject a turn; swap landed next turn. num_predict cap FAIL→FIXED (Ollama `/v1` ignores `max_completion_tokens`; fixed via `extra_body={"max_tokens": LIVE_NUM_PREDICT_CAP}`). |
| Gate D: q8_0→F16 KV re-check per tag | LLM-04 | **PASS** — Fast 7408 MB, Better 8912 MB, q8_0 KV engaged, no F16 fallback (2 `vram-validate.sh` fixes). |

**Final verdict: PASS** — 4 gates PASS, 1 risk-accepted (Gate B, operator-approved),
0 blocking failures. Deployment finding logged separately and fixed: faster-whisper-server
cold-start dropped the first turn after 300s idle → pinned resident via `WHISPER__TTL=-1`.
