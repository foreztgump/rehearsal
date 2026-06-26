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


async def _handle_control(ws: WebSocket, state: dict, msg: dict) -> dict:
    """Handle a JSON control frame; return the (possibly rebuilt) stream state."""
    kind = msg.get("type")
    if kind == "flush":
        async with _gpu_lock:
            text = await asyncio.to_thread(backend.finalize, _model, state)
        # Client-driven (NOT a server heuristic): reset the per-turn decode state
        # in direct response to the flush so the next FINAL is THIS turn only.
        # The encoder cache is carried forward (cache-aware streaming preserved).
        backend.reset_turn_state(state)
        await ws.send_json({"type": "final", "text": text})
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
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            # Starlette delivers a disconnect dict (no text/bytes). Raise the
            # disconnect ws_stream catches instead of looping into another
            # receive() (which would RuntimeError on a noisy traceback).
            raise WebSocketDisconnect()
        if message.get("text") is not None:
            state = await _handle_control_frame(websocket, state, message["text"])
            continue
        pcm = message.get("bytes")
        if pcm is None:
            continue
        await _emit_delta(websocket, state, pcm)


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
    """Decode one PCM frame and send the growing cumulative interim transcript."""
    try:
        cumulative = await _decode_off_loop(state, pcm)
    except Exception as exc:  # noqa: BLE001 - report any decode error to the client
        logger.exception("nemo-stt decode error")
        await websocket.send_json({"type": "error", "message": str(exc)})
        return
    await websocket.send_json({"type": "delta", "text": cumulative})


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
