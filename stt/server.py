"""nemo-stt — FastAPI websocket server for Nemotron cache-aware streaming ASR.

Serves the Nemotron streaming ASR checkpoint (single-sourced via the
STT_MODEL env var — NO hardcoded tag, AGENTS.md) behind a websocket that takes
16 kHz mono int16 PCM frames in and streams growing interim transcripts out, with
a FINAL emitted ONLY on the agent's `flush` control frame. Native punctuation +
capitalization come out of the model and are surfaced AS-IS (STT-03).

Contract (frozen for the Wave-2 NemoSTT plugin — 09-RESEARCH §2):
  WS /v1/audio/stream
    client → {"type":"config","language":"en"}, then raw int16 PCM binary frames;
             control frames {"type":"flush"} (drain → FINAL, then auto-reset the
             per-turn decode state so the NEXT FINAL is that turn only) /
             {"type":"reset"} (full per-connection state rebuild).
    server → {"type":"ready"} | {"type":"delta","text":<cumulative>} |
             {"type":"final","text":<final>} | {"type":"error","message":...}.
  GET  /health                  → 200 only after the model is resident (else 503).
  POST /v1/audio/transcriptions → optional whole-file OpenAI-compat path for the
                                  09-STT-VERIFY offline checks (mirrors warm_whisper).

The model is loaded resident at lifespan startup and NEVER offloaded (mirrors
WHISPER__TTL=-1 — avoids the cold-reload first-turn-drop bug). GPU access is
serialized with an asyncio.Lock and the blocking decode runs off the event loop.

Heavy imports (nemo, torch, numpy) live INSIDE functions / the lifespan so this
module byte-compiles in the GPU-less sandbox; the real decode is an operator GPU
gate (09-STT-VERIFY).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import logging
import os
import wave
from typing import Any

from fastapi import FastAPI, Response, UploadFile, WebSocket, WebSocketDisconnect

logger = logging.getLogger("nemo-stt")

# --- Config (module scope, no hardcoded tag) ----------------------------------
# Single-source the model tag the SAME way agent/main.py:resolved_llm_tag does:
# KeyError → SystemExit if unset, so the baked weights and the loaded model can
# never drift (the v1.0 no-hardcoded-tag invariant).
try:
    MODEL_NAME: str = os.environ["STT_MODEL"]
except KeyError as exc:  # pragma: no cover - exercised only at process start
    raise SystemExit("STT_MODEL is not set — supplied by docker-compose build/env") from exc

# att_context_size = [left, right] in 80 ms encoder frames (STT-04). Balanced
# default [56,3]; set ONCE on the encoder at load. `right` trades latency vs
# accuracy (lower = snappier, higher = more accurate).
ATT_CONTEXT_SIZE = ast.literal_eval(os.environ.get("STT_ATT_CONTEXT_SIZE", "[56,3]"))

# RNNT decoder-stall watchdog (09-RESEARCH §1, PITFALL B2). Named constants, no
# magic values. If cumulative text stops growing for STALL_FRAMES while audio is
# STILL arriving, recycle decoder state and CONTINUE — the server NEVER auto-emits
# FINAL (the turn detector owns finalize). STT_RECYCLE_* bound the recycle so it
# stays stall-recovery only.
STALL_FRAMES = int(os.environ.get("STT_STALL_FRAMES", "50"))
RECYCLE_MIN_CHARS = int(os.environ.get("STT_RECYCLE_MIN_CHARS", "120"))
RECYCLE_HARD_CHARS = int(os.environ.get("STT_RECYCLE_HARD_CHARS", "400"))

PORT = 8000
SAMPLE_RATE = 16000
INT16_FULL_SCALE = 32768.0

# Module-level model handles + readiness gate + GPU serialization lock.
_model: Any = None
_ready: bool = False
_gpu_lock = asyncio.Lock()


def load_model() -> Any:
    """Load the Nemotron streaming model resident, set the att_context_size knob.

    Heavy imports are local so the GPU-less sandbox can byte-compile this module.
    The exact `conformer_stream_step` signature + preprocessing are confirmed
    against the in-container `nemo.collections.asr` source at the operator GPU
    gate (09-STT-VERIFY) — the sandbox cannot import NeMo.
    """
    import nemo.collections.asr as nemo_asr  # noqa: PLC0415 - GPU-only dep

    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    model.eval()
    model.encoder.set_default_att_context_size(ATT_CONTEXT_SIZE)
    # Greedy single-step RNNT decoding — lowest latency for streaming.
    _set_greedy_decoding(model)
    logger.info("nemo-stt model loaded: %s att_context_size=%s", MODEL_NAME, ATT_CONTEXT_SIZE)
    return model


def _set_greedy_decoding(model: Any) -> None:
    """Switch the RNNT head to greedy single-step decoding (alignments off)."""
    from omegaconf import open_dict  # noqa: PLC0415 - GPU-only dep

    cfg = model.cfg.decoding
    with open_dict(cfg):
        cfg.strategy = "greedy"
        cfg.preserve_alignments = False
    model.change_decoding_strategy(decoding_cfg=cfg)


def new_stream_state() -> dict:
    """Fresh per-connection streaming state (cache + stall-tracking counters)."""
    channel, time_state, channel_len = _model.encoder.get_initial_cache_state(batch_size=1)
    return {
        "cache_last_channel": channel,
        "cache_last_time": time_state,
        "cache_last_channel_len": channel_len,
        "prev_hyps": None,
        "frames_since_growth": 0,
        "last_text_len": 0,
    }


def _extract_features(pcm: bytes) -> tuple[Any, Any]:
    """int16 PCM bytes → mel features via the model's own preprocessor."""
    import numpy as np  # noqa: PLC0415 - GPU-only dep
    import torch  # noqa: PLC0415 - GPU-only dep

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / INT16_FULL_SCALE
    signal = torch.tensor(samples).unsqueeze(0)
    length = torch.tensor([signal.shape[1]])
    feats, feat_len = _model.preprocessor(input_signal=signal, length=length)
    return feats, feat_len


def decode_chunk(state: dict, pcm: bytes) -> str:
    """Run one cache-aware stream step; return the CUMULATIVE transcript.

    Native PnC is surfaced AS-IS (no strip/lowercase — STT-03). Recycles decoder
    state on a stall but NEVER emits FINAL (the turn detector owns finalize).
    """
    import torch  # noqa: PLC0415 - GPU-only dep

    feats, feat_len = _extract_features(pcm)
    with torch.inference_mode():
        text, channel, time_state, channel_len, hyps = _model.conformer_stream_step(
            processed_signal=feats,
            processed_signal_length=feat_len,
            cache_last_channel=state["cache_last_channel"],
            cache_last_time=state["cache_last_time"],
            cache_last_channel_len=state["cache_last_channel_len"],
            keep_all_outputs=True,
            previous_hypotheses=state["prev_hyps"],
            return_transcription=True,
        )
    state["cache_last_channel"] = channel
    state["cache_last_time"] = time_state
    state["cache_last_channel_len"] = channel_len
    state["prev_hyps"] = hyps
    cumulative = hyps[0].text if hyps else ""
    _track_stall(state, cumulative)
    return cumulative


def _track_stall(state: dict, cumulative: str) -> None:
    """Stall watchdog: recycle decoder state if text stops growing (no FINAL)."""
    grew = len(cumulative) > state["last_text_len"]
    state["last_text_len"] = len(cumulative)
    if grew:
        state["frames_since_growth"] = 0
        return
    state["frames_since_growth"] += 1
    stalled = state["frames_since_growth"] >= STALL_FRAMES
    if stalled and len(cumulative) >= RECYCLE_MIN_CHARS:
        # Reset prev_hyps, carry the encoder cache forward, continue. Log only —
        # do NOT emit FINAL (single-turn-source invariant, 09-RESEARCH §1/§4).
        logger.info("nemo-stt RNNT stall recycle at %d chars (cache carried forward)", len(cumulative))
        state["prev_hyps"] = None
        state["frames_since_growth"] = 0


def finalize(state: dict) -> str:
    """Drain the stream and return the final transcript (flush→final response)."""
    cumulative = ""
    if state["prev_hyps"]:
        cumulative = state["prev_hyps"][0].text
    return cumulative


def reset_turn_state(state: dict) -> None:
    """Clear per-turn decode state after a FINAL so the next utterance starts clean.

    Resets the RNNT hypotheses + stall counters but CARRIES THE ENCODER CACHE
    forward (cache_last_*) — same as the stall recycle — so cache-aware streaming
    semantics are preserved across the turn boundary. Without this, prev_hyps is
    fed back into the next decode and every FINAL accumulates the whole session.
    """
    state["prev_hyps"] = None
    state["frames_since_growth"] = 0
    state["last_text_len"] = 0


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load the model resident at startup; keep it forever (no offload)."""
    global _model, _ready
    _model = await asyncio.to_thread(load_model)
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
    """Serialize GPU access (asyncio.Lock) and run the blocking decode off-loop."""
    async with _gpu_lock:
        return await asyncio.to_thread(decode_chunk, state, pcm)


async def _handle_control(ws: WebSocket, state: dict, msg: dict) -> dict:
    """Handle a JSON control frame; return the (possibly rebuilt) stream state."""
    kind = msg.get("type")
    if kind == "flush":
        async with _gpu_lock:
            text = await asyncio.to_thread(finalize, state)
        # Client-driven (NOT a server heuristic): reset the per-turn decode state
        # in direct response to the flush so the next FINAL is THIS turn only.
        # The encoder cache is carried forward (cache-aware streaming preserved).
        reset_turn_state(state)
        await ws.send_json({"type": "final", "text": text})
    elif kind == "reset":
        state = new_stream_state()
    return state


@app.websocket("/v1/audio/stream")
async def ws_stream(websocket: WebSocket) -> None:
    """Primary streaming endpoint. config → ready → deltas; flush → final."""
    await websocket.accept()
    await websocket.receive_json()  # the {"type":"config", ...} handshake
    await websocket.send_json({"type": "ready"})
    state = new_stream_state()
    try:
        await _stream_loop(websocket, state)
    except WebSocketDisconnect:
        return


async def _stream_loop(websocket: WebSocket, state: dict) -> None:
    """Receive loop: JSON control frames vs binary PCM frames (nesting ≤3)."""
    while True:
        message = await websocket.receive()
        if message.get("text") is not None:
            state = await _handle_control(websocket, state, json.loads(message["text"]))
            continue
        pcm = message.get("bytes")
        if pcm is None:
            continue
        await _emit_delta(websocket, state, pcm)


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
    """Decode a 16 kHz mono int16 WAV through the same per-chunk decode loop."""
    with wave.open(io.BytesIO(raw), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    state = new_stream_state()
    decode_chunk(state, pcm)
    return finalize(state)
