---
plan: 09-01
title: NeMo streaming STT server (stt/ FastAPI WS + baked Blackwell image) + full Compose swap (delete whisper, add nemo-stt) + STT_* env template
phase: 9
wave: 1
depends_on: []
autonomous: false
requirements: [STT-01, STT-04]
files_modified:
  - stt/server.py
  - stt/Dockerfile
  - stt/requirements.txt
  - docker-compose.yml
  - .env.example
---

# Plan 09-01: The nemo-stt server + image + Compose swap — a runnable, health-checkable Nemotron streaming STT service on the `adept` network, faster-whisper deleted

## User Story

**As** the operator standing up the Adept stack, **I want** a `nemo-stt` Compose service that
serves `nvidia/nemotron-speech-streaming-en-0.6b` behind a FastAPI websocket — model resident at
startup, `/health` gating, an `att_context_size` knob — replacing the faster-whisper service, **so
that** the agent (Wave 2) can stream 16 kHz mono int16 audio in and get growing interim + final
transcripts back, with no audio leaving the LAN.

## Context

This is the **server half** of the pipeline swap. It produces the `stt/` directory (FastAPI WS
server + baked Blackwell-capable image + pinned deps) and performs the **entire** `docker-compose.yml`
swap — DELETE the `whisper:` service, ADD `nemo-stt:`, repoint the agent `depends_on`, fix the
header comment — plus the `.env.example` `STT_*` knobs. After this plan, `docker compose build
nemo-stt && up -d` brings up a health-checkable STT server independent of the agent plugin; Wave 2
(09-02) then writes the `NemoSTT` plugin that matches the WS contract frozen here.

**The WS/HTTP contract this plan FREEZES (Wave 2 matches it verbatim — RESEARCH §2):**
- `WS /v1/audio/stream` — client sends `{"type":"config","language":"en"}`, then raw int16 PCM
  binary frames; control frames `{"type":"flush"}` (drain → emit FINAL) and `{"type":"reset"}`.
- Server→client JSON: `{"type":"ready"}` (after config), `{"type":"delta","text":"<cumulative>"}`
  (growing interim), `{"type":"final","text":"<final>"}` (ONLY in response to `flush`),
  `{"type":"error","message":"..."}`.
- `GET /health` — returns 200 ONLY after the model is loaded (so Compose `service_healthy` gates
  the agent); 503 while loading.
- `POST /v1/audio/transcriptions` — OPTIONAL OpenAI-compat whole-file endpoint mirroring
  `ollama/warmup.py`'s `warm_whisper` request shape, for `09-STT-VERIFY.md` offline WER/latency
  checks without the agent. Port **8000** (freed by removing whisper; reuse keeps `LAN_BIND_IP`
  patterns identical).

**Cache-aware streaming decode loop (RESEARCH §1).** Per-connection fresh encoder cache state via
`model.encoder.get_initial_cache_state(batch_size=1)`; per audio chunk a blocking
`model.conformer_stream_step(...)` (run in a worker thread, GPU access serialized by an
`asyncio.Lock` — single-user, one active stream is the norm). `prev_hyps[0].text` is CUMULATIVE →
re-emit the whole string as the INTERIM `delta`. Native PnC comes out of the model — surfaced AS-IS,
zero post-processing (STT-03 satisfied for free server-side). `att_context_size` set ONCE at load
via `model.encoder.set_default_att_context_size(ATT)` from `STT_ATT_CONTEXT_SIZE` (default `[56,3]`,
STT-04).

**RNNT decoder-stall watchdog (RESEARCH §1, PITFALL B2 — CRITICAL).** The server tracks "frames
since cumulative text last grew"; if it exceeds `STT_STALL_FRAMES` **while audio is still arriving**,
it RECYCLES decoder state (reset `prev_hyps`, carry the encoder cache forward) and CONTINUES — it
LOGS the recycle and does **NOT** emit a FINAL. The turn detector (Wave 2 / unchanged) owns finalize;
the server must NEVER auto-emit FINAL on its own heuristics (preserves the single-turn-source
invariant). Keep `STT_RECYCLE_MIN_CHARS` / `STT_RECYCLE_HARD_CHARS` envs with conservative defaults
so recycling is stall-recovery only.

**Keep-resident-forever (CONTEXT, mirrors `WHISPER__TTL=-1` / `OLLAMA_KEEP_ALIVE=-1`).** Load the
model in the FastAPI lifespan startup, never offload — avoids the cold-reload first-turn-drop bug
that bit whisper (STATE.md, commit 06920c5). `/health` is 503 until load completes.

**Baked Blackwell image (RESEARCH §6, PATTERNS §3).** Base on a CUDA-12.8+ Blackwell-capable NeMo
image; the Kokoro service comment (`docker-compose.yml:122-124`) is the precedent — stock torch
crashes on sm_120 with "no kernel image is available." Bake the `.nemo` into the image at build
(`from_pretrained('${STT_MODEL}')`) with `STT_MODEL` as a build ARG — NO hardcoded tag (AGENTS.md
single-source), offline-capable at runtime. `HEALTHCHECK` on `/health` with a generous
`start_period` (model load is slow).

**Sandbox vs operator split (RESEARCH §8).** The sandbox has NO GPU, NO Docker daemon, and cannot
import NeMo/torch. Sandbox-verifiable: `python3 -m py_compile stt/server.py`, the FastAPI route/JSON
framing with a STUBBED `decode_chunk` (no model), and `docker compose config` IF a compose binary is
present. The real model load, `conformer_stream_step` signature confirmation, Blackwell sm_120
kernel execution, and the multi-GB image build are **operator GPU gates** authored in Wave 2's
`09-STT-VERIFY.md`. Marked `autonomous: false`.

**Scope discipline (YAGNI).** NO CPU-ONNX runtime, NO VRAM-aware placement (Phase 10). NO language/
prompt steering (the reference repo targets multilingual 3.5 — drop ALL of it; our model is
English-only). NO client-side PnC post-processing. NO mid-utterance FINAL heuristics. Keep each
function ≤40 lines / ≤3 params / ≤3 nesting (AGENTS.md) — split into `load_model()`,
`new_stream_state()`, `decode_chunk(state, pcm) -> str`, `finalize(state) -> str`,
`ws_stream(websocket)`.

## Tasks

<task id="09-01-1">
  <title>Create stt/requirements.txt — pinned server deps (fastapi, uvicorn, numpy, soundfile; nemo_toolkit[asr] only if base image lacks it)</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§2 "Server deps"; §6 base-image options; PITFALL B1 image bloat — [asr] NOT [all])
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§4 — tight-pin posture from agent/requirements.txt)
    - agent/requirements.txt (the explicit-pin posture to mirror)
  </read_first>
  <action>
    Create `stt/requirements.txt` listing ONLY the runtime server deps the chosen Blackwell base
    image does NOT already ship, with explicit pins (no `:latest`, no unpinned float — mirror
    agent/requirements.txt posture). Required: `fastapi`, `uvicorn[standard]`, `numpy`, `soundfile`.
    Add `nemo_toolkit[asr]` (NOT `[all]` — PITFALL B1 image bloat) with a comment that it is needed
    ONLY if the base image (`nvcr.io/nvidia/nemo:25.11`) does not already provide NeMo; if the NeMo
    base is used, comment it out / note it is base-provided. Add a one-line header comment naming the
    purpose ("nemo-stt FastAPI websocket STT server deps") and that torch/CUDA come from the base
    image (NOT pip-installed here — Blackwell sm_120 needs the base's CUDA-12.8 build, RESEARCH §6).
    Do NOT add aiohttp (that is the AGENT's WS-client dep, Wave 2). Do NOT add test frameworks.
  </action>
  <acceptance_criteria>
    - `stt/requirements.txt` exists and lists fastapi, uvicorn[standard], numpy, soundfile with explicit pins (`grep -nE "fastapi|uvicorn\[standard\]|numpy|soundfile" stt/requirements.txt`)
    - It uses `nemo_toolkit[asr]` NOT `nemo_toolkit[all]` (`grep -n "nemo_toolkit\[asr\]" stt/requirements.txt`; `grep -n "nemo_toolkit\[all\]" stt/requirements.txt` returns nothing)
    - No `:latest` and no aiohttp (`grep -n ":latest\|aiohttp" stt/requirements.txt` returns nothing)
  </acceptance_criteria>
</task>

<task id="09-01-2">
  <title>Create stt/server.py — FastAPI WS server: lifespan model load, /health gate, cache-aware decode loop, flush→FINAL, RNNT stall-recovery watchdog (no premature FINAL), native PnC as-is</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§1 decode loop + att_context_size + stall watchdog; §2 endpoints + WS message shapes + concurrency Lock + keep-resident; the conformer_stream_step ⚠️ signature-drift note)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§2 Analog A whisper service contract :95-119; Analog B warm_whisper 16k/mono/int16 input contract; Analog C single-source STT_MODEL via env like resolved_llm_tag)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-CONTEXT.md (§decisions Server Packaging & Contract; §specifics 16kHz int16, native PnC as-is, no audio leaves LAN)
    - ollama/warmup.py (_sine_wav_bytes :64-76 — the 16kHz mono int16 wav convention the optional /v1/audio/transcriptions endpoint mirrors; warm_whisper :118-127 files=/data= request shape)
    - agent/main.py (resolved_llm_tag :127-132 — the SystemExit-if-unset env single-source posture to mirror for STT_MODEL)
  </read_first>
  <action>
    Create `stt/server.py` — the NeMo cache-aware streaming decode server. Structure into small
    functions (≤40 lines / ≤3 params / ≤3 nesting, AGENTS.md):
    - **Config (module scope, no hardcoded tag):** `MODEL_NAME = os.environ["STT_MODEL"]`
      (KeyError/SystemExit if unset, mirroring resolved_llm_tag); `ATT =
      ast.literal_eval(os.environ.get("STT_ATT_CONTEXT_SIZE", "[56,3]"))`; named stall/recycle
      constants from env: `STT_STALL_FRAMES`, `STT_RECYCLE_MIN_CHARS`, `STT_RECYCLE_HARD_CHARS`
      (conservative defaults, each a named constant — no magic values). Port 8000.
    - **`load_model()`:** `nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)`, `.eval()`,
      `model.encoder.set_default_att_context_size(ATT)` (the STT-04 knob, set ONCE), greedy single-
      step RNNT decoding strategy. Copy the reference server's preprocessing
      (`AudioToMelSpectrogramPreprocessor` via `model.preprocessor`) — see RESEARCH §1. Add a clear
      comment that the exact `conformer_stream_step` signature is confirmed against the in-container
      `nemo.collections.asr` source at build/operator time (09-STT-VERIFY Gate) — the sandbox cannot
      import NeMo.
    - **FastAPI lifespan startup:** load the model resident (keep-forever, mirrors `WHISPER__TTL=-1`);
      set a module `_ready` flag True after load. NEVER offload.
    - **`GET /health`:** 200 `{"status":"ok"}` only when `_ready`, else 503 — so Compose
      `service_healthy` gates the agent.
    - **`new_stream_state()`:** fresh per-connection `cache_last_channel/time/channel_len` from
      `model.encoder.get_initial_cache_state(batch_size=1)`, `prev_hyps=None`, plus stall-tracking
      counters (frames-since-text-grew, last-text-len).
    - **`decode_chunk(state, pcm) -> str`:** int16→float32, feature-extract, `conformer_stream_step`
      under `torch.inference_mode()`; return `prev_hyps[0].text` (CUMULATIVE). Surface PnC AS-IS (no
      strip/lowercase — STT-03).
    - **Stall watchdog (inside the decode path):** if cumulative text did not grow for
      `STT_STALL_FRAMES` WHILE audio is still arriving, recycle decoder state (reset `prev_hyps`,
      carry encoder cache forward), `logger.info` the recycle — do **NOT** emit FINAL (RESEARCH §1/§4;
      the turn detector owns finalize). `STT_RECYCLE_*` are stall-recovery thresholds only.
    - **`finalize(state) -> str`:** drain the buffer and return the final transcript text (the
      flush→final response; target ~100 ms drain).
    - **`WS /v1/audio/stream` (`ws_stream`):** accept; await `{"type":"config"}`; send
      `{"type":"ready"}`; then loop — on a JSON `{"type":"flush"}` send `{"type":"final","text":...}`;
      on `{"type":"reset"}` rebuild stream state; on a binary frame run `decode_chunk` (in
      `asyncio.to_thread`, guarded by a single `asyncio.Lock` to serialize GPU access) and send
      `{"type":"delta","text":<cumulative>}`. Early-`continue` on control frames to keep nesting ≤3.
      On any decode error send `{"type":"error","message":...}`.
    - **OPTIONAL `POST /v1/audio/transcriptions`:** whole-file OpenAI-compat path mirroring
      warm_whisper's `files=`/`data=` shape (decode the wav, run the same per-chunk loop, return the
      joined transcript) — for offline VERIFY checks. Keep it small; reuse decode_chunk.
    - NO language/prompt steering anywhere (English-only model; drop ALL the reference multilingual
      bits). NO mid-utterance FINAL heuristics. NO audio written to disk/db (local-first, in-memory).
    The real decode runs only on the GPU (operator gate); this task is sandbox-verified by
    `py_compile` and a stubbed-`decode_chunk` route test (next task's harness note).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile stt/server.py` exits 0 (syntax valid without importing NeMo/torch — keep heavy imports inside functions/lifespan if needed so py_compile passes)
    - The model tag is single-sourced from `STT_MODEL` with no hardcoded `nvidia/nemotron` literal in code (`grep -n "STT_MODEL" stt/server.py`; `grep -n "nvidia/nemotron-speech-streaming" stt/server.py` returns nothing)
    - `att_context_size` is read from `STT_ATT_CONTEXT_SIZE` (default `[56,3]`) and set once on the encoder (`grep -n "STT_ATT_CONTEXT_SIZE\|set_default_att_context_size" stt/server.py`)
    - `/health` and `WS /v1/audio/stream` routes exist; the WS sends `ready`/`delta`/`final`/`error` JSON shapes (`grep -nE "/health|/v1/audio/stream|\"ready\"|\"delta\"|\"final\"|\"error\"" stt/server.py`)
    - FINAL is emitted ONLY on a `flush` control frame — the stall watchdog recycles state and does NOT emit FINAL (`grep -n "flush\|recycle\|STT_STALL_FRAMES" stt/server.py`; the watchdog branch contains no `"final"` send — verify by reading the function)
    - The model loads at lifespan startup and is kept resident (no offload call) (`grep -n "lifespan\|from_pretrained\|_ready" stt/server.py`)
    - GPU access is serialized with an asyncio.Lock and decode runs off the event loop (`grep -n "asyncio.Lock\|to_thread" stt/server.py`)
    - No language/prompt steering (`grep -ni "set_inference_prompt\|language_steering\|inference_prompt" stt/server.py` returns nothing)
    - OPERATOR-VERIFICATION (GPU, deferred — 09-STT-VERIFY): the model loads, `conformer_stream_step` signature matches in-container NeMo, a real clip streams growing deltas + a flush returns a PnC final, and the stall watchdog recycles without a premature FINAL on a run-on answer
  </acceptance_criteria>
</task>

<task id="09-01-3">
  <title>Create stt/Dockerfile — Blackwell CUDA-12.8 base, pinned deps, model baked at build via STT_MODEL ARG, /health HEALTHCHECK with generous start_period</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§6 Dockerfile — base options nvcr.io/nvidia/nemo:25.11 or pytorch:25.11-py3, model bake, Blackwell sm_120/CUDA-12.8 gate, HEALTHCHECK start_period)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§3 Analog agent/Dockerfile bake-weights pattern + the Kokoro CUDA-12.8 precedent docker-compose.yml:122-124)
    - agent/Dockerfile (the COPY requirements + install + bake-artifacts-at-build pattern to mirror)
    - docker-compose.yml (kokoro service comment :122-124 — the sm_120 "no kernel image" precedent to cite)
  </read_first>
  <action>
    Create `stt/Dockerfile` baking an offline-capable, Blackwell-capable image:
    - `FROM` a CUDA-12.8+ Blackwell-capable NeMo/torch base (`nvcr.io/nvidia/nemo:25.11`, or
      `nvcr.io/nvidia/pytorch:25.11-py3` + pip nemo_toolkit[asr]). Add a comment citing the Kokoro
      precedent (docker-compose.yml:122-124): stock torch ships sm_50..sm_90 only and crashes on
      sm_120 with "no kernel image is available" — so a CUDA-12.8 base is REQUIRED; the operator
      confirms sm_120 kernel execution on the real RTX 5090 (09-STT-VERIFY gate).
    - `ARG STT_MODEL` (no default literal in the Dockerfile body — the Compose `build.args` supplies
      it from the single-sourced env; NO hardcoded tag, AGENTS.md). 
    - `COPY requirements.txt ./` + pip install the pinned deps (skip nemo if base-provided).
    - `COPY server.py ./`.
    - **Bake the model** (the NeMo equivalent of agent/Dockerfile's `download-files`):
      `RUN python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"`
      so the ~2.4 GB `.nemo` is in the image (no first-run download; offline/local-first). Reference
      `ARG STT_MODEL` so there is no hardcoded tag.
    - `ENV STT_MODEL=${STT_MODEL}` so the runtime server reads the SAME single-sourced tag the bake
      used (no drift between baked weights and loaded model).
    - `EXPOSE 8000`; `CMD` runs `uvicorn server:app --host 0.0.0.0 --port 8000`.
    - `HEALTHCHECK` hitting `/health` with a GENEROUS `start_period` (model load is slow — e.g. the
      180s the Compose healthcheck uses), `interval`/`timeout`/`retries` consistent with the Compose
      healthcheck (task 09-01-4). Use a `python -c` urllib probe (NOT `curl` — not guaranteed in the
      NeMo base image), identical to the Compose healthcheck command.
    The multi-GB build + sm_120 execution are operator gates; this task only authors the Dockerfile.
  </action>
  <acceptance_criteria>
    - `stt/Dockerfile` exists, bases on a CUDA-12.8+ Blackwell-capable NeMo/torch image with a comment citing the Kokoro sm_120 precedent (`grep -niE "cuda|nemo|sm_120|blackwell|no kernel image" stt/Dockerfile`)
    - The model is baked at build via an `ARG STT_MODEL` (no hardcoded `nvidia/nemotron` literal) (`grep -n "ARG STT_MODEL\|from_pretrained" stt/Dockerfile`; `grep -n "nvidia/nemotron-speech-streaming" stt/Dockerfile` returns nothing)
    - The runtime `ENV STT_MODEL` matches the bake ARG so loaded == baked (`grep -n "ENV STT_MODEL" stt/Dockerfile`)
    - It EXPOSEs 8000, runs uvicorn, and HEALTHCHECKs `/health` with a generous start_period (`grep -niE "EXPOSE 8000|uvicorn|HEALTHCHECK|/health|start" stt/Dockerfile`)
    - OPERATOR-VERIFICATION (GPU, deferred — 09-STT-VERIFY): `docker compose build nemo-stt` succeeds, the baked `.nemo` is present (no first-run download), and the container runs sm_120 kernels on the RTX 5090 without "no kernel image"
  </acceptance_criteria>
</task>

<task id="09-01-4">
  <title>Swap docker-compose.yml: DELETE the whisper service, ADD nemo-stt (build ARG + env + LAN-bound 8000 + GPU reservation + /health healthcheck + keep-resident), repoint agent depends_on, fix header comment</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§6 full nemo-stt YAML + agent depends_on service_healthy gating; port-8000 reuse note)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§5 — clone the whisper block shape; header comment 8-9; agent depends_on 42-47; cross-cutting GPU-reservation-verbatim, LAN-bind, no-env_file, no-hardcoded-tag rows)
    - docker-compose.yml (whisper service :95-119; agent depends_on :42-47; header comment :8-9; kokoro GPU+CUDA block :121-139 for the reservation+sm_120 precedent)
  </read_first>
  <action>
    Edit `docker-compose.yml` to replace whisper with nemo-stt and gate the agent on it:
    - **DELETE** the entire `whisper:` service block (:95-119).
    - **ADD** a `nemo-stt:` service cloning whisper's runtime shape (GPU reservation block VERBATIM,
      `ports: ["${LAN_BIND_IP:-127.0.0.1}:8000:8000"]`, `networks: [adept]`, NO `env_file` (M3 — no
      LiveKit secret), `restart: unless-stopped`) and ADDING:
      - `build: { context: ./stt, args: { STT_MODEL: ${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b} } }`
        — the ONE place the default tag literal lives (single-source; the agent/code carry no
        hardcoded tag).
      - `environment: [ STT_MODEL=${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b},
        STT_ATT_CONTEXT_SIZE=${STT_ATT_CONTEXT_SIZE:-[56,3]} ]` (STT-04 default `[56,3]`).
      - `healthcheck: { test: ["CMD","python","-c","import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"], start_period:
        180s, interval: 10s, timeout: 5s, retries: 30 }` (generous start_period — model load is slow).
        Use `python` (guaranteed present in the NeMo/PyTorch base image) NOT `curl` — `curl` is not
        guaranteed in `nvcr.io/nvidia/nemo:*` and a missing-curl healthcheck would never pass, so the
        agent would hang forever on `service_healthy`. The Dockerfile HEALTHCHECK (task 09-01-3) MUST
        use the SAME python-urllib check for consistency.
      - A comment mirroring whisper's keep-resident note: the model is loaded resident at startup and
        never offloaded (mirrors the `WHISPER__TTL=-1` fix that stopped the first-turn-drop bug).
    - **Repoint the agent `depends_on` (:42-47):** convert to long-form and gate on health —
      `nemo-stt: { condition: service_healthy }` (replacing `- whisper`), keeping the other three.
      (Long-form is recommended because model load is slow; if any existing dep lacks a healthcheck,
      use `condition: service_started` for those so the block stays valid.)
    - **Fix the header comment (:8-9):** drop the "except faster-whisper, which is pinned by digest"
      clause — nemo-stt is now a locally-built service, not a digest-pinned upstream image.
    Do NOT touch ollama/kokoro/livekit-server/web services. Do NOT add an `env_file` to nemo-stt.
  </action>
  <acceptance_criteria>
    - The whisper service block is gone (`grep -n "whisper" docker-compose.yml` returns nothing)
    - A `nemo-stt:` service exists with a build context ./stt + STT_MODEL build arg, env (STT_MODEL + STT_ATT_CONTEXT_SIZE default [56,3]), LAN-bound 8000, GPU reservation, /health healthcheck, restart unless-stopped, and NO env_file (`grep -nE "nemo-stt:|context: ./stt|STT_MODEL|STT_ATT_CONTEXT_SIZE|8000:8000|/health|service_healthy" docker-compose.yml`)
    - The default tag literal appears ONLY in compose build.args/environment defaults, not in any agent/server source (`grep -rn "nvidia/nemotron-speech-streaming-en-0.6b" docker-compose.yml` shows it; the same grep over stt/server.py + agent/*.py returns nothing)
    - The agent depends_on references nemo-stt (not whisper) (`grep -n "nemo-stt" docker-compose.yml` includes the depends_on entry)
    - The header comment no longer claims a faster-whisper digest pin (`grep -ni "faster-whisper" docker-compose.yml` returns nothing)
    - OPERATOR-VERIFICATION (deferred — 09-STT-VERIFY): `docker compose config` validates; `docker compose build nemo-stt && up -d` brings nemo-stt to healthy and the agent starts only after (gated on service_healthy)
  </acceptance_criteria>
</task>

<task id="09-01-5">
  <title>Add STT_MODEL + STT_ATT_CONTEXT_SIZE to .env.example with the no-hardcoded-tag rationale + cyber-vocab fine-tune HOOK note (STT-04); confirm no WHISPER_* vars remain</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§7 .env.example — add STT_* commented with rationale; §10 cyber-vocab fine-tune HOOK seam)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§8 — the existing model-tag env block with no-hardcoded-tag rationale to mirror)
    - .env.example (the OLLAMA model-tag block :41-51 — the no-hardcoded-tag comment style to mirror; confirm no WHISPER_* lines exist)
  </read_first>
  <action>
    Edit `.env.example` to document the STT knobs (single-sourced with the Compose default + build
    ARG). Below the Ollama block, add an STT section mirroring the OLLAMA no-hardcoded-tag comment
    style:
    - A comment: the STT model is single-sourced via this env var + the Compose `build.args`/
      `environment` default + the Dockerfile ARG, so the baked weights and the loaded model never
      drift; NO hardcoded tag in agent or server code (the v1.0 invariant).
    - `STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b`
    - A comment for the balanced profile (STT-04): `[56,3]` is the balanced default; `right` controls
      lookahead/latency-vs-accuracy (lower = snappier, higher = more accurate); low-latency vs high-
      accuracy operator profiles are a FUTURE item (STT-F2, not now).
    - `STT_ATT_CONTEXT_SIZE=[56,3]`
    - A cyber-vocab fine-tune HOOK note (CONTEXT / STT-04 / RESEARCH §10): a future fine-tuned `.nemo`
      can be swapped in with ZERO code change by pointing `STT_MODEL` at the custom checkpoint and
      rebuilding — no fine-tune code/data ships in this phase.
    Confirm there are NO `WHISPER_*` vars in `.env.example` to remove (none exist today — code
    defaults only); if any are found, remove them. Do NOT add `NEMO_STT_URL` here (that is the
    agent-side env, Wave 2 — it defaults in code to `ws://nemo-stt:8000/v1/audio/stream`).
  </action>
  <acceptance_criteria>
    - `.env.example` documents both STT knobs (`grep -n "STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b\|STT_ATT_CONTEXT_SIZE=\[56,3\]" .env.example`)
    - The no-hardcoded-tag / single-source rationale and the cyber-vocab fine-tune HOOK note are present (`grep -ni "single-source\|no hardcoded\|fine-tune\|hook" .env.example`)
    - No WHISPER_* vars remain (`grep -n "WHISPER_" .env.example` returns nothing)
    - No NEMO_STT_URL added here (`grep -n "NEMO_STT_URL" .env.example` returns nothing — it is Wave 2's code default)
  </acceptance_criteria>
</task>

## Verification

- `python3 -m py_compile stt/server.py` exits 0; the server single-sources `STT_MODEL` (no hardcoded
  tag), sets `att_context_size` from `STT_ATT_CONTEXT_SIZE` (default `[56,3]`) once at load, exposes
  `/health` (503-until-loaded) + `WS /v1/audio/stream` with the frozen `ready`/`delta`/`final`/`error`
  JSON contract, emits FINAL ONLY on a `flush` control frame, recycles RNNT state on stall WITHOUT a
  premature FINAL, surfaces native PnC as-is, serializes GPU access with an `asyncio.Lock`, and keeps
  the model resident (no offload, no language steering).
- `stt/requirements.txt` pins fastapi/uvicorn[standard]/numpy/soundfile (and `nemo_toolkit[asr]` not
  `[all]`), no `:latest`, no aiohttp.
- `stt/Dockerfile` bases on a CUDA-12.8+ Blackwell image (Kokoro precedent cited), bakes the model via
  an `ARG STT_MODEL` (no hardcoded tag), runtime `ENV STT_MODEL` == bake ARG, EXPOSEs 8000, runs
  uvicorn, and HEALTHCHECKs `/health` with a generous start_period.
- `docker-compose.yml`: whisper deleted; `nemo-stt` added (build ./stt + STT_MODEL arg, env incl.
  STT_ATT_CONTEXT_SIZE `[56,3]`, LAN-bound 8000, GPU reservation verbatim, `/health` healthcheck,
  no env_file, restart unless-stopped, keep-resident); agent `depends_on` gates on
  `nemo-stt: { condition: service_healthy }`; header comment no longer claims a faster-whisper digest
  pin. The default tag literal lives ONLY in compose (single-source).
- `.env.example` documents `STT_MODEL` + `STT_ATT_CONTEXT_SIZE=[56,3]` with the no-hardcoded-tag
  rationale + cyber-vocab fine-tune HOOK; no WHISPER_* remain.
- BUILD-FIRST (operator, before any live gate — baked-image invariant, CONTEXT §Established Patterns):
  `docker compose build nemo-stt && docker compose up -d && docker compose ps` (nemo-stt healthy).
- OPERATOR GATE (GPU — deferred; authored in Wave 2's `09-STT-VERIFY.md`): model load + the
  `conformer_stream_step` signature confirmation against in-container NeMo; Blackwell sm_120 kernel
  execution on the RTX 5090; a real clip streams growing deltas and a flush returns a PnC final; the
  stall watchdog recycles on a run-on answer with no premature FINAL; `/health` gates the agent.
- DEFER (do NOT mark passed in this plan): all GPU/Docker operator items; the sandbox has no
  GPU/Docker daemon and cannot import NeMo/torch.

## must_haves

truths:
- STT-01: faster-whisper is REMOVED from the stack (the `whisper:` Compose service is deleted) and a
  `nemo-stt` service serves `nvidia/nemotron-speech-streaming-en-0.6b` via NeMo behind a FastAPI
  websocket on the `adept` LAN-only network — no audio leaves the local network (LAN-bound port, no
  egress).
- STT-01: the model is loaded resident at server startup and kept resident forever (lifespan load +
  no offload), mirroring `WHISPER__TTL=-1` — avoiding the cold-reload first-turn-drop bug.
- STT-04: `att_context_size` is a config knob read from `STT_ATT_CONTEXT_SIZE` (default balanced
  `[56,3]`) and applied once at model load; a cyber-vocab fine-tune HOOK is NOTED (swap `STT_MODEL`
  at a future checkpoint) but NOT implemented.
- The WS contract (`ready`/`delta` growing-cumulative/`final`-on-flush/`error`, `/health` gating) is
  frozen here for the Wave-2 plugin to match; FINAL is emitted ONLY on the agent's `flush` — the
  server never auto-finalizes (the RNNT stall watchdog recycles state and continues, single-turn-
  source invariant preserved).
- Native punctuation + capitalization are surfaced AS-IS server-side (no strip/lowercase) — STT-03
  satisfied for free at the source.
- The model tag is single-sourced: the literal default lives ONLY in `docker-compose.yml`
  build.args/environment; server.py, the Dockerfile body, and .env.example carry it via env/ARG — NO
  hardcoded tag in code.

must_haves.prohibitions:
- NO faster-whisper service, image, or env left in docker-compose.yml or .env.example.
- NO hardcoded `nvidia/nemotron-speech-streaming-en-0.6b` literal in `stt/server.py` or the
  Dockerfile body — single-sourced via `STT_MODEL` env/ARG (the v1.0 no-hardcoded-tag invariant).
- NO mid-utterance / heuristic FINAL from the server — FINAL only on the agent's `flush`; the stall
  watchdog recycles decoder state and does NOT emit FINAL (turn detector owns finalize).
- NO language/prompt steering / multilingual bits (English-only model — drop ALL of the reference
  repo's 3.5 steering).
- NO client-side or server-side PnC post-processing (native cased text passed through as-is).
- NO `nemo_toolkit[all]` (image bloat) — `[asr]` only; NO CPU-ONNX runtime / VRAM-aware placement
  (Phase 10); NO audio written to disk/db (in-memory, local-first).
- NO env_file on the nemo-stt service (M3 — it carries no LiveKit secret).
- NO marking any GPU/Docker OPERATOR-VERIFICATION step passed in this plan.

## Artifacts this plan produces

- `stt/server.py` (new): FastAPI websocket NeMo streaming STT server. Symbols: FastAPI `app` (with
  lifespan model load), `load_model()`, `new_stream_state()`, `decode_chunk(state, pcm) -> str`,
  `finalize(state) -> str`, `ws_stream(websocket)` (the `WS /v1/audio/stream` handler), `GET /health`,
  optional `POST /v1/audio/transcriptions`. Reads env `STT_MODEL`, `STT_ATT_CONTEXT_SIZE`,
  `STT_STALL_FRAMES`, `STT_RECYCLE_MIN_CHARS`, `STT_RECYCLE_HARD_CHARS`.
- `stt/Dockerfile` (new): CUDA-12.8+ Blackwell base, pinned deps, `ARG STT_MODEL` model bake,
  `ENV STT_MODEL`, EXPOSE 8000, uvicorn CMD, `/health` HEALTHCHECK.
- `stt/requirements.txt` (new): pinned fastapi, uvicorn[standard], numpy, soundfile (+ optional
  nemo_toolkit[asr]).
- `docker-compose.yml` (modified): `whisper:` service DELETED; `nemo-stt:` service ADDED (build
  ./stt + STT_MODEL arg, STT_MODEL/STT_ATT_CONTEXT_SIZE env, LAN-bound 8000, GPU reservation,
  `/health` healthcheck, keep-resident, no env_file); agent `depends_on` → `nemo-stt: { condition:
  service_healthy }`; header comment fixed.
- `.env.example` (modified): `STT_MODEL=nvidia/nemotron-speech-streaming-en-0.6b` +
  `STT_ATT_CONTEXT_SIZE=[56,3]` documented with no-hardcoded-tag rationale + cyber-vocab fine-tune
  HOOK note.
- WS contract introduced (frozen for Wave 2): `WS /v1/audio/stream` with client `config`/`flush`/
  `reset` + binary int16 PCM; server `ready`/`delta`/`final`/`error`. New Compose service: `nemo-stt`.
  New env vars: `STT_MODEL`, `STT_ATT_CONTEXT_SIZE` (+ server-only `STT_STALL_FRAMES`,
  `STT_RECYCLE_MIN_CHARS`, `STT_RECYCLE_HARD_CHARS`).
</content>
</invoke>
