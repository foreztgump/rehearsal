# Installation Manual

This page is the user-facing install guide for Rehearsal. It covers what the
installer does, what the host must already provide, and how much network/disk
space to expect on the first run.

Checked against upstream docs and registry metadata on 2026-07-01.

## What The Installer Does

The one-line installer clones Rehearsal, creates `.env`, generates
`LIVEKIT_API_SECRET`, asks which response model tier to install, builds the local
images, starts Ollama, pulls and pins the selected model tags, then starts the
stack.

Default services:

| Service | Purpose |
| --- | --- |
| `livekit-server` | Local WebRTC room server. |
| `agent` | LiveKit Agents voice pipeline worker. |
| `ollama` | Local LLM server. |
| `kokoro` | Local TTS server. |
| `nemo-stt-cpu` | Default CPU speech-to-text server. |
| `web` | Browser UI on `http://localhost:3000`. |

The GPU STT service, `nemo-stt`, is opt-in with `--profile stt-gpu`.

## Prerequisites

### All Platforms

- Git.
- Docker with the Compose v2 subcommand: `docker compose version`.
- Chromium or Chrome for the local browser session.
- At least 60 GB free disk for a first build; 100 GB is more comfortable.
- A supported GPU for live voice latency. The best-tested target is NVIDIA with
  16 GB VRAM or more.

Firefox is not recommended for local use because it blocks loopback WebRTC
candidates by default.

### Linux NVIDIA

Install Docker Engine plus the Compose v2 plugin, a driver that advertises CUDA
12.8 or newer, then install and configure the NVIDIA Container Toolkit:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify GPU containers:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

Run the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | bash
```

Choose another install directory:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | REHEARSAL_INSTALL_DIR="$HOME/apps/rehearsal" bash
```

### Windows NVIDIA

Use Docker Desktop with the WSL2 backend. Docker's current Windows WSL2 backend
requirements include WSL 2.1.5 or later, Windows 11 23H2 build 22631 or later
or Windows 10 22H2 build 19045, 8 GB system RAM, SLAT, and hardware
virtualization enabled.

Install Git for Windows, PowerShell, Docker Desktop, and a current NVIDIA driver
that advertises CUDA 12.8 or newer. The installer can offer Docker Desktop and
Ollama through `winget`, but Docker Desktop still needs first-run UI acceptance.

Run:

```powershell
irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1 | iex
```

The Linux `curl ... install.sh | bash` command also works from Git Bash on
Windows; it detects Windows and hands off to `install.ps1`.

Non-interactive install:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1))) -Yes
```

Install somewhere else:

```powershell
$env:REHEARSAL_INSTALL_DIR = "D:\apps\rehearsal"
irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1 | iex
```

If Docker Desktop or a driver was just installed, open Docker Desktop, accept the
service agreement, wait for "Engine running", then open a fresh terminal.

After an NVIDIA driver update, if Windows `nvidia-smi` works but containers
cannot see the GPU, run:

```powershell
wsl --shutdown
```

Then restart Docker Desktop, or reboot.

### Linux AMD

Linux AMD is best effort. Use the ROCm override after the normal checkout:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.amd.yml docker compose up -d
```

On Linux the `COMPOSE_FILE` separator is `:`; on Windows it is `;` (the `:`
collides with drive letters), so on Windows use explicit `-f` flags instead of
`COMPOSE_FILE`.

The default installer path is NVIDIA-first. Treat AMD as manual until it has
been validated on your exact ROCm host.

### Windows AMD

Windows AMD is best effort and **manual** — the one-line installer does not drive
it. On AMD the LLM runs in **native host Ollama** (not a container); only the CPU
services run in Docker. `install.ps1` detects AMD and prints these steps, then
stops, so it never silently runs the wrong NVIDIA topology.

Consumer RDNA cards (for example the RX 6600 XT / gfx1032) are off Ollama's ROCm
support list, so native Ollama falls back to CPU unless you force its **Vulkan**
backend. Vulkan is the one GPU lever on those cards.

1. Install native Ollama, then reopen PowerShell so `ollama` is on `PATH`:

   ```powershell
   winget install -e --id Ollama.Ollama
   ```

2. Force the Vulkan backend and make it permanent (the Ollama tray app is a
   background process, so a per-session variable is lost on restart). Restart
   Ollama so it picks the variables up:

   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_LLM_LIBRARY", "vulkan", "User")
   [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
   Get-Process ollama* | Stop-Process -Force; Start-Process ollama
   ```

3. Pull the model into native Ollama (not the container) and confirm GPU use:

   ```powershell
   ollama pull evalengine/unbound-e2b:latest
   ollama ps   # the PROCESSOR column should show GPU, not 100% CPU
   ```

4. Scaffold `.env` and pin the single installed model. When you narrow to one
   model, write all five keys as **uncommented** active lines (leaving the
   `.env.example` comments in place makes the picker surface empty tiers that
   crash the agent):

   ```powershell
   Copy-Item .env.example .env
   # set a long random LIVEKIT_API_SECRET, then set the model config:
   #   REHEARSAL_MODEL_CHOICES=fast
   #   NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=Fast
   #   REHEARSAL_DEFAULT_MODEL=fast
   #   OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest
   #   OLLAMA_MODEL=evalengine/unbound-e2b:latest
   ```

5. Build and start with the AMD plus CPU TTS overrides. Use explicit `-f` flags —
   the `COMPOSE_FILE=...:...` colon form fails on Windows (the `:` collides with
   drive letters):

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml `
     -f docker-compose.cpu-tts.yml up -d --build
   ```

The Docker stack reaches native Ollama through `host.docker.internal:11434`. On an
8 GB Vulkan card, prefer the `fast` model; the first turn is slow while the model
loads, and it will not hit the sub-second P50 the 16 GB NVIDIA target aims for.

### macOS (Apple Silicon)

macOS is best effort and **manual** — the one-line installer detects macOS, prints
these steps, then stops. Docker Desktop on Mac runs Linux containers in a VM with
**no GPU passthrough**, so the Apple GPU (Metal/MPS) is unreachable from any
container. The LLM therefore runs in **native host Ollama** (the Ollama Mac app,
which is Metal/MLX-accelerated on Apple Silicon) and only the CPU services run in
Docker — the same split as Windows AMD. The Docker stack reaches native Ollama
through `host.docker.internal:11434`.

Apple Silicon (M-series) is the recommended target. Intel Macs work too, on the
same topology, but Ollama falls back to CPU there.

1. Install the native Ollama Mac app from https://ollama.com/download, then reopen
   a terminal so `ollama` is on `PATH`:

   ```bash
   ollama --version
   ```

2. Widen Ollama's bind so containers can reach it. Native Ollama binds `127.0.0.1`
   by default, so `host.docker.internal` requests are refused until you set
   `OLLAMA_HOST`, then restart the Ollama app:

   ```bash
   launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
   ```

   **Security note:** this binds Ollama's *unauthenticated* API to all interfaces,
   so model inference becomes reachable by other devices on your LAN. `0.0.0.0` is
   required only because the Docker VM's `host.docker.internal` cannot reach a
   `127.0.0.1`-only bind. Keep the macOS firewall on, stay off untrusted networks,
   and never port-forward `11434` to the WAN (same posture as the `127.0.0.1`
   default-port rule for the rest of the stack).

3. Pull the recommended model into **native** Ollama (not the container), then
   confirm it is loaded:

   ```bash
   ollama pull evalengine/unbound-e2b:latest
   ollama ps
   ```

   The default ladder tags are **abliterated GGUF** finetunes. GGUF already runs
   GPU-accelerated on Metal via Ollama, and — critically for a voice **persona**
   trainer — they will not refuse a difficult persona. Recommended tier: `fast`
   (on 8 GB Macs choose `floor`).

   **MLX opt-in (advanced, max speed):** Ollama's MLX engine is even faster on
   Apple Silicon, but its model tags are **stock Google Gemma 4 — content
   filtered**, so the persona is no longer the sole guardrail and the model may
   refuse a hostile/difficult character. Opt in only if you accept that tradeoff:

   ```bash
   ollama pull gemma4:e2b-nvfp4      # or gemma4:e4b-mlx-bf16 for the Better tier
   ```

4. Scaffold `.env` and pin the single installed model. When you narrow to one
   model, write all five keys as **uncommented** active lines (leaving the
   `.env.example` comments in place makes the picker surface empty tiers that
   crash the agent):

   ```bash
   cp .env.example .env
   # set a long random LIVEKIT_API_SECRET, then set the model config:
   #   REHEARSAL_MODEL_CHOICES=fast
   #   NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=Fast
   #   REHEARSAL_DEFAULT_MODEL=fast
   #   OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest
   #   OLLAMA_MODEL=evalengine/unbound-e2b:latest
   ```

5. Build and start with the macOS plus CPU TTS overrides:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.macos.yml \
     -f docker-compose.cpu-tts.yml up -d --build
   ```

TTS (Kokoro) runs on CPU in Docker via the `cpu-tts` override, and **it is the
dominant latency cost on macOS**. Measured on an M5, native Ollama on Metal keeps
the LLM fast (time-to-first-token P50 ~640 ms), but CPU Kokoro TTS time-to-first-
byte runs ~1.5–2.0 s, pushing voice-to-voice to roughly 2–3 s — well above the
sub-second P50 the 16 GB NVIDIA target aims for. The stack is fully usable, just
not snappy.

Most of that TTS cost appears to be Docker-VM overhead rather than the lack of a
GPU: for an 82M model, PyTorch/MPS carries per-op dispatch overhead that can make
it *no faster* (sometimes slower) than the ONNX CPU path, so a native Metal (MPS)
Kokoro via the upstream `start-gpu_mac.sh` is **not** an obvious win and is out of
scope here (it would also add a second native host service). Running Kokoro
natively at all — even on CPU — is the more promising follow-up, but it is
unmeasured on this stack; treat lower macOS TTS latency as a future optimization.
The first turn is additionally slow while models warm.

#### macOS validation checklist

Run these in order after `docker compose ... up -d` to confirm the topology end to
end (verified on an M5):

1. **Ollama recent + bind widened:** `ollama --version`, then confirm the bind —
   `launchctl getenv OLLAMA_HOST` prints `0.0.0.0:11434`, and the Ollama app was
   restarted after step 2.
2. **Model loaded on Metal:** `ollama ps` lists the pulled tag with a non-zero
   size (loaded), not just present in `ollama list`.
3. **Reachable host → container** (this is the step the `OLLAMA_HOST` bind fixes):

   ```bash
   curl -s http://localhost:11434/v1/models        # from the host
   docker run --rm curlimages/curl \
     -s http://host.docker.internal:11434/v1/models # from inside a container
   ```

   Both must return the model list. A refused container-side request means
   `OLLAMA_HOST` is still `127.0.0.1` (redo step 2 and restart Ollama).
4. **Services healthy on arm64:** `docker compose ps` shows `livekit-server`,
   `agent`, `kokoro`, `nemo-stt-cpu`, and `web` up; `agent` logs reach
   `registered worker` (`docker compose logs -f agent`).
5. **One voice-to-voice turn:** open `http://localhost:3000`, grant the mic, pick a
   persona, and complete a spoken turn (mic → transcript → spoken reply).

### No Supported GPU

No-GPU mode is best effort only. CPU STT is the default, but local LLM and TTS
latency will not meet the live voice target without a supported GPU profile.

## Download Size Expectations

Sizes are approximate compressed downloads for amd64 unless noted. Docker
unpacks layers and keeps build cache, so on-disk usage is much larger.

| Item | Approx download | When used |
| --- | ---: | --- |
| `livekit/livekit-server:v1.10.1` | 35 MB | All installs. |
| `ollama/ollama:0.30.11` | 3.39 GB | NVIDIA/default LLM container. |
| `ollama/ollama:0.30.11-rocm` | 1.46 GB | Linux AMD override. |
| `ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128` | 8.10 GB | NVIDIA/default TTS. |
| `ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0` | 1.66 GB | CPU TTS override. |
| `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0` | 13.02 GB | Linux AMD TTS override. |
| `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` | 68 MB | Agent build base. |
| `node:24-bookworm-slim` | 80 MB | Web build/runtime base. |
| `python:3.11-slim` | 45 MB | CPU STT runtime stage. |
| `alpine:3.21` | 4 MB | Windows AMD / macOS Ollama stub. |
| `nvcr.io/nvidia/nemo:25.11` | 19.44 GB | GPU STT runtime and CPU STT export builder. |
| Sherpa ONNX Parakeet int8 bundle | 482 MB | Baked into STT images. |

Selected Ollama model downloads add more:

| Model tier | Approx footprint |
| --- | ---: |
| Fast | About 1.6 GB observed on the Windows field test. |
| Better | About 5.3 GB per the pinned ladder comment. |
| Floor | About 2.5 GB for the first rung, 1.1 GB for the smaller fallback. |

Practical first-run expectations:

| Path | Plan for |
| --- | --- |
| Linux/Windows NVIDIA default | 30+ GB network before npm/Python/model cache variance; 60-100 GB free disk. |
| GPU STT opt-in | Adds the heavy NeMo GPU STT runtime and baked model path. |
| Linux AMD ROCm | Large ROCm TTS image; keep 100 GB free disk. |
| Windows AMD | Smaller Docker stack, but native Ollama model storage still lives on the host. |
| macOS (Apple Silicon) | Smaller Docker stack (arm64 images); native Ollama model storage lives on the host. |

## First Run

After install, open:

```text
http://localhost:3000
```

Useful checks:

```bash
docker compose ps
docker compose logs -f agent
```

```powershell
docker compose ps
docker compose logs -f agent
```

The first turn can be slow while models warm. That is expected; a permanent
agent restart loop is not.

## Upgrading From A Pre-Rename Install

The project's compose name is `rehearsal`. Installs created before the rename ran
under the `voice-trainer` project (derived from the old directory name), so after
upgrading you may see two issues:

- **`down` stops nothing.** `docker compose down` targets the `rehearsal` project
  and leaves the old `voice-trainer-*` containers up. Stop them once, explicitly:

  ```bash
  docker compose -p voice-trainer down
  ```

- **Models look missing.** The fresh `rehearsal` project creates an empty
  `rehearsal_ollama-models` volume; your pulled models still live in the old
  `voice-trainer_ollama-models` volume. Re-pull into the new volume with the
  installer (or `./ollama/pull-and-pin.sh`), or copy the old volume's contents
  over with a one-off `docker run ... -v` if you want to avoid re-downloading.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `docker` not found after `winget` install | Current terminal has stale PATH. | Open a fresh terminal or add Docker Desktop's CLI path, then rerun. |
| Docker Desktop installed but `docker compose` fails | Engine not running or first-run UI not accepted. | Start Docker Desktop, accept prompts, wait for Engine running. |
| Container GPU probe fails after driver update | WSL2 GPU mount is stale. | `wsl --shutdown`, restart Docker Desktop, or reboot. |
| `cuda>=12.8` runtime error | NVIDIA driver is too old for the Kokoro CUDA image. | Update the NVIDIA driver, then rerun `.\scripts\gpu-doctor.ps1` or `./scripts/gpu-doctor.sh`. |
| Browser cannot connect after WSL restart | Docker port proxies are stale. | Run `docker compose down`, then `docker compose up -d`. |
| Agent crash-loops with `ws_url is required` | Missing `LIVEKIT_URL`. | Fixed in compose (agent sets `LIVEKIT_URL`); rebuild from the latest tree. |
| Agent loops during prewarm | Cold model load exceeded worker init timeout. | `AGENT_INIT_TIMEOUT_S` defaults to 300s; raise it further on very slow hosts. |
| Agent stuck on "Listening to you..."; logs show `Connection error.` | `.env` selects GPU STT (`STT_FORCE_CPU=0` + `STT_HEADROOM_MEASURED=1`) but the opt-in `stt-gpu` profile is not running. | Start it: `docker compose --profile stt-gpu up -d nemo-stt` (or `COMPOSE_PROFILES=stt-gpu ./up.sh -d`). `up.sh`/`up.ps1` warn about this. |
| First turn slow / not sub-second on a small GPU | Cold STT/LLM/TTS warmup and/or sub-16GB VRAM. | Expected. The installer defaults `<=8GB` NVIDIA cards to the `floor` model; wait for `registered worker` in the agent logs. |
| `./down.sh` stops nothing after upgrading | Pre-rename containers ran under the old `voice-trainer` compose project (now `rehearsal`). | Stop the old project once: `docker compose -p voice-trainer down`. See "Upgrading from a pre-rename install". |

## AI-Agent Install Prompt

Use this prompt with a local coding agent that can run shell commands on your
machine:

```text
Install Rehearsal on this machine.

Rules:
- Keep everything local. Do not use cloud inference endpoints.
- Read README.md and INSTALLATION.md first.
- Detect OS, GPU vendor, VRAM, Docker/Compose status, and browser.
- For Windows, verify Docker Desktop uses WSL2 and tell me if first-run UI or UAC approval is needed.
- For NVIDIA, run the GPU doctor before building and stop to report any CUDA, driver, or container-GPU issue.
- Use the official one-line installer unless this is already a clone.
- After install, run docker compose ps and docker compose logs --tail=80 agent.
- Open Rehearsal at http://localhost:3000 only after the stack is healthy.
- If a command fails, show the exact command, exit code, and last relevant output. Do not keep retrying blindly.
```

## Sources Checked

- Docker Desktop Windows install docs: https://docs.docker.com/desktop/setup/install/windows-install/
- Docker Desktop WSL2 backend docs: https://docs.docker.com/desktop/features/wsl/
- Docker Compose install docs: https://docs.docker.com/compose/install/
- NVIDIA Container Toolkit install docs: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- NVIDIA Docker specialized config docs: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
- Microsoft WSL GPU compute docs: https://learn.microsoft.com/en-us/windows/wsl/tutorials/gpu-compute
- LiveKit Agents worker/environment docs via Context7: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and `initialize_process_timeout`.
- Docker Hub tag APIs and raw OCI manifests for the pinned image sizes.
