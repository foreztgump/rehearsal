# Windows one-line install — design

**Date:** 2026-06-30
**Status:** accepted

## Problem

Rehearsal ships a Linux "easy install" one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/foreztgump/rehearsal/master/install.sh | bash
```

`install.sh` self-bootstraps: when run outside a checkout (piped from `curl`),
it `git clone`s into `~/rehearsal` and re-execs itself (`install.sh:32-55`).

Windows has a *native* installer (`install.ps1`, `up.ps1`, `down.ps1`,
`scripts/gpu-doctor.ps1`), but **no equivalent one-liner**:

- `install.ps1` starts with `Set-Location $PSScriptRoot` and assumes the repo is
  already cloned. Piped through `iex` (`irm … | iex`) there is no `$PSScriptRoot`
  and no repo on disk, so it breaks — there is no clone/bootstrap step.
- The documented `curl … install.sh | bash` command, when run in Git Bash on
  Windows, falls into the Linux prerequisite path (apt/dnf/pacman), which is
  meaningless on Windows, instead of the winget-based Docker Desktop path.

## Goals

1. A native Windows one-liner: `irm …/install.ps1 | iex`.
2. The existing `curl …/install.sh | bash` command also works on Windows
   (Git Bash / MSYS / Cygwin), landing in the same PowerShell installer.
3. Preserve the idempotent, safe-clone contract of `install.sh` (no clobbering
   an existing directory; re-entry guard against loops).

Non-goals: WSL-specific handling; changing the Linux flow; a full end-to-end
build test (requires Docker + GPU + multi-GB pulls).

## Design

### A. `install.ps1` self-bootstrap (mirrors `install.sh:32-55`)

Prepended before the existing `Set-Location`:

- `In-Checkout $dir` — true when `docker-compose.yml`, `.env.example`, and
  `ollama/pull-and-pin.sh` all exist in `$dir`.
- Determine the checkout dir: `$PSScriptRoot` when set (run as a file), else the
  current directory (piped via `iex`).
- If not in a checkout:
  - Re-entry guard: if `$env:REHEARSAL_BOOTSTRAPPED -eq "1"`, error (incomplete
    checkout) and exit — no loop.
  - Require `git`; if missing, print the manual `git clone` command and exit.
  - Clone target: `$env:REHEARSAL_INSTALL_DIR` or `$env:USERPROFILE\rehearsal`.
    If it exists but is not a complete checkout, error (do not clobber).
  - `git clone $repo $dir`, then re-invoke the cloned installer as a file with
    `$env:REHEARSAL_BOOTSTRAPPED = "1"`, forwarding `$args`, and exit with its code.
- Replace `Set-Location $PSScriptRoot` with `Set-Location $checkoutDir`.

Arg passing: `irm | iex` cannot bind `-Yes` (params don't bind through `iex`).
The plain `| iex` form runs interactively (correct default). Non-interactive
callers use the scriptblock form, documented in the README:
`& ([scriptblock]::Create((irm url))) -Yes`.

### B. `install.sh` Windows delegation

After `bootstrap_checkout "$@"` guarantees a checkout, detect Windows via
`uname -s` matching `MINGW*|MSYS*|CYGWIN*`. If Windows:

- Locate a PowerShell host: prefer `pwsh`, fall back to `powershell`.
- If found, `exec` it against the local installer:
  `pwsh -ExecutionPolicy Bypass -File ./install.ps1` with `-Yes` when
  `ASSUME_YES=1`. This hands Windows users to the winget-based path.
- If no PowerShell host is found, print guidance to run `install.ps1` manually.

Placed after the clone-bootstrap so the checkout (and `install.ps1`) exist
before delegating.

### C. Robustness fix

`install.ps1` invokes `& ./ollama/pull-and-pin.sh`, which silently needs bash.
Change to invoke via `bash ./ollama/pull-and-pin.sh` and check for `bash` first,
erroring clearly if absent. Low-risk; prevents a confusing failure on the
Windows build path.

## Testing (on the dev Windows device)

This device has git, curl, bash (MINGW64), pwsh, powershell, winget, and an
NVIDIA GPU, but **no Docker installed** — ideal for exercising bootstrap →
detect → prerequisite-gate without a multi-GB build.

1. `pwsh scripts/test_install.ps1` and `bash scripts/test_install.sh` stay green.
2. Extend both suites:
   - `test_install.ps1`: parse still passes; add a check of the checkout-detection
     helper (`In-Checkout` returns false in an empty temp dir, true in a stub
     checkout).
   - `test_install.sh`: add a scenario that mocks `uname` to a Windows value and a
     `pwsh`/`powershell` stub, asserting `install.sh` delegates to `install.ps1`.
3. Live smoke test: run `install.ps1` here; with Docker absent it must reach
   "Docker Desktop is not installed → offer winget install," which we decline.
   Proves detect → gate works end-to-end.

## Docs

README gains a "Windows one-line install" block (both `irm | iex` and the note
that `curl … | bash` works in Git Bash). CHANGELOG updated under Unreleased.
