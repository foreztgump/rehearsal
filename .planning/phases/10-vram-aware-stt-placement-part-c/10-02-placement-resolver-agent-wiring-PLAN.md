---
plan: 10-02
title: agent/placement.py pure resolve_stt_placement (STT_FORCE_CPU first → worst-case-LLM headroom → default-CPU-when-unmeasured) + main.py NEMO_STT_CPU_URL wiring resolved-once-at-session-start + STT_FORCE_CPU=1 safe default in .env.example + vram-validate.sh 4-cell matrix + 10-PLACEMENT-VERIFY runbook
phase: 10
wave: 2
depends_on: [10-01]
autonomous: false
requirements: [STT-06, STT-07]
files_modified:
  - agent/placement.py
  - agent/main.py
  - tests/test_placement.py
  - .env.example
  - scripts/vram-validate.sh
  - .planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md
---

# Plan 10-02: The placement leg — a pure resolve_stt_placement wired once into build_session, the STT_FORCE_CPU=1 safe default, the 4-cell VRAM co-residency matrix, and the operator GPU-gate runbook

## User Story

**As** the operator deploying the VRAM-aware stack, **I want** STT placement (GPU-NeMo vs CPU-ONNX)
resolved EXACTLY ONCE at session start from the selected LLM + a static measured-headroom table —
with `STT_FORCE_CPU` as the first-checked global pin and CPU as the safe default until the operator
co-residency gate proves E4B + GPU-STT + Kokoro co-fit — **so that** the picker is VRAM-safe out of
the box, a mid-session Fast↔Better LLM swap never thrashes the runtime, and the agent connects to the
right STT URL with zero runtime switching.

## Context

This is the **placement-decision half** of Phase 10, built on Wave 1's `STT_RUNTIME` backend
contract + the `nemo-stt-cpu` service URL. It writes `agent/placement.py` (the pure
`resolve_stt_placement(llm_choice, env) -> "gpu"|"cpu"` resolver + the static VRAM table), wires it
ONCE into `build_session`, ships `STT_FORCE_CPU=1` as the `.env.example` safe default + the
`NEMO_STT_CPU_URL` const, parametrizes `vram-validate.sh` to the 4-cell `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}`
matrix, and authors the operator GPU-gate runbook `10-PLACEMENT-VERIFY.md`. Depends on **10-01**
because the agent picks between `NEMO_STT_URL` (GPU) and `NEMO_STT_CPU_URL` (the Wave-1 CPU service)
and the matrix exercises both runtimes.

**The resolver is a pure, livekit-free decision module (PATTERNS §1, Analog `agent/history.py`).**
`resolve_stt_placement(llm_choice: str, env: Mapping[str,str]) -> str` returning `"gpu"`/`"cpu"`,
frozen UPPER_CASE table constants, a `_self_check()` under `if __name__ == "__main__":` so `python3
agent/placement.py` runs in the sandbox. No `nvidia-smi`, no livekit import, no exception escapes — it
ALWAYS returns `"gpu"`/`"cpu"`. The EFFECT (picking the URL) lives in `main.py` — same DECISION/EFFECT
split as `history.py`/`interview.py`.

**Resolution order is LOCKED (RESEARCH §3, CONTEXT):**
1. **`STT_FORCE_CPU` FIRST** — truthy (`{"1","true","yes","on"}`, normalized) → return `"cpu"`
   immediately, BEFORE any headroom logic (STT-07). The global pin for both LLMs.
2. **A `measured` gate** — the GPU branch is gated behind an explicit `STT_HEADROOM_MEASURED`
   (truthy) signal the operator sets ONLY after the 4-cell matrix passes. `if not measured: return
   "cpu"` (the default-CPU-when-unmeasured lock).
3. **Static measured-headroom table, worst-case-LLM math (STT-06)** — only when measured: compute
   against the HEAVIEST LLM that could be selected this session (E4B/Better), so a mid-session
   Fast↔Better swap is always VRAM-safe. If `worst_llm + KOKORO_MB + STT_GPU_MB > ceiling` → `"cpu"`
   for the WHOLE session; else `"gpu"`.

**The table constants (RESEARCH §3 — cite + flag each):** `VRAM_TOTAL_MB=16384`,
`VRAM_HEADROOM_MB=1024` (ceiling 15360), `LLM_PEAK_MB={"fast":7408,"better":8912}` (MEASURED Phase 8
Gate D, STATE.md:114), `STT_GPU_MB=2400` (GPU-NeMo, Phase 9), `STT_CPU_GPU_MB=0` (CPU-ONNX uses no
VRAM), `KOKORO_MB=2048` (⚠️ UNMEASURED PLACEHOLDER — the operator co-residency gate pins the real
number). The arithmetic with the placeholder *says* GPU fits, but Kokoro is unmeasured AND the LLM
peaks were measured WITHOUT a co-resident GPU-STT — so the `measured` gate (step 2) keeps the default
CPU until the 4-cell matrix proves it. The shipped `.env.example` carries `STT_FORCE_CPU=1` so the
picker is VRAM-safe out of the box regardless.

**Input validation at the boundary (RESEARCH §3, Phase 6/8 discipline).** `llm_choice` normalized
against `MODEL_CHOICES`; an unknown choice → treated as WORST-CASE (CPU-safe), NOT a crash. `env`
booleans parsed via a single helper. The resolver is a hot-path session decision — it RETURNS a value,
never `raise SystemExit` (unlike `resolved_model_tag`).

**Wiring is resolve-ONCE (RESEARCH §3, PATTERNS §6, CONTEXT lock).** Add `NEMO_STT_CPU_URL` beside
`NEMO_STT_URL` (main.py:55, default `ws://nemo-stt-cpu:8000/v1/audio/stream`). In `build_session`
call `resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)` ONCE, pick `NEMO_STT_URL` (gpu) vs
`NEMO_STT_CPU_URL` (cpu), and construct `NemoSTT(ws_url=<resolved>, language="en")` (replacing the
fixed `NEMO_STT_URL` at main.py:200). `build_session` runs once in `entrypoint` (main.py:370) before
`session.start`. **DO NOT touch `handle_model_update` (main.py:536-554)** — placement is read once at
session start and NEVER re-consulted on an LLM swap (STT-06, no thrash, no coupling/guard added). Use
`DEFAULT_MODEL_CHOICE` (the session's initial pick) — the worst-case-LLM math inside the resolver is
what makes a later swap safe, so the resolver need not see the live `current_model`.

**The 4-cell VRAM matrix (RESEARCH §7, PATTERNS §8).** Parametrize `vram-validate.sh`: a
`--stt-runtime gpu|cpu` flag (or `STT_RUNTIME_UNDER_TEST`) sets `EXPECTED_GPU_PROCS` to **3** (GPU-STT:
ollama/nemo-stt/kokoro) or **2** (CPU-STT: ollama/kokoro — `nemo-stt-cpu` is NOT a GPU process); sweep
`OLLAMA_MODEL` over E2B (Fast) / E4B (Better), restarting ollama between tags to clear `keep_alive=-1`;
the peak `< total−1 GB` (15360) assertion is UNCHANGED per cell; the STT health probe targets
`nemo-stt` (8000) or `nemo-stt-cpu` (host 8001) per cell. The **GPU-STT × E4B cell is load-bearing** —
if its peak ≥ ceiling, the safe default stays `STT_FORCE_CPU=1` and the resolver returns CPU for E4B.

**The operator runbook (RESEARCH §9, PATTERNS §9, Analog `09-STT-VERIFY.md`).** Author
`10-PLACEMENT-VERIFY.md` with `status: pending-operator`, `requirement_ids: [STT-05, STT-06, STT-07]`,
a `harness_note` (no GPU/Docker/ORT in the sandbox), a §0 baked-image BUILD-FIRST step (`docker compose
build nemo-stt-cpu agent && up -d`), and unsigned gates: real ONNX export (cache_support=True) +
int8/int4 quant + size check; the mel-parity check; >6× realtime + WER-under-contention vs FP32/NeMo;
the 4-cell `{E2B,E4B}×{GPU,CPU}` co-residency matrix (peak < total−1 GB, 3 vs 2 procs) at the KB-load
prefill peak; the Kokoro `KOKORO_MB`-placeholder measurement; and the safe-default flip
(`STT_FORCE_CPU=1`→`0` + `STT_HEADROOM_MEASURED=1`, ONLY after the matrix passes). Every gate PENDING,
none marked passed by the executor.

**Sandbox vs operator split (RESEARCH §9).** Sandbox-verifiable: `placement.py` pure-fn unit tests
(`llm_choice × STT_FORCE_CPU × measured/headroom → gpu/cpu`, including force-cpu-first,
worst-case-LLM lock, default-CPU-when-unmeasured); `py_compile agent/placement.py` + `agent/main.py`;
the resolved-URL pick; `bash -n scripts/vram-validate.sh`. Operator gates: everything GPU/Docker/ORT/
accuracy, authored unsigned in `10-PLACEMENT-VERIFY.md`. Marked `autonomous: false`.

**Scope discipline (YAGNI).** NO live `nvidia-smi` probe driving placement (static table only). NO
mid-session re-resolution / GPU↔CPU thrash. DO NOT touch `handle_model_update`, the VAD/turn-detector/
`turn_handling`, or `agent/metrics.py` (READ-ONLY — `git diff` must stay empty). NO change to the WS
contract or the Wave-1 backends. Keep each function ≤40 lines / ≤3 params / ≤3 nesting.

## Tasks

<task id="10-02-1">
  <title>Create agent/placement.py — pure resolve_stt_placement(llm_choice, env) -> "gpu"|"cpu": STT_FORCE_CPU first, measured-gate, worst-case-LLM headroom table, default CPU; frozen VRAM constants + _self_check under __main__</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§3 the locked signature + resolution order + the table constants with citations + the worst-case-LLM math + the measured-flag rationale + input validation)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§1 Analog A history.py module shape + _self_check; Analog B resolved_model_tag env-validate posture but RETURN not SystemExit; Analog C resolve-once-never-thrash; the ≤40-line/pure-module invariants)
    - agent/history.py (the full pure-module template: from __future__ import annotations, frozen UPPER_CASE consts, typed pure fns, _self_check guarded by __main__)
    - agent/main.py (MODEL_CHOICES :132, DEFAULT_MODEL_CHOICE :133, resolved_model_tag :150-159 — the normalize-against-MODEL_CHOICES + env-read posture)
  </read_first>
  <action>
    Create `agent/placement.py` mirroring `agent/history.py`'s pure-module shape (cite history.py +
    interview.py in the docstring as the DECISION-owns-here / EFFECT-in-main.py split):
    - `from __future__ import annotations`; `import sys`; typing `Mapping`.
    - **Frozen table constants (RESEARCH §3, cite + flag each):** `VRAM_TOTAL_MB=16384`,
      `VRAM_HEADROOM_MB=1024`, `LLM_PEAK_MB={"fast":7408,"better":8912}` (comment: MEASURED Phase 8
      Gate D, STATE.md:114), `STT_GPU_MB=2400` (GPU-NeMo, Phase 9), `STT_CPU_GPU_MB=0`,
      `KOKORO_MB=2048` (comment: ⚠️ UNMEASURED PLACEHOLDER — operator co-residency gate pins it).
      Derive `_CEILING_MB = VRAM_TOTAL_MB - VRAM_HEADROOM_MB`.
    - `MODEL_CHOICES = ("fast", "better")` (local copy so the module stays livekit-free — do NOT import
      main.py). A `_FORCE_CPU_TRUTHY = {"1","true","yes","on"}` set.
    - **`_truthy(env, key) -> bool`:** read `env.get(key,"")`, lower/strip, return membership in the
      truthy set. The single boolean helper for `STT_FORCE_CPU` + `STT_HEADROOM_MEASURED`.
    - **`_gpu_fits() -> bool`:** worst-case-LLM math — `worst = max(LLM_PEAK_MB.values())`; return
      `worst + KOKORO_MB + STT_GPU_MB <= _CEILING_MB`. (With the placeholder this is True, but the
      caller gates it behind `measured`.)
    - **`resolve_stt_placement(llm_choice, env) -> str`:** (1) `if _truthy(env, "STT_FORCE_CPU"):
      return "cpu"` FIRST (STT-07, before any headroom logic); (2) `if not _truthy(env,
      "STT_HEADROOM_MEASURED"): return "cpu"` (default-CPU-when-unmeasured lock); (3) normalize
      `llm_choice` — unknown → treat as worst-case (still CPU-safe); (4) `return "gpu" if _gpu_fits()
      else "cpu"`. No exception escapes; always returns `"gpu"`/`"cpu"`. Keep ≤40 lines / ≤3 nesting
      (push the math into `_gpu_fits`). Docstring states the worst-case-LLM lock makes a mid-session
      Fast↔Better swap VRAM-safe (STT-06) so placement is read ONCE and never re-resolved.
    - **`_self_check()`** guarded by `if __name__ == "__main__":` (mirror history.py:41-57): assert
      force-cpu-first wins even when measured+gpu-fits; unmeasured → cpu for both choices; measured +
      gpu-fits → gpu for both; unknown choice → cpu (worst-case, when measured the math still decides);
      determinism. `print("placement _self_check OK", file=sys.stderr)`. No livekit import.
    No `nvidia-smi`, no live probe, no livekit/main import. Single boolean helper, no magic strings.
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile agent/placement.py` exits 0 AND `python3 agent/placement.py` runs `_self_check` and prints OK (no livekit import) (`python3 agent/placement.py`)
    - The signature is exactly `resolve_stt_placement(llm_choice, env) -> str` returning "gpu"/"cpu" (`grep -n "def resolve_stt_placement" agent/placement.py`)
    - STT_FORCE_CPU is the FIRST check and short-circuits to "cpu" before any headroom logic (`grep -n "STT_FORCE_CPU" agent/placement.py`; read the function — it returns "cpu" before _gpu_fits is consulted)
    - The GPU branch is gated behind STT_HEADROOM_MEASURED (default CPU when unmeasured) (`grep -n "STT_HEADROOM_MEASURED" agent/placement.py`)
    - The VRAM table constants are present with the measured/placeholder citations (`grep -nE "VRAM_TOTAL_MB|VRAM_HEADROOM_MB|LLM_PEAK_MB|STT_GPU_MB|KOKORO_MB|7408|8912|PLACEHOLDER" agent/placement.py`)
    - The worst-case-LLM math uses max(LLM_PEAK_MB) so a Fast↔Better swap is safe (`grep -n "max(LLM_PEAK_MB" agent/placement.py`)
    - No nvidia-smi / live probe / livekit import (`grep -ni "nvidia-smi\|subprocess\|import livekit\|import main" agent/placement.py` returns nothing)
    - SANDBOX-TEST: the _self_check + test_placement (task 10-02-2) cover force-cpu-first, default-CPU-when-unmeasured, worst-case-LLM lock, and measured→gpu
  </acceptance_criteria>
</task>

<task id="10-02-2">
  <title>Create tests/test_placement.py — exhaustive pure-fn matrix: llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED → gpu/cpu, asserting force-cpu-first, default-CPU-when-unmeasured, worst-case-LLM lock, unknown-choice CPU-safe</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§9 the sandbox-verifiable placement cases enumerated; §3 the resolution order being tested)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§1 the pure-module testability — env passed as a Mapping)
    - agent/placement.py (the resolver authored in 10-02-1 — the function + constants under test)
    - agent/history.py (the _self_check assertion style to mirror if the repo has no pytest convention)
  </read_first>
  <action>
    Create `tests/test_placement.py` (or the repo's test convention — match how Phase 9 placed its
    sandbox tests; planner discretion) exhaustively covering `resolve_stt_placement` as a PURE function
    with `env` passed as a plain dict (no real os.environ needed):
    - **Force-cpu-first:** `STT_FORCE_CPU=1` (and `true`/`yes`/`on`) → `"cpu"` for BOTH choices, EVEN
      when `STT_HEADROOM_MEASURED=1` and the math would fit GPU (force wins over everything).
    - **Default-CPU-when-unmeasured:** no `STT_FORCE_CPU`, no `STT_HEADROOM_MEASURED` → `"cpu"` for both
      `fast` and `better` (the safe default).
    - **Measured → GPU:** `STT_HEADROOM_MEASURED=1`, no force → with the placeholder table `_gpu_fits`
      is True → `"gpu"` for both choices (the worst-case math passes for both since it uses max).
    - **Worst-case-LLM lock (STT-06):** assert the decision is IDENTICAL for `fast` and `better` under
      the same env (the resolver uses `max(LLM_PEAK_MB)`, so it never returns gpu-for-fast / cpu-for-
      better — proving a mid-session swap can't strand placement). If you parametrize a tightened table
      (e.g. monkeypatch `KOKORO_MB` high) so `_gpu_fits` is False, assert BOTH choices → `"cpu"`.
    - **Unknown choice CPU-safe:** `llm_choice="nonsense"` never raises and resolves CPU-safe under the
      unmeasured default; under measured it follows the worst-case math (still safe).
    - **Truthy normalization:** `STT_FORCE_CPU` in `{"1","true","TRUE","yes","on"}` all pin CPU;
      `{"0","false","",  "no"}` do not.
    - **No-exception invariant:** every combination returns `"gpu"` or `"cpu"` (assert membership), never
      raises.
    Keep it sandbox-only (`python3 -m pytest tests/test_placement.py` OR a `__main__` assert harness if
    pytest isn't the repo convention). No GPU, no livekit.
  </action>
  <acceptance_criteria>
    - The test runs green in the sandbox (`python3 -m pytest tests/test_placement.py` exits 0, or the `__main__` harness exits 0)
    - It asserts force-cpu-first beats measured+gpu-fits (`grep -nE "STT_FORCE_CPU|force" tests/test_placement.py`)
    - It asserts default CPU when unmeasured for both fast and better (`grep -nE "MEASURED|unmeasured|default" tests/test_placement.py`)
    - It asserts the worst-case-LLM lock: same decision for fast and better under the same env (`grep -nE "worst|fast.*better|same" tests/test_placement.py`)
    - It asserts unknown-choice never raises + is CPU-safe (`grep -nE "unknown|nonsense|raise|cpu" tests/test_placement.py`)
    - It asserts the no-exception/return-membership invariant across the matrix (`grep -nE "in \(.gpu., .cpu.\)|assert.*gpu.*cpu" tests/test_placement.py`)
  </acceptance_criteria>
</task>

<task id="10-02-3">
  <title>Wire placement into agent/main.py: add NEMO_STT_CPU_URL const + import resolve_stt_placement; resolve ONCE in build_session and construct NemoSTT(ws_url=<resolved>); DO NOT touch handle_model_update</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§3 the wiring lines + the resolve-once / no-handle_model_update lock)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§6 Analog A the URL-const block :49-56 + Analog B build_session construction :194-200 + the resolve-once invariant; §1 Analog C handle_model_update :536-554 must NOT re-place)
    - agent/main.py (NEMO_STT_URL :55, build_session :194-200 stt=NemoSTT(ws_url=NEMO_STT_URL...), DEFAULT_MODEL_CHOICE :133, entrypoint build_session call :370, handle_model_update :536-554)
  </read_first>
  <action>
    Edit `agent/main.py` to pick the STT URL from placement, resolved once:
    - **Const:** add `NEMO_STT_CPU_URL = os.environ.get("NEMO_STT_CPU_URL",
      "ws://nemo-stt-cpu:8000/v1/audio/stream")` beside `NEMO_STT_URL` (:55), with a comment mirroring
      NEMO_STT_URL's "ws:// route on the nemo-stt-cpu service (Wave-1 10-01), CPU-ONNX runtime".
    - **Import:** add `from placement import resolve_stt_placement` to the local-module import block
      (beside `import history` / `from nemo_stt import NemoSTT`).
    - **build_session:** at the top of `build_session` (before the `return AgentSession(...)`), resolve
      ONCE: `placement = resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)`; `stt_url =
      NEMO_STT_URL if placement == "gpu" else NEMO_STT_CPU_URL`. Replace `stt=NemoSTT(ws_url=
      NEMO_STT_URL, language="en")` (:200) with `stt=NemoSTT(ws_url=stt_url, language="en")`. Add a
      comment: placement is resolved ONCE here at session start from the worst-case LLM, so a
      mid-session Fast↔Better swap is always VRAM-safe and STT is NEVER re-placed (STT-06); the
      resolver checks STT_FORCE_CPU first (STT-07) and defaults CPU until the operator measured flag.
    - **DO NOT touch `handle_model_update` (:536-554)** — it stays LLM-only; no placement re-check,
      no guard, no coupling added. The `vad=`/`llm=`/`tts=`/`turn_handling=` args stay EXACTLY as-is
      (endpoint authority unchanged).
    `build_session` takes `vad` only and is called once in `entrypoint` (:370) before `session.start` —
    keep that signature (read `DEFAULT_MODEL_CHOICE` + `os.environ` inside; do NOT thread
    `current_model` in, since the worst-case math makes the initial choice sufficient). `py_compile` is
    the sandbox gate (cannot import livekit).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile agent/main.py` exits 0
    - `NEMO_STT_CPU_URL` defaults to the ws:// nemo-stt-cpu route and `from placement import resolve_stt_placement` is imported (`grep -n "NEMO_STT_CPU_URL = os.environ.get\|from placement import resolve_stt_placement" agent/main.py`)
    - build_session resolves placement ONCE and constructs `stt=NemoSTT(ws_url=stt_url, language=\"en\")` from it (`grep -n "resolve_stt_placement(DEFAULT_MODEL_CHOICE\|ws_url=stt_url" agent/main.py`)
    - The fixed `stt=NemoSTT(ws_url=NEMO_STT_URL` construction is gone (`grep -n "ws_url=NEMO_STT_URL" agent/main.py` returns nothing — replaced by stt_url)
    - `handle_model_update` is UNCHANGED — no placement call inside it (`grep -n "resolve_stt_placement" agent/main.py` shows it ONLY in build_session, not in handle_model_update :536-554)
    - The VAD/turn_handling/llm/tts args are unchanged (`grep -n "turn_handling\|MultilingualModel" agent/main.py` still present; no edits inside)
    - SANDBOX-TEST: a unit test (or assert) that `build_session`'s URL pick maps placement "gpu"→NEMO_STT_URL and "cpu"→NEMO_STT_CPU_URL (drive resolve_stt_placement with a stub env)
    - OPERATOR-VERIFICATION (deferred — 10-PLACEMENT-VERIFY): with STT_FORCE_CPU=1 the agent connects to nemo-stt-cpu (CPU runtime) and transcribes; flipping the measured flag + STT_FORCE_CPU=0 routes E2B/E4B sessions per the matrix
  </acceptance_criteria>
</task>

<task id="10-02-4">
  <title>Ship STT_FORCE_CPU=1 as the .env.example safe default + NEMO_STT_CPU_URL code-default note + STT_HEADROOM_MEASURED=0; document the operator flip-after-matrix gate</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§6 STT_FORCE_CPU safe-default + NEMO_STT_CPU_URL note + the operator-flip-only-after-matrix rule; §3 the measured flag)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§7 the safe-default comment style + the HOOK-note style)
    - .env.example (the STT block :53-66 + the STT_ONNX_MODEL/STT_QUANT lines added in 10-01-7 — append below them)
  </read_first>
  <action>
    Edit `.env.example` to ship the placement safe default below the Wave-1 STT_ONNX_MODEL/STT_QUANT
    lines:
    - **`STT_FORCE_CPU=1`** — the documented SAFE DEFAULT (CONTEXT/STT-07): comment that it pins
      CPU-ONNX for BOTH LLM choices, the picker is VRAM-safe out of the box, and the operator sets
      `STT_FORCE_CPU=0` (AND `STT_HEADROOM_MEASURED=1`) ONLY after the 4-cell matrix proves E4B +
      GPU-STT + Kokoro co-fit at the KB-load prefill peak (peak < total−1 GB). Mirror the HOOK-note
      style.
    - **`STT_HEADROOM_MEASURED=0`** — the measured gate: comment that the GPU branch of the resolver is
      LOCKED OFF until the operator measures Kokoro + the co-residency matrix and flips this to `1`;
      until then placement defaults CPU even with STT_FORCE_CPU=0.
    - **`NEMO_STT_CPU_URL`** — note the code default `ws://nemo-stt-cpu:8000/v1/audio/stream` (parity
      with `NEMO_STT_URL` which is code-default-only); the agent reaches the CPU service by this URL.
    - Comment that `STT_RUNTIME` is per-service in compose (NOT here), consistent with the 10-01-7 note.
    Do NOT remove the Wave-1 STT_ONNX_MODEL/STT_QUANT lines or the Phase-9 STT_MODEL/STT_ATT_CONTEXT_SIZE
    lines.
  </action>
  <acceptance_criteria>
    - `.env.example` ships `STT_FORCE_CPU=1` as the documented safe default with the flip-after-matrix rationale (`grep -nE "STT_FORCE_CPU=1|safe default|4-cell|co-fit" .env.example`)
    - `STT_HEADROOM_MEASURED=0` is present with the locked-until-measured comment (`grep -n "STT_HEADROOM_MEASURED=0" .env.example`)
    - `NEMO_STT_CPU_URL` code default is noted (`grep -n "NEMO_STT_CPU_URL\|ws://nemo-stt-cpu:8000/v1/audio/stream" .env.example`)
    - The Wave-1 STT_ONNX_MODEL/STT_QUANT and Phase-9 STT_MODEL/STT_ATT_CONTEXT_SIZE lines are intact (`grep -nE "STT_ONNX_MODEL|STT_QUANT|STT_MODEL=nvidia|STT_ATT_CONTEXT_SIZE" .env.example`)
  </acceptance_criteria>
</task>

<task id="10-02-5">
  <title>Parametrize scripts/vram-validate.sh to the 4-cell {E2B,E4B}×{GPU-NeMo,CPU-ONNX} matrix: --stt-runtime gpu|cpu sets EXPECTED_GPU_PROCS 3|2, sweep OLLAMA_MODEL E2B/E4B, per-cell STT health probe (8000 vs 8001), peak<ceiling unchanged</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§7 the 4-cell parametrization + EXPECTED_GPU_PROCS 3-vs-2 + the load-bearing GPU-STT×E4B cell)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§8 Analog A EXPECTED_GPU_PROCS :45,158-164 + Analog B parse_args :173-184 + require_tag :60-66)
    - scripts/vram-validate.sh (EXPECTED_GPU_PROCS :45, NEMO_STT_BASE_URL :43, assert_three_gpu_procs :158-164, parse_args :173-184, require_tag :60-66, the peak assertion :201-202, the q8_0 grep :130-156)
  </read_first>
  <action>
    Edit `scripts/vram-validate.sh` to parametrize the 4-cell matrix (keep `bash -n` clean):
    - **`EXPECTED_GPU_PROCS` is no longer a constant 3** — make it a runtime value set from a new
      `--stt-runtime gpu|cpu` flag (extend `parse_args` :173-184; default `gpu` for back-compat). `gpu`
      → 3 (ollama, nemo-stt, kokoro); `cpu` → 2 (ollama, kokoro — `nemo-stt-cpu` runs OFF-GPU and must
      NOT be counted). Drop the `readonly` on the constant or compute it after parse. Reject any value
      other than gpu|cpu (mirror the `unknown argument` fail).
    - **Rename `assert_three_gpu_procs` → a runtime-count assert** (or keep the name but make the
      message dynamic): the expected-proc message names "ollama, nemo-stt, kokoro" for gpu vs "ollama,
      kokoro" for cpu, and asserts `proc_count == EXPECTED_GPU_PROCS` per cell.
    - **STT health probe per cell:** the STT base URL targets `nemo-stt` (`http://127.0.0.1:8000`,
      `NEMO_STT_BASE_URL`) for gpu and `nemo-stt-cpu` (`http://127.0.0.1:8001`) for cpu — add a
      `STT_RUNTIME_UNDER_TEST`-derived base URL or a per-runtime var.
    - **LLM sweep:** the script already reads `OLLAMA_MODEL` (`require_tag` :60-66) — document (header +
      a comment) that the operator runs the 4 cells by sweeping `OLLAMA_MODEL` over E2B (Fast) / E4B
      (Better) × `--stt-runtime gpu|cpu`, restarting ollama between tags to clear `keep_alive=-1` (Gate
      D). Do NOT auto-loop all 4 in one invocation unless trivial — per-cell invocation is fine and
      matches Phase-9 usage; the runbook drives the sweep.
    - **Peak assertion UNCHANGED:** `peak < VRAM_CEILING_MB` (15360) per cell (:201-202); the CPU-STT
      cells show a LOWER peak (no +2.4 GB STT on GPU) — that's the headroom the placement table banks
      on. Keep the q8_0-engaged grep (:130-156) and the `--with-kb` KB-load peak path.
    - Update the header comment block (:1-34) to describe the 4-cell matrix + the `--stt-runtime` flag +
      the load-bearing GPU-STT×E4B cell.
    Do NOT change ollama/kokoro behaviour or the peak ceiling. `bash -n` must pass.
  </action>
  <acceptance_criteria>
    - `bash -n scripts/vram-validate.sh` exits 0
    - A `--stt-runtime gpu|cpu` flag exists and sets EXPECTED_GPU_PROCS to 3 (gpu) or 2 (cpu) (`grep -nE "stt-runtime|EXPECTED_GPU_PROCS" scripts/vram-validate.sh`)
    - The CPU cell expects 2 procs (ollama, kokoro) and does NOT count nemo-stt-cpu as a GPU process (`grep -nE "ollama, kokoro|nemo-stt-cpu" scripts/vram-validate.sh`; the assert message is dynamic per runtime)
    - The STT health probe targets 8000 (gpu) vs 8001 (cpu) per cell (`grep -nE "8000|8001|nemo-stt-cpu" scripts/vram-validate.sh`)
    - The peak<ceiling assertion + the q8_0 grep are unchanged (`grep -nE "VRAM_CEILING_MB|q8_0" scripts/vram-validate.sh`)
    - The header documents the 4-cell {E2B,E4B}×{GPU,CPU} matrix + the load-bearing GPU-STT×E4B cell (`grep -niE "4-cell|E2B|E4B|GPU-STT|load-bearing" scripts/vram-validate.sh`)
    - OPERATOR-VERIFICATION (GPU, deferred — 10-PLACEMENT-VERIFY): all 4 cells run; GPU-STT×E4B peak < 15360 decides the safe-default flip; CPU-STT cells show the lower peak (2 procs)
  </acceptance_criteria>
</task>

<task id="10-02-6">
  <title>Author 10-PLACEMENT-VERIFY.md — operator GPU-gate runbook (status pending-operator, [STT-05,STT-06,STT-07]): baked-image build-first, real ONNX export+quant+size, mel-parity, >6× realtime + WER-under-contention, 4-cell co-residency matrix, Kokoro measurement, safe-default flip; all gates PENDING</title>
  <read_first>
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-RESEARCH.md (§9 the sandbox-vs-operator table + §10 risks 1-9 — the gate set; §1.1 quant tiers; §1.3 mel parity; §7 the 4-cell matrix)
    - .planning/phases/10-vram-aware-stt-placement-part-c/10-PATTERNS.md (§9 Analog 09-STT-VERIFY front-matter + §0 baked-image guard + per-gate result-table shape + overall sign-off matrix)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md (the exact format to mirror: frontmatter, harness_note, frozen-contract notes, §0 build-first, per-gate Goal/Steps/ASSERT/Results tables, overall sign-off, none marked passed)
  </read_first>
  <action>
    Create `.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md` mirroring
    `09-STT-VERIFY.md`:
    - **Frontmatter:** `status: pending-operator`, `phase: 10-vram-aware-stt-placement-part-c`, `plan:
      10-02`, `requirement_ids: [STT-05, STT-06, STT-07]`, a `verifies:` list, and a `harness_note` that
      the sandbox has no GPU/Docker/ORT and cannot import NeMo/torch/onnxruntime so every gate is
      deferred and NONE are marked passed by the executor (note what ships sandbox-green: placement.py
      pure-fn tests, py_compile of server+backends+placement+main, docker compose config, the stubbed
      STT_RUNTIME dispatch).
    - **Frozen-contract notes:** the WS contract is byte-unchanged (the ONNX backend matches it);
      placement is resolved ONCE at session start, never re-consulted on an LLM swap (STT-06);
      `handle_model_update` / VAD-turn-detector / `agent/metrics.py` are untouched (READ-ONLY — `git
      diff` empty); the STT_ONNX_MODEL single-source (no hardcoded tag).
    - **PIN the placement semantics:** STT_FORCE_CPU is checked FIRST; the default is CPU until
      STT_HEADROOM_MEASURED=1; the GPU branch uses worst-case-LLM (E4B) math so a Fast↔Better swap is
      always safe.
    - **§0 BUILD-FIRST (baked-image guard):** `docker compose build nemo-stt-cpu agent && docker compose
      up -d && docker compose ps` (nemo-stt-cpu healthy on 8001) before any live gate.
    - **Gates (each with a result table, all PENDING/unsigned):**
      - **Gate 1 — ONNX export + quant + size (STT-05, RESEARCH §1.1/§5):** `export_onnx.py` runs
        cache_support=True export → encoder + decoder/joint; int8-dynamic encoder ~0.88 GB on disk; the
        int4-kquant ~0.67 GB stretch is a SEPARATE operator build (custom tooling). Record sizes.
      - **Gate 2 — mel-preprocessor parity (RESEARCH §1.3, HIGHEST RISK):** the CPU backend's
        self-computed 128-band Slaney mel matches the NeMo preprocessor numerically (compare features /
        WER on a fixed clip); a mismatch tanks WER.
      - **Gate 3 — CPU-ONNX contract parity + >6× realtime + WER-under-contention (STT-05):** nemo-stt-cpu
        serves the byte-identical ready/delta/final/error; a real clip streams growing deltas + a flush
        FINAL; measured CPU throughput >6× realtime; WER within target vs FP32/NeMo under load.
      - **Gate 4 — 4-cell co-residency matrix (STT-06, RESEARCH §7):** `vram-validate.sh --stt-runtime
        gpu|cpu` × OLLAMA_MODEL E2B/E4B at the `--with-kb` prefill peak; peak < 15360 per cell; 3 procs
        (GPU-STT) vs 2 (CPU-STT). The **GPU-STT × E4B cell is load-bearing**.
      - **Gate 5 — Kokoro VRAM measurement (RESEARCH §3 placeholder):** measure the real Kokoro-82M GPU
        footprint to replace the `KOKORO_MB=2048` placeholder; feed it back into the table sanity-check.
      - **Gate 6 — placement resolves once / no thrash (STT-06):** with the measured flag set, a live
        Fast↔Better `model.update` swap does NOT change the STT runtime (STT stays on the
        session-start URL); confirm in the agent logs.
      - **Gate 7 — STT_FORCE_CPU global pin (STT-07):** `STT_FORCE_CPU=1` pins CPU for BOTH LLM choices
        regardless of headroom/measured; the agent connects to nemo-stt-cpu.
      - **Gate 8 — safe-default flip:** ONLY after Gates 1-5 pass, flip `STT_FORCE_CPU=1`→`0` +
        `STT_HEADROOM_MEASURED=1` and confirm E2B/E4B route per the matrix (E4B → CPU if its GPU cell
        failed; GPU otherwise).
    - **Overall sign-off matrix** with Operator/Date/VM lines (mirror 09-STT-VERIFY:308-325). Mark every
      gate PENDING. Do NOT mark anything passed.
  </action>
  <acceptance_criteria>
    - `10-PLACEMENT-VERIFY.md` exists with `status: pending-operator` + `requirement_ids: [STT-05, STT-06, STT-07]` (`grep -n "status: pending-operator\|STT-05, STT-06, STT-07" .planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md`)
    - It PINS the placement semantics (force-cpu-first, default-CPU-until-measured, worst-case-LLM) (`grep -niE "STT_FORCE_CPU|measured|worst-case" .../10-PLACEMENT-VERIFY.md`)
    - A §0 baked-image BUILD-FIRST step (build nemo-stt-cpu agent && up -d) precedes the gates (`grep -niE "docker compose build nemo-stt-cpu|build.*first|baked" .../10-PLACEMENT-VERIFY.md`)
    - Gates cover ONNX export+quant+size, mel-parity, >6× realtime + WER, the 4-cell co-residency matrix, Kokoro measurement, resolve-once/no-thrash, STT_FORCE_CPU pin, and the safe-default flip (`grep -niE "export|mel|realtime|WER|4-cell|co-residency|kokoro|thrash|STT_FORCE_CPU|flip" .../10-PLACEMENT-VERIFY.md`)
    - The int4-kquant ~0.67 GB is marked the operator-gated STT-05 stretch (not the int8 default) (`grep -niE "int4-kquant|0.67|0.88|stretch" .../10-PLACEMENT-VERIFY.md`)
    - No gate is marked passed/signed by the executor (`grep -ni "PENDING" .../10-PLACEMENT-VERIFY.md` shows the verdicts; none asserted PASS)
  </acceptance_criteria>
</task>

## Verification

- `python3 agent/placement.py` runs `_self_check` OK; `python3 -m pytest tests/test_placement.py` (or
  the `__main__` harness) is green — the full `llm_choice × STT_FORCE_CPU × STT_HEADROOM_MEASURED`
  matrix asserts force-cpu-first, default-CPU-when-unmeasured, the worst-case-LLM lock (identical
  decision for fast/better), unknown-choice CPU-safe, and the no-exception/return-membership invariant.
- `python3 -m py_compile agent/placement.py agent/main.py` exits 0; `bash -n scripts/vram-validate.sh`
  exits 0.
- `agent/placement.py` is pure + livekit-free (frozen VRAM table, `_self_check` under `__main__`, no
  nvidia-smi/livekit import); the signature is exactly `resolve_stt_placement(llm_choice, env) ->
  "gpu"|"cpu"`; STT_FORCE_CPU is the FIRST check; the GPU branch is gated behind STT_HEADROOM_MEASURED;
  the math uses `max(LLM_PEAK_MB)` (worst-case-LLM, STT-06).
- `agent/main.py` adds `NEMO_STT_CPU_URL`, imports `resolve_stt_placement`, resolves ONCE in
  `build_session`, and constructs `NemoSTT(ws_url=stt_url, ...)`; `handle_model_update`, the VAD/
  `turn_handling`, and `agent/metrics.py` are UNTOUCHED (`git diff agent/metrics.py` empty).
- `.env.example` ships `STT_FORCE_CPU=1` (safe default) + `STT_HEADROOM_MEASURED=0` + the
  `NEMO_STT_CPU_URL` code-default note, with the operator flip-after-matrix rationale.
- `scripts/vram-validate.sh` parametrizes the 4-cell `{E2B,E4B}×{GPU,CPU}` matrix via `--stt-runtime`
  (EXPECTED_GPU_PROCS 3 vs 2), per-cell STT probe (8000 vs 8001), peak<15360 unchanged, q8_0 grep
  unchanged.
- `10-PLACEMENT-VERIFY.md` (status pending-operator, [STT-05,STT-06,STT-07]) authors the baked-image
  build-first + the export/quant/size, mel-parity, >6× realtime + WER, 4-cell matrix, Kokoro
  measurement, resolve-once/no-thrash, STT_FORCE_CPU pin, and safe-default-flip gates — all PENDING,
  none passed.
- BUILD-FIRST (operator, baked-image invariant): `docker compose build nemo-stt-cpu agent && docker
  compose up -d && docker compose ps` before any live gate.
- OPERATOR GATE (GPU/host/build — deferred; authored in `10-PLACEMENT-VERIFY.md`): real ONNX export +
  int8/int4 quant + size; mel parity; >6× realtime + WER-under-contention; the 4-cell co-residency
  matrix (peak < total−1 GB, 3 vs 2 procs) at the KB-load prefill peak; Kokoro measurement;
  resolve-once/no-thrash; STT_FORCE_CPU pin; the safe-default flip.
- DEFER (do NOT mark passed in this plan): all GPU/Docker/ORT/accuracy operator items; the sandbox has
  no GPU/Docker daemon and cannot import NeMo/torch/onnxruntime.

## must_haves

truths:
- STT-06: STT placement is resolved EXACTLY ONCE at session start by the pure
  `resolve_stt_placement(llm_choice, env)` from a STATIC measured-headroom table (no live nvidia-smi
  probe); it is read once in `build_session` and NEVER re-consulted — `handle_model_update` stays
  LLM-only, so a mid-session Fast↔Better swap never thrashes the STT runtime.
- STT-06: the GPU branch uses worst-case-LLM (E4B/Better) math so if the heaviest LLM that could be
  selected this session cannot co-fit GPU-STT, the resolver returns CPU for the WHOLE session — an
  in-session swap is always VRAM-safe; the resolver returns the same decision for fast and better.
- STT-07: `STT_FORCE_CPU` is the FIRST check in the resolver and short-circuits to CPU for BOTH LLM
  choices before any headroom logic — the global pin that makes the LLM picker VRAM-safe.
- The default when unmeasured is CPU-ONNX (gated behind `STT_HEADROOM_MEASURED`); `.env.example` ships
  `STT_FORCE_CPU=1` as the documented SAFE DEFAULT so the picker is VRAM-safe out of the box, and the
  operator flips it (+ the measured flag) ONLY after the 4-cell co-residency matrix proves E4B +
  GPU-STT + Kokoro co-fit.
- `agent/placement.py` is a pure, livekit-free decision module (frozen VRAM constants citing Phase 8
  Gate D measurements + the Kokoro placeholder, `_self_check` under `__main__`, no exception escapes);
  the agent picks `NEMO_STT_URL` (gpu) vs `NEMO_STT_CPU_URL` (cpu) from its single return value.
- `scripts/vram-validate.sh` proves the 4-cell `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}` co-residency matrix
  (EXPECTED_GPU_PROCS 3 for GPU-STT / 2 for CPU-STT, peak < total−1 GB per cell); the GPU-STT×E4B cell
  is load-bearing for the safe-default flip.

must_haves.prohibitions:
- NO live `nvidia-smi` probe driving placement — the static measured-headroom table is the authority
  (the operator co-residency gate pins the real numbers).
- NO mid-session re-resolution / GPU↔CPU thrash; placement is read ONCE and never re-consulted; NO
  placement call/guard/coupling added to `handle_model_update`.
- NO edit to `agent/metrics.py` (READ-ONLY — `git diff` must stay empty), the VAD/`MultilingualModel`
  turn detector / `turn_handling`, or the `model.update` LLM-swap RPC handler.
- NO hardcoded model tag in `placement.py`/`main.py`; the resolver never imports livekit or main; it
  RETURNS rather than raises (always "gpu"/"cpu").
- NO change to the Wave-1 WS contract, the backends, or the `nemo-stt-cpu` service shape.
- NO function over 40 lines / 3 params / 3 nesting.
- NO marking any GPU/Docker/ORT/accuracy OPERATOR-VERIFICATION step passed in this plan; all gates in
  `10-PLACEMENT-VERIFY.md` ship unsigned (status: pending-operator).

## Artifacts this plan produces

- `agent/placement.py` (new): pure `resolve_stt_placement(llm_choice, env) -> "gpu"|"cpu"` resolver
  (STT_FORCE_CPU first → STT_HEADROOM_MEASURED gate → worst-case-LLM headroom → default CPU) + the
  frozen VRAM table (`VRAM_TOTAL_MB`, `VRAM_HEADROOM_MB`, `LLM_PEAK_MB`, `STT_GPU_MB`, `STT_CPU_GPU_MB`,
  `KOKORO_MB`) + `_truthy`/`_gpu_fits` helpers + `_self_check` under `__main__`.
- `tests/test_placement.py` (new): the exhaustive pure-fn matrix (force-cpu-first, default-CPU-when-
  unmeasured, worst-case-LLM lock, unknown-choice CPU-safe, truthy normalization, no-exception
  invariant).
- `agent/main.py` (modified): `NEMO_STT_CPU_URL` const (default `ws://nemo-stt-cpu:8000/v1/audio/
  stream`); `from placement import resolve_stt_placement`; `build_session` resolves ONCE +
  `stt=NemoSTT(ws_url=stt_url, language="en")`; `handle_model_update`/VAD/`turn_handling`/metrics
  untouched.
- `.env.example` (modified): `STT_FORCE_CPU=1` safe default + `STT_HEADROOM_MEASURED=0` +
  `NEMO_STT_CPU_URL` code-default note; the operator flip-after-matrix rationale.
- `scripts/vram-validate.sh` (modified): the 4-cell `{E2B,E4B}×{GPU,CPU}` matrix — `--stt-runtime
  gpu|cpu` sets `EXPECTED_GPU_PROCS` 3|2, per-cell STT probe (8000 vs 8001), peak<15360 + q8_0 grep
  unchanged, header documents the load-bearing GPU-STT×E4B cell.
- `.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md` (new): operator GPU-gate
  runbook (status pending-operator, [STT-05,STT-06,STT-07]) — baked-image build-first + the export/
  quant/size, mel-parity, >6× realtime + WER, 4-cell co-residency matrix, Kokoro measurement,
  resolve-once/no-thrash, STT_FORCE_CPU pin, and safe-default-flip gates. Unsigned.
- Env vars introduced: `NEMO_STT_CPU_URL` (agent-side code default), `STT_FORCE_CPU` (safe default 1),
  `STT_HEADROOM_MEASURED` (default 0). Function introduced: `resolve_stt_placement`.
