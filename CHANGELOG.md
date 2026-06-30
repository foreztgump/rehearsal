# Changelog

All notable changes to Adept are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); commits use
[Conventional Commits](https://www.conventionalcommits.org/).

## [unreleased] — R7 cross-platform installer (2026-06-29)

Adept is now installable from a local repo checkout on Linux and native
Windows, with install-time model selection and best-effort Windows-AMD
support.

### Added
- `install.sh` / `install.ps1` — two native installers (bash + PowerShell)
  with offer-to-install prerequisites, a model-selection prompt, and
  per-model user-chosen aliases. Aliases are baked into the web build so
  the picker shows only what was installed, named as the user named it.
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
  set from `ADEPT_MODEL_CHOICES`, narrowing `default_model_choice` to the
  installed set. Single installed model renders a read-only field.
- `web/app/ModelPanel.tsx` — choices + labels baked at build time via
  `NEXT_PUBLIC_ADEPT_MODEL_CHOICES` / `NEXT_PUBLIC_ADEPT_MODEL_LABELS`;
  one model renders as a read-only `<input>`, two-plus as a dropdown.

### Changed
- `docker-compose.yml` — web service build args pass the baked model
  choice/label env to the Next.js build.
- `install.sh` `write_model_env` now runs after `pull-and-pin.sh` succeeds
  (was writing `.env` before tags were confirmed).
- `README.md` — both-OS install commands, the supported-host profile
  matrix, model-selection guidance, and the per-VRAM doctor recommendations.

### Fixed
- `offer_install_prereqs` sudo failure now falls back to guidance instead
  of a silent `set -e` abort.
- `install.ps1` `Set-EnvKey` hoisted to a top-level function (was scoped
  inside the param block).

### Notes
- R3 STT decision: `buffered` non-streaming Parakeet is the supported path.
  `streaming` and `hybrid` engines are retained in code as legacy/manual
  comparison modes only.
- Operator-deferred (need Windows / `pwsh` / real GPU hardware): PowerShell
  parse checks, Windows NVIDIA Docker GPU probe, Windows AMD native Ollama
  probe. Linux AMD ROCm and Windows AMD profiles are gated on R6 verification.
