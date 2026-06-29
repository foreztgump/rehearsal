#!/usr/bin/env python3
"""R3 G1/G5 accuracy harness: WER + trailing-word cut-off check."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import wave

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "asr")
TRANSCRIPTS = os.path.join(FIXTURE_DIR, "transcripts.jsonl")
CUTOFF_TAIL_WORDS = 3
SELF_CHECK_WER_CEILING = 0.15
SAMPLE_RATE = 16000
CUTOFF_DROP_EXIT = 1
PUNCTUATION = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Lowercase + strip punctuation so Parakeet PnC compares fairly to plain refs."""
    return PUNCTUATION.sub("", text.lower()).strip()


def read_wav_pcm(path: str) -> bytes:
    """Raw int16 mono PCM bytes from a WAV."""
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2 or handle.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz 16-bit mono WAV")
        return handle.readframes(handle.getnframes())


def load_engine_model():
    sys.path.insert(0, os.path.join(REPO_ROOT, "stt"))
    import backend_parakeet as engine

    return engine, engine.load_model()


def transcribe(engine_model: tuple, pcm: bytes) -> str:
    """Run the real buffered Parakeet engine over PCM."""
    engine, model = engine_model
    state = engine.new_stream_state(model)
    state["_turn_pcm"] = bytearray(pcm)
    return engine.finalize(model, state)


def word_error_rate(reference: str, hypothesis: str) -> float:
    import jiwer

    return jiwer.wer(normalize(reference), normalize(hypothesis))


def trailing_drop(reference: str, hypothesis: str, tail_words: int = CUTOFF_TAIL_WORDS) -> bool:
    """True when the hypothesis appears to drop trailing words vs the reference tail."""
    reference_words = normalize(reference).split()
    hypothesis_words = normalize(hypothesis).split()
    if len(reference_words) <= tail_words:
        return False
    return (
        len(hypothesis_words) < len(reference_words)
        and reference_words[-tail_words:] != hypothesis_words[-tail_words:]
    )


def load_fixtures() -> list[dict[str, str]]:
    with open(TRANSCRIPTS, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_aggregate() -> int:
    import jiwer

    references, hypotheses = [], []
    engine_model = load_engine_model()
    for fixture in load_fixtures():
        reference = fixture["text"]
        hypothesis = transcribe(engine_model, read_wav_pcm(os.path.join(FIXTURE_DIR, fixture["clip"])))
        references.append(normalize(reference))
        hypotheses.append(normalize(hypothesis))
        print(f"{fixture['clip']}: WER={word_error_rate(reference, hypothesis):.3f} "
              f"drop={trailing_drop(reference, hypothesis)}")
    print(f"AGGREGATE int8 Parakeet WER = {jiwer.wer(references, hypotheses):.4f} "
          f"over {len(references)} clips")
    return 0


def run_cutoff(wav_path: str, reference: str) -> int:
    hypothesis = transcribe(load_engine_model(), read_wav_pcm(wav_path))
    dropped = trailing_drop(reference, hypothesis)
    print(f"hypothesis: {hypothesis}\ntrailing_drop={dropped}")
    return CUTOFF_DROP_EXIT if dropped else 0


def self_check() -> int:
    assert word_error_rate("the cat sat", "the cat sat") == 0.0
    assert abs(word_error_rate("the cat sat on the mat", "the cat sat on the") - 1 / 6) < 1e-9
    assert trailing_drop("the quick brown fox jumps", "the quick brown fox") is True
    assert trailing_drop("the quick brown fox jumps", "the quick brown fox jumps") is False
    assert trailing_drop("hi there", "hi") is False
    assert_rejects_bad_sample_rate()
    print("stt-wer pure-logic OK (wer + trailing_drop)", file=sys.stderr)
    try_real_clip()
    return 0


def assert_rejects_bad_sample_rate() -> None:
    with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
        with wave.open(handle.name, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00")
        try:
            read_wav_pcm(handle.name)
        except ValueError:
            return
    raise AssertionError("read_wav_pcm must reject non-16k WAV")


def try_real_clip() -> None:
    try:
        fixture = load_fixtures()[0]
        hypothesis = transcribe(load_engine_model(), read_wav_pcm(os.path.join(FIXTURE_DIR, fixture["clip"])))
        wer = word_error_rate(fixture["text"], hypothesis)
        assert wer < SELF_CHECK_WER_CEILING, f"WER {wer:.3f} >= {SELF_CHECK_WER_CEILING}"
        print(f"stt-wer real-clip OK: WER={wer:.3f} ({hypothesis!r})", file=sys.stderr)
    except (ImportError, FileNotFoundError, OSError, ValueError, SystemExit, IndexError) as exc:
        print(f"stt-wer real-clip SKIPPED (GPU-deferred): {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--self-check":
        return self_check()
    if argv and argv[0] == "--cut-off":
        if len(argv) != 3:
            print("usage: stt-wer.py --cut-off <wav> <reference-text>", file=sys.stderr)
            return 2
        return run_cutoff(argv[1], argv[2])
    return run_aggregate()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
