# Phase 09 — Nemotron Streaming ASR (Part B): Pattern Mapping

**Purpose:** Map every new/modified/deleted file in Phase 9 to its closest existing
analog in the repo, with real code excerpts + line references. This is the
"copy-from-here" index for the PLAN — each new file says *which* existing file is
its template and *which* lines to clone vs. drop.

**Sources:** `09-CONTEXT.md` (decisions), `09-RESEARCH.md` §7 (file inventory),
repo HEAD (`agent/main.py`, `agent/metrics.py`, `docker-compose.yml`,
`web/app/Transcript.tsx`, `ollama/warmup.py`, `scripts/vram-validate.sh`,
`.env.example`).

**Confirmed by glob:** no `stt/` dir and no `whisper/` build-context dir exist
today (whisper is a pinned upstream image, not a local build). So the `stt/`
directory is wholly new, and the DELETE work is Compose/code references only —
nothing on disk to `rm`.

---

## File inventory (role + data-flow classification)

| File | Verb | Role | Data flow | Closest analog |
|---|---|---|---|---|
| `stt/server.py` | CREATE | GPU model server (FastAPI WS) | audio frames in → INTERIM/FINAL JSON out | `docker-compose.yml` whisper service contract + (no in-repo FastAPI analog — reference `stt-server/server.py`) |
| `stt/Dockerfile` | CREATE | Baked GPU image | build-time model bake | `agent/Dockerfile` (uv venv + bake-weights pattern) |
| `stt/requirements.txt` | CREATE | Server deps | n/a | `agent/requirements.txt` (pinning posture) |
| `agent/nemo_stt.py` | CREATE | LiveKit STT plugin | AgentSession frames → WS → SpeechEvents | `agent/main.py` `build_session()` `stt=openai.STT(...)` (the wiring it replaces) + `agent/metrics.py` `_on_stt_metrics` (the STTMetrics contract it must feed) |
| `09-STT-VERIFY.md` | CREATE | Operator GPU-gate runbook | n/a | existing `*-VERIFY.md` runbooks (referenced by CONTEXT) |
| `agent/main.py` | MODIFY | Agent wiring + config | swap STT plugin | self (lines 51–73, 210–215) |
| `agent/requirements.txt` | MODIFY | Agent deps | add `aiohttp` | self |
| `docker-compose.yml` | MODIFY | Stack topology | replace whisper→nemo-stt | self (whisper block 95–119) |
| `ollama/warmup.py` | MODIFY | Host warmer | drop whisper warm | self (`warm_whisper` 118–127) |
| `.env.example` | MODIFY | Env template | add `STT_*` | self |
| `README.md` | MODIFY | Docs | STT section | self |
| `scripts/vram-validate.sh` | MODIFY | VRAM proof | whisper→nemo naming | self (43, 158–164) |
| whisper Compose block | DELETE | — | — | `docker-compose.yml` 95–119 |
| `web/app/Transcript.tsx` | NO CHANGE (interim styling optional) | transcript UI | native transcription in | self |
| `agent/metrics.py` | NO CHANGE (READ-ONLY) | metrics scaffold | STTMetrics in | self |

---

## 1. CREATE `agent/nemo_stt.py` — `NemoSTT` + `NemoSpeechStream`

### Analog A — the wiring site it replaces: `agent/main.py:210-215`

This is the EXACT call being swapped. The new `NemoSTT(...)` must be a drop-in at
this position inside `build_session()`'s `AgentSession(...)` constructor.

```python
# agent/main.py:208-215 (build_session)
    return AgentSession(
        vad=vad,
        stt=openai.STT(
            base_url=WHISPER_BASE_URL,
            model=WHISPER_MODEL,
            api_key="none",
            language=WHISPER_PARAMS["language"],
        ),
```

**Becomes** (RESEARCH §3 wiring):
```python
        stt=NemoSTT(ws_url=NEMO_STT_URL, language="en"),
```

**Why a custom plugin, not `openai.STT`:** CONTEXT decision — NeMo streaming needs
a true `SpeechStream`, not an OpenAI-compat shim. `openai.STT` is non-streaming
(single POST per utterance); `NemoSTT` subclasses `livekit.agents.stt.STT` and
exposes `stream() -> RecognizeStream`.

### Analog B — the import + endpoint-const pattern: `agent/main.py:26, 49-52`

The plugin import joins the existing plugin imports; `NEMO_STT_URL` mirrors the
`*_BASE_URL` env-with-default constants (note: the new one is a `ws://` URL, not
`http://.../v1`).

```python
# agent/main.py:26
from livekit.plugins import openai, silero
# agent/main.py:49-52
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://ollama:11434/api/generate")
WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://whisper:8000/v1")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://kokoro:8880/v1")
```

**Add** (mirrors the env-with-default form):
```python
from nemo_stt import NemoSTT
NEMO_STT_URL = os.environ.get("NEMO_STT_URL", "ws://nemo-stt:8000/v1/audio/stream")
```
**Delete** `WHISPER_BASE_URL` (51), `WHISPER_MODEL` (58) + its comment (54–57),
`WHISPER_PARAMS` (66–73).

### Analog C — the metrics contract it MUST feed: `agent/metrics.py:258-265`

This is the single most important analog and the non-obvious gotcha (RESEARCH §5).
`metrics.py` is READ-ONLY this phase; it reads `STTMetrics.duration`:

```python
# agent/metrics.py:258-265
def _on_stt_metrics(metric: Any) -> None:
    """Per-plugin STT handler: buffer transcription duration on the active turn.

    STTMetrics has no speech_id, so attach to the most-recently-touched buffer.
    """
    buffer = _turns.get(_last_turn_key)
    if buffer is not None:
        buffer.stt_ms = _seconds_to_ms(getattr(metric, "duration", None))
```

`openai.STT` (non-streaming) auto-emits a real `duration`; a streaming plugin does
NOT (base monitor hardcodes `duration=0.0` for streamed=True). **Consequence:**
`stt_ms` stays NULL forever unless `NemoSpeechStream` explicitly emits a
`STTMetrics` with a measured `duration` on each FINAL. The subscription that will
receive it is set up in `attach()`:

```python
# agent/metrics.py:327-335
    handlers = {
        "llm": _on_llm_metrics,
        "stt": _on_stt_metrics,
        "tts": _on_tts_metrics,
    }
    for plugin_name, handler in handlers.items():
        plugin = getattr(session, plugin_name, None)
        if plugin is not None:
            plugin.on("metrics_collected", handler)
```

So `NemoSTT` must `self.emit("metrics_collected", STTMetrics(... duration=dur ...))`
(RESEARCH §5 skeleton) — `session.stt` IS the `NemoSTT` instance, so the existing
`plugin.on("metrics_collected", _on_stt_metrics)` binds to it unchanged.

### Analog D — keep-each-method-small house style: `agent/main.py:172-201`

`_warmup_llm_ttft_ms` is the in-repo example of the AGENTS.md ≤40-line / small-
function discipline RESEARCH §3 calls for in the `_run`/`_recv_loop`/`_emit_final`
split. Mirror its docstring-first, single-responsibility shape.

---

## 2. CREATE `stt/server.py` — FastAPI websocket NeMo decode server

**No in-repo FastAPI/websocket analog exists** — the model servers (whisper,
kokoro, ollama) are all pinned upstream images. The structural template is the
external reference `stt-server/server.py` (RESEARCH §1–§2). The in-repo analogs
constrain the *contract*, not the code:

### Analog A — the service contract it must satisfy: `docker-compose.yml:95-119`

The server's runtime shape (port 8000, `/health` for the healthcheck, keep-
resident, no secrets) is dictated by the whisper service it replaces:

```yaml
# docker-compose.yml:95-119
  whisper:
    image: fedirz/faster-whisper-server@sha256:0b64050...
    # No env_file (M3): the STT server takes its model/params per request ...
    environment:
      - WHISPER__MODEL=Systran/faster-whisper-large-v3
      - WHISPER__TTL=-1          # keep-resident — mirror with module-scope model load
    ports:
      - "${LAN_BIND_IP:-127.0.0.1}:8000:8000"
    networks:
      - adept
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped
```

Maps to server requirements:
- `WHISPER__TTL=-1` keep-resident → load model at module/lifespan startup, never
  offload (RESEARCH §2 "Keep-resident").
- port 8000 → `uvicorn` binds 8000; reused after whisper is removed.
- `/health` → must return 200 only after model load completes, so Compose
  `depends_on: service_healthy` gates the agent.

### Analog B — the warm/decode HTTP-client idioms: `ollama/warmup.py:64-127`

`warm_whisper` (118–127) shows the existing 16 kHz / mono / int16 audio
conventions the server's input contract matches (`SILENT_WAV_RATE = 16000`,
`setnchannels(1)`, `setsampwidth(2)`):

```python
# ollama/warmup.py:64-76 — 16kHz mono int16 audio, the server's input contract
def _sine_wav_bytes() -> bytes:
    """A short mono sine WAV — a non-silent clip whisper can transcribe."""
    frame_count = int(SILENT_WAV_RATE * SILENT_WAV_SECONDS)   # 16000
    ...
        wav.setnchannels(1)
        wav.setsampwidth(2)            # int16
        wav.setframerate(SILENT_WAV_RATE)
```

The optional `POST /v1/audio/transcriptions` whole-file endpoint (RESEARCH §2)
should mirror `warm_whisper`'s `files=`/`data=` form so `09-STT-VERIFY.md` offline
checks reuse this exact request shape.

### Analog C — single-source-the-model-tag (no hardcoded tag): `agent/main.py:127-132`

```python
# agent/main.py:127-132
def resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (no hardcoded gemma tag)."""
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise SystemExit("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag
```

`stt/server.py` reads `STT_MODEL` (env, single-sourced with the build ARG +
Compose env) the same way — `MODEL_NAME = os.environ["STT_MODEL"]` (RESEARCH §1).
`STT_ATT_CONTEXT_SIZE` parsed via `ast.literal_eval` of the `[56,3]` default.

---

## 3. CREATE `stt/Dockerfile` — baked GPU image, model pre-fetched

### Analog — `agent/Dockerfile` (the bake-weights-at-build pattern)

`agent/Dockerfile` is the in-repo template for "install pinned deps + bake model
artifacts into the image so the container starts offline-capable":

```dockerfile
# agent/Dockerfile:18-23
COPY requirements.txt ./
RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python -r requirements.txt

# Pre-fetch VAD + turn-detector weights into the image (offline-capable).
RUN python -m livekit.agents download-files
```

**Differences for `stt/Dockerfile`** (RESEARCH §6):
- Base on a Blackwell-capable NeMo/torch image (`nvcr.io/nvidia/nemo:25.11` or
  `nvcr.io/nvidia/pytorch:25.11-py3`), NOT the uv slim base — the Kokoro precedent
  (`docker-compose.yml:122-125`) documents that stock images crash on sm_120 with
  "no kernel image is available."
- The bake step is the NeMo equivalent of `download-files`:
  `RUN python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"`
  with `STT_MODEL` as a build ARG (no hardcoded tag).
- `HEALTHCHECK` on `/health` with a generous `start_period` (model load is slow).

The Kokoro CUDA-12.8 comment is the precedent to cite for the base-image choice:
```yaml
# docker-compose.yml:122-124
  kokoro:
    # CUDA 12.8 build — required for Blackwell (RTX 50-series, sm_120). The
    # v0.2.4 image bundles PyTorch for sm_50..sm_90 only and crashes at startup ...
```

---

## 4. CREATE `stt/requirements.txt`

### Analog — `agent/requirements.txt` (tight-pin posture)

```python
# agent/requirements.txt:24-26 — the pin discipline to mirror (no :latest, no float)
pymupdf4llm
pymupdf~=1.27
python-docx~=1.1
```

Contents (RESEARCH §2 "Server deps"): `fastapi`, `uvicorn[standard]`, `aiohttp`,
`numpy`, `soundfile` (+ `nemo_toolkit[asr]` **not `[all]`** if not in base image).
Apply the same explicit-pin posture.

---

## 5. MODIFY `docker-compose.yml` — replace whisper with nemo-stt

### Analog — the whisper block (clone its shape, swap the internals)

The new `nemo-stt:` service clones `whisper:` (95–119) exactly: GPU reservation
block verbatim, `${LAN_BIND_IP:-127.0.0.1}:8000:8000`, `networks: [adept]`, no
`env_file` (M3), `restart: unless-stopped`. It ADDS a `build:` (with `STT_MODEL`
ARG), an `environment:` block (`STT_MODEL`, `STT_ATT_CONTEXT_SIZE`), and a
`healthcheck:` (whisper had none). See RESEARCH §6 for the full YAML.

### The two edits beyond the block swap:

**Header comment (line 8-9)** — drop the faster-whisper digest-pin note:
```yaml
# docker-compose.yml:8-9
# except faster-whisper, which is pinned by digest below).
```

**Agent `depends_on` (42-47)** — currently short-form list; swap `whisper`→`nemo-stt`.
To gate on health (recommended, since model load is slow) convert to long-form:
```yaml
# docker-compose.yml:42-47 (current)
    depends_on:
      - livekit-server
      - ollama
      - whisper
      - kokoro
```
→ swap `- whisper` to `- nemo-stt`, or long-form `nemo-stt: { condition: service_healthy }`.

---

## 6. MODIFY `agent/requirements.txt` — add aiohttp

### Analog — the host-client dep note already present:
```python
# agent/requirements.txt:16-17
# Host-side warmup client (ollama/warmup.py logic reused at agent startup).
httpx
```
Add `aiohttp` (WS client for `NemoSpeechStream._run`) with a matching one-line
rationale comment. Keep `livekit-plugins-openai==1.6.4` — still needed for LLM+TTS.

---

## 7. MODIFY `ollama/warmup.py` — drop whisper warm

### Analog (self) — remove `warm_whisper` + WHISPER_* refs:

```python
# ollama/warmup.py:118-127 — DELETE this function
def warm_whisper(client: httpx.Client) -> dict:
    """Transcribe a short sine clip to force the STT weights resident."""
    started = _now_ms()
    files = {"file": ("warmup.wav", _sine_wav_bytes(), "audio/wav")}
    data = {"model": WHISPER_MODEL, "language": "en", "response_format": "json"}
    response = client.post(
        f"{WHISPER_BASE_URL}/v1/audio/transcriptions", files=files, data=data
    )
    response.raise_for_status()
    return {"model": "whisper", "load_ms": round(_now_ms() - started, 1)}
```

Also drop from the `main()` warm-loop:
```python
# ollama/warmup.py:142-145
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for warm in (lambda: warm_llm(client, tag), lambda: warm_whisper(client),
                     lambda: warm_kokoro(client)):
```
and the `WHISPER_BASE_URL`/`WHISPER_MODEL` consts (45, 47). STT warmup is now
"model resident at container start" (no host warmer) per RESEARCH §7; optionally
add a tiny WS warmup ping (`_sine_wav_bytes()` at 64–76 still serves as the 16 kHz
clip source if a measured cold→warm number is wanted).

---

## 8. MODIFY `.env.example` — add STT_* knobs

### Analog (self) — the existing model-tag env block with no-hardcoded-tag rationale:
```bash
# .env.example:41-51
# The two user-selectable response-model tags (Phase 8, LLM-03) ...
OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest
...
OLLAMA_MODEL=evalengine/unbound-e2b:latest
```
Add `STT_MODEL=` + `STT_ATT_CONTEXT_SIZE=[56,3]` (commented) with the same
"no hardcoded tag" rationale and a cyber-vocab fine-tune HOOK note (CONTEXT). No
`WHISPER_*` vars exist in `.env.example` today — nothing to remove here.

---

## 9. MODIFY `scripts/vram-validate.sh` — whisper→nemo naming

### Analog (self) — the whisper references to rename:

```bash
# scripts/vram-validate.sh:43
readonly WHISPER_BASE_URL="${WHISPER_BASE_URL:-http://127.0.0.1:8000}"
```
```bash
# scripts/vram-validate.sh:158-164
assert_three_gpu_procs() {
  local proc_count
  proc_count="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . || true)"
  [ "${proc_count}" -eq "${EXPECTED_GPU_PROCS}" ] \
    || fail "expected ${EXPECTED_GPU_PROCS} GPU processes (ollama, whisper, kokoro), found ${proc_count} ..."
  echo "GPU processes: ${proc_count} (ollama, whisper, kokoro — no embedder/vector store)" >&2
}
```
Swap `WHISPER_BASE_URL`→`NEMO_STT_*`, rename "whisper"→"nemo-stt" in the assert
messages (lines 8, 13 comments too). `EXPECTED_GPU_PROCS=3` (45) is UNCHANGED —
still ollama, nemo-stt, kokoro (RESEARCH §7).

---

## 10. NO CHANGE (validated) — Transcript + metrics

### `web/app/Transcript.tsx` — already consumes native transcription

```tsx
// web/app/Transcript.tsx:15-17
export default function Transcript() {
  const segments = useTranscriptions();
```
`useTranscriptions()` receives interim+final automatically once `NemoSTT` emits
`INTERIM_TRANSCRIPT`/`FINAL_TRANSCRIPT` into the AgentSession. Zero changes
required for function. The CONTEXT "dimmed/italic interim styling, replaced in
place" is the ONLY optional add here — `segment.text` (line 33) is where interim
vs final styling would key off, but native transcription replaces partials in
place by `streamInfo.id` (key at line 25) already.

### `agent/metrics.py` — READ-ONLY, works iff §1 Analog C is implemented

Already covered in §1 Analog C: `_on_stt_metrics` (258–265) reads
`STTMetrics.duration`; `attach()` (327–337) binds it to `session.stt`. No edits —
the plugin must feed it.

---

## Cross-cutting patterns (apply to every new file)

| Pattern | Source line | Applies to |
|---|---|---|
| Keep-resident-forever (`TTL=-1` / `KEEP_ALIVE=-1`) | `docker-compose.yml:67,107` | `stt/server.py` startup model load |
| LAN-bound port `${LAN_BIND_IP:-127.0.0.1}:H:C` | `docker-compose.yml:109` | `nemo-stt` ports |
| No `env_file` on model servers (M3, no LiveKit secret) | `docker-compose.yml:98-99` | `nemo-stt` service |
| No-hardcoded-tag, env-single-source | `agent/main.py:127-132` | `STT_MODEL` everywhere |
| GPU reservation block (verbatim) | `docker-compose.yml:112-118` | `nemo-stt` deploy block |
| Blackwell sm_120 needs CUDA-12.8+ base | `docker-compose.yml:122-124` | `stt/Dockerfile` base image |
| Bake model artifacts at build (offline-capable) | `agent/Dockerfile:22-23` | `stt/Dockerfile` model bake |
| Per-plugin `metrics_collected` for per-turn timing | `agent/metrics.py:327-335` | `NemoSTT` STTMetrics emit |
| Operator-gated `*-VERIFY.md`, unsigned until real GPU | CONTEXT / RESEARCH §8 | `09-STT-VERIFY.md` |
| Rebuild affected services + `up -d` before live verify | CONTEXT "baked images" | agent + nemo-stt + web |
