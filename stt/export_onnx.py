"""export_onnx — operator/build ONNX export + quant recipe (Plan 10-01, RESEARCH §5).

This is the EXPORT-TIME recipe, authored here and run at the operator/build gate (NOT
in the sandbox — it needs NeMo + torch + multi-GB downloads). It produces the FULL
bundle `backend_onnx.load_model` expects from the ORIGINAL `.nemo` checkpoint, so both
Dockerfile.cpu bake paths yield the SAME four artifacts:

    encoder.onnx        — cache-aware FastConformer encoder (quantized per STT_QUANT)
    decoder_joint.onnx  — RNNT decoder (LSTM prediction net) + joiner, FP32
    filterbank.bin      — [1,128,257] Slaney mel filterbank, bit-identical to the
                          .nemo preprocessor (the mel-PARITY invariant — a mismatch
                          silently tanks WER; RESEARCH §1.3)
    tokenizer.model     — SentencePiece model extracted from the .nemo

Quant tiers (RESEARCH §1.1):
  * int8-dynamic (DEFAULT) — stock onnxruntime.quantization.quantize_dynamic on the
    ENCODER ONLY (decoder/joint + cache tensors stay FP32). ~0.88 GB on disk,
    CI/Docker-reproducible.
  * int4-kquant (STRETCH, OPERATOR-GATED) — ~0.67 GB, the literal STT-05 number;
    custom k-quant + MHA fusion (arXiv 2604.14493), NOT a stock call. A documented
    seam below, not a working stock path.

Single-sourced tags: STT_MODEL (source .nemo), STT_ONNX_MODEL (export id),
STT_QUANT (profile) — no hardcoded literals. NeMo/ORT imports are LAZY inside main()
so this module byte-compiles in the GPU-less, ORT-less sandbox.

Do NOT commit any produced .onnx/.bin/.model artifact (multi-GB — baked at build).
"""
from __future__ import annotations

import os
import sys

_VALID_QUANT = ("int8-dynamic", "int4-kquant")


def _resolve_env() -> tuple[str, str, str, str]:
    """Read + validate the single-sourced tags; fail fast with a clear message."""
    try:
        source_model = os.environ["STT_MODEL"]
        onnx_model = os.environ["STT_ONNX_MODEL"]
    except KeyError as exc:  # pragma: no cover - operator build gate only
        raise SystemExit(f"{exc.args[0]} is not set — supplied by docker-compose build/env") from exc
    quant = os.environ.get("STT_QUANT", "int8-dynamic")
    if quant not in _VALID_QUANT:
        raise SystemExit(f"STT_QUANT must be one of {_VALID_QUANT}, got {quant!r}")
    out_dir = os.environ.get("STT_ONNX_DIR", "/app/onnx") + "/" + quant
    return source_model, onnx_model, quant, out_dir


def _export_graphs(model, out_dir: str) -> None:
    """Export the cache-aware encoder + decoder/joint graphs from the .nemo model.

    set_export_config({'cache_support':'True'}) is REQUIRED so the exported encoder
    carries the streaming cache I/O (cache_last_channel/time/channel_len) the ORT
    decode loop feeds back per chunk (RESEARCH §1.2). Hybrid exports as RNNT
    (encoder + decoder+joint) by default.
    """
    os.makedirs(out_dir, exist_ok=True)
    model.set_export_config({"cache_support": "True"})
    model.export(f"{out_dir}/model.onnx")  # → encoder.onnx + decoder_joint.onnx


def _quantize_encoder(out_dir: str, quant: str) -> None:
    """int8-dynamic (stock, encoder-only) default; int4-kquant is operator-gated."""
    from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: PLC0415

    enc_in = f"{out_dir}/encoder.onnx"
    if quant == "int8-dynamic":
        # Stock ORT — encoder MatMul weights → int8; decoder/joint + cache stay FP32.
        quantize_dynamic(enc_in, enc_in, weight_type=QuantType.QInt8)
        return
    # --- int4-kquant STRETCH branch (OPERATOR-GATED, NOT a stock call) ------------
    # ~0.67 GB literal STT-05 target via custom importance-weighted k-quant on the
    # encoder + operator (MHA) fusion per arXiv 2604.14493. This is a DOCUMENTED SEAM,
    # not a working stock path — the paper's custom tooling runs here at the operator
    # build gate. Do NOT claim 4-bit works out of the box.
    raise SystemExit(
        "STT_QUANT=int4-kquant is an operator-gated build (custom k-quant + MHA "
        "fusion, arXiv 2604.14493) — wire the paper's tooling here; not stock ORT.")


def _write_parity_assets(model, out_dir: str) -> None:
    """Extract the mel filterbank + SentencePiece tokenizer from the SAME .nemo.

    CRITICAL (RESEARCH §1.3): the baked filterbank.bin MUST be bit-identical to what
    the .nemo AudioToMelSpectrogramPreprocessor produces — backend_onnx recomputes
    the mel from it, and a numerical mismatch silently tanks WER. Extract it straight
    from the preprocessor's featurizer mel-filter matrix (no re-derivation).
    """
    import numpy as np  # noqa: PLC0415 - export-only dep

    fb = np.asarray(model.preprocessor.featurizer.filter_banks).astype("float32")
    # M4: assert band-major [128,257] before writing so a freq-major [257,128] tensor
    # is caught HERE (the flat .bin can't self-describe its shape, and the loader would
    # silently re-interpret a wrong orientation as [128,257]).
    band_major = (fb.shape[-2], fb.shape[-1])
    if band_major != (128, 257):
        raise SystemExit(
            f"filter_banks is {fb.shape}, expected band-major (..,128,257); "
            "transpose to [n_mels, n_fft//2+1] before writing (M4)")
    fb.reshape(1, fb.shape[-2], fb.shape[-1]).tofile(f"{out_dir}/filterbank.bin")  # [1,128,257]
    src = model.tokenizer.tokenizer.model_path  # SentencePiece .model inside the .nemo
    with open(src, "rb") as fin, open(f"{out_dir}/tokenizer.model", "wb") as fout:
        fout.write(fin.read())
    _write_parity_manifest(model, out_dir)


def _write_parity_manifest(model, out_dir: str) -> None:
    """Surface the preprocessor's normalize/log-guard/window config for the WER gate.

    H1: backend_onnx recomputes the mel OUTSIDE the ONNX graph, so the operator parity
    gate (10-PLACEMENT-VERIFY Gate 2) needs the actual .nemo preprocessor config to
    confirm backend_onnx matches it (normalize mode, log_zero_guard_*, window
    periodicity, STFT centering). Dump the live values rather than re-deriving them.
    """
    import json  # noqa: PLC0415 - export-only dep

    feat = model.preprocessor.featurizer
    manifest = {
        "normalize": getattr(feat, "normalize", None),
        "log_zero_guard_type": getattr(feat, "log_zero_guard_type", None),
        "log_zero_guard_value": getattr(feat, "log_zero_guard_value", None),
        "n_fft": getattr(feat, "n_fft", None),
        "hop_length": getattr(feat, "hop_length", None),
        "win_length": getattr(feat, "win_length", None),
    }
    with open(f"{out_dir}/mel_parity.json", "w") as fout:
        json.dump(manifest, fout, indent=2, default=str)


def main() -> None:
    """Operator entry: export → quant → parity assets. Heavy imports are lazy."""
    import nemo.collections.asr as nemo_asr  # noqa: PLC0415 - export-only dep

    source_model, onnx_model, quant, out_dir = _resolve_env()
    print(f"export_onnx: {source_model} → {onnx_model} ({quant}) → {out_dir}", file=sys.stderr)
    model = nemo_asr.models.ASRModel.from_pretrained(source_model)
    model.eval()
    _export_graphs(model, out_dir)
    _quantize_encoder(out_dir, quant)
    _write_parity_assets(model, out_dir)
    print("export_onnx: wrote encoder.onnx + decoder_joint.onnx + filterbank.bin + tokenizer.model",
          file=sys.stderr)


if __name__ == "__main__":
    main()
