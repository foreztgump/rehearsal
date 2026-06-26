# Phase 09 — Nemotron Streaming ASR (Part B) — Code Review

**Scope:** Waves 1+2 source changes, git range `e397244..dba4902`.
**Reviewer mandate:** correctness bugs that would survive to the operator GPU gate; code-visible issues only (GPU/Docker/NeMo runtime behavior is operator-gated and NOT flagged as "untested").

**Files reviewed:** `stt/server.py`, `stt/Dockerfile`, `stt/requirements.txt`, `docker-compose.yml`, `.env.example`, `agent/nemo_stt.py`, `agent/main.py`, `agent/requirements.txt`, `ollama/warmup.py`, `scripts/vram-validate.sh`, `README.md`. Confirmed `agent/metrics.py` is **NOT** in the diff (read-only invariant upheld).

---

## Verdict

The architecture is sound and most load-bearing invariants hold: the model tag is single-sourced via `STT_MODEL` (functional path), the server never auto-emits FINAL (only on the client `flush` frame), the stall watchdog recycles decoder state without sending a final, GPU access is serialized via `asyncio.Lock` with decode off-loop, both healthchecks use a python-urllib probe (no curl), ports bind LAN-only, no audio touches disk, and `_emit_final` emits an explicit `STTMetrics` with a **real measured** finalize latency (`time.perf_counter()` flush-send→final-receipt) — so `stt_ms` will populate. However there is **one Critical correctness bug**: decoder state (`prev_hyps`) is never reset between turns because the client only ever sends `flush` (never `reset`) and `flush` does not clear state — so every FINAL after the first is the cumulative transcript of the *entire session*, not the current turn. Combined with two High websocket-robustness gaps (malformed/ non-text frames crash the receive loops on both client and server, violating the "validated enough not to crash" invariant), these must be fixed before the GPU gate to avoid shipping garbage transcripts. The remaining items are Medium/Low hardening and a borderline hardcoded-label nit.

**Findings by severity:** Critical: 1 · High: 2 · Medium: 4 · Low: 4 — **11 total.**

---

## Critical

### C1 — Decoder state never resets between turns; FINAL accumulates the whole session
**`stt/server.py:213-222`, `agent/nemo_stt.py:102-117`**

`NemoSpeechStream._run` only ever sends `{"type":"config"}`, raw PCM, and `{"type":"flush"}` — it **never** sends `{"type":"reset"}`. On the server, `_handle_control` handles `flush` by sending the final but **does not reset `state`**; the `reset` branch (`state = new_stream_state()`) is therefore dead code that nothing triggers.

Because `decode_chunk` keeps feeding `previous_hypotheses=state["prev_hyps"]` and `finalize()` returns `state["prev_hyps"][0].text`, the cumulative hypothesis is *carried across turn boundaries*:

- Turn 1 → FINAL = `"What is a firewall?"`
- Turn 2 → FINAL = `"What is a firewall? How does TLS work?"` (turn-1 text prepended)
- …growing every turn for the life of the connection.

This corrupts every transcript after the first and inflates the LLM prefill. The single-turn `RecognizeStream` is reused for the whole session (one ws connection), so this fires on turn 2 onward in every real session.

**Fix:** After emitting `final` on flush, reset the per-turn decode state on the server (clear `prev_hyps`, reset stall counters and `last_text_len`, carry the encoder cache as appropriate), **or** have the client send `{"type":"reset"}` immediately after `flush`. Resetting server-side on flush is the smaller, race-free change. The server must NOT auto-recycle on its own heuristic — but resetting *in direct response to the flush control frame* is client-driven and invariant-safe.

---

## High

### H1 — Malformed JSON control frame crashes the server receive loop
**`stt/server.py:238-248`**

`_stream_loop` calls `json.loads(message["text"])` directly. A text frame containing invalid JSON raises `json.JSONDecodeError`, which is **not** caught (only `WebSocketDisconnect` is handled in `ws_stream`). The receive task dies and the connection drops with an unhandled traceback — violating the invariant "WS input (binary PCM + JSON control) validated enough not to crash on malformed frames." There is also no `{"type":"error",...}` sent back on a bad control frame.

**Fix:** Wrap the `json.loads`/dispatch in a try/except, send `{"type":"error","message":...}` on a parse failure, and `continue` instead of crashing.

### H2 — Non-text / non-JSON ws messages crash the agent receive loop
**`agent/nemo_stt.py:119-140`**

`_recv_loop` does `evt = json.loads(msg.data)` for **every** inbound `aiohttp` `WSMessage` without checking `msg.type`. When the server sends a CLOSE/ERROR/PING/BINARY frame (or any non-text payload), `msg.data` is not a JSON string and `json.loads` raises, killing `_recv_loop`; the exception then surfaces at `await recv` in `_run`. The loop must guard on `msg.type == aiohttp.WSMsgType.TEXT` (and handle `CLOSED`/`ERROR` by breaking).

**Fix:** Filter on `msg.type`; only `json.loads` TEXT frames; break cleanly on close/error.

---

## Medium

### M1 — `await recv` can hang the stream forever if the server keeps the ws open
**`agent/nemo_stt.py:104-117`**

After `_input_ch` is exhausted, `_run` does `await recv`. `_recv_loop`'s `async for msg in ws` only completes when the server closes the socket. The server's `_stream_loop` runs until `WebSocketDisconnect`, so it never proactively closes after a `final`. If the agent finishes pushing input but the connection stays open, `await recv` blocks indefinitely and the stream never tears down. Consider cancelling `recv` (or closing the ws) once input ends, rather than awaiting it unconditionally.

### M2 — `_transcribe_wav` feeds an entire file as one cache-aware stream step
**`stt/server.py:270-276`**

The offline `/v1/audio/transcriptions` path calls `decode_chunk(state, pcm)` with the **whole** file's PCM in a single `conformer_stream_step`. Cache-aware streaming expects fixed-size chunks (~560 ms / 56-frame windows); a multi-second file in one step does not exercise the same path the live loop uses and may mis-decode or blow the cache buffers. It is operator-gated (VERIFY only), so Medium — but the docstring's claim "through the same per-chunk decode loop" is inaccurate (it is a single chunk).

### M3 — Raw `websocket.receive()` disconnect dict not handled distinctly
**`stt/server.py:238-248`**

`_stream_loop` uses the low-level `websocket.receive()`. On disconnect, Starlette delivers a `{"type":"websocket.disconnect"}` message (no `text`/`bytes`), so the loop hits `pcm is None → continue` and calls `receive()` again, which then raises (`Cannot call "receive" once a disconnect message has been received`). It surfaces as a `RuntimeError`, not the `WebSocketDisconnect` that `ws_stream` catches — producing a noisy traceback on every normal disconnect. Detect the disconnect message type explicitly and return.

### M4 — `STT_ATT_CONTEXT_SIZE` parsed with `ast.literal_eval` of an env string with no validation
**`stt/server.py:55`**

`ATT_CONTEXT_SIZE = ast.literal_eval(os.environ.get("STT_ATT_CONTEXT_SIZE", "[56,3]"))`. `ast.literal_eval` is safe from code execution (good — not `eval`), but a malformed value (`"56,3"`, `"[56]"`, `"abc"`) raises at import with an opaque `ValueError`/`SyntaxError`, or silently yields a wrong-shaped object that only fails deep inside `set_default_att_context_size` at the GPU gate. Validate it is a 2-element list of ints and fail fast with a clear message, matching the `STT_MODEL` `SystemExit` posture.

---

## Low

### L1 — Hardcoded model-name literal in agent code (`model` property)
**`agent/nemo_stt.py:59-61`**

`model` returns the literal `"nemotron-speech-streaming-en-0.6b"`. The invariant states NO hardcoded model tag in `agent/*.py` — the literal must live only in `docker-compose.yml`. This is the metrics **label** only (functional tag is server-side via `STT_MODEL`), and it omits the `nvidia/` prefix, so it is not the exact forbidden tag — but it is still a model-name literal in agent code that can drift from `STT_MODEL`. Prefer a generic label (e.g. `"nemotron-streaming"`) or surface the real tag from the server's `ready` frame so the metrics label cannot diverge.

### L2 — `STTMetrics.audio_duration` hardcoded to 0.0
**`agent/nemo_stt.py:170`**

`audio_duration=0.0` is not measured. `metrics.py:_on_stt_metrics` only reads `duration`, so this is not load-bearing, but the field is inaccurate. Low — optionally track total streamed PCM bytes ÷ (sample_rate·2) for a real value.

### L3 — `_flush_started` shared across overlapping flushes (latency race)
**`agent/nemo_stt.py:100,112,158-162`**

`_flush_started` is a single attribute set in `_run` and read in `_recv_loop`. If a second `flush` is sent before the first `final` arrives, the start timestamp is overwritten and the first finalize latency is mismeasured. Turns are serial in practice, so Low — but a per-flush queue/stamp would be robust.

### L4 — `error` frames are only `print`-logged on the agent side
**`agent/nemo_stt.py:138-140`**

Server decode errors arrive as `{"type":"error",...}` and are surfaced via `print(...)` rather than the module `logger`, and no transcript event is synthesized (correct — must not fabricate a transcript). Low/style: route through `logging` for consistency with the rest of the agent. Functionally fine.

---

## Invariants — verification summary

| Invariant | Status | Notes |
|---|---|---|
| No hardcoded model tag in `server.py` / Dockerfile body / `agent/*.py` (functional) | **PASS** (label nit) | Functional tag single-sourced via `STT_MODEL` env/ARG; literal lives in compose `build.args`+`environment` and `.env.example`. See **L1** for the metrics-label literal. |
| `agent/metrics.py` is READ-ONLY (absent from diff) | **PASS** | Not in `git diff --name-only`. |
| `STTMetrics` emit is load-bearing; `duration` is a REAL measured finalize latency | **PASS** | `dur = perf_counter() - _flush_started`; field set plausible (label/request_id/timestamp/duration/audio_duration/streamed). `audio_duration` hardcoded (**L2**), not load-bearing. |
| Server NEVER auto-emits FINAL; FINAL only on `flush` | **PASS** | `final` sent only in `_handle_control` flush branch; watchdog logs + recycles, no send. |
| Stall watchdog recycles state and CONTINUES, no final in watchdog branch | **PASS** | `_track_stall` resets `prev_hyps`/counter, logs only. |
| Healthcheck uses python-urllib (NOT curl) in BOTH Dockerfile + compose | **PASS** | Identical urllib probe in both; `service_healthy` gate present. |
| Functions ≤40 lines / ≤3 params / ≤3 nesting | **PASS** | Server + plugin decomposed into small methods; nesting capped via early-`continue`. |
| GPU serialized with `asyncio.Lock`; decode off the event loop (`to_thread`) | **PASS** | `_decode_off_loop` + flush finalize both under `_gpu_lock` → `to_thread`. |
| WS errors send `{"type":"error",...}` not an unhandled crash | **PARTIAL** | Decode errors handled (`_emit_delta`); malformed control frames are NOT (**H1**), non-text frames crash client (**H2**). |
| No audio to disk/db; in-memory only | **PASS** | No file/db writes in the STT path. |
| No language/prompt steering; English-only | **PASS** | `language:"en"` is a passthrough label only; no prompt/biasing. |
| No client-side PnC post-processing | **PASS** | Native text surfaced as-is; no lowercase/strip/recapitalize. |
| Security: no secrets logged; LAN-bound ports; no command injection | **PASS** | No `env_file` on `nemo-stt` (no LiveKit secret); ports bound to `${LAN_BIND_IP:-127.0.0.1}`; healthcheck is an argv-list `python -c` (no shell interpolation); `vram-validate.sh` JSON-encodes prompts via `json_string`. |
| Cross-turn correctness | **FAIL** | **C1** — decoder state never reset; transcripts accumulate across turns. |

---

## Recommended fix order before the GPU gate
1. **C1** — reset decode state on `flush` (server-side) so each FINAL is a single turn.
2. **H1 / H2** — guard both receive loops against malformed/non-text frames.
3. **M1** — don't block forever on `await recv`; tear down when input ends.
4. **M3 / M4** — handle the disconnect message type; validate `STT_ATT_CONTEXT_SIZE`.
5. **L1** — de-literalize the metrics label.
