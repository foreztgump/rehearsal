# Rehearsal

Local-first, private voice practice with expert personas.

<p align="center">
  <img src="docs/assets/rehearsal-demo.gif" alt="Rehearsal UI: pick a persona, speak, and get a near-real-time spoken reply — all running locally." width="820">
  <br>
  <em>Pick a persona and practice out loud — fast, near-real-time replies (voice-to-voice P50 &lt; 1.0s), 100% local. <sub>(UI preview)</sub></em>
</p>

Rehearsal lets you pick a persona, choose a practice mode, optionally add local
reference documents, and speak with the agent in your browser. STT, LLM, TTS,
LiveKit, and browser assets run locally or on your LAN; audio, transcripts, KB
files, and prompts are not sent to cloud inference services.

Current release: `0.3.0`

## Quick Start

Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.ps1 | iex
```

Already cloned:

```bash
./install.sh
```

```powershell
.\install.ps1
```

Open `http://localhost:3000` in Chromium or Chrome. Firefox blocks loopback
WebRTC candidates by default.

Full prerequisites, platform notes, download sizes, troubleshooting, and an
AI-agent install prompt are in [INSTALLATION.md](INSTALLATION.md).

## Platform Support

| Host | Status |
| --- | --- |
| Linux NVIDIA | Primary supported path. |
| Windows NVIDIA | Supported with Docker Desktop WSL2 and a current NVIDIA driver. |
| Linux AMD | Best effort via the ROCm compose override. |
| Windows AMD | Best effort: native Windows Ollama plus Docker CPU services. |
| macOS (Apple Silicon) | Best effort: native host Ollama + Kokoro TTS (both Metal) plus Docker CPU services. |
| No supported GPU | Best effort only; not expected to hit live voice latency targets. |

On AMD / no-GPU Linux hosts the installer automatically layers the CPU compose
overrides (`docker-compose.cpu-llm.yml` + `docker-compose.cpu-tts.yml` via
`COMPOSE_FILE` in `.env`) so ollama + kokoro run on CPU and the stack boots — CPU
inference will not meet the live-voice latency target.

Default published ports bind to `127.0.0.1`. Do not expose them to the WAN. To
serve another LAN device, follow the TLS reverse-proxy runbook in
[docs/lan-exposure.md](docs/lan-exposure.md) and keep firewall rules LAN-only.

## Daily Use

```bash
./up.sh -d
./down.sh
```

```powershell
.\up.ps1 -d
.\down.ps1
```

## Development Checks

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from ruff==0.15.20 ruff check agent stt tests
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --from basedpyright==1.39.9 basedpyright agent stt tests
npm --prefix web run typecheck
```

Some checks need Docker or GPU hardware and must run on the target host.

## Security

Run `./scripts/security-check.sh` before release-sensitive changes. Optional
package-behavior scanning is available through `./scripts/guarddog-check.sh`.
Artifact provenance is tracked in [SECURITY_PROVENANCE.md](SECURITY_PROVENANCE.md).

## Credits

Rehearsal builds on LiveKit, Ollama, NVIDIA NeMo/Parakeet/Nemotron Speech,
Kokoro-FastAPI, sherpa-onnx, Next.js, React, Three.js, TalkingHead, Docker, uv,
Ruff, BasedPyright, TypeScript, Syft, Grype, OSV-Scanner, Gitleaks, pip-audit,
GuardDog, and ShellCheck.
