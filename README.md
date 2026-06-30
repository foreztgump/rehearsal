# Adept — Near-Real-Time Voice Persona Trainer

Voice-first, local-first web app for spoken practice with a configurable AI expert
persona. Self-hosted on a single 16GB-VRAM GPU via Docker Compose. See
[`.planning/PROJECT.md`](.planning/PROJECT.md) for full scope.

## Quick start

**Linux** (Ubuntu/Debian, Fedora, Arch):

```bash
./install.sh            # detect + scaffold .env + prompt for models + plan + build + pull
# …confirm the plan when prompted; then it boots the stack and prints start/stop.
```

**Windows** (native PowerShell, not WSL-only):

```powershell
.\install.ps1           # detect + scaffold .env + prompt for models + plan + build + pull
```

The installer detects Docker + GPU, scaffolds `.env` with a generated
`LIVEKIT_API_SECRET`, prompts for **which models to install** and their **aliases**
(see [Model selection](#model-selection)), shows a plan, then builds and pulls the
selected models. On Linux it offers to install missing Docker/Compose/Ollama via
your package manager (apt/dnf/pacman) behind a confirmation gate; on Windows it
offers `winget install Docker.DockerDesktop` / `Ollama.Ollama`. If you decline or
the NVIDIA Container Toolkit is missing, it prints the exact install commands and
exits non-zero. Use `./install.sh -y` (or `ASSUME_YES=1` / `.\install.ps1 -Yes`)
to accept the plan non-interactively.

Already set up? Start and stop with:

```bash
./up.sh -d              # Linux:  preflight (gpu-doctor) + docker compose up -d
./down.sh               # Linux:  clean stop (docker compose down)
```
```powershell
.\up.ps1 -d             # Windows: preflight (gpu-doctor) + docker compose up -d
.\down.ps1              # Windows: clean stop (docker compose down)
```

`./down.sh` (or `.\down.ps1`) removes the containers + network but keeps named
volumes (pulled models, caches); pass `-v` to also drop volumes (models re-pull
next boot).

Prefer to do it by hand? `cp .env.example .env`, set a `LIVEKIT_API_SECRET`, then
`./up.sh` (it runs the GPU doctor then `docker compose up` — see
[GPU setup](#gpu-setup-nvidia-container-toolkit); plain `docker compose up` works too).

## Model selection

At install time the installer asks which response models to pull and what to call
them. The web picker then shows **only the installed models** — if you install one
model, the picker shows a single read-only option instead of a dropdown. The
installer recommends a default based on your hardware (Fast on most GPUs, Floor on
weak/CPU-only hosts, Better when you want higher quality and have the VRAM).

The installed set and labels are baked into `.env`:

| `.env` key | Purpose |
|---|---|
| `ADEPT_MODEL_CHOICES` | Comma list of installed choice keys (e.g. `fast,better` or just `floor`) |
| `NEXT_PUBLIC_ADEPT_MODEL_LABELS` | Comma list of picker labels, same order (baked into the web build) |
| `ADEPT_DEFAULT_MODEL` | Which installed model the host boots on |

To **add or remove a model later**: edit `ADEPT_MODEL_CHOICES` +
`NEXT_PUBLIC_ADEPT_MODEL_LABELS` in `.env`, then `docker compose build web` (the
labels are bake-time build args, so a web rebuild is required) and re-pull the model
with `./ollama/pull-and-pin.sh`. Raw Ollama tags stay in `.env`
(`OLLAMA_MODEL_FAST` / `_BETTER` / `_FLOOR`); the picker surfaces plain labels only.

## Supported host profiles

| Host | Profile |
|---|---|
| Linux NVIDIA | Docker full stack; CPU STT default, GPU STT opt-in (`--profile stt-gpu`) |
| Linux AMD | Docker AMD ROCm (Ollama + Kokoro on GPU via `docker-compose.amd.yml`); CPU STT |
| Windows NVIDIA | Docker Desktop (WSL2 backend) + NVIDIA GPU containers |
| Windows AMD | Native Windows Ollama (CPU build, best-effort) + Docker CPU services (CPU STT, CPU Kokoro). AMD GPU inference on Windows needs a custom HIP SDK build — guide-only, not turnkey. |
| No supported GPU | CPU/floor guidance; best-effort startup (the LLM/TTS won't hit real-time latency without a GPU) |

The installer can install Docker Desktop + Ollama (winget on Windows) or
Docker/Compose/Ollama (apt/dnf/pacman on Linux) behind a confirmation gate. GPU
drivers, the NVIDIA Container Toolkit, and the AMD HIP SDK are **guide-only** —
the installer diagnoses and explains them but never installs them.

Then open **http://localhost:3000** in **Chromium/Chrome** and click *Start
talking*. That's it — no certs, no TLS, no browser config.

Why it just works: `localhost` is a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts),
so the microphone and WebRTC are available over plain HTTP — no TLS needed for a
local install. The browser talks to the web shell (`http://localhost:3000`) and
LiveKit (`ws://localhost:7880`) directly.

> **Browser note:** Chromium/Chrome is recommended. Firefox blocks loopback
> (`127.0.0.1`) WebRTC candidates by default, so an on-box Firefox call to a
> localhost server fails ("could not establish pc connection") unless you set
> `media.peerconnection.ice.loopback=true` in `about:config` — a profile-wide
> change we don't recommend. Just use Chromium for the local install.

All published ports bind to `LAN_BIND_IP` (default `127.0.0.1`) — nothing is
forwarded to the WAN. To serve **other LAN devices** (not the same machine), see
[Serving other LAN devices (optional TLS)](#serving-other-lan-devices-optional-tls)
below.

## Development checks

Python diagnostics use BasedPyright for semantic LSP/type checks and Ruff for fast
syntax/undefined-name checks. The web app uses the project-pinned TypeScript compiler.

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from ruff==0.15.20 ruff check agent stt tests
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from basedpyright==1.39.9 basedpyright agent stt tests
npm --prefix web run typecheck
```

Editors can run `basedpyright-langserver --stdio` and `ruff server` from the same
pinned dev-tool versions in [`requirements-dev.txt`](requirements-dev.txt).
R3 STT gate helpers also use that file for `scripts/stt-wer.py` (`jiwer` +
`sherpa-onnx`).

## Local security baseline

Run the local baseline before release-sensitive changes:

```bash
./scripts/security-check.sh
```

It checks npm dependencies, Python dependencies, OSV advisories, Syft SBOM output,
Grype vulnerabilities, and tracked-source secrets. Reports are written to
`security/reports/` and are not committed.

For a slower poisoned-package review, run the optional GuardDog scan:

```bash
./scripts/guarddog-check.sh
```

GuardDog looks for malicious package signals such as exfiltration, install-time
network behavior, obfuscation, typosquatting, and suspicious metadata. Its generic
capability findings can be noisy, so this script fails only on high-confidence
malicious rules and treats capability-style findings as warnings for review.

See [`SECURITY_PROVENANCE.md`](SECURITY_PROVENANCE.md) for Docker images, vendored
browser assets, model downloads, and known pinning gaps.

## GPU setup (NVIDIA Container Toolkit)

`docker compose up` on your own machine is the only supported deployment. The three
model containers — `ollama`, `kokoro`, and the GPU STT `nemo-stt` (opt-in, see below)
— need an NVIDIA GPU on that machine. STT also has an off-GPU CPU path, so the
**default boots VRAM-safe without the GPU STT** and the only host step is installing
the NVIDIA Container Toolkit.

> **Speech-to-text:** STT now uses buffered non-streaming Parakeet as the primary
> path. On good NVIDIA hardware, the GPU `nemo-stt` service runs
> `nvidia/parakeet-tdt-0.6b-v2` through NeMo for fast, accurate finals. The model is
> **baked into the image at build time** (offline-capable, no first-run download)
> and stays resident for the life of the container. The default `docker compose up`
> still boots the VRAM-safe CPU STT service (`nemo-stt-cpu`); opt into the GPU
> service with the `stt-gpu` profile.

### Install the toolkit (the only host step)

Install the NVIDIA Container Toolkit so Docker can hand the GPU to containers, then
point the Docker runtime at it:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the GPU is reachable from a container (this is the operator gate — record the
output):

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

It must print the GPU table from inside a container. Once it does, `docker compose up`
gives the model services the GPU via the `deploy.resources.reservations.devices`
blocks in `docker-compose.yml`.

### Preflight: `./up.sh`

`./up.sh` runs [`scripts/gpu-doctor.sh`](scripts/gpu-doctor.sh) first — it checks
driver → toolkit → CUDA version → VRAM in order and prints either `OK: GPU ready` or
an exact remedy plus a copy-paste env snippet, then runs `docker compose up`. It is
**advise-only** and never blocks; set `SKIP_DOCTOR=1 ./up.sh` to skip the preflight.

```bash
./up.sh            # preflight, then docker compose up
./up.sh -d         # detached
```

### Default CPU STT vs opt-in GPU STT

`docker compose up` (or `./up.sh`) brings up **CPU STT** — the VRAM-safe default
(`STT_FORCE_CPU=1`). On 16GB+ NVIDIA hardware, run buffered Parakeet on the GPU for
speed by setting `STT_FORCE_CPU=0` + `STT_HEADROOM_MEASURED=1` in `.env` and opting
into the `stt-gpu` profile:

```bash
docker compose --profile stt-gpu up
```

On a sub-spec (<16 GB) or non-NVIDIA host, the doctor recommends staying on
`STT_FORCE_CPU=1` + the Fast `OLLAMA_MODEL` and the stack still comes up usable. Note:
`ollama` and `kokoro` always need a working NVIDIA GPU — a fully non-NVIDIA host can
run STT on CPU but not the LLM/TTS (a v1.1 limitation).

### Pick your STT by hardware

`STT_ENGINE` selects the speech-recognition mode; `./scripts/gpu-doctor.sh` recommends one for your
GPU (advise-only — it never edits `.env`). All three run fully local.

| Mode | Best for | Live partials | Latency | Set in `.env` |
|---|---|---|---|---|
| `buffered` (default) | accurate English STT; no early tail drop | no | ~640ms endpoint wait + fast final pass | `STT_ENGINE=buffered` |
| `streaming` | legacy comparison only | yes | lowest STT-only latency | `STT_ENGINE=streaming` |
| `hybrid` | legacy experiment only | yes (cosmetic) | accuracy-mode | `STT_ENGINE=hybrid` |

| Detected VRAM | gpu-doctor recommends |
|---|---|
| ≥ 16 GB | `STT_ENGINE=buffered`, `STT_FORCE_CPU=0`, `STT_HEADROOM_MEASURED=1`, run `--profile stt-gpu` |
| 12 GB to < 16 GB | `STT_ENGINE=buffered`, `STT_FORCE_CPU=1` |
| < 12 GB / CPU-only | `STT_ENGINE=buffered`, `STT_BUFFERED_DEVICE=cpu` |

GPU `buffered` uses NVIDIA `parakeet-tdt-0.6b-v2` through NeMo
`ASRModel.transcribe()`. CPU `buffered` uses the baked sherpa-onnx Parakeet bundle.
This replaces the Nemotron streaming model as the supported path because live smoke
testing showed better accuracy and natural enough latency at `STT_STREAM_CHUNK_MS=320`
+ `STT_ENDPOINT_SILENCE_MS=640`.
(A `TTS_ENGINE` seam mirroring this is the v1.3 path; today TTS is Kokoro-only.)

### Diagnosing the two common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `could not select device driver "nvidia" with capabilities: [[gpu]]` | NVIDIA Container Toolkit missing / Docker runtime not configured | Run the `nvidia-ctk runtime configure --runtime=docker` step above, restart Docker |
| `capabilities is required` (compose error) | A GPU service is missing `capabilities: [gpu]` in its reservation block | Ensure each model service's `devices` entry includes `capabilities: [gpu]` |

> The first `docker compose up` builds/pulls multi-GB GPU images and bakes the STT
> model — watch `docker compose ps` for health `starting → healthy` (`start_period`
> is 180 s for GPU STT, 30 s for CPU STT). It is **not** hung. This repo does not alter
> host configuration; the toolkit install above is the only operator step, and the
> compose manifest only *reserves* the GPU once it is in place.

## LiveKit self-host networking (ICE / firewall)

LiveKit runs fully self-hosted (no LiveKit Cloud, ever). Its config lives in
[`livekit.yaml`](livekit.yaml): the server signals on TCP **7880**, accepts
ICE/TCP fallback on **7881**, and muxes **all** WebRTC media UDP over a single
port **7882** (udp mux — one firewall rule instead of a 10k range). For a local
install the browser reaches all of this over `localhost`; no firewall changes are
needed.

**Advertised IP:** WebRTC only works if the server advertises a browser-reachable
IP as its ICE host candidate. We pin it explicitly with `--node-ip` (sourced from
`LIVEKIT_NODE_IP` in `.env`) rather than `use_external_ip: true`, because the
latter reaches out to a public STUN server to discover its IP — outbound WAN
traffic that violates the local-first invariant. The default `127.0.0.1` is
correct for a local install; set it to the host's LAN IP only when serving other
LAN devices (next section).

## Serving other LAN devices (optional TLS)

Everything above is for a **local install** (browser on the same machine). To use
the app from **other devices on your LAN** (a phone, a second laptop), those
browsers reach the server over `https://<lan-ip>` — and unlike `localhost`, a raw
LAN IP is **not** a secure context, so the mic (`navigator.mediaDevices`) is
unavailable without TLS. This is the only scenario that needs certificates.

To set it up:

1. Set `LAN_BIND_IP`, `LIVEKIT_NODE_IP`, and `NEXT_PUBLIC_LIVEKIT_URL` in `.env`
   to the host's LAN IP (e.g. `192.168.1.50` / `wss://192.168.1.50:7443`).
2. Mint a LAN-trusted cert and trust the CA on every client device — see
   [`certs/README.md`](certs/README.md).
3. Add a TLS reverse proxy (e.g. Caddy) terminating `:443 → web:3000` and
   `:7443 → livekit-server:7880`, and open inbound LAN-only ports **7882/udp**,
   **7881/tcp**, **7443/tcp** (never port-forward any from the WAN).
