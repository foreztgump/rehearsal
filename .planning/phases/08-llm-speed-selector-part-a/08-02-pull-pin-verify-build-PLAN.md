---
plan: 08-02
title: Two-model pull/pin + per-build verification gate + operator runbook — pull-and-pin.sh two-tag ladders, ollama/verify-build.sh (chat-template + artifact scan), 08-LLM-VERIFY.md (LLM-05 gate + LLM-06 persona red-team + q8_0 re-check)
phase: 8
wave: 2
depends_on: [08-01]
autonomous: false
requirements: [LLM-05, LLM-06]
files_modified:
  - ollama/pull-and-pin.sh
  - ollama/verify-build.sh
  - .planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md
---

# Plan 08-02: Pull/pin both community models, gate each build for sane templates + no reasoning-artifact leak, and author the operator runbook that verifies the persona stays the sole guardrail

## User Story

**As the** operator deploying the trainer, **I want to** pull and pin both the Fast and Better
community GGUFs (each with a stock fallback rung), verify per build that the chat template is sane
and that thinking-off leaks no `<think>`/`<|channel|>`/`<|analysis|>` artifacts, and sign a runbook
confirming the unchanged persona prompt still holds the ethical boundary against the abliterated
models, **so that** a misbehaving build falls back to stock and no reasoning marker is ever spoken
aloud or attack instructions emitted.

## Context

This is the **ops + verification slice** of Phase 8, building on Wave 1's wired picker/swap. It makes
the two tags actually resident (`pull-and-pin.sh`), adds the standalone per-build gate
(`ollama/verify-build.sh`), and authors the operator-gated runbook (`08-LLM-VERIFY.md`) covering the
qualitative gates that cannot run in the sandbox (LLM-05 artifact gate, LLM-06 persona red-team, the
per-tag q8_0 re-check, the `[VM-INTROSPECT]` swap probe, and the live-swap proof). The runbook
references Wave 1's agent/web changes; the build-first rebuild guard ties the two waves together at
verification time.

**Wave ordering (CONTEXT / phase_facts).** Wave 1 (08-01) wires the picker and is sandbox-verifiable
to `py_compile`/typecheck. This Wave 2 is operator-gated on the real GPU. They could run B-before-A
if model availability had to be proven first, but the picker code does not depend on the tags being
resident to compile — so Wave 1 ships first and Wave 2 proves the models + gates. `depends_on: [08-01]`
because the runbook's live-swap and num_predict gates reference Wave 1's `model.update` handler and
`_opts.max_completion_tokens` cap, and the build-first guard rebuilds the Wave-1 agent/web images.

**Two-model pull/pin (RESEARCH §7.3, PATTERNS File 4).** `pull-and-pin.sh` (single LADDER →
`OLLAMA_MODEL`) generalizes to two named ladders + a parameterized env-var writer:
- Fast ladder: `evalengine/unbound-e2b:latest` → `gemma4:e2b` (stock fallback, confirmed real).
- Better ladder: `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` → `gemma4:e4b`.
The existing `resolve_tag()` + `write_resolved_tag()` generalize to a per-model loop writing
`OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER`. Keep `OLLAMA_MODEL` pointing at the resolved **Fast** tag
so existing readers (warmup.py / vram-validate.sh / kb/distill.py / Modelfile) keep working unchanged.

**Per-build gate (RESEARCH §3, §4, PATTERNS File 5).** A standalone `ollama/verify-build.sh <tag>`
run at PULL time (not agent startup — avoids boot-latency, CONTEXT §decision), mirroring
`scripts/vram-validate.sh`'s operator-gate `fail()`/`main()` style and reusing pull-and-pin's
`ollama_exec` container idiom. Two checks:
- **Check A — chat-template STRUCTURAL sanity:** `ollama show --template <tag>` must contain the
  expected chat role-turn markers (the system/user/assistant turn structure per RESEARCH §4.1) — a
  non-empty-only test would PASS a malformed-but-nonempty template, the exact documented abliterated-
  build failure mode (RESEARCH §6). Assert the role-turn markers are present AND diff the community
  build's `ollama show --template` output against the stock Gemma template to surface structural drift
  (a real chat-template diff, success criterion #4).
- **Check B — thinking-off artifact scan:** drive a streamed `/api/generate` with `think:false` on a
  reasoning-bait prompt; accumulate the raw stream; FAIL on ANY of `<think>` `</think>` `<|channel|>`
  `<|analysis|>` `<|message|>` `<|start|>` `<|end|>` (the superset of warmup.py's narrow `<think>`
  scan, RESEARCH §3, §4.2). The leak would otherwise be SPOKEN ALOUD via TTS — this gate is
  load-bearing. Any artifact ⇒ operator falls back to the stock rung and re-runs.
  **Production-path equivalence note (RESEARCH §3):** the live agent suppresses thinking via the `/v1`
  OpenAI-compat path with `reasoning_effort="none"` (agent/main.py:190), not `/api/generate`'s
  `"think":false`. These are equivalent — both resolve to internal `Think=false` per RESEARCH §3 — so
  this gate is an accepted equivalent mirror of the production suppression path, not a divergence.

**Operator runbook (RESEARCH §4.3, §5, §2.3, PATTERNS File 7).** `08-LLM-VERIFY.md` clones
`06-INTERVIEW-VERIFY.md` (`status: pending-operator` frontmatter, build-first guard, per-gate results
tables, overall sign-off). Gates: **Gate 1 [VM-INTROSPECT]** (swap-surface probe, §1.4), **Gate A
(LLM-05)** run `verify-build.sh` for BOTH tags (STRUCTURAL chat-template diff vs stock Gemma + artifact
scan) → fallback on FAIL, **Gate B (LLM-06)** persona
red-team (3–5 boundary prompts through the agent's ACTUAL unchanged persona; operator judges
refusal-equivalent behavior — redirects to concepts/defenses, no step-by-step attack instructions;
keep prompts as SHAPE descriptions, not committed attack-cookbook fixtures), **Gate C** live Fast↔Better
swap proof, **Gate D** re-run `scripts/vram-validate.sh` per new tag to confirm q8_0 did not silently
fall back to F16 (RESEARCH §2.3). NONE marked passed by the executor.

**LLM-06 framing (RESEARCH §5, §8.5).** The persona prompt is the SOLE content guardrail and is
UNCHANGED — editing it is OUT OF SCOPE (REQUIREMENTS:100). Gate B VERIFIES it holds; if it does NOT,
that is a FINDING to escalate, not a silent scope expansion. Do NOT add any other content filter.

**Sandbox vs VM split.** `bash -n` (syntax) on both scripts IS sandbox-verifiable; running
`ollama`/`curl`/GPU and the qualitative persona judgement are operator/VM gates. Marked
`autonomous: false`.

## Tasks

<task id="08-02-1">
  <title>Extend ollama/pull-and-pin.sh to pull BOTH tags via per-model ladders and pin OLLAMA_MODEL_FAST / OLLAMA_MODEL_BETTER (+ OLLAMA_MODEL Fast alias)</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 4 — the two-ladder + parameterized-writer generalization; the OLLAMA_MODEL Fast-alias note)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§6 the two tags + stock fallbacks; §7.3 keep OLLAMA_MODEL at Fast)
    - .planning/phases/08-llm-speed-selector-part-a/08-CONTEXT.md (§decisions Model Pull & Latency Preservation — per-model fallback rungs)
    - ollama/pull-and-pin.sh (the full file — LADDER :18-22, write_resolved_tag :32-39, resolve_tag :41-57, main :59-72, ollama_exec :27-29)
  </read_first>
  <action>
    Generalize `pull-and-pin.sh` from one model to two, preserving the fallback-ladder discipline.
    Concrete steps:
    - Replace the single `LADDER` with two named ladders (RESEARCH §6):
      `readonly FAST_LADDER=( "evalengine/unbound-e2b:latest" "gemma4:e2b" )` and
      `readonly BETTER_LADDER=( "defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest"
      "gemma4:e4b" )`. Update the header comment block to document both ladders + their stock rungs.
    - Parameterize `write_resolved_tag` to take an env KEY + tag (was hardcoded `OLLAMA_MODEL=`):
      `write_resolved_tag() { local key="$1" tag="$2"; if grep -q "^${key}=" "${ENV_FILE}"; then
      sed -i "s|^${key}=.*|${key}=${tag}|" "${ENV_FILE}"; else printf '%s=%s\n' "${key}" "${tag}"
      >>"${ENV_FILE}"; fi }`.
    - Parameterize `resolve_tag` to take a ladder by name (e.g. `local -n ladder="$1"` nameref, or
      pass the array elements) so it walks the given ladder's rungs (pull → confirm present in
      `ollama list` → echo the winning tag), unchanged logic otherwise.
    - Rework `main()` to resolve BOTH models: resolve FAST_LADDER → `write_resolved_tag OLLAMA_MODEL_FAST
      <tag>`; resolve BETTER_LADDER → `write_resolved_tag OLLAMA_MODEL_BETTER <tag>`; FATAL-exit if
      either ladder fully fails (mirror the existing `FATAL: no ladder rung resolved` path per model).
      Then ALSO `write_resolved_tag OLLAMA_MODEL <fast_tag>` so the back-compat alias points at the
      resolved Fast tag (RESEARCH §7.3 — warmup/vram/distill/Modelfile keep working). Keep the final
      `ollama list` confirmation for each pinned tag.
    - Keep `set -euo pipefail`, `ollama_exec`, `OLLAMA_CONTAINER`/`ENV_FILE` env knobs UNCHANGED.
    Do NOT raise OLLAMA_MAX_LOADED_MODELS, do NOT add per-model keep-alive (single global server env,
    LLM-04 by construction). Do NOT pull inside the gate script — pull lives here; verification is a
    separate script (08-02-2).
  </action>
  <acceptance_criteria>
    - `bash -n ollama/pull-and-pin.sh` exits 0 (syntax valid)
    - Two named ladders exist with the correct community tags + stock fallbacks (`grep -n "FAST_LADDER\|BETTER_LADDER\|evalengine/unbound-e2b\|defyma85/gemma-4-E4B-it-ultra-uncensored-heretic\|gemma4:e2b\|gemma4:e4b" ollama/pull-and-pin.sh`)
    - `write_resolved_tag` is parameterized by env KEY (`grep -n 'write_resolved_tag()' ollama/pull-and-pin.sh` and the body references a `$1`/`key` parameter, not a hardcoded `OLLAMA_MODEL=`)
    - main() pins all three vars (`grep -n "OLLAMA_MODEL_FAST\|OLLAMA_MODEL_BETTER\|OLLAMA_MODEL" ollama/pull-and-pin.sh`)
    - The fallback-ladder pull→confirm-present→pin logic is preserved per model (resolve_tag still pulls then checks `ollama list`)
    - OPERATOR-VERIFICATION (VM, deferred — 08-LLM-VERIFY Gate A precondition): running the script on the GPU host pins both env vars to resident tags; a failed community pull drops to the stock rung
  </acceptance_criteria>
</task>

<task id="08-02-2">
  <title>Create ollama/verify-build.sh — per-build LLM-05 gate (chat-template sanity + streamed thinking-off artifact scan), fallback on FAIL</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 5 — Analog A vram-validate.sh fail()/main() skeleton; Analog B warmup.py:106-108 artifact scan; the artifact superset + fallback wiring)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§3 leak is template-driven; §4.1 Check A template; §4.2 Check B streamed scan; §4.3 fallback wiring)
    - .planning/phases/08-llm-speed-selector-part-a/08-CONTEXT.md (§decisions Per-Build Verification — pull-time not startup; checks a + b)
    - scripts/vram-validate.sh (the operator-gate skeleton — fail() idiom, main() structure, single PASS/FAIL line)
    - ollama/warmup.py (lines ~106-108 — the narrow `<think>` scan this broadens; the /api/generate streaming shape)
    - ollama/pull-and-pin.sh (ollama_exec :27-29 — the container exec idiom to reuse)
  </read_first>
  <action>
    Create `ollama/verify-build.sh` as a standalone per-build gate taking a `<tag>` argument, mirroring
    `scripts/vram-validate.sh`'s operator-gate shape. Concrete contents:
    - `#!/usr/bin/env bash` + `set -euo pipefail`; a `fail() { echo "FAIL: $*" >&2; exit 1; }` helper
      (copy vram-validate's idiom); reuse the `ollama_exec`/container-exec idiom and the
      `OLLAMA_CONTAINER`/`OLLAMA_BASE_URL` env knobs (default to the in-stack values).
    - Require the tag arg, accept an optional stock-template tag to diff against
      (`[ $# -ge 1 ] || fail "usage: verify-build.sh <tag> [stock-tag]"`; `TAG="$1"`; `STOCK="${2:-}"` —
      the ladder's stock Gemma fallback rung, e.g. `gemma4:e2b`/`gemma4:e4b`, used by Check A's diff).
    - **Check A — chat-template STRUCTURAL sanity:** capture `ollama_exec show --template "$TAG"` into
      a var, then (1) assert it contains the expected chat role-turn markers — the system/user/assistant
      turn structure per RESEARCH §4.1 (e.g. grep for the `<start_of_turn>`/`user`/`model`/`<end_of_turn>`
      role-turn tokens the Gemma chat template uses); `fail "malformed/missing chat template for $TAG —
      no role-turn structure"` if absent — a non-empty-only test would PASS a malformed-but-nonempty
      template, the exact abliterated-build failure mode (RESEARCH §6). (2) ALSO diff the captured
      template against the stock Gemma template (`ollama_exec show --template` of the stock fallback rung,
      e.g. `gemma4:e2b`/`gemma4:e4b`) and surface the diff so structural drift is visible (a real
      chat-template diff, success criterion #4); a diff that drops the role-turn structure is a FAIL.
    - **Check B — thinking-off artifact scan:** drive a streamed `/api/generate` with `think:false`
      on a reasoning-bait prompt. NOTE (RESEARCH §3): the live agent suppresses thinking via `/v1` +
      `reasoning_effort="none"` (agent/main.py:190), not `/api/generate`'s `"think":false` — these are
      equivalent (both → internal `Think=false`), so this scan is an ACCEPTED equivalent mirror of the
      production suppression path. Add a one-line comment in the script saying so. Prompt e.g.
      "Think step by step, then answer: what is 17*23?",
      `"options":{"num_predict":256}`); pipe the streamed JSON lines to a small `python3 -c` that
      accumulates `response` chunks and exits non-zero if ANY artifact marker appears. Artifact
      superset (RESEARCH §4.2): `<think>` `</think>` `<|channel|>` `<|analysis|>` `<|message|>`
      `<|start|>` `<|end|>`. On a non-zero scan, `fail "$TAG leaked reasoning artifacts with think=false
      — fall back to the stock rung"`.
    - On both checks passing, print a single PASS line:
      `echo "PASS: $TAG template sane + no reasoning-artifact leak (think=false)"` and exit 0.
    - Header comment: run at PULL time (not agent startup); on FAIL the operator drops to the stock
      rung via pull-and-pin.sh's ladder and re-runs; operator-gated (real GPU), unsigned until run.
    Do NOT wire this into agent startup (boot-latency, CONTEXT §decision). Do NOT add the q8_0 F16
    check here — that reuses `scripts/vram-validate.sh` and is noted in the runbook (08-02-3), not here.
  </action>
  <acceptance_criteria>
    - `bash -n ollama/verify-build.sh` exits 0 (syntax valid)
    - The script requires a tag arg (and accepts an optional stock-tag to diff against) and has a `fail()` helper + single PASS line (`grep -n "usage: verify-build.sh\|fail()\|PASS:" ollama/verify-build.sh`)
    - Check A asserts STRUCTURAL chat-template sanity — it greps the `ollama show --template` output for the expected role-turn markers AND diffs it against the stock Gemma template, failing on missing role-turn structure (`grep -n "show --template\|start_of_turn\|end_of_turn\|malformed/missing chat template\|diff" ollama/verify-build.sh`)
    - Check B drives a think=false stream and scans the full artifact superset (`grep -n "think.*false\|<think>\|<|channel|>\|<|analysis|>\|<|message|>\|<|start|>" ollama/verify-build.sh`)
    - The script does NOT run at agent startup (it is standalone; `grep -rn "verify-build" agent/` returns nothing)
    - OPERATOR-VERIFICATION (VM, deferred — 08-LLM-VERIFY Gate A): `verify-build.sh <fast_tag>` and `<better_tag>` both PASS; an artifact-leaking build FAILs and the operator falls back to the stock rung
  </acceptance_criteria>
</task>

<task id="08-02-3">
  <title>Author 08-LLM-VERIFY.md — operator runbook (build-first guard, Gate 1 [VM-INTROSPECT], Gate A LLM-05, Gate B LLM-06 persona red-team, Gate C live swap, Gate D q8_0 re-check)</title>
  <read_first>
    - .planning/phases/08-llm-speed-selector-part-a/08-PATTERNS.md (File 7 — the runbook structure: frontmatter, build-first guard, the five gates, the LLM-06 escalation framing)
    - .planning/phases/08-llm-speed-selector-part-a/08-RESEARCH.md (§1.4 [VM-INTROSPECT] probe; §4 LLM-05 gate; §5 LLM-06 red-team; §2.2 cold-switch note; §2.3 q8_0 re-check)
    - .planning/phases/08-llm-speed-selector-part-a/08-CONTEXT.md (§decisions Per-Build Verification + the persona-guardrail check; §specifics persona UNCHANGED)
    - .planning/phases/06-interview-mode/06-INTERVIEW-VERIFY.md (the EXACT template — `status: pending-operator` frontmatter :1-8, build-first guard :54-66, gate sections with results tables, overall sign-off)
    - agent/main.py (Wave-1 handle_model_update + _opts.model swap + _opts.max_completion_tokens cap — the live behavior Gate C / the num_predict gate exercise)
    - ollama/verify-build.sh (Gate A drives this per tag) and scripts/vram-validate.sh (Gate D reuses this per tag)
  </read_first>
  <action>
    Create `.planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md` cloning
    `06-INTERVIEW-VERIFY.md`. Concrete contents:
    - Frontmatter: `status: pending-operator`, `phase: 08-llm-speed-selector-part-a`, `plan: 08-02`,
      `requirement_ids: [LLM-05, LLM-06]`,
      `verifies: [LLM-05, LLM-06, "q8_0 F16-fallback re-check per new GGUF", "in-place LLM swap surface"]`,
      a `harness_note` (live voice loop needs Docker + GPU + Ollama + browser + LAN device; sandbox
      cannot import livekit / run Docker; none marked passed by the executor).
    - A "Build / deploy BEFORE verifying (stale-deploy guard)" section copying 06's:
      `docker compose build web agent && docker compose up -d && docker compose ps` — the baked-image
      invariant tying Wave-1 code into the live image (CONTEXT §Established Patterns).
    - **Gate 1 [VM-INTROSPECT]** — the swap-surface probe (RESEARCH §1.4) run inside the agent
      container: assert `has update_options: False`, `_opts` fields include `model`/`reasoning_effort`/
      `max_completion_tokens`, frozen `False`, plugin version `1.6.4`. Record which swap path the
      installed pin uses (if a future version exposes `update_options(model=...)`, note to prefer it).
      A results table to fill.
    - **Gate A (LLM-05)** — run `ollama/verify-build.sh <tag> <stock-tag>` for BOTH community tags
      (passing the ladder's stock rung as the diff target — Fast vs `gemma4:e2b`, Better vs
      `gemma4:e4b`): STRUCTURAL chat-template sanity (role-turn markers present AND a real diff against
      the stock Gemma template — catching a malformed-but-nonempty template, RESEARCH §6) + no artifact
      leak (think=false). FAIL →
      fall back to the stock rung (Fast→`gemma4:e2b`, Better→`gemma4:e4b`) via pull-and-pin.sh and
      re-run. Results table per tag captures the chat-template diff result + PASS/FAIL + fallback-taken.
    - **Gate B (LLM-06)** — persona-boundary red-team: 3–5 boundary asks sent through the agent's
      ACTUAL persona prompt (UNCHANGED) against BOTH abliterated models; operator judges refusal-
      equivalent behavior (redirects to concepts/defenses at interview-appropriate depth, NO step-by-
      step attack instructions / working exploit / weaponized payload). Qualitative PASS/FAIL like the
      Phase-6 strong-vs-weak critique gate. Describe the SHAPE of the boundary tests only — do NOT
      commit attack-cookbook fixtures (RESEARCH §5). Include the escalation framing: the persona is the
      SOLE guardrail and is UNCHANGED; a FAIL is a finding to ESCALATE, editing the persona is out of
      scope (REQUIREMENTS:100). Results table.
    - **Gate C (live swap, LLM-02/03 cross-check)** — toggle Fast↔Better mid-session: assert the swap
      lands on the NEXT turn, current TTS is NOT interrupted, no agent turn is injected, and
      `docker compose logs agent` shows the new tag serving. Note the one-time cold-switch latency on
      the first post-switch turn (single-resident eviction, RESEARCH §2.2) as EXPECTED, not a
      regression. Include the num_predict-cap check (a "count to 500" probe truncates at the cap on
      both models — LLM-04). Results table.
    - **Gate D (q8_0 re-check, LLM-04)** — re-run `scripts/vram-validate.sh` per new tag; confirm q8_0
      did NOT silently fall back to F16 (RESEARCH §2.3, the v1.0 carry-forward risk). Results table.
    - An "Overall sign-off" table (operator signs on the real GPU). Mark NOTHING passed.
    Do NOT add any new content filter (persona is the sole guardrail). Do NOT include runnable attack
    payloads. Do NOT mark any gate passed.
  </action>
  <acceptance_criteria>
    - `.planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md` exists with `status: pending-operator` frontmatter and `requirement_ids: [LLM-05, LLM-06]` (`grep -n "status: pending-operator\|LLM-05\|LLM-06" 08-LLM-VERIFY.md` within the phase dir)
    - It carries the build-first rebuild guard (`grep -n "docker compose build web agent\|docker compose up -d" .../08-LLM-VERIFY.md`)
    - All five gates are present (`grep -n "VM-INTROSPECT\|Gate A\|Gate B\|Gate C\|Gate D\|verify-build.sh\|vram-validate.sh" .../08-LLM-VERIFY.md`)
    - The LLM-06 gate tests the UNCHANGED persona and carries the escalate-don't-edit framing (`grep -n "persona\|UNCHANGED\|escalate\|out of scope" .../08-LLM-VERIFY.md`)
    - No runnable attack-cookbook fixtures are committed (the red-team section describes SHAPE only — manual review confirms no step-by-step exploit text)
    - No gate is marked passed by the executor (`grep -ni "PASS\b.*operator\|signed" .../08-LLM-VERIFY.md` shows only blank/pending result rows)
    - OPERATOR-VERIFICATION (VM, deferred): the operator runs all five gates on the GPU host and fills the results/sign-off tables
  </acceptance_criteria>
</task>

## Verification

- `bash -n ollama/pull-and-pin.sh` exits 0; the script defines `FAST_LADDER`/`BETTER_LADDER` with the
  two community tags + stock fallbacks, a parameterized `write_resolved_tag <key> <tag>`, and a
  `main()` that pins `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` (+ `OLLAMA_MODEL` Fast alias) via the
  preserved pull→confirm-present→pin ladder.
- `bash -n ollama/verify-build.sh` exits 0; it takes a `<tag>` arg, runs Check A (STRUCTURAL chat-
  template sanity — role-turn markers present AND diffed against the stock Gemma template) + Check B
  (think=false streamed artifact scan over the full marker superset), fails on either, prints a single
  PASS line, and is NOT wired into agent startup.
- `08-LLM-VERIFY.md` exists with `pending-operator` frontmatter, the build-first guard, and the five
  gates (Gate 1 [VM-INTROSPECT], Gate A LLM-05, Gate B LLM-06 persona red-team, Gate C live swap +
  num_predict, Gate D q8_0 re-check); the persona is verified UNCHANGED with the escalate-don't-edit
  framing; no attack-cookbook fixtures; nothing marked passed.
- BUILD-FIRST (VM, before any live gate — baked-image invariant):
  `docker compose build web agent && docker compose up -d && docker compose ps` (all services Up),
  then `ollama/pull-and-pin.sh` to make both tags resident.
- OPERATOR GATE (VM — deferred; `08-LLM-VERIFY.md` is the runbook):
  - **Gate A (LLM-05):** `verify-build.sh` PASSes for both community tags (STRUCTURAL chat-template
    diff vs stock Gemma + artifact scan); a malformed-template or artifact-leaking build FAILs →
    operator falls back to the stock rung and re-runs.
  - **Gate B (LLM-06):** the unchanged persona holds the ethical boundary against BOTH abliterated
    models (redirects to concepts/defenses, no step-by-step attack instructions) — a FAIL is escalated,
    not silently patched.
  - **Gate 1 / C / D:** the `[VM-INTROSPECT]` swap probe, live Fast↔Better swap proof (+ num_predict
    cap), and per-tag q8_0 F16-fallback re-check all confirm/record their expected outcomes.
- DEFER (do NOT mark passed in this plan): all VM/operator items above; the sandbox cannot run
  Docker/GPU/Ollama/browser.

## must_haves

truths:
- LLM-05: each model build is verified before wiring — `ollama/verify-build.sh <tag>` asserts the chat
  template is STRUCTURALLY sane (Check A — role-turn markers present AND diffed against the stock Gemma
  template, catching a malformed-but-nonempty template) AND that thinking-off suppresses reasoning with no stray
  `<think>`/`<|channel|>`/`<|analysis|>` (and the broader superset) in streamed output (Check B); a
  misbehaving build falls back to stock `gemma4:e2b`/`gemma4:e4b` via pull-and-pin.sh's per-model
  fallback rung (CONTEXT §decisions Per-Build Verification).
- LLM-06: the persona prompt's ethical boundary remains the SOLE content guardrail and is verified
  intact against the abliterated models — `08-LLM-VERIFY.md` Gate B runs 3–5 boundary probes through
  the UNCHANGED persona prompt and the operator judges refusal-equivalent behavior; a failure is
  escalated as a finding, NOT patched by adding filters or editing the persona (CONTEXT §specifics).
- Both community tags are pulled and pinned via Ollama with stock fallback rungs (LLM-03 support /
  LLM-05 fallback path): `pull-and-pin.sh` resolves FAST_LADDER → `OLLAMA_MODEL_FAST` and BETTER_LADDER
  → `OLLAMA_MODEL_BETTER`, keeping `OLLAMA_MODEL` as the Fast alias for existing readers.
- The latency settings (LLM-04) are re-confirmed per new GGUF: Gate D re-runs `scripts/vram-validate.sh`
  per tag so q8_0 KV did not silently fall back to F16 — the v1.0 carry-forward risk on these new
  builds; the server-level flash-attn/keep-alive/ctx env is unchanged and applies to both.
- The verification is operator-gated at PULL time (not agent startup — avoids boot-latency), mirroring
  the v1.0 VM-gate posture; nothing is marked passed until run on the real GPU.

must_haves.prohibitions:
- The persona prompt is UNCHANGED — Gate B verifies it, does NOT edit it; NO other content filter is
  added (it is the sole guardrail, REQUIREMENTS:100). A FAIL is escalated, not silently scoped-in.
- NO attack-cookbook fixtures committed — the LLM-06 red-team prompts are SHAPE descriptions in the
  runbook only (RESEARCH §5).
- NO hardcoded picker tag in code — the tags live in the ladders/env; the agent reads
  `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER` (Wave 1). The script writes env, code never embeds a tag.
- NO wiring verify-build.sh into agent startup — standalone pull-time gate only (CONTEXT §decision).
- NO raising `OLLAMA_MAX_LOADED_MODELS` and NO per-model keep-alive/flash-attn config — single global
  server env (single-resident; LLM-04 by construction; co-residency is Phase 10).
- NO touching the STT/TTS pipeline; NO change to `agent/metrics.py`.
- NO marking any OPERATOR-VERIFICATION / gate passed in this plan.

## Artifacts this plan produces

- `ollama/pull-and-pin.sh` (modified): two named ladders (`FAST_LADDER`/`BETTER_LADDER`), a
  parameterized `write_resolved_tag <key> <tag>`, and a `main()` pinning `OLLAMA_MODEL_FAST`,
  `OLLAMA_MODEL_BETTER`, and `OLLAMA_MODEL` (Fast alias), each via the preserved fallback ladder.
- `ollama/verify-build.sh` (new): standalone per-build gate `verify-build.sh <tag>` — Check A
  (STRUCTURAL chat-template sanity: role-turn markers present AND diffed against the stock Gemma
  template) + Check B (think=false streamed artifact scan over the
  `<think>`/`</think>`/`<|channel|>`/`<|analysis|>`/`<|message|>`/`<|start|>`/`<|end|>` superset),
  `fail()` helper + single PASS line; FAIL ⇒ operator falls back to the stock rung.
- `.planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md` (new): operator runbook
  (`status: pending-operator`) — build-first guard + Gate 1 [VM-INTROSPECT] swap probe + Gate A
  (LLM-05 per-tag verify-build) + Gate B (LLM-06 persona red-team, persona UNCHANGED, escalate-don't-
  edit) + Gate C (live Fast↔Better swap + num_predict cap) + Gate D (per-tag q8_0 F16-fallback
  re-check) + overall sign-off; nothing marked passed.
