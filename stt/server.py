"""nemo-stt — FastAPI websocket server for cache-aware streaming ASR (gpu|cpu).

Serves streaming ASR behind a websocket that takes 16 kHz mono int16 PCM frames in
and streams growing interim transcripts out, with a FINAL emitted ONLY on the
agent's `flush` control frame. Native punctuation + capitalization come out of the
model and are surfaced AS-IS (STT-03).

Two runtimes behind the SAME frozen contract (Phase 10, RESEARCH §2). `STT_RUNTIME`
selects a backend module that exposes the SAME four callables — the WS/HTTP layer
below is byte-unchanged from Phase 9:
  * STT_RUNTIME=gpu → backend_nemo (full GPU NeMo, the Phase-9 decode body, moved).
  * STT_RUNTIME=cpu → backend_onnx (off-GPU ONNX-Runtime CPU port, three-graph
    cache loop + numpy mel). Single-sourced via STT_ONNX_MODEL (no hardcoded tag).
The agent plugin is runtime-agnostic — only the URL differs.

Contract (frozen for the NemoSTT plugin — 09-RESEARCH §2; UNCHANGED in Phase 10):
  WS /v1/audio/stream
    client → {"type":"config","language":"en"}, then raw int16 PCM binary frames;
             control frames {"type":"flush"} (drain → FINAL, then auto-reset the
             per-turn decode state so the NEXT FINAL is that turn only) /
             {"type":"reset"} (full per-connection state rebuild).
    server → {"type":"ready"} | {"type":"delta","text":<cumulative>} |
             {"type":"final","text":<final>} | {"type":"error","message":...}.
  GET  /health                  → 200 only after the model is resident (else 503).
  POST /v1/audio/transcriptions → optional whole-file OpenAI-compat path for the
                                  offline VERIFY checks (mirrors warm_whisper).

The model is loaded resident at lifespan startup and NEVER offloaded (mirrors
WHISPER__TTL=-1 — avoids the cold-reload first-turn-drop bug). Decode access is
serialized with an asyncio.Lock and the blocking decode runs off the event loop.

Heavy imports (nemo/torch or onnxruntime/numpy) live INSIDE the chosen backend so
this module byte-compiles in the GPU-less, ORT-less sandbox; the real decode is an
operator gate (10-PLACEMENT-VERIFY).
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import io
import json
import logging
import os
import wave
from typing import Any

from fastapi import FastAPI, Response, UploadFile, WebSocket, WebSocketDisconnect

logger = logging.getLogger("nemo-stt")

# --- Backend dispatch (validate-or-SystemExit, mirrors _parse_att_context_size) ---
# STT_RUNTIME selects which decode backend module to import lazily by name. The
# backend exposes load_model()/new_stream_state(model)/decode_chunk(model,state,pcm)/
# finalize(model,state)/reset_turn_state(state); server.py owns the single model
# handle + the WS/HTTP layer. Heavy imports stay inside the backend so this module
# byte-compiles in the GPU-less, ORT-less sandbox.
RUNTIME = os.environ.get("STT_RUNTIME", "gpu")
if RUNTIME not in ("gpu", "cpu"):
    raise SystemExit(f"STT_RUNTIME must be gpu|cpu, got {RUNTIME!r}")
backend = importlib.import_module("backend_nemo" if RUNTIME == "gpu" else "backend_onnx")

PORT = 8000
SAMPLE_RATE = 16000
# Offline-path window: feed whole-file PCM through the per-chunk decode loop in
# fixed ~560 ms slices (the live cache-aware step size) rather than one giant
# step, so the VERIFY offline path exercises the same code path as live.
OFFLINE_CHUNK_MS = int(os.environ.get("STT_OFFLINE_CHUNK_MS", "560"))
_BYTES_PER_SAMPLE = 2  # int16 mono
# Live cache-aware streaming step. LiveKit forwards tiny (~10-20 ms) audio frames;
# the FastConformer encoder subsamples 8x, so a sub-chunk PCM frame yields ZERO
# post-subsampling frames and the quantized ConvInteger node errors with
# "Invalid input shape: {0}". Buffer incoming PCM to this fixed step (the same size
# the offline path uses) before invoking the encoder.
STREAM_CHUNK_MS = int(os.environ.get("STT_STREAM_CHUNK_MS", "560"))
_STREAM_CHUNK_BYTES = (SAMPLE_RATE * STREAM_CHUNK_MS // 1000) * _BYTES_PER_SAMPLE

# Autonomous end-of-utterance window. The livekit-agents 1.6.4 turn pipeline does
# NOT send a {"type":"flush"} when the user stops talking — it pushes SILENCE into
# the STT stream and waits for the plugin to emit FINAL_TRANSCRIPT on its own
# (provider-side endpointing, like Deepgram/AssemblyAI). _run_eou_detection then
# guards `if stt and not _audio_transcript: return`, and _audio_transcript is filled
# ONLY by FINAL events — so WITHOUT an autonomous final the turn never commits and
# the LLM never runs. We detect end-of-utterance as: cumulative text was non-empty
# and then stopped growing for ENDPOINT_SILENCE_MS of audio (the transcript stalls
# the moment speech stops), then emit {"type":"final"} and reset the turn. The
# framework's MultilingualModel + endpointing.min_delay still own the SEMANTIC
# decision to reply, and it concatenates successive finals (_audio_transcript +=),
# so a mid-sentence pause that fires early is recombined, not lost.
ENDPOINT_SILENCE_MS = int(os.environ.get("STT_ENDPOINT_SILENCE_MS", "700"))
_ENDPOINT_SILENCE_CHUNKS = max(1, -(-ENDPOINT_SILENCE_MS // STREAM_CHUNK_MS))  # ceil

# Module-level model handle + readiness gate + decode serialization lock. The
# _gpu_lock name is kept for continuity but it now serializes the single decode
# session per connection for BOTH runtimes (under cpu it serializes the one ORT
# session — single-user, one active stream); no behavioural change.
_model: Any = None
_ready: bool = False
_gpu_lock = asyncio.Lock()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load the model resident at startup; keep it forever (no offload)."""
    global _model, _ready
    _model = await asyncio.to_thread(backend.load_model)
    _ready = True
    yield
    # No offload on shutdown — keep-resident-forever mirrors WHISPER__TTL=-1.


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> Response:
    """200 only once the model is resident, so Compose service_healthy gates the agent."""
    if _ready:
        return Response(content=json.dumps({"status": "ok"}), media_type="application/json")
    return Response(content=json.dumps({"status": "loading"}), status_code=503,
                    media_type="application/json")


async def _decode_off_loop(state: dict, pcm: bytes) -> str:
    """Serialize decode access (asyncio.Lock) and run the blocking decode off-loop."""
    async with _gpu_lock:
        return await asyncio.to_thread(backend.decode_chunk, _model, state, pcm)


async def _send_final(ws: WebSocket, state: dict, text: str) -> None:
    """Emit {"type":"final"} and reset per-turn decode + endpoint/dedup markers.

    Shared by the explicit `flush` control frame AND the autonomous end-of-utterance
    path. reset_turn_state carries the encoder cache forward (cache-aware streaming
    preserved) but clears prev_hyps so the NEXT final is that turn only.
    """
    backend.reset_turn_state(state)
    state.pop("_last_delta_text", None)
    state["_silent_chunks"] = 0
    state["_final_pending"] = False
    await ws.send_json({"type": "final", "text": text})


async def _handle_control(ws: WebSocket, state: dict, msg: dict) -> dict:
    """Handle a JSON control frame; return the (possibly rebuilt) stream state."""
    kind = msg.get("type")
    if kind == "flush":
        async with _gpu_lock:
            text = await asyncio.to_thread(backend.finalize, _model, state)
        await _send_final(ws, state, text)
    elif kind == "reset":
        state = backend.new_stream_state(_model)
    return state


@app.websocket("/v1/audio/stream")
async def ws_stream(websocket: WebSocket) -> None:
    """Primary streaming endpoint. config → ready → deltas; flush → final."""
    await websocket.accept()
    await websocket.receive_json()  # the {"type":"config", ...} handshake
    await websocket.send_json({"type": "ready"})
    state = backend.new_stream_state(_model)
    try:
        await _stream_loop(websocket, state)
    except WebSocketDisconnect:
        return


async def _stream_loop(websocket: WebSocket, state: dict) -> None:
    """Receive loop: JSON control frames vs binary PCM frames (nesting ≤3)."""
    buf = bytearray()
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            # Starlette delivers a disconnect dict (no text/bytes). Raise the
            # disconnect ws_stream catches instead of looping into another
            # receive() (which would RuntimeError on a noisy traceback).
            raise WebSocketDisconnect()
        if message.get("text") is not None:
            buf = await _drain_buffer(websocket, state, buf)
            state = await _handle_control_frame(websocket, state, message["text"])
            continue
        pcm = message.get("bytes")
        if pcm is None:
            continue
        buf.extend(pcm)
        # Only invoke the encoder once a full streaming chunk has accumulated; the
        # FastConformer 8x subsampling needs >= one chunk of samples or the
        # quantized ConvInteger node sees a zero-length time axis.
        while len(buf) >= _STREAM_CHUNK_BYTES:
            await _emit_delta(websocket, state, bytes(buf[:_STREAM_CHUNK_BYTES]))
            del buf[:_STREAM_CHUNK_BYTES]


async def _drain_buffer(websocket: WebSocket, state: dict, buf: bytearray) -> bytearray:
    """Decode any sub-chunk PCM tail before a control frame (e.g. flush) lands.

    Pad the partial tail up to one full streaming chunk so the encoder still sees a
    valid (non-zero) time axis — the remainder would otherwise be lost on flush.
    """
    if not buf:
        return buf
    padded = bytes(buf) + b"\x00" * (_STREAM_CHUNK_BYTES - len(buf))
    await _emit_delta(websocket, state, padded)
    return bytearray()


async def _handle_control_frame(websocket: WebSocket, state: dict, text: str) -> dict:
    """Parse + dispatch a JSON control frame; a bad frame replies error, no crash."""
    try:
        msg = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": f"bad control frame: {exc}"})
        return state
    if not isinstance(msg, dict):
        await websocket.send_json({"type": "error", "message": "control frame must be an object"})
        return state
    return await _handle_control(websocket, state, msg)


async def _emit_delta(websocket: WebSocket, state: dict, pcm: bytes) -> None:
    """Decode one PCM frame; emit a delta on growth, an autonomous final on silence.

    Two jobs, both driven by whether the cumulative transcript GREW this chunk:

    1. Interim dedup — only send {"type":"delta"} when the text actually CHANGES.
       The cache-aware loop decodes every STREAM_CHUNK_MS forever, re-emitting the
       SAME string through post-utterance silence; LiveKit reads each interim as
       "still speaking", so identical interims would pin the turn open. Suppress
       unchanged interims.

    2. Autonomous end-of-utterance — when the text has been non-empty and then
       stops growing for _ENDPOINT_SILENCE_CHUNKS, emit {"type":"final"}. The
       livekit-agents turn pipeline does NOT send a flush frame on end-of-speech;
       it pushes silence and waits for the plugin's FINAL (see ENDPOINT_SILENCE_MS
       note above). Without this the turn never commits and the LLM never runs.
    """
    try:
        cumulative = await _decode_off_loop(state, pcm)
    except Exception as exc:  # noqa: BLE001 - report any decode error to the client
        logger.exception("nemo-stt decode error")
        await websocket.send_json({"type": "error", "message": str(exc)})
        return
    grew = cumulative != state.get("_last_delta_text")
    if grew:
        state["_last_delta_text"] = cumulative
        state["_silent_chunks"] = 0
        state["_final_pending"] = bool(cumulative)
        await websocket.send_json({"type": "delta", "text": cumulative})
        return
    # No growth this chunk: count toward end-of-utterance. Fire ONE final per
    # utterance (guarded by _final_pending so steady silence does not spam finals).
    if not state.get("_final_pending"):
        return
    state["_silent_chunks"] = state.get("_silent_chunks", 0) + 1
    if state["_silent_chunks"] >= _ENDPOINT_SILENCE_CHUNKS:
        async with _gpu_lock:
            text = await asyncio.to_thread(backend.finalize, _model, state)
        await _send_final(websocket, state, text)


@app.post("/v1/audio/transcriptions")
async def transcribe_file(file: UploadFile) -> dict:
    """Optional whole-file OpenAI-compat path (mirrors warm_whisper) for VERIFY."""
    raw = await file.read()
    text = await asyncio.to_thread(_transcribe_wav, raw)
    return {"text": text}


def _transcribe_wav(raw: bytes) -> str:
    """Decode a 16 kHz mono int16 WAV through the same per-chunk decode loop.

    The file PCM is sliced into fixed OFFLINE_CHUNK_MS windows and fed through the
    backend's decode_chunk one at a time — the SAME cache-aware per-chunk path the
    live websocket loop uses — instead of one multi-second step.
    """
    with wave.open(io.BytesIO(raw), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    state = backend.new_stream_state(_model)
    step = (SAMPLE_RATE * OFFLINE_CHUNK_MS // 1000) * _BYTES_PER_SAMPLE
    for start in range(0, len(pcm), step):
        backend.decode_chunk(_model, state, pcm[start:start + step])
    return backend.finalize(_model, state)
