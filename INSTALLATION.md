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

The default installer path is NVIDIA-first. Treat AMD as manual until it has
been validated on your exact ROCm host.

### Windows AMD

Windows AMD is best effort. Run native Windows Ollama for the LLM, then use the
Windows AMD plus CPU TTS overrides:

```powershell
docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml -f docker-compose.cpu-tts.yml up -d
```

The Docker stack reaches native Ollama through `host.docker.internal:11434`.

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
| `alpine:3.21` | 4 MB | Windows AMD Ollama stub. |
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

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `docker` not found after `winget` install | Current terminal has stale PATH. | Open a fresh terminal or add Docker Desktop's CLI path, then rerun. |
| Docker Desktop installed but `docker compose` fails | Engine not running or first-run UI not accepted. | Start Docker Desktop, accept prompts, wait for Engine running. |
| Container GPU probe fails after driver update | WSL2 GPU mount is stale. | `wsl --shutdown`, restart Docker Desktop, or reboot. |
| `cuda>=12.8` runtime error | NVIDIA driver is too old for the Kokoro CUDA image. | Update the NVIDIA driver, then rerun `.\scripts\gpu-doctor.ps1` or `./scripts/gpu-doctor.sh`. |
| Browser cannot connect after WSL restart | Docker port proxies are stale. | Run `docker compose down`, then `docker compose up -d`. |
| Agent crash-loops with `ws_url is required` | Missing `LIVEKIT_URL`. | PR #1 fixes this in compose; rebuild from the latest branch. |
| Agent loops during prewarm | Cold model load exceeded worker init timeout. | PR #1 raises `AGENT_INIT_TIMEOUT_S` default to 300s. |
| `/api/stt-debug` 502 | GPU STT debug endpoint is not running in default CPU-STT mode. | Harmless; the frontend debug window is disabled. |

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
