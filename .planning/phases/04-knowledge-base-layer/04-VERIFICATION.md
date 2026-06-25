---
phase: 04-knowledge-base-layer
status: human_needed
verified: 2026-06-25
verifier: gsd-verify-work
sandbox_layer: passed
operator_gates: pending
---

# Phase 04 — Knowledge Base Layer: VERIFICATION

**Status: HUMAN_NEEDED** — the sandbox-verifiable code-and-artifact layer is **complete and
correct** (all three plans implemented as written, all self-checks green, all prohibitions
honored). The phase goal's **live proofs** (Ollama distill grounding KB-04, and the entire
flat-TTFT/cache-hit/VRAM keystone KB-05) are **legitimately deferred VM/operator gates**, not
implementation gaps. They are captured as a runnable operator runbook in `04-KB-VERIFY.md` and
require the Proxmox VM (Docker + RTX 5090 + Ollama + browser + LAN device) the sandbox does not
have.

This is the expected terminal state for an MVP phase with heavy operator/VM-gated verification.
No genuine implementation gaps were found.

---

## Requirement traceability (PLAN frontmatter ↔ REQUIREMENTS.md)

Every requirement ID claimed across the three plan frontmatters is accounted for:

| Req | Plan | Layer | Sandbox verdict | Live verdict |
|-----|------|-------|-----------------|--------------|
| KB-01 | 04-01 | upload PDF/TXT/MD/DOCX as byte streams | **passed** (code) | operator (sendFile round-trip) |
| KB-07 | 04-01 | KB-active indicator + doc count | **passed** (code) | operator (attribute round-trip) |
| KB-08 | 04-01 | size guard on extracted tokens | **passed** (self-check) | n/a |
| REL-03 | 04-01 | typed parse errors → session continues | **passed** (self-check) | operator (UI surfacing) |
| KB-02 | 04-02 | distill docs → compact brief | **passed** (code) | operator (live distill quality) |
| KB-03 | 04-02 | inject once into frozen KB_SLOT | **passed** (golden green) | operator (cache-hold) |
| KB-04 | 04-02 | agent references user material | code present | **operator** (live grounding) |
| KB-06 | 04-02 | ephemeral in-memory KB | **passed** (no disk/db) | operator (teardown) |
| KB-05 | 04-03 | flat-TTFT invariant | runbook authored | **operator** (the keystone proof) |

All 9 IDs map to REQUIREMENTS.md rows (KB-01..08 + REL-03), all marked Complete in the
traceability table. No unaccounted IDs. No orphan IDs in plans.

---

## Success criteria assessment

1. **Upload + parse + distill into a brief** — code complete (04-01 parser, 04-02 distill). Pure
   parser `_self_check` green over fixture bytes; live parse/distill quality is an operator gate.
2. **KB-loaded references material; none → does not** — `render_prompt(p, "")` byte-identical to
   golden (no-KB unchanged, asserted); the FACTS-anchor brief lands in the prefix (asserted).
   The *demonstrable live grounding* (KB-04) is an operator gate.
3. **Per-turn TTFT stays flat** — KB-05 keystone; entirely operator/VM (Proof A in
   `04-KB-VERIFY.md`). Code path (inject once + freeze, no per-turn re-distill) is correct.
4. **Ephemeral + indicator + size guard** — `_SessionKb` in-memory only (no disk/db in path,
   grep-confirmed); KbPanel shows status + doc count; size guard on extracted tokens with
   `oversize_warn` + `oversize` error. **passed (code)**.
5. **Failed upload surfaces clear error, session continues** — typed `KbParseError` /
   `DistillError`, never raised across the boundary; `kb.state` error + early return. **passed**.

---

## Sandbox-verifiable layer — PASSED

### Self-checks & compile
- `python3 agent/kb/parse.py` → `kb.parse _self_check OK` (exit 0) — dispatch + extraction gate +
  size guard + all four typed reasons (`unsupported`/`scanned`/`corrupt`/`oversize`) +
  `oversize_warn` mid-size signal all asserted.
- `python3 agent/persona.py` → `persona _self_check OK` (exit 0) — golden `EXPECTED_DEFAULT`
  unchanged + empty-brief equivalence + fixed-brief determinism + brief-in-prefix.
- `python3 -m py_compile kb/parse.py kb/__init__.py kb/distill.py persona.py main.py` → exit 0.
- `build_distill_prompt('x')==build_distill_prompt('x')` → deterministic (exit 0).
- `bash -n scripts/vram-validate.sh` → exit 0.

### Prohibitions honored (grep-verified)
- No bare `except:` anywhere in `agent/kb/` (boundary returns typed errors).
- No livekit import in `agent/kb/` (only doc-string mentions + lazy `import fitz` inside `_extract`).
- No `format`/`format=json` in `distill.py` (Ollama #15260-safe); no hardcoded gemma tag.
- No volatile data (`datetime|time.|uuid|random|now()`) in `parse.py`.
- `agent/metrics.py` byte-identical (`git diff --stat` empty) — frozen per-turn key set untouched.
- DOCX via `python-docx` (`Document`, `doc.tables`, `doc.paragraphs`), NOT pymupdf4llm.
- Deps pinned tight: `pymupdf~=1.27`, `python-docx~=1.1` (pymupdf4llm meta-package documented).
- `COPY kb/ ./kb/` ships the whole package (incl. distill.py) in the agent image.
- `num_ctx 8192` justified by documented persona+brief+history+headroom accounting; "grows in
  Phase 4" forecast removed.

### Code-claim cross-check (summaries vs actual)
- 04-01: `_SessionKb` in-memory, `register_byte_stream_handler("kb.upload", ...)` after
  `session.start`, `_active_tasks` GC-guard + `add_done_callback`, `set_attributes({"kb.state":...})`
  — all present in `main.py`. KbPanel `sendFile(file,{topic})` + `useParticipantAttributes` +
  `distilling` status union member present. Mounted inside `<LiveKitRoom>` in VoiceRoom.
- 04-02: `render_prompt(p, kb_brief)` places `kb_brief or KB_SLOT` last; `render_persona` delegates;
  `_ingest_kb` does `distilling → distill() (try/except DistillError) → update_instructions(...)
  once → ready → priming generate_reply`; `handle_persona_update` composes via
  `render_prompt(p, session_kb.brief)` + updates `current_persona`. Verified in `main.py`/`persona.py`.
- 04-03: Modelfile `num_ctx 8192` + accounting; vram-validate.sh additive `--with-kb`/`KB_FIXTURE`
  mode, all four assertions intact, default path unchanged; `04-KB-VERIFY.md` proofs A–D present.

### Commits
All 11 task commits present (`8177a73 772993e aa57993 b902dc2 a5d16cd 866afe2 4c876db 61e11e1
c92607c 5ba5f27 2760aac`) plus three plan-completion docs commits.

---

## Deferred operator gates (human_verification — NOT gaps)

These are intentionally `autonomous: false` / `[VM-INTROSPECT]` / OPERATOR-VERIFICATION items.
They are pending, not failed, and correctly NOT marked passed by the executors.

1. **Live SDK signatures** (`[VM-INTROSPECT]`): `register_byte_stream_handler` / `reader.info` /
   `set_attributes` on the installed rtc SDK; `sendFile` + attribute-change event on
   `livekit-client@2.20.0`; `update_instructions` coroutine; silent `generate_reply` prime;
   `pymupdf4llm.to_markdown` signature. (Client types statically verified; live flow is the gate.)
2. **KB-04 live grounding**: upload a doc with a distinctive fact → trainer references it by voice;
   no-KB does not invent it; persona edit after KB load preserves grounding (compose, not clobber).
3. **KB-05 keystone (Success Criterion 3)** — `04-KB-VERIFY.md` Proofs A–D, all blank/pending:
   - Proof A: turn-2 `llm_ttft_ms` ≪ turn-1; turn-2(KB) ≈ turn-2(no-KB).
   - Proof B: Ollama turn-2 prompt-eval small (cache hit, not brief re-eval).
   - Proof C: measured brief tokens → confirm `num_ctx` smallest covering value.
   - Proof D: KB-loaded peak VRAM < 16384 MB (headroom), q8_0 engaged, 3 GPU procs (PERF-02).
4. **MANUAL upload matrix**: PDF/TXT/MD/DOCX → `ready (1 docs)`; scanned/empty → "looks scanned" +
   loop continues; unsupported → clear error; oversize → guard fires.

**Operator action:** run the four proofs in `04-KB-VERIFY.md` on the VM and fill the results tables
before relying on KB-04 / KB-05 / PERF-02 re-validation.

---

## Verdict

- **Sandbox layer:** PASSED — code complete, all self-checks green, all prohibitions honored, every
  requirement ID accounted for, no genuine implementation gaps.
- **Phase status:** HUMAN_NEEDED — the keystone live proofs (KB-04 grounding, KB-05 flat-TTFT,
  PERF-02 VRAM re-check) are legitimately deferred VM/operator gates, captured as a runnable
  runbook. This is the correct terminal state for this operator-gated MVP phase.
