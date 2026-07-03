# Changelog

All notable changes to Rehearsal are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); commits use
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Changed
- `web` SettingsDrawer scrim/panel/close/End controls now use the shared theme
  classes (`.drawer-scrim`, `.surface`, `.btn-ghost[.danger]`, `.btn-apply.danger`)
  instead of hardcoded inline styles.

### Fixed
- Agent worker no longer crash-loops on every job with `Could not find file
  "languages.json"`. The F34 non-root-user hardening baked the turn-detector
  weights into `/root/.cache/huggingface` (root-owned, since `download-files`
  ran before `USER app`), but the runtime `app` user had no writable HOME
  (`--no-create-home`) and couldn't read the root cache, so the local
  `MultilingualModel` turn detector failed to initialize on every room dispatch
  and the publisher data channel closed. The Dockerfile now pins
  `HF_HOME=/app/.hf-cache` so the cache bakes under `/app` and is chowned to
  `app` by the existing `chown -R app:app /app`, making it readable at runtime.

## [0.2.1] - 2026-07-03

Review Batches A–H (PR #2 and #3): KB/STT/web fixes, the LAN TLS proxy
override, hardening and supply-chain pinning, CI, and latency/perf
optimizations. Also ships the Windows one-line install and installer
robustness work.

### Added
- LAN TLS proxy override (`docker-compose.proxy.yml`) with `PROXY_BIND_IP`
  split-binding and caddy 2.11.4, so the stack can be exposed on the LAN with
  a single pinned-image override; a compose test asserts the topology.
- STT concurrent-connection cap plus a LAN hardening runbook, bounding how many
  simultaneous ASR sessions the sidecar accepts.
- Minimal GitHub Actions CI workflow (typecheck, ruff, basedpyright, stub
  tests).
- `ollama/pull-and-pin.sh` now records pulled model manifest digests and wires
  `verify-build` into the pull flow.
- Agent and web containers run as a non-root `USER` with a `HEALTHCHECK`, and
  the agent base image is digest-pinned.
- Windows one-line install (`irm …/install.ps1 | iex`) that clones the repo and
  runs the native installer, mirroring the Linux curl bootstrap.
- `INSTALLATION.md` with platform prerequisites, first-run download size
  expectations, troubleshooting, and an AI-agent install prompt.

### Changed
- Web `tsconfig` strict mode enabled and enforced in CI.
- Ollama pinned image bumped 0.30.10 -> 0.30.11.
- KB ingest now short-circuits before parse when the session is full, and
  multi-file uploads coalesce into one batched distill call.
- STT raw-silence EOU logic extended to the buffered path.
- CPU legacy-ONNX export gated behind a build ARG so GPU images stay lean.
- Agent deps install with `uv --no-cache`.
- Web `Visualizer` hoists the per-frame `Uint8Array` allocation out of the
  render loop; per-line transcript rendering is memoized.
- `curl … install.sh | bash` detects Windows (Git Bash / MSYS / Cygwin) and
  hands off to the PowerShell installer; `install.ps1` runs `pull-and-pin.sh`
  via Git Bash (not the WSL `bash.exe` shim) with a clear error when absent.
- `gpu-doctor.ps1` checks the driver's CUDA version against the 12.8 floor
  (parity with `gpu-doctor.sh`).
- README is shorter and points detailed install guidance to `INSTALLATION.md`.

### Security
- KB DOCX parser rejects XML DTD/entity declarations before parsing.
- KB distill delimiters neutralized against spoofing and a token budget enforced
  on the distilled stream.
- Agent KB distill stream bounded by wall-clock and byte count; Ollama error
  chunks surfaced instead of swallowed.
- Agent PDF extraction capped at a max page count.
- `livekit-agents` pinned to `==1.6.4` and the `_opts` surface guarded at
  startup.
- STT `python-multipart` pinned in the GPU image deps.
- STT offline `/v1/audio/transcriptions` route hardened (lock, size cap, WAV
  validation).
- `STT_DEBUG_HYBRID` exposure now warns, and dead debug code was dropped.

### Fixed
- STT folds held text forward on stall recycle; caps hybrid `_turn_pcm` at
  `_MAX_BUFFER_BYTES`; guards the WS config handshake with try/except + timeout;
  suppresses spurious empty deltas after finals; deletes dead
  `RECYCLE_HARD_CHARS` config; trims inter-turn silence from the buffered
  finalize buffer.
- `NemoSTT` reconnects on transport errors and survives bad correction
  callbacks.
- Agent KB byte stream capped in-loop and accumulated into a bytearray;
  unexpected `ingest_kb` failures are contained so the KB panel unsticks;
  `ByteStreamInfo.mime_type` is used to unbrick KB upload.
- Web confirms the top-bar End before destroying the session; recovers from
  terminal LiveKit disconnect; handles drag/drop on both KB dropzones; gates
  setup apply on agent readiness and honors RPC acks; re-arms the
  `avatar.update` retry budget on every toggle; strips unknown persona keys on
  load so agent apply doesn't silently fail.
- Compose Windows-AMD ollama stub port publish reset (field report Bug #1).
- Install gates AMD/no-GPU hosts onto the CPU compose override and makes the
  bootstrap idempotent.
- `gpu-doctor.ps1` WSL2 toolkit remedy corrected; gpu-doctor stops backtick
  escapes garbling Windows advise messages.
- Windows `up.ps1`/`down.ps1` gained the missing `up`/`down` subcommand.
- `security-check.sh` gates shellcheck at `-S error` to drop benign false
  positives; CI installs numpy so the STT stub tests pass.
- Added `.gitattributes` forcing LF for shell scripts. With `core.autocrlf=true`
  (the Git-for-Windows default) they were checked out CRLF, and `bash` inside
  the Docker build failed on `set -o pipefail` — breaking `docker compose
  build` for every Windows one-line install.
- `install.ps1` checks `$LASTEXITCODE` after each `docker compose` step; its
  Docker-missing gate now stops correctly.
- Agent receives `LIVEKIT_URL` (compose), and its `initialize_process_timeout`
  is raised (env-tunable via `AGENT_INIT_TIMEOUT_S`, default 300s) so cold
  warmup can load the model on modest/low-VRAM GPUs.
- GPU doctor CUDA parsing accepts the newer `CUDA UMD Version` header.
- The STT debug window no longer mounts in the main talking UI.

### Docs
- Corrected stale STT 560ms "equals the live step" claims, stale model-tag
  claims in compose/Modelfile/vram-validate, and stale README TLS refs;
  documented phone-background room timeouts.
- Added `caddy:2.11.4` to the provenance Docker Images table; un-ignored the
  LAN-exposure runbook and Windows-AMD field report (the latter kept
  local-only).
- Fixed the proxy bring-up command for the override design; replaced an
  impossible `--profile` example with `COMPOSE_PROFILES`; switched Windows docs
  to `-f` flags instead of colon `COMPOSE_FILE`.
- `security-check` now excludes `docs/**` and allowlists the `savedPersonas`
  key.

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
