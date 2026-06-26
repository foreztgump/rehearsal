"""backend_onnx — the STT_RUNTIME=cpu backend (off-GPU ONNX-Runtime CPU port).

This reproduces the IDENTICAL cumulative growing transcript the GPU NeMo path emits
(backend_nemo) over ONNX Runtime, behind the SAME four-callable seam server.py
dispatches through (RESEARCH §1.2/§2):

    load_model() -> Any
    new_stream_state(model) -> dict
    decode_chunk(model, state, pcm) -> str
    finalize(model, state) -> str
    reset_turn_state(state) -> None

The single NeMo `conformer_stream_step` is replaced by an explicit three-graph cache
loop: an `encoder.onnx` session updating the streaming cache, then a greedy RNNT loop
over the encoder output against `decoder_joint.onnx` (LSTM dec_state fed back, blank=
1024, ≤10 symbols/frame), then SentencePiece detokenize → the cumulative string (the
analog of `prev_hyps[0].text`). The WS bytes on the wire are unchanged — only the
*inside* of these callables differs (RESEARCH §1.2).

Heavy imports (`onnxruntime`, `numpy`, `sentencepiece`) live INSIDE the functions so
this module byte-compiles in the ORT-less sandbox; the real ORT run + the mel-parity
check are operator host/build gates (10-PLACEMENT-VERIFY). The sandbox cannot download
or run ORT — the exact graph I/O names + cache shapes are confirmed against the export
`config.json` at the operator build gate.
"""
from __future__ import annotations

import logging
import os
from typing import Any

# Share the watchdog thresholds + streaming constants via the TAG-FREE common module
# so the stall semantics are identical across both runtimes WITHOUT importing
# backend_nemo (whose module body hard-requires STT_MODEL, which the CPU image never
# sets — importing it on the CPU path would SystemExit at startup; Phase 10 C1).
from backend_common import (
    INT16_FULL_SCALE,
    RECYCLE_MIN_CHARS,
    STALL_FRAMES,
)

logger = logging.getLogger("nemo-stt")

# --- Config (module scope, no hardcoded tag) ----------------------------------
# Single-source the ONNX artifact tag/path the SAME way backend_nemo reads STT_MODEL:
# KeyError → SystemExit if unset, so the baked artifact and the loaded artifact can
# never drift (the v1.0 no-hardcoded-tag invariant — the literal default lives ONLY
# in docker-compose.yml build.args/environment).
try:
    ONNX_MODEL: str = os.environ["STT_ONNX_MODEL"]
except KeyError as exc:  # pragma: no cover - exercised only at process start
    raise SystemExit("STT_ONNX_MODEL is not set — supplied by docker-compose build/env") from exc

# Quant profile selector. int8-dynamic (~0.88 GB on disk, stock onnxruntime
# quantize_dynamic, encoder-only) is the CI/Docker-reproducible DEFAULT. int4-kquant
# (~0.67 GB, the literal STT-05 number) is an OPERATOR-GATED stretch BUILD (custom
# k-quant + MHA fusion, arXiv 2604.14493 — NOT a stock call). This file only SELECTS
# which baked artifact to load by name; it does NOT quantize anything.
_VALID_QUANT = ("int8-dynamic", "int4-kquant")
QUANT = os.environ.get("STT_QUANT", "int8-dynamic")
if QUANT not in _VALID_QUANT:
    raise SystemExit(f"STT_QUANT must be one of {_VALID_QUANT}, got {QUANT!r}")

# Cache-aware streaming tensor shapes — verified from the reference ONNX export
# config.json (RESEARCH §1.2). The CPU analog of get_initial_cache_state(batch_size=1).
_CACHE_LAST_CHANNEL_SHAPE = (1, 24, 70, 1024)
_CACHE_LAST_TIME_SHAPE = (1, 24, 1024, 8)
_DEC_STATE_SHAPE = (2, 1, 640)  # RNNT LSTM h/c (two of these)
_BLANK_ID = 1024                # vocab 1025, blank is the last id
_MAX_SYMBOLS_PER_FRAME = 10     # greedy RNNT inner-loop bound

# Mel preprocessor params — verified from the export config.json (RESEARCH §1.3).
_PRE_EMPHASIS = 0.97
_N_FFT = 512
_HOP = 160      # 10 ms @ 16 kHz
_WIN = 400      # 25 ms @ 16 kHz
_N_MELS = 128   # Slaney norm, band-major [n_mels, n_frames]


def load_model() -> Any:
    """Build the encoder + decoder/joint ORT sessions + tokenizer + baked filterbank.

    Returns a handle bundle holding all four artifacts the cache loop needs. The
    artifacts are baked into the image by export_onnx.py (encoder.onnx,
    decoder_joint.onnx, filterbank.bin [1,128,257], tokenizer.model) keyed off
    ONNX_MODEL/QUANT. Heavy imports are local so the ORT-less sandbox byte-compiles
    this module; the real session build is an operator gate (10-PLACEMENT-VERIFY).
    The exact graph I/O names + cache shapes are confirmed against the export
    config.json at that gate — the sandbox cannot download/run ORT.
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep
    import onnxruntime  # noqa: PLC0415 - ORT-only dep
    import sentencepiece  # noqa: PLC0415 - ORT-only dep

    bundle_dir = _resolve_bundle_dir()
    providers = ["CPUExecutionProvider"]
    encoder = onnxruntime.InferenceSession(f"{bundle_dir}/encoder.onnx", providers=providers)
    decoder_joint = onnxruntime.InferenceSession(
        f"{bundle_dir}/decoder_joint.onnx", providers=providers)
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=f"{bundle_dir}/tokenizer.model")
    filterbank = np.fromfile(f"{bundle_dir}/filterbank.bin", dtype=np.float32).reshape(1, _N_MELS, _N_FFT // 2 + 1)
    logger.info("nemo-stt-cpu ORT sessions loaded: %s quant=%s", ONNX_MODEL, QUANT)
    return {
        "encoder": encoder,
        "decoder_joint": decoder_joint,
        "tokenizer": tokenizer,
        "filterbank": filterbank,
    }


def _resolve_bundle_dir() -> str:
    """Local dir holding the baked artifact bundle for this ONNX_MODEL/QUANT."""
    base = os.environ.get("STT_ONNX_DIR", "/app/onnx")
    return f"{base}/{QUANT}"


def new_stream_state(model) -> dict:
    """Fresh per-connection streaming state — cache zeros + stall-tracking counters.

    The cache tensors stay FP32 (only the encoder is quantized). The keys mirror the
    NeMo state shape so the watchdog logic is identical across both backends.
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    return {
        "cache_last_channel": np.zeros(_CACHE_LAST_CHANNEL_SHAPE, dtype=np.float32),
        "cache_last_time": np.zeros(_CACHE_LAST_TIME_SHAPE, dtype=np.float32),
        "cache_last_channel_len": np.zeros((1,), dtype=np.int64),
        "dec_state": [np.zeros(_DEC_STATE_SHAPE, dtype=np.float32),
                      np.zeros(_DEC_STATE_SHAPE, dtype=np.float32)],
        "emitted_token_ids": [],
        "prev_text": "",
        "frames_since_growth": 0,
        "last_text_len": 0,
    }


def _extract_features(model, pcm: bytes):
    """int16 PCM bytes → band-major [1,128,n_frames] log-mel (numpy-only).

    !!! HIGHEST-RISK PARITY SEAM (RESEARCH §1.3) !!!
    The NeMo AudioToMelSpectrogramPreprocessor is NOT in the exported ONNX graph, so
    the CPU backend MUST recompute the 128-band Slaney mel ITSELF before the encoder
    session. This is the single largest piece of new code and the highest-risk parity
    item — a numerical mismatch vs the NeMo preprocessor SILENTLY TANKS WER (the
    operator WER gate in 10-PLACEMENT-VERIFY is the catch). It uses the BAKED Slaney
    filterbank.bin (bit-identical to the .nemo preprocessor, extracted by
    export_onnx.py) + a numpy STFT — numpy-only, NO librosa, numerically matched to
    the export. Params (pre-emphasis 0.97, FFT 512 / hop 160 / win 400 Hann, 128
    bands) are verified from the export config.json.
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / INT16_FULL_SCALE
    emphasized = np.append(samples[:1], samples[1:] - _PRE_EMPHASIS * samples[:-1])
    power = _stft_power(emphasized)                              # [n_frames, n_fft/2+1]
    mel = power @ model["filterbank"][0].T                       # [n_frames, 128]
    log_mel = np.log(np.clip(mel, a_min=1e-9, a_max=None))
    return log_mel.T[np.newaxis, :, :].astype(np.float32)        # band-major [1,128,n]


def _stft_power(signal):
    """Framed Hann STFT magnitude-squared → [n_frames, n_fft/2+1] (numpy-only)."""
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    window = np.hanning(_WIN).astype(np.float32)
    if len(signal) < _WIN:
        signal = np.pad(signal, (0, _WIN - len(signal)))
    n_frames = 1 + (len(signal) - _WIN) // _HOP
    frames = np.stack([signal[i * _HOP:i * _HOP + _WIN] * window for i in range(n_frames)])
    spectrum = np.fft.rfft(frames, n=_N_FFT, axis=1)
    return (np.abs(spectrum) ** 2).astype(np.float32)


def decode_chunk(model, state, pcm) -> str:
    """Run one encoder step + greedy RNNT loop; return the CUMULATIVE transcript.

    Native PnC is surfaced AS-IS (no strip/lowercase — STT-03). Recycles decoder
    state on a stall but NEVER emits FINAL (the turn detector owns finalize).
    """
    mel = _extract_features(model, pcm)
    enc = model["encoder"].run(None, {
        "audio_signal": mel,
        "cache_last_channel": state["cache_last_channel"],
        "cache_last_time": state["cache_last_time"],
        "cache_last_channel_len": state["cache_last_channel_len"],
    })
    enc_out, state["cache_last_channel"], state["cache_last_time"], state["cache_last_channel_len"] = enc
    _greedy_rnnt(model, state, enc_out)
    text = model["tokenizer"].decode(state["emitted_token_ids"])
    state["prev_text"] = text
    _track_stall(state, text)
    return text


def _greedy_rnnt(model, state, enc_out) -> None:
    """Greedy RNNT over enc_out frames; append non-blank ids, feed dec_state back.

    blank=1024, ≤10 symbols/frame; dec_state (LSTM h/c) is carried in `state` across
    chunks. enc_out is [1, D, T]; each time-step feeds [1,D,1] into decoder_joint.
    """
    n_frames = enc_out.shape[2]
    for t in range(n_frames):
        enc_step = enc_out[:, :, t:t + 1]
        for _ in range(_MAX_SYMBOLS_PER_FRAME):
            token, dec_state = _decode_step(model, state, enc_step)
            if token == _BLANK_ID:
                break
            state["emitted_token_ids"].append(int(token))
            state["dec_state"] = dec_state


def _decode_step(model, state, enc_step):
    """One decoder/joint step → (argmax token id, new dec_state). Helper ≤3 nesting."""
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    last = state["emitted_token_ids"][-1] if state["emitted_token_ids"] else _BLANK_ID
    targets = np.array([[last]], dtype=np.int64)
    logits, h, c = model["decoder_joint"].run(None, {
        "encoder_outputs": enc_step,
        "targets": targets,
        "input_states_1": state["dec_state"][0],
        "input_states_2": state["dec_state"][1],
    })
    return int(np.argmax(logits.reshape(-1))), [h, c]


def _track_stall(state, cumulative) -> None:
    """Stall watchdog: recycle decoder state if text stops growing (no FINAL).

    Identical semantics to backend_nemo. The ONNX analog of `prev_hyps=None` is the
    `dec_state` reset + the emitted-token-list reset; the encoder cache is CARRIED
    forward. Log only — NEVER emit FINAL (single-turn-source invariant).
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    grew = len(cumulative) > state["last_text_len"]
    state["last_text_len"] = len(cumulative)
    if grew:
        state["frames_since_growth"] = 0
        return
    state["frames_since_growth"] += 1
    stalled = state["frames_since_growth"] >= STALL_FRAMES
    if stalled and len(cumulative) >= RECYCLE_MIN_CHARS:
        logger.info("nemo-stt-cpu RNNT stall recycle at %d chars (cache carried forward)", len(cumulative))
        state["dec_state"] = [np.zeros(_DEC_STATE_SHAPE, dtype=np.float32),
                              np.zeros(_DEC_STATE_SHAPE, dtype=np.float32)]
        state["emitted_token_ids"] = []
        state["frames_since_growth"] = 0


def finalize(model, state) -> str:
    """Drain the stream and return the final transcript (flush→final response)."""
    return model["tokenizer"].decode(state["emitted_token_ids"]) if state["emitted_token_ids"] else ""


def reset_turn_state(state) -> None:
    """Clear per-turn decode state after a FINAL so the next utterance starts clean.

    Resets dec_state + emitted_token_ids + stall counters but CARRIES THE ENCODER
    CACHE forward (cache_last_*) — the exact analog of backend_nemo's reset_turn_state
    so per-turn FINALs don't accumulate the whole session.
    """
    import numpy as np  # noqa: PLC0415 - ORT-only dep

    state["dec_state"] = [np.zeros(_DEC_STATE_SHAPE, dtype=np.float32),
                          np.zeros(_DEC_STATE_SHAPE, dtype=np.float32)]
    state["emitted_token_ids"] = []
    state["prev_text"] = ""
    state["frames_since_growth"] = 0
    state["last_text_len"] = 0
