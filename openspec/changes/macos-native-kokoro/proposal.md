# macOS native-host Kokoro TTS (Metal default, CPU fallback)

## Why

On macOS today the stack runs Kokoro TTS as a **CPU container** (`docker-compose.cpu-tts.yml`),
because Docker Desktop on Mac has no GPU passthrough. Benchmarking on a real M5 (see
`docs/macos-tts-benchmark-results.md` + `docs/adr/0001`/`0002`) measured that container path
at ~799 ms P50 and showed a **native-host Kokoro on Metal/MPS reaches ~256 ms P50** — and
still beats native-CPU (485 ms) even while Ollama saturates the same Metal GPU. This mirrors
the topology decision the repo already made for the LLM: the GPU is only reachable from a
native host process, so Kokoro should join Ollama as a **second native host service**, with
the Docker `kokoro` container reduced to a no-op stub.

## What Changes

- **`docker-compose.macos.yml`** — stub the `kokoro` service (copy the existing `ollama`
  stub: `alpine:3.21` / `sleep infinity` / `ports: !reset []` / devices `!reset []`) and add
  `KOKORO_BASE_URL=http://host.docker.internal:8880/v1` to `agent.environment` beside the
  existing `OLLAMA_BASE_URL`. Consequence: macOS no longer loads `docker-compose.cpu-tts.yml`
  — the up command becomes the 2-file form.
- **`scripts/kokoro-native-macos.sh`** (new) — bring-up helper that encodes the upstream
  gotchas found during benchmarking: `brew install uv espeak-ng`, clone Kokoro-FastAPI pinned
  to `v0.5.0`, set `ESPEAK_DATA_PATH` to the brew path, create the venv + install `.[cpu]`
  explicitly (working around upstream's install-before-venv bug), then launch
  `uvicorn api.src.main:app --host 0.0.0.0 --port 8880`. **Default Metal**
  (`USE_GPU=true DEVICE_TYPE=mps PYTORCH_ENABLE_MPS_FALLBACK=1`); `--cpu` selects the CPU
  fallback. A `stop` subcommand kills the backgrounded server.
- **`install.sh`** — extend `show_macos_guidance_and_exit()` with native-Kokoro steps
  (run the helper, verify `curl -sf http://localhost:8880/health`) and drop
  `-f docker-compose.cpu-tts.yml` from the printed step-5 up command.
- **`INSTALLATION.md`** — flip the macOS latency note from "native Kokoro is unmeasured" to
  the measured result (native Metal ~256 ms P50; CPU ~433 ms as the documented fallback),
  add a native-Kokoro bring-up subsection + a health-check validation line, and update the
  up command to the 2-file form.
- **`CHANGELOG.md` `[Unreleased]`** — Added: native-host Kokoro helper + macOS override;
  Changed: macOS default TTS is native Metal, not the CPU-TTS container.
- **`.gitignore`** — carve the decision record back in (`!docs/adr/`,
  `!docs/macos-tts-benchmark-results.md`) since `docs/*` is otherwise ignored.

BREAKING: operator-facing only — the macOS `docker compose … up` command drops the
`-f docker-compose.cpu-tts.yml` file. No agent/web code changes; the `KOKORO_BASE_URL`
contract is unchanged (only its value differs on macOS).

## Capabilities

None new. This is a deployment-topology change for an existing capability (macOS TTS),
reusing the established native-host-Ollama pattern; no SHALL/MUST behavior changes, so no
`specs/` capability spec is warranted (PONYTAIL). `design.md` is skipped — the design
decisions are already recorded in `docs/adr/0001` and `docs/adr/0002`.

## Recorded design decisions (see ADRs)

- **Metal default, CPU fallback** — `docs/adr/0002` (measured: Metal wins isolated and under
  GPU contention; the earlier CPU-default recommendation was retracted).
- **Pin `v0.5.0`** — `docs/macos-native-kokoro-scope.md` (highest real tag; matches the
  Docker baseline image; voice parity verified).
- **Helper = bring-up + `stop` only** — not full lifecycle; native Ollama is likewise
  user-managed after first bring-up.
