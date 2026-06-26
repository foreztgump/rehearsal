# Phase 9: Nemotron Streaming ASR (Part B) - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b` served via NeMo behind a local HTTP/websocket server and wired into the LiveKit agent as the STT plugin — delivering a growing interim transcript while the user speaks, ~100ms finalize after end-of-speech, native punctuation/capitalization surfaced as-is, and an `att_context_size` config knob — without regressing voice-to-voice P50 < 1.0s.

Covers requirements STT-01 through STT-04. GPU-NeMo placement ONLY; the GPU-vs-CPU-ONNX placement story (STT-05/06/07) is deferred to Phase 10 (Part C). LLM (Part A) and TTS (Kokoro) legs are untouched. The persona prompt remains unchanged.

</domain>

<decisions>
## Implementation Decisions

### NeMo STT Server Packaging & Contract
- New `stt/` directory + a new `nemo-stt` Compose service, mirroring the established whisper service shape: NVIDIA GPU reservation, LAN-bound port (`${LAN_BIND_IP:-127.0.0.1}:PORT`), no `env_file` (the STT server carries no LiveKit secret), `restart: unless-stopped`
- Server framework: FastAPI + websocket — audio frames stream in, INTERIM + FINAL transcript events stream out; the NeMo cache-aware streaming decode loop runs server-side
- Model load policy: load `nvidia/nemotron-speech-streaming-en-0.6b` resident at server startup and keep it resident forever (mirror `WHISPER__TTL=-1` / `OLLAMA_KEEP_ALIVE=-1` — correct for a single-user local tool; avoids the cold-reload first-turn-drop bug seen with whisper)
- Remove faster-whisper: delete the `whisper` Compose service and the `WHISPER_*` agent code in this phase (STT-01 says faster-whisper is "removed" — no disabled-profile fallback kept). The off-GPU CPU-ONNX runtime arrives in Phase 10, not as a whisper fallback

### LiveKit Agent STT Plugin Integration
- Custom `livekit.agents.stt.STT` subclass (`NemoSTT`) exposing a real streaming `SpeechStream` to the `nemo-stt` service over websocket — NOT an OpenAI-compat shim (whisper used `openai.STT`; NeMo streaming needs a true streaming plugin)
- Streaming protocol: the agent pushes audio frames over the websocket; the server returns INTERIM (growing) and FINAL events
- Decoder-stall watchdog: a stall watchdog forces a finalize if the RNNT decoder stalls on a long run-on (interview-mode) answer, so deliberate pause-heavy answers are not stranded by the documented RNNT decoder stall
- Endpoint coupling: the existing Silero VAD + local `MultilingualModel` turn detector REMAIN the endpoint authority; the STT FINAL is triggered off that semantic end-of-speech (~100ms finalize after end-of-speech). NeMo does NOT own turn-taking — preserves the single-turn-source invariant from v1.0

### Transcript UX (Interim vs Final)
- Growing interim transcript styled distinctly (dimmed/italic) in the EXISTING transcript panel, replaced IN PLACE by the final (no duplicate lines)
- Transport: reuse LiveKit's native transcription event stream (interim + final) that the existing transcript panel already consumes — no new custom data channel
- Native NeMo punctuation + capitalization enabled and passed AS-IS to BOTH the transcript and the LLM — zero client-side post-processing (STT-03)
- Final replaces the interim text in place

### Config Knobs & Latency
- `att_context_size` exposed as an env/config knob, default balanced `[56,3]` (STT-04)
- Cyber-vocabulary fine-tune: documented as a HOOK/NOTE only in config comments/docs — NOT implemented (STT-04 explicit)
- Latency: an operator GPU gate — voice-to-voice P50 < 1.0s with the new STT leg, the STT finalize leg tightening toward sub-100ms — documented as a runbook in `09-STT-VERIFY.md`, unsigned until run on the real consumer GPU (mirrors the v1.0 `*-VERIFY.md` operator-gate style)
- VRAM / placement: GPU-NeMo ONLY in this phase; the GPU-vs-CPU-ONNX placement + co-residency story is entirely deferred to Phase 10 (Part C)

### the agent's Discretion
- Exact websocket message schema, port number, FastAPI route names, NeMo streaming-buffer parameters, `NemoSTT` class internals, and the precise stall-watchdog timeout are at the agent's discretion within the decisions above.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agent/main.py` `build_session()` — `stt=openai.STT(base_url=WHISPER_BASE_URL, model=WHISPER_MODEL, ...)` is the exact wiring site to replace with the new `NemoSTT` streaming plugin
- `agent/main.py` `WHISPER_BASE_URL` / `WHISPER_MODEL` / `WHISPER_PARAMS` (lines 51–73) — the STT config block to retire/replace with `NEMO_STT_*` equivalents
- `docker-compose.yml` `whisper:` service (lines 95–119) — the GPU-reservation + LAN-bind + keep-resident service template to clone for `nemo-stt`; this service is REMOVED and replaced
- `agent/metrics.py` — per-plugin `metrics_collected` subscription computes `stt_ms` per turn; the new plugin must surface STT timing the same way (metrics.py is READ-ONLY per the Phase 6 note)
- Existing transcript panel in `web/` — already consumes LiveKit native transcription (interim + final); reuse it, only add interim styling
- Silero VAD + `MultilingualModel` turn detector in `build_session` — the endpoint authority that stays unchanged

### Established Patterns
- Keep-resident-forever for local model servers (`WHISPER__TTL=-1`, `OLLAMA_KEEP_ALIVE=-1`) — apply to nemo-stt to avoid cold-reload first-turn drops
- No model drift: single-source the STT model name via an env var + default shared between the server and any warmer
- Stack runs from baked Docker images — a phase touching agent/web/compose MUST `docker compose build` the affected services `&& up -d` before live verification
- Operator-gated VM proofs are documented `*-VERIFY.md` runbooks, unsigned until run on the real GPU
- LAN-bound ports via `${LAN_BIND_IP:-127.0.0.1}:HOST:CONTAINER`; the STT server carries no `.env`/LiveKit secret (M3)
- Per-plugin (not session-level) `metrics_collected` subscription for real per-turn timing

### Integration Points
- `agent/main.py` `build_session()` — swap `stt=` from `openai.STT(...)` to the new `NemoSTT(...)`
- `agent/main.py` STT config block (lines 51–73) — replace `WHISPER_*` with `NEMO_STT_BASE_URL` / `att_context_size` / model env knobs
- `docker-compose.yml` — replace the `whisper` service with `nemo-stt` (GPU reservation, LAN-bound port, keep-resident)
- `.env` / `.env.example` — replace `WHISPER_*` env vars with `NEMO_STT_*` (base URL, att_context_size default `[56,3]`)
- `agent/Dockerfile` / `agent/requirements.txt` — add any client deps needed for the websocket streaming STT plugin
- New `stt/` directory — Dockerfile + FastAPI/websocket server + NeMo streaming decode loop

</code_context>

<specifics>
## Specific Ideas

- STT model: `nvidia/nemotron-speech-streaming-en-0.6b` (REQUIREMENTS.md STT-01); English checkpoint deliberately chosen — it is the one with the 4-bit ONNX CPU port Part C needs (REQUIREMENTS.md out-of-scope: multilingual nemotron-3.5)
- `att_context_size` default `[56,3]` — the balanced profile (STT-04); low-latency vs high-accuracy profiles are a future item (STT-F2)
- ~100ms finalize after end-of-speech is the target; the finalize leg should tighten toward sub-100ms (STT-02 / PERF-04)
- Native punctuation + capitalization surfaced as-is — clean cased text to both transcript and LLM, no client post-processing (STT-03)
- Interview-mode run-on answers are the known stress case for the RNNT decoder stall — the stall watchdog directly addresses STT-02's "long run-on answers are not stranded"
- No audio leaves the local network — nemo-stt is a LAN-local service on the `adept` Docker network (STT-01)

</specifics>

<deferred>
## Deferred Ideas

- CPU-ONNX 4-bit runtime, VRAM-aware GPU-vs-CPU placement, and the global-CPU-ONNX fallback (STT-05/06/07) — Phase 10 (Part C)
- Nemotron fine-tuning on cybersecurity vocabulary/acronyms (STT-F1) — future release; only a hook/note now
- Operator-exposed `att_context_size` low-latency vs high-accuracy profiles (STT-F2) — future release
- Empty/garbled-transcription reprompt (REL-02) is built ON Part B's finalize but lands in Phase 13 (polish), not here

</deferred>
