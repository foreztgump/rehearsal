# macOS TTS benchmark: three arms through one HTTP contract

To decide whether native Kokoro is worth adding to the macOS topology, we benchmark
three arms through the identical Kokoro-FastAPI `/dev/captioned_speech` HTTP contract
the agent uses: **Docker-CPU** (shipped baseline), **native-CPU**, and **native-Metal**
(PyTorch/MPS via upstream `start-gpu_mac.sh`).

## Revised at execution time (see Status)

The original plan put native-CPU on **ONNX** to make `Docker-CPU → native-CPU` a clean
test of the leading hypothesis (that most of the ~1752 ms macOS TTFB is Docker-VM overhead,
not the missing GPU). **On inspection this was not buildable:** current upstream
Kokoro-FastAPI (v0.6.0-rc1) has dropped the ONNX runtime entirely — `start-cpu.sh` sets
`USE_ONNX=false` and installs `torch` (`.[cpu]`), and there is no `onnxruntime` dependency
anywhere in its `pyproject.toml`. Metal (`start-gpu_mac.sh`) is likewise PyTorch (`DEVICE_TYPE=mps`).

So **both native arms run PyTorch.** The consequences of that:

- `native-CPU → native-Metal` is now the **clean, both-PyTorch CPU-vs-MPS test** — exactly
  the comparison that isolates whether the Apple GPU helps this 82M model.
- `Docker-CPU → native-CPU` still answers the dominant "does escaping Docker help?" question
  (both CPU), but with a v0.5.0→v0.6.0-rc1 image-version skew folded in — noted, not controlled.

An additional live signal reshaped the premise: the isolated Docker-CPU baseline measured
**~799 ms P50**, roughly half the ~1752 ms seen in-stack. That points at pipeline co-residency
contention, not Docker-VM overhead, as the real in-stack cost — weakening the original
motivation for going native at all.

## Considered Options

- **Pin the native clone to v0.5.0** to kill the version skew — rejected as extra yak-shaving
  once the baseline already showed native is unlikely to clear the ADR-0002 bar.
- **A fourth arm** to separate version from backend — rejected as over-scoped on a scarce
  physical M5.
