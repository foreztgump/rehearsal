# Phase 10: VRAM-Aware STT Placement (Part C) - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase ships the **mechanism** to run STT on either of two runtimes behind the
single frozen WS contract from Phase 9 — full GPU NeMo (`nemo-stt`) or an off-GPU
4-bit ONNX CPU port (`nemo-stt-cpu`, ~0.67GB) — and the **placement decision** that
selects between them **exactly once at session start** from the selected LLM + VRAM
headroom, with a single env-flagged global-CPU-ONNX fallback (`STT_FORCE_CPU`) that
makes the LLM picker VRAM-safe with **zero runtime switching**.

Delivers: a runtime switch inside the existing `stt/` server (`STT_RUNTIME=gpu|cpu`,
ORT vs NeMo) so the agent plugin stays runtime-agnostic; a second lightweight
`nemo-stt-cpu` Compose service; an `agent/placement.py` pure resolver wired into
`build_session`; the `STT_FORCE_CPU` safe-default knob; an extended 4-cell
`vram-validate.sh` co-residency matrix; an ONNX export/quantize recipe; and the
operator GPU-gate runbook `10-PLACEMENT-VERIFY.md`.

Requirements: STT-05 (CPU-ONNX alternate runtime, same contract, >6× realtime),
STT-06 (placement resolved once at session start, no mid-session GPU↔CPU thrash),
STT-07 (`STT_FORCE_CPU` global fallback pins CPU for both LLMs).

**Out of scope:** mid-session runtime switching/thrashing; live VRAM probing as the
authority; the consumer-GPU deployment/preflight doctor (Phase 11); the avatar
(Phase 12); any change to the Phase 9 WS contract, the LLM-swap RPC semantics, or
the VAD/turn-detector endpoint authority.

</domain>

<decisions>
## Implementation Decisions

### Placement Resolution Logic (placement.py)
- New `agent/placement.py` exposing a **pure function** `resolve_stt_placement(llm_choice, env) -> "gpu" | "cpu"`, called **once at session start** (in `build_session`/entrypoint), never re-consulted thereafter.
- Inputs are deterministic: the LLM choice plus a **STATIC measured-headroom table** (anchored to the Phase 8 Gate D numbers — Fast/E2B ≈ 7408 MB, Better/E4B ≈ 8912 MB — against the 16 GB floor, leaving Kokoro + the ~2.4 GB GPU-NeMo / ~0.67 GB CPU-ONNX footprints). **No live `nvidia-smi` probe** drives the decision (avoids nondeterminism; the real numbers are pinned by the operator co-residency gate).
- STT placement is **LOCKED at session start and NEVER re-resolved on a mid-session LLM swap** (STT-06, no thrash). If the worst-case LLM (E4B) cannot co-fit GPU-STT for the session, the resolver returns CPU for the **whole** session so an in-session Fast↔Better swap is always VRAM-safe.
- The **default when unmeasured is CPU-ONNX** (VRAM-safe for both LLMs) until the operator co-residency gate proves E4B + GPU-STT + Kokoro co-fit the target GPU.

### CPU-ONNX Runtime & nemo-stt-cpu Service
- The 4-bit ONNX model is **baked into the `nemo-stt-cpu` image at build**, single-sourced via an `STT_ONNX_MODEL` build ARG + matching runtime `ENV` (no hardcoded tag — AGENTS.md single-source, mirrors `STT_MODEL`).
- **Identical frozen WS contract** as Phase 9 — reuse `stt/server.py` with an `STT_RUNTIME=gpu|cpu` switch (ONNX Runtime vs NeMo decode backend) so the agent plugin is **runtime-agnostic** (same `ready`/`delta`/`final`/`error`, same `/health` gating).
- **ONE `stt/` codebase, TWO Compose services**: `nemo-stt` (GPU, existing, `STT_RUNTIME=gpu`) and `nemo-stt-cpu` (CPU, **no GPU reservation**, `STT_RUNTIME=cpu`, ~0.67 GB).
- **Both services are defined**; only the placement-resolved one must be healthy for a given session. The CPU service is lightweight; the agent connects to the placement-picked URL.

### Agent Wiring & Env Surface
- The agent reaches the chosen runtime via two URL consts: `NEMO_STT_URL` (GPU, existing) and `NEMO_STT_CPU_URL` (default `ws://nemo-stt-cpu:8000/v1/audio/stream`). `build_session` constructs `NemoSTT(ws_url=<resolved>)` from `resolve_stt_placement(...)`.
- `STT_FORCE_CPU=1` **short-circuits placement → CPU for both LLM choices** (STT-07) and is the **FIRST** check in `placement.py` (before any headroom logic).
- **Ship `STT_FORCE_CPU=1` as the documented SAFE DEFAULT** in `.env.example` until the operator co-residency gate flips it (the picker is VRAM-safe out of the box).
- **Do NOT touch the live `model.update` LLM-swap RPC handler** — it stays LLM-only; placement is read once at session start and never re-consulted (no coupling, no re-check, no guard added).

### Verification & Operator Gate
- **Sandbox-verifiable:** `placement.py` pure-function unit tests across `llm_choice × STT_FORCE_CPU × headroom → gpu/cpu`; `py_compile`; `docker compose config`; the `STT_RUNTIME` switch path exercised with a **stubbed** model/backend (no GPU, no ONNX runtime download).
- **Operator-gated (GPU, deferred, unsigned in `10-PLACEMENT-VERIFY.md`):** real ONNX **>6× realtime** + **WER-under-contention** check; the `{E2B,E4B}×{GPU-NeMo,CPU-ONNX}` co-residency matrix measured at the **KB-load prefill peak** (q8_0 engaged, peak < total−1 GB); the final safe-default determination.
- **Extend `vram-validate.sh`** to parametrize the **4-cell matrix**; GPU-process count varies per cell (3 with GPU-STT: ollama/nemo-stt/kokoro; 2 with CPU-STT: ollama/kokoro), peak < total−1 GB per cell.
- **Author the ONNX export/quantize recipe** (Dockerfile build step + a script); the multi-GB build and the accuracy/WER check are operator-gated. Do **not** commit the `.onnx` artifact.

### the agent's Discretion
- Exact module/function signatures inside `placement.py` (beyond the pinned `resolve_stt_placement(llm_choice, env) -> "gpu"|"cpu"` shape), the headroom-table representation, and how the `STT_RUNTIME` backend split is factored inside `stt/server.py` are at the planner/executor's discretion, subject to the single-source/no-thrash/contract-frozen invariants above.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `stt/server.py` (Phase 9): FastAPI WS server with the frozen `ready`/`delta`/`final`/`error` contract, `/health` 503-until-ready gate, lifespan keep-resident load, `decode_chunk`/`finalize`/`new_stream_state` split. The `STT_RUNTIME=gpu|cpu` switch factors the decode backend behind these same functions.
- `stt/Dockerfile` (Phase 9): CUDA-12.8 Blackwell base with `ARG STT_MODEL` bake + python-urllib HEALTHCHECK — the bake/single-source pattern the CPU image mirrors (CPU base, no CUDA, `ARG STT_ONNX_MODEL`).
- `agent/nemo_stt.py` (Phase 9): `NemoSTT(ws_url=...)` plugin is **runtime-agnostic** — it speaks the WS contract, so a CPU vs GPU URL is the only difference. No change needed beyond the URL it is handed.
- `agent/main.py` `build_session` (line ~194): constructs `NemoSTT(ws_url=NEMO_STT_URL, ...)`; `_MODEL_ENV` (line ~134) maps `fast`/`better` → `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`; `DEFAULT_MODEL_CHOICE` and `current_model[]` hold the per-session pick — the LLM choice `placement.py` reads.
- `scripts/vram-validate.sh` (Phase 9): `EXPECTED_GPU_PROCS=3`, peak-VRAM assertion, q8_0-engaged grep, here-string log scan — the harness the 4-cell matrix parametrizes.
- `docker-compose.yml` `nemo-stt:` block (lines 101-139): the GPU service to clone (minus the GPU reservation) into `nemo-stt-cpu`, plus the `agent` `depends_on`/`environment` surface.

### Established Patterns
- **Single-source model tags** (AGENTS.md / v1.0 invariant): the literal default lives ONLY in `docker-compose.yml` build.args/environment; code/Dockerfile-body carry it via env/ARG. `STT_ONNX_MODEL` follows `STT_MODEL`.
- **Resolve-once-at-session-start, never thrash** (Phase 5 history windowing, Phase 8 LLM pick): per-session decisions are taken once and held; this is the exact posture STT-06 demands.
- **Operator-gated GPU proofs unsigned until run on real hardware** (Phases 4/5/6/8/9): GPU/Docker/accuracy claims are authored as `*-VERIFY.md` runbooks with `status: pending-operator`, no gate marked passed by the executor.
- **Validate-before-use at the env/RPC boundary** (Phase 6/8): `STT_FORCE_CPU` and the headroom inputs are validated/normalized before driving placement.
- **BAKED-image invariant**: the stack runs from built images — the operator must `docker compose build nemo-stt-cpu && up -d` before any live verify.

### Integration Points
- `agent/placement.py` (NEW) ← read by `build_session` in `agent/main.py` to pick the STT URL.
- `agent/main.py`: add `NEMO_STT_CPU_URL` const beside `NEMO_STT_URL`; call `resolve_stt_placement(current_model[0], os.environ)` once before constructing `NemoSTT`.
- `docker-compose.yml`: add `nemo-stt-cpu:` service; the `agent` reads `STT_FORCE_CPU` + both STT URLs from env.
- `.env.example`: add `STT_ONNX_MODEL`, `NEMO_STT_CPU_URL` (or note code default), and `STT_FORCE_CPU=1` as the documented safe default.
- `stt/server.py` + `stt/Dockerfile`: `STT_RUNTIME` switch + a CPU/ONNX Dockerfile variant (or build target) baking `STT_ONNX_MODEL`.
- `scripts/vram-validate.sh`: parametrized to the 4-cell `{E2B,E4B}×{GPU,CPU}` matrix.
- `.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md` (NEW): operator GPU-gate runbook.

</code_context>

<specifics>
## Specific Ideas

- Anchor the static headroom table to the **measured Phase 8 Gate D numbers** (Fast/E2B ≈ 7408 MB, Better/E4B ≈ 8912 MB) so placement math is grounded in real measurements, not guesses; the operator co-residency gate is what ultimately pins/flips the safe default.
- The CPU-ONNX target is **~0.67 GB, >6× realtime** with negligible WER loss under contention — those are the STT-05 acceptance numbers the operator benchmark must hit.
- Safe default ships as **global CPU-ONNX** (`STT_FORCE_CPU=1`) — the operator flips it to auto-resolve / GPU-STT **only if** E4B + GPU-STT + Kokoro is proven to co-fit at the KB-load prefill peak (peak < total−1 GB).

</specifics>

<deferred>
## Deferred Ideas

- Consumer-GPU detection / passthrough / preflight "doctor" message → Phase 11 (Part E).
- Any avatar work → Phase 12 (Part D, frontend-only).
- SESS/REL polish + final P50<1.0s latency tuning → Phase 13.

</deferred>
</content>
</invoke>
