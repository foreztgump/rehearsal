---
title: R7 Cross-Platform Local Installer Design
date: 2026-06-29
status: draft for user review
scope: v1.2 R7
---

# R7 - Cross-Platform Local Installer Design

## Summary

R7 makes Adept installable from a local repo checkout on Linux and native Windows.

Chosen path: **two native installers, shared profile rules**.

- Keep `install.sh` for Linux.
- Add `install.ps1` for native Windows PowerShell.
- Add a Windows system check beside the existing Linux doctor.
- Detect OS, Docker, GPU vendor, VRAM, Ollama, and viable deployment profile.
- Offer to install safe prerequisites after confirmation.
- Write `.env` with the selected profile and recommended LLM model.
- Keep GPU driver/toolkit fixes detect-and-guide by default.

R7 is not the public `curl | sh` installer yet. That comes after the repo is public.

## Goals

- Support local-first installation on Linux and native Windows.
- Support Ubuntu/Debian, Fedora, and Arch automatic prerequisite paths on Linux.
- Support Windows native PowerShell, not Git Bash or WSL-only install.
- Support NVIDIA and AMD detection on both Linux and Windows.
- Recommend a deployment profile and LLM model from detected hardware.
- Tell users they can edit `.env` and app settings after install.
- Keep all inference local.
- Keep the installer understandable and recoverable when prerequisites are missing.

## Non-Goals

- No public remote bootstrap script.
- No custom installer framework.
- No automatic GPU driver installation by default.
- No live in-app hardware or engine switching.
- No Windows AMD all-Docker ROCm profile until Docker Desktop exposes a reliable ROCm device path.
- No new model research or model ladder changes.

## Alternatives Considered

### A. Two Native Installers

Linux keeps Bash; Windows gets PowerShell. Both follow the same profile matrix.

This is selected. It satisfies native Windows support without introducing Python, Node,
or an installer framework as a new prerequisite.

### B. One Python Installer

This would share logic cleanly, but it makes Python itself a prerequisite or forces a
bootstrap step before the installer can run.

Rejected for R7.

### C. Bash-Only Windows Path

This would rely on Git Bash or WSL. It is smaller, but it does not meet the native
PowerShell requirement.

Rejected.

## Architecture

R7 adds platform-native entrypoints and keeps the profile rules simple.

| File | Purpose |
| --- | --- |
| `install.sh` | Linux installer for Ubuntu/Debian, Fedora, and Arch. |
| `install.ps1` | Native Windows PowerShell installer. |
| `scripts/gpu-doctor.sh` | Linux system and GPU check. |
| `scripts/gpu-doctor.ps1` | Windows system and GPU check. |
| `up.sh` / `down.sh` | Linux start/stop wrappers. |

Shared behavior is a documented matrix, not a shared runtime dependency. A little
duplication between Bash and PowerShell is acceptable if it keeps install-time failure
modes obvious.

## Deployment Profiles

| Host | R7 profile |
| --- | --- |
| Linux NVIDIA | Docker full stack. CPU STT default; GPU STT available after explicit profile selection. |
| Linux AMD | Docker AMD ROCm profile for Ollama/Kokoro where hardware passes; CPU STT. |
| Windows NVIDIA | Docker Desktop with WSL2 backend and NVIDIA GPU containers. |
| Windows AMD | Native Windows Ollama ROCm for LLM; Docker for agent, web, LiveKit, CPU STT, and CPU Kokoro. |
| No supported GPU | CPU/floor guidance and best-effort startup only. |

Windows AMD is intentionally hybrid:

- Native Ollama listens on `localhost:11434`.
- Docker services reach it through `host.docker.internal:11434`.
- STT stays CPU buffered Parakeet.
- TTS uses a CPU Kokoro Compose path. R7 must verify the CPU image preserves the
  OpenAI `/v1/audio/speech` endpoint and `/dev/captioned_speech` before claiming
  word-timed avatar support on this profile. If captioned speech is missing, the
  avatar falls back to Path-A/voice-only behavior.

## Installer Flow

1. User runs `./install.sh` on Linux or `.\install.ps1` on Windows.
2. Installer checks OS, package manager, Docker/Compose, Docker daemon, GPU vendor,
   VRAM, Ollama availability, and profile viability.
3. Installer offers to install safe missing prerequisites after confirmation:
   - Windows: Docker Desktop and Ollama through `winget` when available.
   - Linux: Docker/Compose/Ollama through the distro's package path when safe.
4. Installer prints the selected deployment profile and recommended LLM model.
5. User confirms before `.env` is written or changed.
6. Installer preserves existing secrets and writes only profile-specific keys.
7. Installer builds, pulls, and starts the selected stack.
8. Installer prints exact start, stop, log, and settings-edit commands.

GPU driver and toolkit issues are diagnosed and explained, not silently fixed.

## LLM Recommendation

The installer recommends actual model slots, not just hardware tiers.

| Hardware result | Recommendation |
| --- | --- |
| Weak, CPU-only, or low VRAM | Floor model |
| Most GPU hosts | Fast model |
| Comfortable GPU headroom and quality preference | Better model |

The installer should show plain labels first:

```text
Recommended LLM:
  Fast model - best default for live conversation on this machine.

Other choices:
  Floor model  - safest for weak hardware
  Better model - higher quality, more VRAM/cold-load cost

You can change this later in .env or from the app settings where available.
```

The installer writes `ADEPT_DEFAULT_MODEL=<floor|fast|better>` and preserves the
existing model slots:

- `OLLAMA_MODEL_FLOOR`
- `OLLAMA_MODEL_FAST`
- `OLLAMA_MODEL_BETTER`

Raw tags remain available in `.env` and advanced docs. Normal prompts should use
plain labels.

## Environment Writes

The installer may write:

- `LIVEKIT_API_SECRET`
- `ADEPT_DEFAULT_MODEL`
- `OLLAMA_BASE_URL` / `OLLAMA_GENERATE_URL` for native Windows Ollama profiles
- `STT_ENGINE`
- `STT_FORCE_CPU`
- `STT_BUFFERED_DEVICE`
- `STT_HEADROOM_MEASURED`
- `VRAM_TOTAL_MB` when detected
- Windows/Linux profile notes as comments when practical

It must preserve existing secrets and avoid rewriting unrelated settings.

## Error Handling

- Docker missing and user declines install: stop with exact install command.
- Docker installed but daemon is down: stop with Docker Desktop or daemon-start guidance.
- Windows Docker Desktop not using Linux containers or WSL2 backend: stop with settings guidance.
- NVIDIA detected but container GPU probe fails: guide driver/toolkit fix.
- Linux AMD missing `/dev/kfd` or `/dev/dri`: guide ROCm and permissions.
- Windows AMD native Ollama missing: offer `winget install Ollama.Ollama`.
- Windows AMD Ollama installed but no ROCm/HIP GPU: ask before falling back to CPU/best-effort.
- Any CPU fallback after a GPU profile decision requires user confirmation.

No silent fallback from GPU to CPU after profile selection.

## Deployment Checks

R7 adds a deployment smoke layer where it can be tested cheaply.

| Profile | Automated checks | Hardware checks |
| --- | --- | --- |
| CPU-only | Compose config renders; CPU STT service selected; web/LiveKit/agent/STT health where available. | Optional full voice smoke. |
| CPU + GPU | GPU LLM/TTS with CPU STT config renders; GPU STT not resident unless requested. | Ollama, Kokoro, CPU STT, and agent smoke. |
| Full GPU | `stt-gpu` config includes Ollama, Kokoro, and GPU STT reservations. | Real NVIDIA Docker GPU probe and full-stack smoke. |
| Linux AMD | AMD compose override renders; ROCm images/devices selected; NVIDIA reservations removed. | Real AMD Linux ROCm smoke. |
| Windows AMD | Native Ollama health; Docker can reach `host.docker.internal:11434`; CPU STT and CPU Kokoro services render. | Real native Ollama ROCm generation plus CPU Kokoro speech smoke. |

Hardware smoke commands should be opt-in through a flag such as
`RUN_HARDWARE_SMOKE=1` or a PowerShell equivalent.

## Testing

Required local checks:

- `bash -n install.sh up.sh down.sh scripts/gpu-doctor.sh`
- `scripts/test_install.sh`
- `scripts/test_gpu_doctor.sh`
- `scripts/test_compose_topology.sh`
- PowerShell parse checks for `install.ps1` and `scripts/gpu-doctor.ps1`
- Mocked PowerShell checks for:
  - Docker missing
  - Docker daemon down
  - Windows NVIDIA profile
  - Windows AMD native-Ollama profile
  - user declines prerequisite install
- README/profile matrix checks.
- `.env.example` includes the Windows AMD native Ollama path.
- CPU Kokoro compose path preserves the OpenAI speech endpoint; captioned-speech
  support is verified or the avatar fallback is documented.

Manual gates:

- Windows NVIDIA Docker GPU probe.
- Windows AMD native Ollama ROCm probe.
- Linux AMD ROCm Compose profile.
- Linux NVIDIA full-stack profile.

## Documentation

README should explain:

- Linux install command.
- Windows PowerShell install command.
- Supported host/profile matrix.
- Which prerequisites can be installed by the installer.
- Which GPU driver/toolkit steps are guide-only.
- How to edit `.env` manually after install.
- How to change LLM model choice later.
- Start/stop/log commands per OS.

## References

- Docker Desktop GPU support: `https://docs.docker.com/desktop/features/gpu/`
- Docker Compose GPU reservations: `https://docs.docker.com/compose/how-tos/gpu-support/`
- Ollama GPU support: `https://github.com/ollama/ollama/blob/main/docs/gpu.mdx`
- Ollama Docker ROCm path: `https://github.com/ollama/ollama/blob/main/docs/docker.mdx`
- Kokoro-FastAPI Docker images and OpenAI speech endpoint: `https://github.com/remsky/Kokoro-FastAPI`
- AMD ROCm Docker device model: `https://rocm.docs.amd.com/en/latest/conceptual/ai-pytorch-inception.html`
- AMD HIP SDK Windows component support: `https://rocm.docs.amd.com/projects/install-on-windows/en/latest/conceptual/component-support.html`

## Exit Criteria

- A Linux user can run the local installer and get a usable profile for their host.
- A Windows user can run native PowerShell and get a usable profile for their host.
- Windows AMD is supported through native Ollama ROCm plus Docker CPU STT and CPU Kokoro.
- Installer recommends an LLM model and tells users how to change it later.
- CPU-only, CPU+GPU, GPU, Linux AMD, and Windows AMD profiles have config or smoke coverage.
- No GPU driver stack is modified without explicit future work.
