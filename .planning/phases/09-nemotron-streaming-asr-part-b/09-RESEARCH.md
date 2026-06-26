# Phase 09 — Nemotron Streaming ASR (Part B): Implementation Research

**Question answered:** *What do I need to know to PLAN this phase well?*
**Scope:** Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b`, served by a
NeMo cache-aware decode loop behind a FastAPI websocket server (`nemo-stt` Compose service),
wired into the LiveKit agent as a **custom streaming STT plugin** (`NemoSTT`) — NOT an
OpenAI-compat shim.

This doc researches **HOW** to implement the locked decisions in `09-CONTEXT.md`. It does not
relitigate them. Every API below is version-pinned to what the repo actually runs
(`livekit-agents` 1.6.4, NeMo 25.11).

---

## 0. Source-of-truth references (all fetched/verified this phase)

| Reference | What it gives us | Trust |
|---|---|---|
| `nvidia/nemotron-speech-streaming-en-0.6b` HF model card | NeMo API, att_context_size, 16kHz mono, native PnC, NeMo 25.11 req | Canonical (vendor) |
| LiveKit blog *"…teleprompter"* + repo **ShayneP/local-teleprompter** | FastAPI NeMo server + `LocalNemotronSTT`/`SpeechStream` plugin blueprint | Canonical (LiveKit-published) |
| `livekit-agents@1.6.4` `stt/stt.py` (555 ln, fetched to `/tmp/lk-stt/stt.py`) | Exact `STT`/`RecognizeStream`/`SpeechEvent`/`SpeechData`/`RecognitionUsage` contract | Pinned source |
| `livekit-agents@1.6.4` `metrics/base.py` | `STTMetrics` dataclass fields | Pinned source |
| Repo files (`agent/main.py`, `metrics.py`, `docker-compose.yml`, `web/app/Transcript.tsx`) | Removal targets + native-transcription validation | Repo HEAD |

> **Note on the reference repo:** it targets the **multilingual 3.5** model and includes
> `set_inference_prompt`/language-steering. Our model is **English-only `…-en-0.6b`** → drop ALL
> language/prompt steering. Adapt the *structure*, not the multilingual bits.

---

## 1. The model & NeMo decode loop (server-side)

**Model:** `nvidia/nemotron-speech-streaming-en-0.6b` — Cache-Aware Streaming FastConformer-RNNT,
~600M params, English. **Native punctuation + capitalization built into the model output** — no
separate PnC pass (CONTEXT: pass PnC as-is to transcript AND LLM, zero post-processing → satisfied
for free). License: NVIDIA Open Model License (commercial OK, local-first OK).

**Hard input contract:** **16 kHz, mono, int16 PCM.** (Reference: `SAMPLE_RATE=16000`,
`NUM_CHANNELS=1`.) LiveKit delivers 48 kHz frames — handled by the plugin (see §3), not the server.

**`att_context_size = [left, right]`** in 80 ms encoder frames. `right` controls
lookahead/latency-vs-accuracy. Locked default **`[56, 3]`** (env-knob `STT_ATT_CONTEXT_SIZE`).
`right=0` snappiest, `right=13` most accurate. Set ONCE at load.

**Decode loop (cache-aware streaming), server-side, version-correct NeMo 25.11:**

```python
import nemo.collections.asr as nemo_asr
import torch, json, ast

MODEL_NAME = os.environ["STT_MODEL"]            # single-source; no hardcoded tag
ATT = ast.literal_eval(os.environ.get("STT_ATT_CONTEXT_SIZE", "[56,3]"))

model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)   # baked into image (§6)
model.eval()
model.encoder.set_default_att_context_size(ATT)               # locked knob
# RNNT decode strategy: greedy, single-step streaming (lowest latency)
model.change_decoding_strategy(decoding_cfg=...)              # greedy_batch, preserve_alignments off

# Per connection: fresh streaming state
cache_last_channel, cache_last_time, cache_last_channel_len = model.encoder.get_initial_cache_state(
    batch_size=1
)
prev_hyps = None
# Per audio chunk (a fixed window of int16→float32 samples):
with torch.inference_mode():
    (text, cache_last_channel, cache_last_time, cache_last_channel_len, prev_hyps) = \
        model.conformer_stream_step(
            processed_signal=feats, processed_signal_length=feat_len,
            cache_last_channel=cache_last_channel,
            cache_last_time=cache_last_time,
            cache_last_channel_len=cache_last_channel_len,
            keep_all_outputs=True,
            previous_hypotheses=prev_hyps,
            return_transcription=True,
        )
growing_text = prev_hyps[0].text   # CUMULATIVE — re-emit whole string as INTERIM
```

> ⚠️ Exact `conformer_stream_step` signature/feature-extraction varies slightly across NeMo
> minor versions. **Operator/build step must pin the NeMo version and confirm the call against the
> in-container `nemo.collections.asr` source** (see §10 — sandbox cannot import NeMo). The
> reference `stt-server/server.py` is the working template; copy its preprocessing
> (`AudioToMelSpectrogramPreprocessor` via `model.preprocessor`) verbatim and only swap the model
> name + drop language steering.

**RNNT decoder-stall watchdog (CONTEXT requirement; PITFALL B2).** RNNT can stall after a sentence
boundary on long run-on speech (cumulative text stops growing while audio still flows). The
reference server mitigates with char-threshold *state recycling* (`STT_RECYCLE_MIN_CHARS`,
`STT_RECYCLE_HARD_CHARS`). **For Adept, the turn detector owns finalize (§4), so we do NOT want the
server emitting mid-utterance finals.** Implement the watchdog as: server tracks "frames since text
last grew"; if it exceeds `STT_STALL_FRAMES` *while audio is still arriving*, recycle decoder state
(reset `prev_hyps`, carry forward encoder cache) and continue — log it, do NOT emit FINAL. Keep
`STT_RECYCLE_*` envs but set conservative defaults so recycling is stall-recovery only.

---

## 2. FastAPI websocket server (`stt/server.py`)

Mirror the reference `stt-server/server.py`. Endpoints:

| Endpoint | Purpose |
|---|---|
| `WS /v1/audio/stream` | **Primary.** Client opens, sends `{"type":"config", ...}`, then raw int16 PCM binary frames; server streams JSON deltas back. Control msgs: `{"type":"flush"}` (drain + emit FINAL), `{"type":"reset"}`. |
| `GET /health` | Liveness for Compose healthcheck (returns 200 only after model loaded). |
| `GET /v1/models` | Optional, parity. |
| `POST /v1/audio/transcriptions` | OpenAI-compat whole-file — **optional**, useful for `09-STT-VERIFY.md` offline WER/latency checks without the agent. |

**WS message shapes (server→client):**
```json
{"type":"ready"}                       // sent after config accepted
{"type":"delta","text":"<cumulative>"} // growing interim
{"type":"final","text":"<final>"}      // only in response to {"type":"flush"}
{"type":"error","message":"..."}
```

**Concurrency rule (latency-first, AGENTS.md):** the NeMo model + CUDA stream is single-GPU; run
the blocking `conformer_stream_step` in a worker thread (`asyncio.to_thread` / a single-worker
executor) per connection, and **serialize GPU access** (one decode at a time) — Adept is
single-user so one active stream is the norm; guard with an `asyncio.Lock` to avoid CUDA races if a
turn overlaps reconnect.

**Keep-resident:** load the model at process startup (module scope / lifespan startup), never
offload (mirror whisper `TTL=-1` intent). `/health` returns unhealthy until load completes so
Compose `depends_on: service_healthy` gates the agent.

**Server deps:** `fastapi`, `uvicorn[standard]`, `numpy`, `soundfile`, `torch`,
`nemo_toolkit[asr]` (**NOT `[all]`** — PITFALL B1 image bloat).

**≤40 lines / ≤3 params / ≤3 nesting (AGENTS.md):** split into small functions —
`load_model()`, `new_stream_state()`, `decode_chunk(state, pcm) -> str`, `ws_stream(websocket)`,
`finalize(state) -> str`. The decode loop body stays under the nesting cap by early-`continue` on
control frames.

---

## 3. The LiveKit custom STT plugin (`agent/nemo_stt.py`)

**Verified contract from `livekit-agents@1.6.4` `stt/stt.py`:**

- `class STT(ABC, EventEmitter[...])` — construct with
  `STTCapabilities(streaming=True, interim_results=True)`.
- Must implement `stream(...) -> RecognizeStream` (the streaming entrypoint the AgentSession
  calls). `RecognizeStream` is the streaming class (aka "SpeechStream").
- `_recognize_impl(...)` is abstract → provide a stub that raises `NotImplementedError`
  (`offline_recognize` unused; the AgentSession uses `stream()`).
- **`SpeechEvent`** (dataclass, ln 112): `type: SpeechEventType`, `request_id: str`,
  `alternatives: list[SpeechData]`, `recognition_usage: RecognitionUsage | None`,
  `speech_start_time`.
- **`SpeechData`**: `text`, `language`, plus `start_time/end_time/confidence` (optional → leave 0).
- **`SpeechEventType`**: `INTERIM_TRANSCRIPT`, `FINAL_TRANSCRIPT`, `RECOGNITION_USAGE`,
  `START_OF_SPEECH`, `END_OF_SPEECH`.
- **`RecognitionUsage`**: `audio_duration: float`, `input_tokens=0`, `output_tokens=0`.
- `RecognizeStream.push_frame(frame)` **auto-resamples** to the `sample_rate` passed to
  `super().__init__(...)` (ln ~473–480 build an `rtc.AudioResampler` when the input SR differs).
  → **Pass `sample_rate=16000`** and LiveKit's 48 kHz frames are downsampled for us. Mono enforced
  by the resampler config.
- Input is consumed from `self._input_ch` (yields `rtc.AudioFrame` or a `_FlushSentinel`).
- Output events are pushed to `self._event_ch.send_nowait(SpeechEvent(...))`.
- `flush()` / `end_input()` enqueue the flush sentinel (this is what the AgentSession calls at
  end-of-turn).

**Skeleton (English-only, websocket transport, structure adapted from `local_stt.py`):**

```python
# agent/nemo_stt.py
from livekit.agents import stt, utils, APIConnectOptions
from livekit.agents.metrics import STTMetrics
from livekit import rtc
import aiohttp, asyncio, json, time

class NemoSTT(stt.STT):
    def __init__(self, *, ws_url: str, language: str = "en"):
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=True))
        self._ws_url, self._language = ws_url, language

    @property
    def model(self) -> str: return "nemotron-speech-streaming-en-0.6b"
    @property
    def provider(self) -> str: return "nemo"

    async def _recognize_impl(self, *a, **k):
        raise NotImplementedError("NemoSTT is streaming-only")

    def stream(self, *, language=None, conn_options=...) -> "NemoSpeechStream":
        return NemoSpeechStream(stt=self, ws_url=self._ws_url, language=self._language,
                                conn_options=conn_options)


class NemoSpeechStream(stt.RecognizeStream):
    def __init__(self, *, stt, ws_url, language, conn_options):
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16000)  # auto-resample
        self._ws_url, self._language = ws_url, language

    async def _run(self) -> None:
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(self._ws_url) as ws:
                await ws.send_json({"type": "config", "language": self._language})
                recv = asyncio.create_task(self._recv_loop(ws))
                t0 = time.perf_counter()
                async for data in self._input_ch:
                    if isinstance(data, self._FlushSentinel):
                        await ws.send_json({"type": "flush"}); continue
                    await ws.send_bytes(data.data.tobytes())   # int16 PCM, already 16k mono
                await recv

    async def _recv_loop(self, ws) -> None:
        last_final_started = time.perf_counter()
        async for msg in ws:
            evt = json.loads(msg.data)
            if evt["type"] == "delta":
                self._event_ch.send_nowait(stt.SpeechEvent(
                    type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                    alternatives=[stt.SpeechData(language=self._language, text=evt["text"])]))
            elif evt["type"] == "final":
                self._emit_final(evt["text"], dur=time.perf_counter() - last_final_started)
                last_final_started = time.perf_counter()
```

`_emit_final` emits the FINAL event **and** the metrics event (see §5). Keep each method ≤40 lines /
≤3 nesting (AGENTS.md) — the `_run`/`_recv_loop` split above already satisfies this.

**Wiring (`agent/main.py`, replacing `openai.STT`):**
```python
from nemo_stt import NemoSTT
NEMO_STT_URL = os.environ.get("NEMO_STT_URL", "ws://nemo-stt:8000/v1/audio/stream")
...
stt=NemoSTT(ws_url=NEMO_STT_URL, language="en"),
```

---

## 4. Endpoint authority (Silero VAD + turn detector) — UNCHANGED

CONTEXT lock: **Silero VAD + local `MultilingualModel` turn detector remain the sole endpoint
authority**; STT FINAL is triggered off that (~100 ms finalize). This is satisfied *by the LiveKit
AgentSession contract*, no special code:

- The AgentSession streams audio frames into `NemoSpeechStream.push_frame` continuously and emits
  `INTERIM_TRANSCRIPT` as the user speaks.
- When the **turn detector** decides end-of-utterance, the AgentSession calls `end_input()`/`flush()`
  on the STT stream → our `_run` forwards `{"type":"flush"}` → server drains its buffer and replies
  `{"type":"final"}` → we emit `FINAL_TRANSCRIPT`. Target ~100 ms server drain.
- **Server must NOT auto-emit FINAL on its own heuristics** (char recycle is stall-recovery only,
  §1). This preserves the single-turn-source invariant the rest of the pipeline assumes.

No changes needed to VAD/turn-detector config in `build_session` — that block stays as-is.

---

## 5. Metrics — the one non-obvious gotcha (must get right)

`agent/metrics.py` is **READ-ONLY** this phase. `_on_stt_metrics` (ln 258) does:
```python
buffer.stt_ms = _seconds_to_ms(getattr(metric, "duration", None))
```
i.e. it reads `STTMetrics.duration` (seconds) off the per-plugin `metrics_collected` event.

**Verified from `stt/stt.py` source:** the streaming path does **NOT** auto-emit a timed
`STTMetrics`. Only the *non-streaming* `recognize()` (ln 197–224) measures `duration` and emits.
For streaming, `STTMetrics` is emitted **only** when the plugin pushes a `RECOGNITION_USAGE`
`SpeechEvent`, and even then the base monitor **hardcodes `duration=0.0`** (streamed=True). The
reference `LocalNemotronSTT` emits **no STT metrics at all**.

➡️ Consequence: a naive port leaves **`stt_ms` NULL forever** (faster-whisper worked because
`openai.STT` is non-streaming and emitted a real `duration`). To keep the `09-STT-VERIFY.md`
latency gate measurable, **`NemoSTT` must explicitly emit a `STTMetrics` with a real measured
`duration`** on each FINAL:

```python
def _emit_final(self, text: str, dur: float) -> None:
    self._event_ch.send_nowait(stt.SpeechEvent(
        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        alternatives=[stt.SpeechData(language=self._language, text=text)]))
    self._stt.emit("metrics_collected", STTMetrics(
        request_id="", timestamp=time.time(), duration=dur,   # measured finalize seconds
        label=self._stt.label, audio_duration=0.0, streamed=True))
```
`STTMetrics` required fields (verified `metrics/base.py`): `label, request_id, timestamp,
duration, audio_duration, streamed` (+ optional token/acquire fields).
`metrics.py` keys STT to the most-recently-touched buffer (no `speech_id` on `STTMetrics` — already
handled, ln 261–265), so no buffer-keying work is required.

> `duration` here means **finalize latency** (flush→final). If we want full transcription latency
> instead, measure from first audio frame of the turn. **PLAN must pick one definition and state it
> in `09-STT-VERIFY.md`** so the P50<1.0s gate is unambiguous. Recommend: finalize latency
> (matches the ~100 ms target) for the per-stage `stt` budget (currently 150 ms in `BUDGET_MS`).

---

## 6. Docker / Compose (`stt/` dir + `nemo-stt` service)

**New `stt/Dockerfile`** — baked, multi-stage, model pre-fetched into the image (PITFALL B1):

- Base on a **Blackwell-capable** image. Two viable bases (operator picks/verifies on real GPU):
  - `nvcr.io/nvidia/nemo:25.11` (NeMo + sm_120-capable torch preinstalled), **or**
  - `nvcr.io/nvidia/pytorch:25.11-py3` + `pip install nemo_toolkit[asr]`.
  - **Why this matters:** the Kokoro service comment in `docker-compose.yml` already documents that
    Blackwell (RTX 50-series, sm_120) needs CUDA-12.8+ builds or it crashes with *"no kernel image
    is available."* NeMo's stock pip torch may not include sm_120 → **operator GPU gate**.
- `pip install fastapi uvicorn[standard] aiohttp soundfile numpy` (+ nemo if not in base).
- **Bake the model:** a build step runs
  `python -c "import nemo.collections.asr as a; a.models.ASRModel.from_pretrained('${STT_MODEL}')"`
  so the `.nemo` (~2.4 GB) is in the image (no first-run download; offline/local-first). Pass
  `STT_MODEL` as a build ARG so there's **no hardcoded tag** (AGENTS.md single-source).
- `HEALTHCHECK` hitting `/health` with a **generous `start_period`** (model load is slow).

**Compose service `nemo-stt`** — mirror whisper exactly (lines 95–119):
```yaml
  nemo-stt:
    build:
      context: ./stt
      args:
        STT_MODEL: ${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
    # No env_file (M3): STT takes model/params via build-ARG + per-request; no LiveKit secret.
    environment:
      - STT_MODEL=${STT_MODEL:-nvidia/nemotron-speech-streaming-en-0.6b}
      - STT_ATT_CONTEXT_SIZE=${STT_ATT_CONTEXT_SIZE:-[56,3]}
    ports:
      - "${LAN_BIND_IP:-127.0.0.1}:8000:8000"
    networks: [adept]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      start_period: 180s
      interval: 10s
      timeout: 5s
      retries: 30
    restart: unless-stopped
```
**Agent gating:** add `depends_on: { nemo-stt: { condition: service_healthy } }` (replace the
whisper depends_on). Keeps the agent from starting before the model is resident.

> Port 8000 is freed by removing whisper; reusing it keeps `LAN_BIND_IP` patterns identical. Pick a
> distinct port if the plan wants whisper/nemo to coexist during migration — but CONTEXT deletes
> whisper, so reuse is clean.

---

## 7. Exact files to CREATE / MODIFY / DELETE

### CREATE
| File | Purpose |
|---|---|
| `stt/server.py` | FastAPI WS server running the NeMo cache-aware decode loop (§1–§2). |
| `stt/Dockerfile` | Baked, multi-stage, model pre-fetched, Blackwell base (§6). |
| `stt/requirements.txt` | `fastapi`, `uvicorn[standard]`, `aiohttp`, `numpy`, `soundfile` (+ `nemo_toolkit[asr]` if base lacks it). |
| `agent/nemo_stt.py` | `NemoSTT` + `NemoSpeechStream` custom streaming plugin (§3, §5). |
| `.planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md` | Operator GPU-gate runbook (P50<1.0s, WER spot-check) — per CONTEXT. |

### MODIFY
| File | Change |
|---|---|
| `agent/main.py` | Delete `WHISPER_BASE_URL` (ln 51), `WHISPER_MODEL` (ln 58) + comment, `WHISPER_PARAMS` (ln 66–73). Replace `stt=openai.STT(...)` (ln 210–215) with `stt=NemoSTT(ws_url=NEMO_STT_URL, language="en")`; add `NEMO_STT_URL` env + `from nemo_stt import NemoSTT`. Update module docstring ln 4 ("faster-whisper STT" → "Nemotron streaming STT"). |
| `agent/requirements.txt` | Add `aiohttp` (WS client). `livekit-plugins-openai` still needed for LLM+TTS — keep. |
| `docker-compose.yml` | Delete `whisper:` service (ln 95–119) + comment ln 9. Add `nemo-stt:` (§6). Agent `depends_on` is currently a **short-form list** (ln 42–46: livekit-server/ollama/whisper/kokoro) — to gate on `service_healthy` convert the whole block to long-form (`<svc>: {condition: service_healthy}`) and swap `whisper`→`nemo-stt`; or keep short-form `- nemo-stt` if healthcheck-gating is deferred. |
| `ollama/warmup.py` | Remove `warm_whisper` + WHISPER_* refs (ln ~45–47, 65, 118). STT warmup now = NeMo model resident at container start (no host warmer needed) OR add a tiny WS warmup ping if the verify runbook wants a measured cold→warm number. |
| `.env.example` | Add `STT_MODEL=` + `STT_ATT_CONTEXT_SIZE=[56,3]` (commented, with the "no hardcoded tag" rationale). (No WHISPER_* vars exist in `.env.example` today — only code defaults — so nothing to remove here.) |
| `README.md` | STT section (ln ~35): faster-whisper → Nemotron streaming; service name/port; build-time model bake note. |
| `scripts/vram-validate.sh` | Confirmed whisper refs: ln 8, 13 (comments), `WHISPER_BASE_URL` ln 43, assert-message ln 162–163. Swap whisper→nemo-stt naming + the `WHISPER_BASE_URL` (port 8000) to `NEMO_STT_*`; still **3** GPU procs (ollama, nemo-stt, kokoro) so `EXPECTED_GPU_PROCS` is unchanged. |

### DELETE
| File/dir | Reason |
|---|---|
| `whisper:` Compose service block | Replaced by `nemo-stt`. |
| Any `whisper/` build context dir, if present | **Check** — whisper used a pinned upstream image (no local dir), so likely nothing to delete. Confirm with a glob before assuming. |

### NO CHANGE (validated)
- `web/app/Transcript.tsx` — uses `useTranscriptions()` from `@livekit/components-react`. Interim+
  final flow arrives automatically via LiveKit **native transcription** as long as `NemoSTT` emits
  proper `INTERIM_TRANSCRIPT`/`FINAL_TRANSCRIPT` events into the AgentSession (CONTEXT: reuse
  native transcription event stream). **Zero client changes.**
- `agent/metrics.py` — READ-ONLY; works as-is **iff** §5 metric emission is implemented.

---

## 8. Verify-able-in-sandbox vs operator-GPU-gate

| Item | Where |
|---|---|
| `NemoSTT`/`NemoSpeechStream` import + instantiate; capabilities; event/metric shapes against `livekit-agents` 1.6.4 | **Sandbox** (pip install livekit-agents, no GPU) — unit-test the plugin with a fake WS server. |
| `agent/main.py` wiring compiles; `metrics.py` `stt_ms` populates from a synthetic `STTMetrics` | **Sandbox** (run `metrics.py` `_self_check` / inject a fake metric). |
| FastAPI server routes/JSON contract (mock the model) | **Sandbox** — stub `decode_chunk` to echo, test WS framing/flush. |
| Compose YAML validity (`docker compose config`) | **Sandbox** if a compose binary is available *without* daemon; else operator. |
| NeMo model load + `conformer_stream_step` real decode | **Operator GPU gate** (no NeMo/CUDA in sandbox). |
| Blackwell sm_120 kernel execution (image actually runs on RTX 5090) | **Operator GPU gate.** |
| Image build (~multi-GB, ~10 min) + model bake | **Operator** (no Docker daemon in sandbox). |
| P50 < 1.0 s latency + WER spot-check (`09-STT-VERIFY.md`) | **Operator GPU gate.** |

---

## 9. Risks / open items the PLAN must address

1. **`conformer_stream_step` signature drift** across NeMo minors → pin NeMo version in the image
   and validate the call against in-container source; the reference server is the template. (Build-
   time / operator.)
2. **Blackwell torch** — confirm chosen base image ships sm_120 kernels (Kokoro precedent shows
   stock images crash otherwise). Operator GPU gate.
3. **`duration` semantics for `stt_ms`** — pick finalize-latency vs full-transcription and document
   it in `09-STT-VERIFY.md` so the gate is unambiguous (§5).
4. **GPU contention** — 3 resident GPU processes (ollama, nemo-stt, kokoro). VRAM budget must fit
   the +2.4 GB model + activations on the target card; re-run `vram-validate.sh`. Operator.
5. **Flush→final timing** — server drain must hit ~100 ms; the RNNT stall-recovery recycle must not
   leak a premature FINAL. Covered by §1/§4 design; verify on GPU.
6. **Reconnect/overlap** — single GPU stream + `asyncio.Lock`; ensure a turn that overlaps a WS
   reconnect doesn't double-decode. Sandbox-testable with the mock server.

---

## 10. Cyber-vocab fine-tune (NOTED HOOK only — not built this phase)

CONTEXT marks this a hook. Leave a clear seam: `STT_MODEL` env-ARG already lets a future
fine-tuned `.nemo` be swapped in with zero code change (single-source tag). No fine-tune code,
data, or scripts in Phase 9. Document the seam in `09-STT-VERIFY.md` / README so Phase-N can point
`STT_MODEL` at a custom checkpoint and rebuild.

---

## RESEARCH COMPLETE
