# Rehearsal

Local first fully private voice practice with expert personas.

Rehearsal is a local web app for practicing a subject out loud. Pick a persona,
choose a practice mode, optionally add local reference documents, then speak with
the agent through your browser. It is built for live spoken practice rather than
chat: STT, LLM, and TTS all run on your machine or LAN.

Current release: `0.2.0`

## What stays private

Audio, transcripts, uploaded knowledge base files, and model prompts are handled
locally. The default stack uses self-hosted LiveKit, local Ollama models, local
speech-to-text, and local Kokoro TTS. Browser assets are vendored so the app does
not need a CDN at runtime.

The default install binds published ports to `127.0.0.1`. Do not expose these
ports to the WAN. If you want to use another device on your LAN, use the optional
TLS setup in `certs/README.md` and keep firewall rules LAN-only.

## Quick start

Linux one-line install:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | bash
```

That clones Rehearsal into `~/rehearsal` and runs the local installer. To choose
another location:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | REHEARSAL_INSTALL_DIR="$HOME/apps/rehearsal" bash
```

Already cloned:

```bash
./install.sh
```

Windows one-line install (PowerShell):

```powershell
irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1 | iex
```

That clones Rehearsal into `%USERPROFILE%\rehearsal` and runs the local installer,
offering to install Docker Desktop + Ollama via winget. To accept the plan
non-interactively, or choose another location, use the script-block form:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1))) -Yes
$env:REHEARSAL_INSTALL_DIR = "D:\apps\rehearsal"; irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1 | iex
```

The `curl … install.sh | bash` command above also works on Windows from Git Bash —
it detects Windows and hands off to the same PowerShell installer.

Already cloned (Windows):

```powershell
.\install.ps1
```

The installer checks Docker, detects the GPU profile, creates `.env`, generates a
`LIVEKIT_API_SECRET`, asks which response models to install, builds the images,
and pulls the selected models.

Already installed:

```bash
./up.sh -d
./down.sh
```

```powershell
.\up.ps1 -d
.\down.ps1
```

Open `http://localhost:3000` in Chromium or Chrome. Firefox blocks loopback
WebRTC candidates by default, so local calls can fail unless you change the
profile-wide `media.peerconnection.ice.loopback` setting.

## Host profiles

| Host | Status |
| --- | --- |
| Linux NVIDIA | Primary path. Docker stack with CPU STT by default and GPU STT opt-in. |
| Linux AMD | ROCm compose override for Ollama and Kokoro, with CPU STT. |
| Windows NVIDIA | Docker Desktop with WSL2 backend and NVIDIA GPU containers. |
| Windows AMD | Native Windows Ollama plus Docker CPU services. Best effort. |
| No supported GPU | Best effort only. It will not hit live voice latency targets. |

For NVIDIA hosts, install the NVIDIA Container Toolkit before starting the stack:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Check Docker GPU access:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## Models

The installer writes the model picker configuration into `.env`:

| Key | Purpose |
| --- | --- |
| `REHEARSAL_MODEL_CHOICES` | Installed model keys, such as `fast,better` or `floor`. |
| `NEXT_PUBLIC_REHEARSAL_MODEL_LABELS` | Labels shown in the web picker. Rebuild `web` after changing this. |
| `REHEARSAL_DEFAULT_MODEL` | Model key used when a new session starts. |

Raw Ollama tags stay in `.env` as `OLLAMA_MODEL_FAST`, `OLLAMA_MODEL_BETTER`,
and `OLLAMA_MODEL_FLOOR`. The UI only sends the plain model key to the agent.

To change the installed model set later, edit the keys above, rebuild the web
image, and rerun the pull script:

```bash
docker compose build web
./ollama/pull-and-pin.sh
```

## Speech-to-text

`STT_ENGINE=buffered` is the supported path. It uses Parakeet for accurate final
transcripts. The default stack routes STT to the CPU service so the GPU has more
room for the LLM and TTS.

On a tested 16 GB or larger NVIDIA GPU, you can opt into GPU STT:

```bash
docker compose --profile stt-gpu up
```

Use `./scripts/gpu-doctor.sh` for host advice. It prints recommended `.env`
settings and does not change files.

## Development checks

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from ruff==0.15.20 ruff check agent stt tests
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from basedpyright==1.39.9 basedpyright agent stt tests
npm --prefix web run typecheck
```

Some checks need Docker or GPU hardware and are meant to run on the target host.

## Security checks

Run the local baseline before release-sensitive changes:

```bash
./scripts/security-check.sh
```

It runs:

- `npm ci`, `npm audit --omit=dev`, and `npm audit signatures`
- `pip-audit` through `uvx`
- OSV-Scanner over the repo
- Syft to write a CycloneDX source SBOM
- Grype against that SBOM
- Gitleaks against tracked source
- ShellCheck when installed
- a small suspicious-pattern scan with `rg`

Reports are written to `security/reports/`, which is ignored by git.

For slower package-behavior review, run:

```bash
./scripts/guarddog-check.sh
```

GuardDog scans direct npm dependencies and Python requirement manifests for
malicious-package signals. Capability-style findings can be noisy, so the script
only blocks on high-confidence malicious rules.

See `SECURITY_PROVENANCE.md` for Docker images, model artifacts, vendored browser
assets, and known pinning gaps.

## Credits

Rehearsal stands on a lot of open source and research work:

- LiveKit and LiveKit Agents for the realtime voice session pipeline.
- Ollama for local LLM serving.
- NVIDIA NeMo, Parakeet, and Nemotron Speech for speech recognition.
- Kokoro-FastAPI and Kokoro for local text-to-speech.
- sherpa-onnx for the CPU Parakeet bundle.
- Next.js, React, and LiveKit's web client libraries for the browser app.
- Three.js and TalkingHead for the optional local avatar.
- Docker, uv, Ruff, BasedPyright, TypeScript, Syft, Grype, OSV-Scanner, Gitleaks,
  pip-audit, GuardDog, and ShellCheck for the build and review toolchain.

Upstream image and artifact details are tracked in `SECURITY_PROVENANCE.md`.
