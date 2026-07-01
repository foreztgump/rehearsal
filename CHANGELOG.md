# Changelog

All notable changes to Rehearsal are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); commits use
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added
- Added a Windows one-line install (`irm …/install.ps1 | iex`) that clones the
  repo and runs the native installer, mirroring the Linux curl bootstrap.

### Changed
- `curl … install.sh | bash` now detects Windows (Git Bash / MSYS / Cygwin) and
  hands off to the PowerShell installer instead of the Linux prerequisite path.
- `install.ps1` now runs `ollama/pull-and-pin.sh` via Git Bash (not the WSL
  `bash.exe` shim) with a clear error when Git Bash is absent.
- `gpu-doctor.ps1` now checks the driver's CUDA version against the 12.8 floor
  (parity with `gpu-doctor.sh`), advising a driver update before `up` fails with
  a cryptic `cuda>=12.8` runtime error.

### Fixed
- Added `.gitattributes` forcing LF for shell scripts. With `core.autocrlf=true`
  (the Git-for-Windows default) they were checked out CRLF, and `bash` inside the
  Docker build failed on `set -o pipefail` — breaking `docker compose build` for
  every Windows one-line install.
- `install.ps1` now checks `$LASTEXITCODE` after each `docker compose` step; a
  failed build previously slipped through to "the stack is up" and exited 0.
- `install.ps1` Docker-missing gate now stops correctly (the guidance text was
  polluting `Require-Docker`'s boolean return via `Write-Output`).
- `agent` now receives `LIVEKIT_URL` (compose), so the worker registers instead
  of crash-looping with "ws_url is required, or set LIVEKIT_URL".
- The agent worker's `initialize_process_timeout` is now raised (env-tunable via
  `AGENT_INIT_TIMEOUT_S`, default 300s) so the prewarm LLM warmup can cold-load
  the model on modest/low-VRAM GPUs; the 10s default SIGUSR1-killed the process
  and looped forever, never letting the model go resident.

## [0.2.0] - 2026-06-30

### Added
- Added browser-local saved personas so custom persona setups can be saved,
  loaded, and deleted from setup or in-session settings.

### Changed
- Reworked setup and live settings around a scenario-first mode/persona flow.
- Updated the product tagline to "Local first fully private voice practice
  with expert personas."

### Fixed
- Guarded live settings updates against stale RPC acknowledgements and
  settings-drawer reopen races.
- Preserved explicit Mock Interview targets while keeping other scenarios
  mapped to the right persona defaults.

## [0.1.0] - 2026-06-30

Rehearsal is now installable with a Linux curl bootstrap, from a local repo
checkout on Linux, and from native Windows, with install-time model selection
and best-effort Windows-AMD support.

### Added
- Added broad voice-practice persona presets across AI/ML, data, software,
  cloud/DevOps, product, sales, customer success, leadership, healthcare
  communication, finance/business, GRC/policy, climate/energy, and language
  conversation practice.
- Added Drill and Roleplay practice modes alongside Learn and Interview.
- `install.sh` / `install.ps1` — two native installers (bash + PowerShell)
  with offer-to-install prerequisites, a model-selection prompt, and
  per-model user-chosen aliases. Aliases are baked into the web build so
  the picker shows only what was installed, named as the user named it.
- `install.sh` curl-style bootstrap — when streamed outside a checkout, it
  clones `foreztgump/rehearsal` into `~/rehearsal` or `REHEARSAL_INSTALL_DIR`
  and then runs the normal local installer.
- `ollama/pull-and-pin.sh` — accepts an `INSTALL_MODELS` set and pulls only
  the selected model ladders; the chosen default is aliased to `OLLAMA_MODEL`.
  Fast/better ladder failures are skip-with-warning (like floor); empty
  `default_tag` falls back to the first installed model.
- `docker-compose.cpu-tts.yml` — CPU Kokoro override
  (`ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0`) for no-GPU / VRAM-tight hosts.
- `docker-compose.windows-amd.yml` — Windows-AMD override: native host
  Ollama via `host.docker.internal`, in-stack `ollama` reduced to an
  `alpine:3.21` no-op stub (profile-gating fails on `depends_on`), CPU Kokoro.
- `scripts/gpu-doctor.ps1`, `up.ps1`, `down.ps1` — Windows PowerShell
  siblings of the Linux wrappers.
- `agent/models.py` `effective_model_choices()` — derives the picker choice
  set from `REHEARSAL_MODEL_CHOICES`, narrowing `default_model_choice` to the
  installed set. Single installed model renders a read-only field.
- `web/app/ModelPanel.tsx` — choices + labels baked at build time via
  `NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES` / `NEXT_PUBLIC_REHEARSAL_MODEL_LABELS`;
  one model renders as a read-only `<input>`, two-plus as a dropdown.
- `scripts/guarddog-check.sh` — optional GuardDog deep supply-chain scan for
  malicious package signals, with JSON reports under `security/reports/guarddog/`.
- `SECURITY.md` — public reporting policy and the local scan commands.

### Changed
- Renamed the app to Rehearsal, including package metadata, UI copy,
  runtime prefixes, Docker labels/network names, and model-picker env keys.
- Rewrote `README.md` for the public repo with setup, privacy, security checks,
  and project credits.
- Default persona changed to Voice Fluency Coach, with Cybersecurity Trainer
  moved into the preset library.
- `docker-compose.yml` — web service build args pass the baked model
  choice/label env to the Next.js build.
- `web/Dockerfile` now uses `npm ci` and declares the model-picker build args.
- `install.sh` `write_model_env` now runs after `pull-and-pin.sh` succeeds
  (was writing `.env` before tags were confirmed).
- `.gitignore` now excludes local AI/planning workspaces, editor state, caches,
  local env files, and security reports.
- Local security baseline now treats OSV resolver-internal errors with a
  valid zero-vulnerability report as a warning, while still failing on
  malformed reports and high/critical findings.
- Local security scans now use the current Gitleaks `git` command and keep
  GuardDog's package sandbox enabled for npm dependency scans.

### Fixed
- `offer_install_prereqs` sudo failure now falls back to guidance instead
  of a silent `set -e` abort.
- `install.ps1` `Set-EnvKey` hoisted to a top-level function (was scoped
  inside the param block).
- Hardened dependency floors for STT (`h11`, `idna`, `python-multipart`,
  `sentencepiece`) and forced the web lockfile to the fixed `postcss` line
  until Next ships a clean transitive dependency.
- Pinned previously unbounded agent direct dependencies so supply-chain scans do
  not resolve prerelease or dev-package artifacts.

### Notes
- R3 STT decision: `buffered` non-streaming Parakeet is the supported path.
  `streaming` and `hybrid` engines are retained in code as legacy/manual
  comparison modes only.
- Linux curl bootstrap live-tested against a real GitHub clone with Docker/Ollama
  shimmed to avoid multi-GB image and model pulls.
- Operator-deferred (need Windows / `pwsh` / real GPU hardware): PowerShell
  parse checks, Windows NVIDIA Docker GPU probe, Windows AMD native Ollama
  probe. Linux AMD ROCm and Windows AMD profiles are gated on R6 verification.
