---
title: R7 Cross-Platform Local Installer Design
date: 2026-06-29
status: draft for user review (revised after deep-dive research + code trace)
scope: v1.2 R7
research: verified 2026-06-29 against current upstream docs (Docker, Ollama, Kokoro-FastAPI, winget, ROCm) and the live repo
---

# R7 - Cross-Platform Local Installer Design

## Summary

R7 makes Adept installable from a local repo checkout on Linux and native Windows.

Chosen path: **two native installers, shared profile rules**.

- Keep `install.sh` for Linux (Ubuntu/Debian, Fedora, Arch).
- Add `install.ps1` for native Windows PowerShell.
- Add a Windows system check (`scripts/gpu-doctor.ps1`) beside the existing Linux doctor (`scripts/gpu-doctor.sh`).
- Detect OS, Docker, GPU vendor, VRAM, Ollama availability, and a viable deployment profile.
- Offer to install safe prerequisites after confirmation.
- Prompt for **which models to install** and **user-chosen aliases**, then pull only those. The web picker shows only the installed models; a single-model install shows a single option.
- Write `.env` with the selected profile, installed model tags + aliases, and the recommended default.
- Keep GPU driver/toolkit fixes detect-and-guide by default.

R7 is not the public `curl | sh` installer yet. That comes after the repo is public.

## Goals

- Support local-first installation on Linux and native Windows.
- Support Ubuntu/Debian, Fedora, and Arch automatic prerequisite paths on Linux.
- Support Windows native PowerShell, not Git Bash or WSL-only install.
- Support NVIDIA and AMD detection on both Linux and Windows.
- Recommend a deployment profile and LLM model from detected hardware.
- Let the user choose at install time which models to pull and what to name them; the picker reflects that choice.
- Tell users they can edit `.env` and app settings after install.
- Keep all inference local.
- Keep the installer understandable and recoverable when prerequisites are missing.

## Non-Goals

- No public remote bootstrap script.
- No custom installer framework.
- No automatic GPU driver installation by default.
- No live in-app hardware or engine switching.
- No Windows AMD all-Docker ROCm profile (Docker Desktop has no reliable ROCm device path; AMD GPU inference on Windows is a custom HIP SDK build, not a turnkey path — see Windows AMD below).
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
| `scripts/gpu-doctor.sh` | Linux system and GPU check (exists; extended). |
| `scripts/gpu-doctor.ps1` | Windows system and GPU check. |
| `scripts/test_install.ps1` | Windows installer parse + mocked-scenario harness (mirrors `test_install.sh`). |
| `scripts/test_gpu_doctor.ps1` | Windows doctor parse + mocked-scenario harness. |
| `up.sh` / `down.sh` | Linux start/stop wrappers (exist). |
| `up.ps1` / `down.ps1` | Windows start/stop wrappers (new; thin `docker compose` passthroughs). |
| `docker-compose.windows-amd.yml` | Windows-AMD override: native Ollama off-stack, CPU Kokoro, CPU STT. |
| `docker-compose.cpu-tts.yml` | CPU Kokoro override (used by Windows-AMD; see Deployment Profiles). |
| `ollama/pull-and-pin.sh` | Extended to accept an explicit install-set + aliases (see Model Selection). |
| `.env.example` | Updated: Windows-AMD native Ollama keys, dynamic model-alias keys, CPU Kokoro notes. |
| `agent/models.py` | Extended to expose installed choices + aliases to the picker (see Model Selection). |
| `web/app/ModelPanel.tsx` | Driven by the installed-choices list (env-baked at build time), not a hardcoded array. |

Shared behavior is a documented matrix, not a shared runtime dependency. A little
duplication between Bash and PowerShell is acceptable if it keeps install-time failure
modes obvious.

## Deployment Profiles

| Host | R7 profile |
| --- | --- |
| Linux NVIDIA | Docker full stack. CPU STT default; GPU STT available after explicit profile selection. |
| Linux AMD | Docker AMD ROCm profile for Ollama/Kokoro where hardware passes; CPU STT. |
| Windows NVIDIA | Docker Desktop with WSL2 backend and NVIDIA GPU containers. |
| Windows AMD | **Native Windows Ollama for LLM** (best-effort) + **Docker CPU services** for agent, web, LiveKit, CPU STT, and **CPU Kokoro**. |
| No supported GPU | CPU/floor guidance and best-effort startup only. |

### Windows AMD (hybrid, best-effort)

Windows AMD is intentionally hybrid and the highest-risk profile:

- Native Ollama serves the LLM on `localhost:11434`. Docker services reach it through `host.docker.internal:11434`.
  - **Research finding (2026-06-29):** the `winget install Ollama.Ollama` package is the **CPU/NVIDIA build** — it does **not** include ROCm. AMD GPU inference on Windows requires a **custom Ollama build against the AMD HIP SDK 6.4.2+** (community-documented; not turnkey). Therefore the Windows-AMD profile:
    - Treats native Ollama as **best-effort / CPU-fallback-eligible**: detect whether the installed Ollama reports an AMD GPU; if not, fall back to CPU Ollama with a user-confirmed prompt (no silent GPU→CPU fallback).
    - Guides the user to the HIP SDK build path only as documentation; R7 does **not** build a custom Ollama.
  - This is consistent with the committed scope in `.planning/v1.2-DESIGN.md`: "AMD ships functional / best-effort, not P50-guaranteed in v1.2. Linux-only (Windows RDNA2 is unsupported by ROCm)." R7's Windows-AMD row is the **CPU-services-on-Docker** part plus best-effort native Ollama; the AMD-GPU-on-Windows path stays guide-only.
- STT stays CPU buffered Parakeet (the existing `nemo-stt-cpu` service, unchanged).
- TTS uses a **CPU Kokoro Compose path** (new override; see below). R7 must verify the CPU image preserves the OpenAI `/v1/audio/speech` endpoint and `/dev/captioned_speech` before claiming word-timed avatar support on this profile. If captioned speech is missing, the avatar falls back to Path-A/voice-only behavior.

### Windows AMD compose-structure change (required)

The default `docker-compose.yml` has `agent.depends_on: ollama (service_started)`, and the `ollama` service is **not** profile-gated (always-on). The Windows-AMD override (`docker-compose.windows-amd.yml`) must:

- Remove the in-stack `ollama` service (`!reset` or override to a no-op stub) so Docker does not start a second Ollama.
- Rewrite `agent.depends_on` to drop the `ollama` dependency (the agent reaches native Ollama by URL, not service DNS).
- Set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` and `OLLAMA_GENERATE_URL=http://host.docker.internal:11434/api/generate` in the agent environment (the agent defaults are in-stack `http://ollama:11434/...`, which do not resolve when Ollama is off-stack).

### CPU Kokoro Compose path (new artifact)

There is **no CPU Kokoro service or override in the repo today** — the default `kokoro` service is `ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128`, and the AMD override swaps to ROCm. The Windows-AMD profile needs a new `docker-compose.cpu-tts.yml` override that:

- Sets `kokoro.image` to `ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0` (pin a version, never `:latest`; the upstream README documents `kokoro-fastapi-cpu:latest` and ONNX-optimized CPU inference).
- Removes the GPU `deploy.resources.reservations.devices` reservation.
- Keeps port 8880 and the existing `KOKORO_BASE_URL` contract — the CPU image is a drop-in replacement and preserves both `/v1/audio/speech` and `/dev/captioned_speech` (word-timestamped) per the upstream README.

The same override is reusable for any no-GPU host that still wants TTS.

## Installer Flow

1. User runs `./install.sh` on Linux or `.\install.ps1` on Windows.
2. Installer checks OS, package manager, Docker/Compose, Docker daemon, GPU vendor, VRAM, Ollama availability, and profile viability.
3. Installer offers to install safe missing prerequisites after confirmation:
   - Windows: Docker Desktop and Ollama through `winget` when available (`winget install -e --id Docker.DockerDesktop`, `winget install -e --id Ollama.Ollama`).
   - Linux: Docker/Compose/Ollama through the distro's package path when safe (apt/dnf/pacman), behind a confirmation gate. This **extends** the existing `install.sh` posture (today it only *guides*; R7 adds offer-to-install behind confirmation). "Safe" = the package manager is present AND the user confirms; never `sudo` silently.
4. Installer prints the selected deployment profile and recommended LLM model.
5. **Model selection step** (see Model Selection): the installer prompts for which models to pull and what to name them.
6. User confirms before `.env` is written or changed.
7. Installer preserves existing secrets and writes only profile-specific keys.
8. Installer builds, pulls, and starts the selected stack (pulling only the chosen models).
9. Installer prints exact start, stop, log, and settings-edit commands.

GPU driver and toolkit issues are diagnosed and explained, not silently fixed.

## Model Selection (install-time)

Today the stack ships three **fixed** tiers (`fast` / `better` / `floor`) with hardcoded ladders in `ollama/pull-and-pin.sh`, and the web picker hardcodes `CHOICES = ["fast", "better"]` (`web/app/ModelPanel.tsx:12`) — `floor` is not selectable in-app, and a host that installed only one model still shows two. R7 makes the installed set and its labels an install-time choice.

### Installer prompt

After profile detection, the installer offers a model menu:

- It shows the profile's recommended model (from the hardware result) plus the other known ladder rungs, as plain labels.
- The user selects **which models to install** (at least one) and may **rename** each selected model with a short alias (default alias = the tier name: e.g. "Fast", "Better", "Floor").
- If the user selects only one model, the picker later shows only that one option (no useless "choose" UI).
- The installer pulls only the selected models (not all three ladders), shortening first-install time on weak hardware.

The installer writes, per selected model:

- The resolved Ollama tag (via the existing ladder resolution in `pull-and-pin.sh`).
- The user's alias (default tier label).

### How the installed set reaches the web picker

The web currently has **no env-driven model list** and **no `model.get` RPC** — the picker is a hardcoded array with a hand-synced comment. Two options, in preference order:

1. **Env-baked choices (recommended, smallest diff):** the installer writes a single env var, `ADEPT_MODEL_CHOICES`, to `.env` — a comma list of the installed choice keys (e.g. `ADEPT_MODEL_CHOICES=fast,better` or just `ADEPT_MODEL_CHOICES=floor`). The web reads it at build time via a `NEXT_PUBLIC_ADEPT_MODEL_CHOICES` build arg (mirroring the existing `NEXT_PUBLIC_LIVEKIT_URL` pattern) and the agent reads `ADEPT_MODEL_CHOICES` at runtime. The alias labels are baked the same way (`NEXT_PUBLIC_ADEPT_MODEL_LABELS=Fast,Better`). This keeps the existing "no `model.get` RPC" invariant and the single-source-of-truth in `.env`.
   - **Operational consequence:** because labels are bake-time build args, changing the installed model set requires a `docker compose build web` (not just a restart). The installer does this as part of its build step; a later manual `.env` edit to add a model must be followed by a web rebuild.
   - When only one model is installed, the web renders the picker as a read-only single-value field (no dropdown) — the user can't pick a nonexistent second model.
2. **`model.get` RPC (deferred):** the agent exposes installed choices over RPC so the web fetches them post-connect. More moving parts (a new RPC handler + a fetch-before-render path); not needed if env-baking covers it.

R7 implements option 1. The picker shows only installed models; a one-model install shows one option.

### Agent + warmup threading

This closes the documented floor-path landmine (`.planning/v1.2-DESIGN.md:258-262`):

- `agent/models.py` reads `ADEPT_MODEL_CHOICES` to derive the effective `MODEL_CHOICES` (falling back to the shipped tuple for back-compat). `default_model_choice` and `resolved_model_tag` continue to validate against this effective set.
- The installer only writes `ADEPT_DEFAULT_MODEL=floor` **after** `OLLAMA_MODEL_FLOOR` is pinned (the existing startup path raises `SystemExit` on an empty floor tag — `agent/models.py:57`). If the user declines the floor model, the installer does not set `ADEPT_DEFAULT_MODEL=floor`; it leaves the safe `fast` default.
- `ollama/pull-and-pin.sh` is extended to accept an explicit install-set (e.g. `INSTALL_MODELS=fast,floor`) so it runs only the selected ladders and pins only those tags. The existing `OLLAMA_MODEL` back-compat alias points at the chosen default, not always Fast.
- `ollama/warmup.py` reads `OLLAMA_MODEL` (the alias the installer points at the chosen default), so warmup warms the model the host will actually boot on — not always Fast. This closes the "prewarm warms the wrong tag" finding.

### `.env` model keys (after R7)

```
ADEPT_MODEL_CHOICES=fast,better,floor      # only the installed set
ADEPT_DEFAULT_MODEL=fast                   # one of the above; floor only if floor pinned
OLLAMA_MODEL_FAST=<tag>                    # present only if fast installed
OLLAMA_MODEL_BETTER=<tag>                  # present only if better installed
OLLAMA_MODEL_FLOOR=<tag>                   # present only if floor installed
OLLAMA_MODEL=<tag>                         # alias = the chosen default's tag
# Labels baked into the web build:
# NEXT_PUBLIC_ADEPT_MODEL_LABELS=Fast,Better,Floor
```

## LLM Recommendation

The installer recommends actual model slots, not just hardware tiers, and the recommendation is the **default selection** in the model menu (the user can change it).

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

Select which models to install (space to toggle, enter to confirm).
You can name each model; names appear in the app picker.
You can change this later in .env or from the app settings where available.
```

Raw tags remain available in `.env` and advanced docs. Normal prompts should use
plain labels.

## Environment Writes

The installer may write:

- `LIVEKIT_API_SECRET` (generated if the placeholder is still present)
- `ADEPT_MODEL_CHOICES` (the installed set)
- `ADEPT_DEFAULT_MODEL` (only a key whose tag is pinned)
- `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` / `OLLAMA_MODEL_FLOOR` (only the installed ones)
- `OLLAMA_MODEL` (alias → chosen default's tag)
- `OLLAMA_BASE_URL` / `OLLAMA_GENERATE_URL` for native Windows Ollama profiles
- `STT_ENGINE`
- `STT_FORCE_CPU`
- `STT_BUFFERED_DEVICE` (only when recommending GPU STT; the CPU-default path need not write it — it only affects the GPU `nemo-stt` service)
- `STT_HEADROOM_MEASURED` (only when the operator has measured; GPU-STT recommendation requires this **and** `VRAM_TOTAL_MB` together — see STT coupling below)
- `VRAM_TOTAL_MB` when detected
- Windows/Linux profile notes as comments when practical

It must preserve existing secrets and avoid rewriting unrelated settings.

### STT coupling (placement)

`VRAM_TOTAL_MB` alone does **not** enable GPU STT. `agent/placement.py:102` returns CPU until `STT_HEADROOM_MEASURED=1` is set, regardless of `VRAM_TOTAL_MB`. The installer must:

- Treat `STT_HEADROOM_MEASURED` as an **operator-measured** flag, not something it auto-sets from `nvidia-smi`. The installer can write `VRAM_TOTAL_MB` from detection, but it writes `STT_HEADROOM_MEASURED=1` only when the operator confirms a co-residency measurement (or leaves it `0`, keeping the safe CPU default).
- When recommending GPU STT, write **both** `VRAM_TOTAL_MB` and `STT_HEADROOM_MEASURED=1`; otherwise the host still boots CPU (safe, but the spec should not imply GPU STT from detection alone).

## Error Handling

- Docker missing and user declines install: stop with exact install command.
- Docker installed but daemon is down: stop with Docker Desktop or daemon-start guidance.
- Windows Docker Desktop not using Linux containers or WSL2 backend: stop with settings guidance. (Research confirms GPU support is WSL2-backend-only; the Windows doctor checks the backend setting.)
- NVIDIA detected but container GPU probe fails: guide driver/toolkit fix.
- Linux AMD missing `/dev/kfd` or `/dev/dri`: guide ROCm and permissions.
- Windows AMD: no custom HIP SDK Ollama available → offer `winget install Ollama.Ollama` (CPU build) **with an explicit "this runs the LLM on CPU" warning**, and ask before proceeding. No silent GPU→CPU fallback.
- Windows AMD Ollama installed but no ROCm/HIP GPU detected: ask before falling back to CPU/best-effort.
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
| Windows AMD | Native Ollama health; Docker can reach `host.docker.internal:11434`; CPU STT and CPU Kokoro services render. | Real native Ollama generation plus CPU Kokoro speech smoke. |

Hardware smoke commands should be opt-in through a flag such as
`RUN_HARDWARE_SMOKE=1` or a PowerShell equivalent.

## Testing

Required local checks (sandbox-runnable where the tool exists):

- `bash -n install.sh up.sh down.sh scripts/gpu-doctor.sh`
- `scripts/test_install.sh`
- `scripts/test_gpu_doctor.sh`
- `scripts/test_compose_topology.sh`
- New: `scripts/test_compose_topology.sh` extended for the Windows-AMD + CPU-Kokoro overrides (render-only; `docker compose -f docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml config`).
- New: `agent/models.py` unit test — `ADEPT_MODEL_CHOICES` narrows the effective set; `default_model_choice` rejects a default not in the set; one-model install yields one choice.

Windows / PowerShell checks (require `pwsh`; **operator-deferred in this sandbox** — no `pwsh` here):

- PowerShell parse checks for `install.ps1`, `up.ps1`, `down.ps1`, and `scripts/gpu-doctor.ps1`.
- Mocked PowerShell checks (a new `scripts/test_install.ps1` harness, mirroring `test_install.sh`'s PATH-shim isolation) for:
  - Docker missing
  - Docker daemon down
  - Windows NVIDIA profile
  - Windows AMD native-Ollama profile
  - user declines prerequisite install
- These skip cleanly when `pwsh` is absent (mirroring how `test_compose_topology.sh` skips when docker is missing).

README/profile matrix checks:

- `.env.example` includes the Windows AMD native Ollama path (`OLLAMA_BASE_URL`/`OLLAMA_GENERATE_URL`) and the `ADEPT_MODEL_CHOICES` keys.
- CPU Kokoro compose path preserves the OpenAI speech endpoint; captioned-speech support is verified or the avatar fallback is documented.

Manual gates (real hardware):

- Windows NVIDIA Docker GPU probe.
- Windows AMD native Ollama (CPU build) + CPU Kokoro probe.
- Linux AMD ROCm Compose profile.
- Linux NVIDIA full-stack profile.

## Sequencing

R7 is the **last** v1.2 stream (ROADMAP: "R7 installs what R2/R3/R6 define"). R6 (AMD ROCm) shipped its compose override + doctor advice (commits `22eec99`, `719753f`), but has **no verification closeout** (`v1.2-R6-VERIFY.md` does not exist). Before R7 executes:

- Either close R6's verification (run its AMD gates on real hardware), or
- Mark R7's Linux-AMD and Windows-AMD rows as **contingent on R6's gates**, so R7 does not claim AMD functionality R6 has not verified.

The R7 plan should gate AMD-profile work behind R6 closeout.

## Documentation

README should explain:

- Linux install command.
- Windows PowerShell install command.
- Supported host/profile matrix.
- Which prerequisites can be installed by the installer (and that Windows AMD GPU inference is a guide-only custom build, not turnkey).
- Which GPU driver/toolkit steps are guide-only.
- How the install-time model selection works (choose models + aliases; picker shows only installed models).
- How to edit `.env` manually after install (including adding/removing a model).
- How to change LLM model choice later.
- Start/stop/log commands per OS.

## References (verified 2026-06-29)

- Docker Desktop Windows GPU (WSL2 only): `https://docs.docker.com/desktop/features/gpu/` — GPU support is Windows + WSL2 backend only; NVIDIA Windows driver + `wsl --update`; compose v2 `deploy.resources.reservations.devices` with `driver: nvidia`, `count: all`, `capabilities: [gpu]` (the repo's existing compose already uses this syntax).
- Docker Compose GPU reservations: `https://docs.docker.com/compose/how-tos/gpu-support/`.
- Ollama GPU support: `https://github.com/ollama/ollama/blob/main/docs/gpu.mdx`.
- Ollama Docker ROCm image: `ollama/ollama:rocm` (rolling) and versioned `0.30.10-rocm` / `0.30.12-rc0-rocm` (the repo pins `0.30.10-rocm` — valid). `:latest` is CPU-only; ROCm requires the `rocm` / `*-rocm` tag. (Docker Hub `ollama/ollama` tags.)
- Ollama Windows AMD: native AMD GPU requires a **custom build against HIP SDK 6.4.2+** (community-documented; `HSA_OVERRIDE_GFX_VERSION` for RDNA3). The `winget Ollama.Ollama` package is the CPU/NVIDIA build, not ROCm. RDNA2 Windows is community-tested only; RDNA3 is the supported target.
- Kokoro-FastAPI images (canonical README): CPU = `ghcr.io/remsky/kokoro-fastapi-cpu:latest` (ONNX-optimized, no GPU); NVIDIA = `:latest-cu126` / `:latest-cu128` (Blackwell); AMD = `kokoro-fastapi-rocm:latest` (experimental). The repo pins `v0.5.0-cu128` (GPU). Both `/v1/audio/speech` and `/dev/captioned_speech` (word-timestamped) are preserved across CPU/GPU images (drop-in).
- Kokoro-FastAPI repo: `https://github.com/remsky/Kokoro-FastAPI`.
- winget package IDs (verified): `Docker.DockerDesktop`, `Ollama.Ollama` (`winget install -e --id <ID>`).
- AMD ROCm Docker device model: `https://rocm.docs.amd.com/en/latest/conceptual/ai-pytorch-inception.html`.
- AMD HIP SDK Windows component support: `https://rocm.docs.amd.com/projects/install-on-windows/en/latest/conceptual/component-support.html`.

## Exit Criteria

- A Linux user can run the local installer and get a usable profile for their host.
- A Windows user can run native PowerShell and get a usable profile for their host.
- Windows AMD is supported through native Ollama (CPU build, best-effort) plus Docker CPU STT and CPU Kokoro; AMD GPU inference on Windows is guide-only.
- The installer prompts for which models to install and their aliases; the web picker shows only the installed models (one model → one option).
- The installer recommends an LLM model and tells users how to change it later.
- The floor path is safe: `ADEPT_DEFAULT_MODEL=floor` is written only when `OLLAMA_MODEL_FLOOR` is pinned; warmup warms the chosen default.
- CPU-only, CPU+GPU, GPU, Linux AMD, and Windows AMD profiles have config or smoke coverage.
- No GPU driver stack is modified without explicit future work.
