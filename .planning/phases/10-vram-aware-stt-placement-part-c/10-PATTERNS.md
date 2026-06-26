# Phase 10 — VRAM-Aware STT Placement (Part C): Pattern Mapping

**Purpose:** Map every new/modified file in Phase 10 to its closest existing
analog in the repo, with real code excerpts + line references. This is the
"copy-from-here" index for the PLAN — each new file says *which* existing file is
its template and *which* lines to clone vs. change.

**Sources:** `10-CONTEXT.md` (decisions), `10-RESEARCH.md` §1–§8 (the runtime
split, the resolver table, the Compose service, the export recipe, the 4-cell
matrix), repo HEAD (`agent/main.py`, `agent/history.py`, `agent/interview.py`,
`stt/server.py`, `stt/Dockerfile`, `stt/requirements.txt`, `docker-compose.yml`,
`.env.example`, `scripts/vram-validate.sh`), and `09-PATTERNS.md` /
`09-STT-VERIFY.md` (the format this phase mirrors).

**Confirmed by read:** `stt/server.py` already exposes the exact seam
(`load_model`/`new_stream_state`/`decode_chunk`/`finalize`/`reset_turn_state`,
343 lines) the `STT_RUNTIME` switch factors behind; `agent/history.py` +
`agent/interview.py` are the in-repo "pure, livekit-free decision module" house
style `placement.py` clones; `docker-compose.yml:101-138` is the `nemo-stt` block
the CPU service clones minus the GPU reservation.

---

## File inventory (role + data-flow classification)

| File | Verb | Role | Data flow | Closest analog |
|---|---|---|---|---|
| `agent/placement.py` | CREATE | Pure STT-placement resolver + static VRAM table | `(llm_choice, env)` → `"gpu"`/`"cpu"` | `agent/history.py` (pure livekit-free decision module) + `agent/main.py:117-159` (`resolved_*_tag` env-single-source/validate posture) |
| `stt/backend_nemo.py` | CREATE | GPU NeMo decode body (moved) | PCM → cumulative text | `stt/server.py:101-221` (the current NeMo body it extracts) |
| `stt/backend_onnx.py` | CREATE | ORT CPU decode body (3-graph cache loop + mel) | PCM → cumulative text | `stt/server.py:101-221` (same four-callable shape) |
| `stt/Dockerfile.cpu` | CREATE | Lean CPU image, ONNX bake | build-time model bake | `stt/Dockerfile` (GPU bake/single-source) + `agent/Dockerfile` (bake-artifacts-at-build) |
| `stt/requirements-cpu.txt` | CREATE | CPU/ORT server deps | n/a | `stt/requirements.txt` (pin posture, no torch/CUDA) |
| `stt/export_onnx.py` | CREATE | Operator export+quant recipe | `.nemo` → `.onnx` int8/int4 | (no in-repo analog — `ollama/pull-and-pin.sh` build-recipe intent) |
| `10-PLACEMENT-VERIFY.md` | CREATE | Operator GPU-gate runbook | n/a | `09-STT-VERIFY.md` + `08-LLM-VERIFY.md` (front-matter + gate-table format) |
| `stt/server.py` | MODIFY | WS server + backend dispatch | unchanged WS contract | self (lines 49-52, 96-221) |
| `agent/main.py` | MODIFY | Agent wiring + URL pick | resolved STT URL | self (lines 49-56, 194-200) |
| `docker-compose.yml` | MODIFY | Stack topology | add `nemo-stt-cpu`, agent `depends_on` | self (`nemo-stt` 101-138, agent 42-53) |
| `.env.example` | MODIFY | Env template | add `STT_*`/`STT_FORCE_CPU` | self (STT block 53-65) |
| `scripts/vram-validate.sh` | MODIFY | 4-cell VRAM matrix | per-cell `EXPECTED_GPU_PROCS` | self (43-45, 158-164, 173-208) |
| `agent/nemo_stt.py` | NO CHANGE | Runtime-agnostic plugin | only the URL it is handed changes | self (CONTEXT) |
| `agent/metrics.py` | NO CHANGE (READ-ONLY) | Metrics scaffold | same `delta`/`final` feeds `stt_ms` | self |
| `handle_model_update` (in main.py) | NO CHANGE | LLM-swap RPC | placement read once, never re-consulted | self (main.py:536-554) |

---

## 1. CREATE `agent/placement.py` — `resolve_stt_placement` pure resolver

### Analog A — the pure, livekit-free decision-module house style: `agent/history.py:1-57`

`history.py` is the in-repo template for "a pure function of simple inputs, no
livekit import, frozen module constants, `_self_check()` under `__main__`,
sandbox-runnable." `placement.py` is the SAME shape — a different decision (STT
placement) over a different input (`llm_choice` + `env`):

```python
# agent/history.py:18-38 — the module shape to clone
from __future__ import annotations
import sys

HISTORY_MAX_ITEMS: int = 20            # frozen module-level constant

def should_trim(item_count: int) -> bool:
    """True when the live history item list has grown past the window budget."""
    return item_count > HISTORY_MAX_ITEMS
```

**Clone:** the `from __future__ import annotations` + frozen UPPER_CASE constants
(the VRAM table — `VRAM_TOTAL_MB`/`VRAM_HEADROOM_MB`/`LLM_PEAK_MB`/`STT_GPU_MB`/
`KOKORO_MB`, RESEARCH §3), typed pure functions, and a `_self_check()` guarded by
`if __name__ == "__main__":` so `python3 agent/placement.py` runs in the sandbox.
`interview.py:1-35` is the second example of the same "owns the DECISION, the
EFFECT lives in main.py" split — cite both in the module docstring.

**Change:** the decision body. `resolve_stt_placement(llm_choice, env) ->
"gpu"|"cpu"` (RESEARCH §3 resolution order): (1) `STT_FORCE_CPU` truthy → `"cpu"`
FIRST, before any headroom logic; (2) worst-case-LLM headroom math (`max(LLM_PEAK_MB)`
+ `KOKORO_MB` + `STT_GPU_MB <= ceiling`) gated behind a `measured` flag; (3) default
`"cpu"` when unmeasured. No exception escapes — always returns `"gpu"`/`"cpu"`.

### Analog B — env-single-source + validate-at-boundary posture: `agent/main.py:117-159`

`resolved_llm_tag` / `resolved_model_tag` are the in-repo "read from env, validate,
fail/normalize, no hardcoded literal" pattern the resolver's env reads mirror:

```python
# agent/main.py:150-159
def resolved_model_tag(choice: str) -> str:
    """Resolve a Fast/Better picker choice to its pinned Ollama tag from env.
    Mirrors resolved_llm_tag's SystemExit-if-unset posture — no hardcoded tag.
    """
    env_var = _MODEL_ENV[choice]
    tag = os.environ.get(env_var, "").strip()
    if not tag:
        raise SystemExit(f"{env_var} is not set — run ollama/pull-and-pin.sh first")
    return tag
```

Note `MODEL_CHOICES = ("fast", "better")` + `_MODEL_ENV` (main.py:132-134) — the
resolver normalizes `llm_choice` against `MODEL_CHOICES`; an unknown choice is
treated as worst-case (CPU-safe), NOT a SystemExit (the resolver never crashes a
session). **Change vs. the analog:** placement reads env via the passed `env`
Mapping (testable), parses booleans (`STT_FORCE_CPU`, `{"1","true","yes","on"}`)
with a single helper, and RETURNS a value rather than `raise SystemExit` — it is a
hot-path session decision, not a startup precondition.

### Analog C — resolve-once-never-thrash: `agent/main.py:408, 536-554`

`current_model[0]` is the per-session pick the resolver reads; `handle_model_update`
mutates ONLY `_opts.model` and is the RPC that must NOT trigger re-placement:

```python
# agent/main.py:546-549 — the live LLM swap; placement is NOT re-consulted here
        current_model[0] = choice
        session.llm._opts.model = resolved_model_tag(choice)
```

**Invariant:** STT placement is LOCKED at session start (worst-case-LLM math) so a
mid-session Fast↔Better swap is always VRAM-safe (STT-06) — `handle_model_update`
stays LLM-only, no placement coupling/guard added.

---

## 2. MODIFY `stt/server.py` — `STT_RUNTIME=gpu|cpu` backend dispatch

### Analog A — the seam already exists (self): `stt/server.py:101-221`

The five frozen-contract callables are the EXACT factoring point. They are pulled
into `backend_nemo.py` verbatim; `server.py` keeps the WS/HTTP/lifespan/health/
lock/stall-watchdog layer and dispatches through the chosen backend module:

```python
# stt/server.py:101-117 — moves verbatim to backend_nemo.py
def load_model() -> Any:
    """Load the Nemotron streaming model resident, set the att_context_size knob."""
    import nemo.collections.asr as nemo_asr  # noqa: PLC0415 - GPU-only dep
    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    ...
```

The decode-loop callers stay in `server.py` unchanged — they just call through the
backend:

```python
# stt/server.py:245-264 — _decode_off_loop / _handle_control stay in server.py
async def _decode_off_loop(state: dict, pcm: bytes) -> str:
    async with _gpu_lock:
        return await asyncio.to_thread(decode_chunk, state, pcm)
```

**Clone:** the WS framing (`ws_stream`/`_stream_loop`/`_handle_control_frame`/
`_emit_delta` 267-319), `/health` 503-gate (236-242), lifespan keep-resident
(223-231), `_gpu_lock` serialize (98, 247), stall watchdog (`_track_stall` 185-200,
backend-agnostic — operates on the cumulative string, stays shared). **Change:**
add the dispatch (RESEARCH §2):

```python
# new in server.py — mirrors the _parse_att_context_size validate-or-SystemExit posture
RUNTIME = os.environ.get("STT_RUNTIME", "gpu")
if RUNTIME not in ("gpu", "cpu"):
    raise SystemExit(f"STT_RUNTIME must be gpu|cpu, got {RUNTIME!r}")
backend = importlib.import_module("backend_nemo" if RUNTIME == "gpu" else "backend_onnx")
```

### Analog B — validate-an-env-knob-or-SystemExit: `stt/server.py:49-72`

`STT_RUNTIME`'s validation mirrors the existing `STT_MODEL` KeyError→SystemExit
(49-52) and `_parse_att_context_size` (57-72) "fail fast at import with a clear
message" posture:

```python
# stt/server.py:49-52 — the single-source / fail-fast posture STT_RUNTIME mirrors
try:
    MODEL_NAME: str = os.environ["STT_MODEL"]
except KeyError as exc:
    raise SystemExit("STT_MODEL is not set — supplied by docker-compose build/env") from exc
```

**Invariant:** heavy imports stay lazy/inside functions (server.py:109, 146-147,
162) so BOTH `backend_nemo.py` and `backend_onnx.py` `py_compile` in the GPU-less,
ORT-less sandbox. `backend_onnx.py` is the largest NEW code (3-graph encoder→greedy-
RNNT cache loop + the 128-band mel preprocessor that leaves the ONNX graph, RESEARCH
§1.2/§1.3) — its callables MUST reproduce the same cumulative growing transcript
(`hyps[0].text`, server.py:180) so the WS `delta`/`final` framing is byte-identical.
Keep ≤40 lines / ≤3 params / ≤3 nesting (server.py:280 `_stream_loop` is the
"nesting ≤3" exemplar).

---

## 3. CREATE `stt/Dockerfile.cpu` — lean CPU image, ONNX bake

### Analog A — the GPU bake/single-source pattern (self): `stt/Dockerfile`

`stt/Dockerfile` is the direct template: `ARG STT_MODEL` (no hardcoded tag) →
bake-at-build → `ENV` so runtime == bake tag, python-urllib HEALTHCHECK:

```dockerfile
# stt/Dockerfile:15-33 — the single-source bake pattern to mirror with STT_ONNX_MODEL
ARG STT_MODEL
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./
RUN python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"
ENV STT_MODEL=${STT_MODEL}
```

**Clone:** the `ARG → bake → ENV` single-source shape (now `ARG STT_ONNX_MODEL`),
`COPY server.py` + the two backend modules, `EXPOSE 8000`, the python-urllib
HEALTHCHECK (Dockerfile:41-42 — keep python-urllib, NOT curl), `CMD uvicorn
server:app ...`. **Change** (RESEARCH §5 Phase B): `FROM python:3.11-slim` (NO
CUDA/NeMo/torch); add `ENV STT_RUNTIME=cpu`; install `requirements-cpu.txt`; a
SHORTER `start_period` is fine (ONNX load ≪ NeMo) but keep python-urllib for parity;
bake the ONNX bundle keyed by `STT_ONNX_MODEL` (multi-stage NeMo+torch builder that
copies the `.onnx` into the slim final stage, OR `hf download` a prebuilt bundle).
Do NOT commit the `.onnx` (CONTEXT — bake at build).

### Analog B — bake-artifacts-at-build (offline-capable): `agent/Dockerfile`

`agent/Dockerfile`'s `download-files` is the "pre-fetch weights into the image so
the container starts offline-capable" precedent the ONNX bake mirrors (cited in
`09-PATTERNS.md §3`). Same intent as the `.nemo` bake at `stt/Dockerfile:30`.

---

## 4. CREATE `stt/requirements-cpu.txt`

### Analog (self) — `stt/requirements.txt` pin posture, minus torch/CUDA

```python
# stt/requirements.txt:7-10 — the explicit-pin posture to mirror
fastapi~=0.115
uvicorn[standard]~=0.34
numpy~=1.26
soundfile~=0.12
```

**Clone:** the explicit `~=` pins (no `:latest`, no unbounded float), the
"why-torch-is-NOT-here" header comment style (requirements.txt:1-6). **Change**
(RESEARCH §1.4): add `onnxruntime` (the **CPU** wheel, NOT `onnxruntime-gpu`),
`sentencepiece` (detokenize RNNT tokens), and the mel dep (numpy-only baked
filterbank preferred over `librosa` to keep deps lean — RESEARCH §1.3). Drop
`soundfile` if unused; NeMo is absent by design.

---

## 5. MODIFY `docker-compose.yml` — add `nemo-stt-cpu`, adjust agent `depends_on`

### Analog A — clone the `nemo-stt` block minus the GPU reservation (self): `docker-compose.yml:101-138`

The new `nemo-stt-cpu:` service clones `nemo-stt:` — same `build.args` single-source
shape, same `STT_*` env, same python-urllib healthcheck, `networks: [adept]`, no
`env_file` (M3), `restart: unless-stopped` — but **DROPS** the `deploy.resources.
reservations.devices` GPU block (121-127) and **ADDS** `STT_RUNTIME=cpu` +
`STT_ONNX_MODEL` build ARG + a distinct host port `8001:8000`:

```yaml
# docker-compose.yml:108-138 — clone this, drop 121-127 (the GPU reservation)
    build:
      context: ./stt
      args:
        STT_MODEL: ${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
    environment:
      - STT_MODEL=${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
      - STT_ATT_CONTEXT_SIZE=${STT_ATT_CONTEXT_SIZE:-[56,3]}
    ports:
      - "${LAN_BIND_IP:-127.0.0.1}:8000:8000"
    deploy:                       # ← DROP this whole block for the CPU service
      resources:
        reservations:
          devices: [ { driver: nvidia, count: all, capabilities: [gpu] } ]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; ..."]
```

**Change:** `build.dockerfile: Dockerfile.cpu`; `STT_RUNTIME=cpu`; `STT_ONNX_MODEL`
build ARG + matching `environment` (single-source, mirrors `STT_MODEL`);
`"${LAN_BIND_IP:-127.0.0.1}:8001:8000"` (distinct host port for host probing —
internal port stays 8000, reached by service DNS `ws://nemo-stt-cpu:8000/...`,
RESEARCH §4). The existing `nemo-stt` keeps `STT_RUNTIME=gpu` (add it explicitly).

### Analog B — the agent `depends_on` (self): `docker-compose.yml:42-53` — the gate this phase CHANGES

```yaml
# docker-compose.yml:44-52 (current) — the Phase-9 service_healthy hard-gate on nemo-stt
    depends_on:
      livekit-server: { condition: service_started }
      ollama:         { condition: service_started }
      nemo-stt:       { condition: service_healthy }   # ← the gate RESEARCH §4 drops
      kokoro:         { condition: service_started }
```

**Change (call it out explicitly — RESEARCH §4/§Risk 6):** the recommended path
DROPS the STT `service_healthy` hard-gate to `service_started` (or removes STT from
`depends_on`) and lets the plugin's WS connect-retry be the readiness point — so a
CPU-default deploy (`STT_FORCE_CPU=1`) does NOT wait on a GPU STT image it never
uses. This is a deliberate change to the Phase 9 gate; the PLAN states it plainly.
Update the header comment (compose:8-9, 42-43) that documents the long-form
`service_healthy` rationale.

---

## 6. MODIFY `agent/main.py` — `NEMO_STT_CPU_URL` + `resolve_stt_placement` in `build_session`

### Analog A — the URL-const block (self): `agent/main.py:49-56`

`NEMO_STT_CPU_URL` joins the existing `ws://` endpoint const, mirroring
`NEMO_STT_URL`'s env-with-default form:

```python
# agent/main.py:52-56 — NEMO_STT_URL is the const to clone
NEMO_STT_URL = os.environ.get("NEMO_STT_URL", "ws://nemo-stt:8000/v1/audio/stream")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://kokoro:8880/v1")
```

**Add** (beside it):
```python
from placement import resolve_stt_placement
NEMO_STT_CPU_URL = os.environ.get("NEMO_STT_CPU_URL", "ws://nemo-stt-cpu:8000/v1/audio/stream")
```

### Analog B — the `build_session` STT construction (self): `agent/main.py:194-200`

```python
# agent/main.py:198-200 — the construction site the resolved URL flows into
    return AgentSession(
        vad=vad,
        stt=NemoSTT(ws_url=NEMO_STT_URL, language="en"),
```

**Change:** resolve ONCE at the top of `build_session` (or pass `current_model[0]`
in), pick the URL, construct `NemoSTT(ws_url=<resolved>, language="en")`:

```python
    placement = resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)   # once, at session start
    stt_url = NEMO_STT_URL if placement == "gpu" else NEMO_STT_CPU_URL
    ...
        stt=NemoSTT(ws_url=stt_url, language="en"),
```

**Invariant (CONTEXT/RESEARCH §3):** resolve-once — DO NOT touch
`handle_model_update` (main.py:536-554); placement is read at session start and
NEVER re-consulted on an LLM swap. `build_session` is called once in `entrypoint`
(main.py:370) before `session.start`.

---

## 7. MODIFY `.env.example` — `STT_ONNX_MODEL`, `STT_FORCE_CPU=1`, `NEMO_STT_CPU_URL`, `STT_QUANT`

### Analog (self) — the Phase-9 STT block + its no-hardcoded-tag rationale: `.env.example:53-65`

```bash
# .env.example:53-63 — the single-source STT block to extend, same comment style
STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b
# att_context_size = [left, right] in 80 ms encoder frames (STT-04). [56,3] balanced...
STT_ATT_CONTEXT_SIZE=[56,3]
```

**Add (mirror the existing single-source comment style, RESEARCH §6):**
- `STT_ONNX_MODEL=...` — the CPU analog of `STT_MODEL`; literal default lives ONLY
  in compose `build.args`/`environment` (no hardcoded tag — same invariant as the
  `STT_MODEL` comment at .env.example:53-57).
- `STT_QUANT=int8-dynamic` — quant profile selector; comment that `int4-kquant` is
  the ~0.67 GB STT-05 target and an operator-gated build (RESEARCH §1.1).
- `NEMO_STT_CPU_URL` — note the code default `ws://nemo-stt-cpu:8000/v1/audio/stream`
  (parity with `NEMO_STT_URL`, which is code-default-only today).
- **`STT_FORCE_CPU=1`** — ship as the documented SAFE DEFAULT (CONTEXT/STT-07):
  comment that it pins CPU-ONNX for BOTH LLMs, the picker is VRAM-safe out of the
  box, and the operator flips it to `0` (+ the measured flag) only after the 4-cell
  matrix proves E4B + GPU-STT + Kokoro co-fit. Mirror the HOOK-note style at
  .env.example:64-65. `STT_RUNTIME` is set per-service in compose, NOT here.

---

## 8. MODIFY `scripts/vram-validate.sh` — 4-cell `{E2B,E4B}×{GPU,CPU}` matrix

### Analog A — `EXPECTED_GPU_PROCS` (self): `scripts/vram-validate.sh:45, 158-164`

The constant becomes a per-cell value (3 with GPU-STT, 2 with CPU-STT):

```bash
# scripts/vram-validate.sh:45 — no longer a constant 3
readonly EXPECTED_GPU_PROCS=3
# scripts/vram-validate.sh:158-164 — the assert to parametrize
assert_three_gpu_procs() {
  ...
    || fail "expected ${EXPECTED_GPU_PROCS} GPU processes (ollama, nemo-stt, kokoro) ..."
  echo "GPU processes: ${proc_count} (ollama, nemo-stt, kokoro — no embedder/vector store)" >&2
}
```

**Change (RESEARCH §7):** add a `--stt-runtime gpu|cpu` flag (or
`STT_RUNTIME_UNDER_TEST` env) that sets `EXPECTED_GPU_PROCS` to **3** (GPU-STT:
ollama/nemo-stt/kokoro) or **2** (CPU-STT: ollama/kokoro — `nemo-stt-cpu` is NOT a
GPU process, must NOT be counted). Rename the assert message dynamically per cell.

### Analog B — `parse_args` + the LLM sweep (self): `scripts/vram-validate.sh:173-208, 60-66`

`parse_args` (173-184) is the existing flag-parse to extend with `--stt-runtime`;
`require_tag` (60-66) reads `OLLAMA_MODEL` — the script already sweeps it. The
4-cell matrix sweeps `OLLAMA_MODEL` over E2B (Fast) / E4B (Better) × `--stt-runtime`
gpu/cpu, restarting ollama between tags to clear `keep_alive=-1` (Gate D). The
peak assertion (201-202, `peak < VRAM_CEILING_MB`) is UNCHANGED per cell; the STT
health probe targets `nemo-stt` (8000) or `nemo-stt-cpu` (host 8001) per cell. Keep
the q8_0-engaged grep (130-156, already 0.30.x-aware). **The GPU-STT × E4B cell is
load-bearing** — if its peak ≥ ceiling, the safe default stays `STT_FORCE_CPU=1`.

---

## 9. CREATE `10-PLACEMENT-VERIFY.md` — operator GPU-gate runbook

### Analog — `09-STT-VERIFY.md` + `08-LLM-VERIFY.md` (the format to mirror)

```yaml
# 09-STT-VERIFY.md:1-20 — the front-matter + harness_note block to clone
---
status: pending-operator
phase: 09-nemotron-streaming-asr-part-b
plan: 09-02
requirement_ids: [STT-01, STT-02, STT-03, STT-04]
verifies: [...]
harness_note: > ...the entire ... path ... are deferred operator gates ...
  NONE are marked passed by the executor ...
---
```

**Clone:** the `status: pending-operator` front-matter, the `harness_note`
(sandbox has no GPU/Docker/ONNX), the **§0 "Build/deploy BEFORE verifying
(baked-image guard)"** section (09-STT-VERIFY.md:86-103 — but now
`docker compose build nemo-stt-cpu agent && up -d`), the per-gate
Goal/Steps/ASSERT/Results-capture table shape, and the "Overall sign-off" matrix
with Operator/Date/VM lines (309-325). **Change:** the gate set (CONTEXT/RESEARCH
§9) — real ONNX export (`cache_support=True`), int8/int4 quant + size check, **>6×
realtime** + **WER-under-contention** vs FP32/NeMo, the mel-parity check, the
4-cell `{E2B,E4B}×{GPU,CPU}` co-residency matrix (peak < total−1 GB, 3 vs 2 procs),
the Kokoro `KOKORO_MB`-placeholder measurement, and the **safe-default flip**
(`STT_FORCE_CPU=1`→`0` + measured flag, only after the matrix passes). Mark every
gate **PENDING**, unsigned. `requirement_ids: [STT-05, STT-06, STT-07]`.

---

## Cross-cutting invariants (apply to every new file)

| Invariant | Source line(s) | Applies to |
|---|---|---|
| Single-source, no-hardcoded-tag → `STT_ONNX_MODEL` (literal only in compose) | `stt/Dockerfile:15-33`, `docker-compose.yml:108-116`, `.env.example:53-57` | `Dockerfile.cpu`, the `nemo-stt-cpu` service, `.env.example` |
| Functions ≤40 lines / ≤3 params / ≤3 nesting | `stt/server.py:280` (`_stream_loop` nesting≤3), `agent/history.py:31-38` | `placement.py`, `backend_onnx.py`, `backend_nemo.py`, server dispatch |
| Resolve-once-no-thrash (per-session decision held, never re-consulted) | `agent/main.py:408, 546-549`; `agent/history.py` (window decision) | `placement.py` ← `build_session`; STT-06 worst-case-LLM lock |
| Validate-before-use at the env/RPC boundary | `stt/server.py:49-72`; `agent/main.py:543-545` (`handle_model_update`) | `STT_FORCE_CPU`/`STT_RUNTIME`/`STT_QUANT` parse + normalize |
| Pure, livekit-free decision module (frozen consts, `_self_check`, `__main__`) | `agent/history.py:1-57`; `agent/interview.py:1-35` | `placement.py` |
| Operator-gated GPU proofs UNSIGNED (`status: pending-operator`, none passed by executor) | `09-STT-VERIFY.md:1-26`; CONTEXT/RESEARCH §9 | `10-PLACEMENT-VERIFY.md` |
| BAKED-image: rebuild affected services + `up -d` before any live verify | `09-STT-VERIFY.md:86-103`; CONTEXT "baked images" | `docker compose build nemo-stt-cpu agent` then verify |
| Heavy imports lazy/inside functions (sandbox `py_compile`) | `stt/server.py:109, 146-147, 162` | `backend_onnx.py` (ORT), `backend_nemo.py` (NeMo) |
| Keep-resident-forever (`/health` 503-until-ready) | `stt/server.py:223-242`; `docker-compose.yml:107` | `nemo-stt-cpu` lifespan + healthcheck |
| LAN-bound port `${LAN_BIND_IP:-127.0.0.1}:H:C`, no `env_file` (M3) | `docker-compose.yml:112-118` | `nemo-stt-cpu` service (host 8001) |
| DO NOT touch: `model.update` RPC / VAD-turn-detector authority / `metrics.py` | `agent/main.py:536-554, 269-281`; `agent/metrics.py` (READ-ONLY) | all of Phase 10 (frozen WS contract + endpoint authority) |

---

## NO CHANGE (validated)

- **`agent/nemo_stt.py`** — runtime-agnostic; speaks the WS contract, so GPU vs CPU
  is purely a different `ws_url` it is handed (CONTEXT/RESEARCH §2).
- **`agent/metrics.py`** — READ-ONLY; the CPU backend emits the same `delta`/`final`,
  so `_on_stt_metrics` still populates `stt_ms` unchanged.
- **`handle_model_update`** (`agent/main.py:536-554`) — placement is read once at
  session start; the LLM-swap RPC stays LLM-only, no placement re-check/guard added.
- **The `turn_handling` dict / `MultilingualModel` turn detector** (`agent/main.py:269-281`)
  — endpoint authority is unchanged; the server still NEVER auto-finalizes.
