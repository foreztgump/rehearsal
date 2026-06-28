"""Sandbox unit test for the Item-1 candidate-B trailing-silence drain math (15a).

Pure-fn, GPU-less: backend_common reads only optional/defaulted env (no STT_MODEL),
so it imports cleanly in the sandbox. Follows the repo's sys.path + __main__ assert
harness convention (tests/test_placement.py, stt/test_dispatch.py).

Run: ``python3 tests/test_finalize_pad.py`` or ``python3 -m pytest tests/test_finalize_pad.py``.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stt"))

import backend_common  # noqa: E402


def test_finalize_pad_pcm_is_silence_of_the_configured_duration():
    # Arrange: 640 ms default at 16 kHz mono int16 = 16000 * 0.640 * 2 bytes.
    expected_samples = backend_common.SAMPLE_RATE * backend_common.FINALIZE_PAD_MS // 1000
    expected_bytes = expected_samples * 2

    # Act
    pcm = backend_common.finalize_pad_pcm()

    # Assert: correct length AND all-zero (true silence, not garbage).
    assert len(pcm) == expected_bytes, (len(pcm), expected_bytes)
    assert pcm == b"\x00" * expected_bytes


if __name__ == "__main__":
    test_finalize_pad_pcm_is_silence_of_the_configured_duration()
    print("ok: finalize_pad_pcm")
