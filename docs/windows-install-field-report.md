# Windows install — field report & hardening guide

**Date:** 2026-07-01
**Author:** end-to-end "full send" test on a real Windows 11 laptop
**Audience:** maintainer — how to make the Windows install path universal

This is the record of taking the Windows install **all the way** on a clean-ish
machine (no Docker, old GPU driver): from `irm … | iex` through a live 6/6 stack
you can actually talk to. It documents every bug, every environment gotcha, the
fix, and what still needs doing so *any* Windows user succeeds first try.

---

## TL;DR

- The Windows one-liner now exists and works, but getting there surfaced **8 real
  bugs** — and **3 of them are cross-platform** (would break a fresh Linux install
  too), not Windows-only.
- The single most important fix is **`.gitattributes` forcing LF on shell
  scripts.** Without it, `git clone` on a Windows box with `core.autocrlf=true`
  (the Git-for-Windows default) checks out `.sh` files as CRLF, and `bash` inside
  the Docker build dies on `set -o pipefail`. That breaks `docker compose build`
  for **every** Windows user of the one-liner. This is non-negotiable.
- Several blockers were **environment**, not code: Docker Desktop PATH not
  refreshed, NVIDIA driver update breaking the WSL2 GPU mount until `wsl
  --shutdown`, stale Docker port-proxies after a WSL restart, and a driver too old
  for kokoro's `cu128` image.
- The installer needs to **fail loudly and preflight better** — most of the pain
  was silent/cryptic failures, not the underlying problems themselves.

---

## Verified-working configuration (this machine)

| Component | Value |
| --- | --- |
| OS | Windows 11 Pro 26100 |
| Docker Desktop | 29.6.1 (WSL2 backend, Ubuntu distro present) |
| docker compose | v5.1.4 |
| GPU | RTX 2060 Max-Q, **6 GB VRAM** (below the 16 GB target) |
| NVIDIA driver | **610.62** (CUDA UMD 13.3) — updated from 566.14 (CUDA 12.7) |
| Model installed | `fast` → `evalengine/unbound-e2b:latest` (1.6 GB resident on GPU) |
| Result | 6/6 services up; web HTTP 200; agent registered; model resident |

Prerequisites already present that mattered: git, curl, **Git Bash (MINGW64)**,
pwsh 7, Windows PowerShell 5, winget, Chocolatey, and a working WSL2 (Ubuntu, v2).

---

## Bugs found (symptom → root cause → fix)

Ordered by blast radius. "Scope" = who it affects.

### 1. CRLF line endings break the Docker build — **CRITICAL, all Windows users**
- **Symptom:** `docker compose build` fails deep in the `nemo-stt-cpu` image:
  `./fetch_parakeet_onnx.sh: line 5: set: pipefail: invalid option name`.
- **Root cause:** No `.gitattributes` + `core.autocrlf=true` (Git-for-Windows
  default) → every `.sh` is checked out CRLF → `bash` inside the Linux container
  chokes on the trailing `\r` in `set -o pipefail`.
- **Why it's insidious:** the repo *blobs* are already LF, so it's invisible on
  the maintainer's Linux box and in CI. It only appears on a Windows checkout, and
  only inside the container build.
- **Fix:** added `.gitattributes` pinning `*.sh`/`*.bash` to `eol=lf` (and
  `* text=auto eol=lf`; `.ps1/.bat/.cmd` stay CRLF), then renormalized the tree.
- **Commit:** `fix(build): force LF for shell scripts via .gitattributes`

### 2. `install.ps1` reports success on a failed build — **all Windows users**
- **Symptom:** the build above failed, yet the installer printed
  "Done. The stack is up." and exited **0**.
- **Root cause:** PowerShell does **not** throw on a native command's non-zero
  exit (even under `$ErrorActionPreference = "Stop"`). `Build-AndPull` ran
  `docker compose build` / `up` without checking `$LASTEXITCODE`.
- **Fix:** gate every `docker compose` step on `$LASTEXITCODE` and `exit 1` with a
  clear message. This is what turned every later failure from "silent + confusing"
  into "loud + diagnosable."
- **Commit:** part of `feat(install): … installer robustness`

### 3. Docker-missing gate never stopped — **all Windows users**
- **Symptom:** with Docker absent, the installer printed "Docker Desktop is not
  installed" and then **kept going** (scaffolded `.env`, prompted for models).
- **Root cause:** `Require-Docker` returns a boolean, but its guidance used
  `Log` = `Write-Output`. In PowerShell, `Write-Output` inside a function is
  **appended to the return value**, so `$dockerOk` became an array; `-not $array`
  is `$false`, so the `exit 1` gate was skipped.
- **Fix:** route guidance in boolean-returning functions through `Write-Host`, not
  `Write-Output`. (General PowerShell footgun — worth auditing other helpers.)
- **Commit:** part of `feat(install): … installer robustness`

### 4. `bash` resolves to the WSL shim, not Git Bash — **Windows**
- **Symptom:** `pull-and-pin.sh` would run in the wrong environment.
- **Root cause:** in PowerShell, `Get-Command bash` returns
  `C:\WINDOWS\System32\bash.exe` — the **WSL launcher** — which runs inside the
  Ubuntu distro (different cwd/paths, needs Docker WSL integration enabled), not
  the native Git Bash whose `docker` is Docker Desktop's CLI.
- **Fix:** `Find-GitBash` prefers `…\Git\bin\bash.exe`, falls back to a PATH bash
  only if it isn't `System32\bash.exe`.
- **Commit:** part of `feat(install): … installer robustness`

### 5. `gpu-doctor.ps1` never checked the CUDA floor — **Windows**
- **Symptom:** a driver below kokoro's `cu128` requirement surfaced only as a
  cryptic `runc … unsatisfied condition: cuda>=12.8` at `up` time.
- **Root cause:** `gpu-doctor.sh` has a `check_cuda_floor` step; `gpu-doctor.ps1`
  defined `CUDA_FLOOR` but **never used it** (chain drift between the two ports).
- **Fix:** ported the check to `.ps1` — read the driver's max CUDA (query field
  with a header-parse fallback) and advise a driver update below 12.8.
- **Commit:** `feat(gpu-doctor): check CUDA floor on Windows (parity with .sh)`

### 6. Agent crash-loops: missing `LIVEKIT_URL` — **CROSS-PLATFORM**
- **Symptom:** `agent` container restarts forever:
  `ValueError: ws_url is required, or set LIVEKIT_URL environment variable`.
- **Root cause:** `LIVEKIT_URL` exists **nowhere** in the repo — not in
  `.env.example`, compose, the agent Dockerfile, or `main.py`. `.env` only has
  `NEXT_PUBLIC_LIVEKIT_URL` (browser-side). `WorkerOptions(...)` passes no
  `ws_url`, so livekit-agents falls back to the unset `LIVEKIT_URL`.
- **This is not Windows-specific** — a fresh Linux `docker compose up` fails
  identically. It was simply never caught because it needs a from-scratch deploy.
- **Fix:** set `LIVEKIT_URL=${LIVEKIT_URL:-ws://livekit-server:7880}` in the agent
  service (in-network service DNS; the browser keeps using `localhost`).
- **Commit:** `fix(agent): wire LIVEKIT_URL and allow slow cold-warmup`

### 7. Agent crash-loops: prewarm exceeds the process-init timeout — **CROSS-PLATFORM (low-VRAM)**
- **Symptom:** after #6, agent still loops:
  `error initializing process` → `SIGUSR1` → `exit code -10` → retry, forever.
  `ollama ps` stays **empty** — the model never goes resident.
- **Root cause:** `prewarm()` does a **real LLM warmup** — it cold-loads the model
  into VRAM and runs one inference. On a modest/low-VRAM GPU that exceeds
  livekit-agents' **10 s default `initialize_process_timeout`**. The worker
  process is SIGUSR1-killed and retried, which **cancels the model load** each
  time, so it never becomes resident → permanent loop (not a slow start).
- **Fix:** raise `WorkerOptions.initialize_process_timeout` (env
  `AGENT_INIT_TIMEOUT_S`, default 300 s). After this the model loads once, stays
  resident (`keep_alive=-1`), and the worker registers.
- **Note:** on a 16 GB machine where the model loads fast (or ollama/warmup.py
  pre-warmed it), 10 s happens to be enough — which is why it was never hit.
- **Commit:** `fix(agent): wire LIVEKIT_URL and allow slow cold-warmup`

### 8. No Windows one-liner existed — **the original ask**
- `install.ps1` started with `Set-Location $PSScriptRoot` and assumed a cloned
  checkout; piped through `iex` there is no `$PSScriptRoot` and no repo on disk.
- **Fix:** self-bootstrap in `install.ps1` (clone into `%USERPROFILE%\rehearsal`,
  re-invoke as a file) mirroring `install.sh`; and `install.sh` now detects
  Windows (MINGW/MSYS/Cygwin) and hands off to `install.ps1`, so
  `curl … install.sh | bash` works from Git Bash too.
- **Commit:** `feat(install): Windows one-line install + installer robustness`

---

## Environment gotchas (not code — but they block users)

These cost the most wall-clock and none are in the repo. A first-time Windows user
*will* hit several.

### G1. Docker Desktop PATH is not live in already-open shells
After `winget install Docker.DockerDesktop`, the machine PATH is updated but any
already-running shell (and the process that spawns your installer) still has the
old PATH — so `docker` isn't found until you restart the shell or prepend
`C:\Program Files\Docker\Docker\resources\bin`. The installer should either detect
this and prepend it, or tell the user to open a fresh terminal.

### G2. Docker Desktop first-run is interactive
First launch shows a service-agreement screen and takes 1–3 min to start the WSL2
engine. A headless installer can't click through it. Users must accept it and wait
for "Engine running" before the build can proceed.

### G3. Elevation (UAC) can't be automated
`winget`/`choco` installs of Docker Desktop and the NVIDIA driver need admin. In a
non-elevated shell they must be launched with `Start-Process -Verb RunAs`, which
pops a UAC prompt the user has to approve. Document this.

### G4. NVIDIA driver update breaks the WSL2 GPU mount until a re-sync
Updating the Windows driver live left `nvidia-smi` on the host working but
**containers could not see the GPU** — `docker run --gpus all` crashed
(`nvidia-container-cli` register dump). Fix without a full reboot:
`wsl --shutdown`, then let Docker Desktop restart the engine. The WSL2 distro
re-copies the new driver libraries on next boot. (A reboot also works.)

### G5. Stale Docker port-proxies after `wsl --shutdown`
After the WSL restart, host port-forwards for containers that weren't recreated
went dead (`web:3000`, `ollama:11434`, `livekit:7880` → `ERR_EMPTY_RESPONSE` /
HTTP 000) **even though the containers were "Up" and listening internally.** The
browser couldn't reach `ws://localhost:7880`. Fix: `docker compose up -d
--force-recreate <svc>`, or a clean `docker compose down && up -d`, which
re-establishes every proxy and the network.

### G6. kokoro needs CUDA ≥ 12.8 (driver ≥ ~570)
`kokoro-fastapi-gpu:v0.5.0-cu128` requires CUDA 12.8. Driver 566.14 (CUDA 12.7)
failed at `up` with a cryptic runc error. Updating to 610.62 (CUDA 13.3) fixed it.
This is exactly what gpu-doctor's CUDA floor (bug #5) is meant to flag up front.

### G7. New NVIDIA drivers changed the `nvidia-smi` output
Driver 610.62 **removed the `cuda_version` query field**
(`--query-gpu=cuda_version` → "not a valid field") and renamed the header to
`CUDA UMD Version: 13.3` (was `CUDA Version: 12.7`). Any parsing of nvidia-smi must
tolerate both — the gpu-doctor port handles the query-field failure with a
header-parse fallback, but the fallback regex should also match `CUDA UMD Version`.
**Follow-up:** confirm/extend both `gpu-doctor.ps1` and `.sh` regexes for this.

### G8. 6 GB VRAM is below the 16 GB target
The stack builds and boots, and the `fast` model (1.6 GB resident) runs, but the
first turn is slow (cold STT/TTS warmup) and it won't hit real-time latency. Not a
bug — but the installer picked `fast` by default on an NVIDIA host; on ≤ 8 GB cards
`floor` may be the better default (see recommendations).

### G9. `/api/stt-debug` 502 is expected in the default deploy
The web route targets `http://nemo-stt:8000` — the **opt-in GPU STT**
(`--profile stt-gpu`), which isn't running by default. It returns
`{enabled:false}` with 502 by design. Harmless; noisy in the browser console.
Consider pointing it at the active STT service or degrading quietly.

### G10. The bash test suite can't run under MINGW
`scripts/test_install.sh` isolates PATH with `env -i PATH=…`, which strips the
MSYS DLL dir so the symlinked `bash` can't load (`error while loading shared
libraries`). The suite is Linux/CI-only; on Windows use `test_install.ps1`.

---

## Recommendations — making it universal for all Windows

**Must-do (correctness):**
1. **Ship `.gitattributes`** (done) — the one change that unbreaks the one-liner
   for every autocrlf=true user. Verify no other container-copied file type
   (Dockerfiles, entrypoints) is CRLF-sensitive.
2. **Keep the `$LASTEXITCODE` gates** (done) — silent success is worse than any
   single bug because it hides all the others.
3. **Fix `LIVEKIT_URL` and the agent init timeout upstream** (done) — both are
   cross-platform; add a from-scratch `docker compose up` smoke test to CI so they
   can't regress.

**Should-do (fewer support tickets):**
4. **Preflight the CUDA floor before build**, not after. gpu-doctor already knows;
   surface it in `install.ps1` and offer to stop early with the driver-update
   remedy. Harden nvidia-smi parsing for the new `CUDA UMD Version` header (G7).
5. **Auto-pick `floor` on ≤ 8 GB cards.** The installer reads `VRAM_TOTAL_MB` from
   gpu-doctor; use it to default the model instead of always `fast` on NVIDIA.
6. **Handle the PATH/first-run/UAC realities in installer output** (G1–G3): after
   installing Docker Desktop, tell the user to accept the agreement, wait for the
   engine, and open a fresh terminal (or re-exec with the Docker bin prepended).
7. **Document the driver-update → `wsl --shutdown` re-sync** (G4) and the
   stale-proxy `--force-recreate` (G5) in the Windows troubleshooting section.
8. **Health-gate the finish line.** `install.ps1` currently ends after `up -d`.
   Have it poll `docker compose ps` for `healthy`/`registered worker` and print a
   real "ready to talk" (or "still warming — first turn is slow on <16 GB").

**Nice-to-have (coverage):**
9. **Windows CI runner** that at least: parses the PS scripts, runs
   `test_install.ps1`, and exercises the `irm | iex` bootstrap against a stub git.
   A GPU-less job can still validate build-context line endings and the
   docker-missing gate.
10. **A `down`/reset path** documented for the "I rebooted / driver changed"
    case — `docker compose down && up -d` is the reliable reset.

---

## The path that actually worked (repeatable)

1. `winget install Docker.DockerDesktop` (elevated) → start it → accept agreement →
   wait for engine.
2. Ensure `docker` on PATH (fresh shell, or prepend the Docker bin).
3. Run the installer (`irm …/install.ps1 | iex`, or from a checkout `.\install.ps1`).
   It detects NVIDIA, scaffolds `.env`, builds, pulls+pins the model, `up -d`.
4. If gpu-doctor advises CUDA < 12.8: update the NVIDIA driver
   (`choco install nvidia-display-driver`, elevated), then `wsl --shutdown` and let
   Docker Desktop restart — **or** reboot.
5. `docker compose down && docker compose up -d` for a clean set of port-proxies.
6. Open `http://127.0.0.1:3000`. First turn is slow while the model/STT/TTS warm.

## Validation matrix for "universal Windows"

Test these before calling it universal:

| Axis | Values to cover |
| --- | --- |
| Entry point | `irm \| iex`; scriptblock form with `-Yes`; `curl \| bash` in Git Bash; local `.\install.ps1` |
| git autocrlf | `true` (default) **and** `input` — the `.sh` files must arrive LF either way |
| GPU | NVIDIA ≥16 GB; NVIDIA <8 GB (default model choice); no GPU (CPU degraded) |
| Driver | CUDA ≥ 12.8 (pass) and < 12.8 (must advise, not crash) |
| Docker | present; absent (winget offer); daemon stopped |
| Shell | pwsh 7 and Windows PowerShell 5.1 |
| Bash for pull-and-pin | Git Bash present; absent (clear error) |
