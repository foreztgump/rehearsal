# install.ps1 — one-command bootstrap for the Rehearsal local-first voice stack on Windows.
#
# Native PowerShell installer (mirrors install.sh). Detects Docker Desktop + GPU
# vendor, offers to install missing prerequisites via winget (behind confirmation),
# scaffolds .env with a generated LIVEKIT_API_SECRET, prompts for which models to
# install + their aliases, prints a setup plan and confirms, builds images +
# pulls/pins the selected models, then prints exact start/stop commands.
#
#   .\install.ps1            # interactive
#   .\install.ps1 -Yes       # accept the plan non-interactively (CI / repeat)
#   $env:ASSUME_YES=1; .\install.ps1
[CmdletBinding()]
param(
  [switch]$Yes,
  [switch]$SkipDoctor
)
$ErrorActionPreference = "Stop"

function Log($msg)  { Write-Output $msg }
function Err($msg)  { Write-Host "ERROR: $msg" -ForegroundColor Red }

# --- 0. curl|iex bootstrap (mirrors install.sh bootstrap_checkout) ------------
# Makes `irm .../install.ps1 | iex` work: when run outside a checkout there is no
# repo on disk (and no $PSScriptRoot), so clone into %USERPROFILE%\rehearsal and
# re-invoke the cloned installer as a file. Idempotent + safe-clone, like install.sh.
$RepoUrl    = if ($env:REHEARSAL_REPO_URL)    { $env:REHEARSAL_REPO_URL }    else { "https://github.com/foreztgump/rehearsal.git" }
$InstallDir = if ($env:REHEARSAL_INSTALL_DIR) { $env:REHEARSAL_INSTALL_DIR } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) "rehearsal" }

function Test-InCheckout($dir) {
  return (Test-Path (Join-Path $dir "docker-compose.yml")) -and
         (Test-Path (Join-Path $dir ".env.example")) -and
         (Test-Path (Join-Path $dir "ollama/pull-and-pin.sh"))
}

# Run as a file → $PSScriptRoot is the checkout. Piped via iex → empty, use CWD.
$CheckoutDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

if (-not (Test-InCheckout $CheckoutDir)) {
  if ($env:REHEARSAL_BOOTSTRAPPED -eq "1") {
    Err "Installer checkout is incomplete: $CheckoutDir"
    exit 1
  }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Err "git is required for the one-line install."
    Log "Install Git for Windows (winget install -e --id Git.Git), or run:"
    Log "  git clone $RepoUrl `"$InstallDir`""
    exit 1
  }
  if ((Test-Path $InstallDir) -and -not (Test-InCheckout $InstallDir)) {
    Err "Install directory already exists but is not a complete Rehearsal checkout:"
    Log "  $InstallDir"
    exit 1
  }
  if (-not (Test-Path $InstallDir)) {
    Log "Cloning Rehearsal into $InstallDir..."
    $parent = Split-Path $InstallDir -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    git clone $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) { Err "git clone failed."; exit 1 }
  }
  # Forward the bound switches explicitly ($args is empty under [CmdletBinding()]).
  $fwd = @()
  if ($Yes)        { $fwd += "-Yes" }
  if ($SkipDoctor) { $fwd += "-SkipDoctor" }
  $env:REHEARSAL_BOOTSTRAPPED = "1"
  & (Join-Path $InstallDir "install.ps1") @fwd
  exit $LASTEXITCODE
}

Set-Location $CheckoutDir

if ($Yes) { $env:ASSUME_YES = "1" }
$AssumeYes = ($env:ASSUME_YES -eq "1")

# --- 1. Prerequisites: offer to install via winget, else guide ----------------
# Returns a plain boolean. Guidance goes through Write-Host (NOT Log/Write-Output):
# Write-Output inside a function is appended to the return value, which would turn
# $dockerOk into an array and silently defeat the `if (-not $dockerOk)` gate.
function Require-Docker {
  $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $dockerCmd) {
    Err "Docker Desktop is not installed."
    Write-Host "Install Docker Desktop, then re-run .\install.ps1:"
    Write-Host "  winget install -e --id Docker.DockerDesktop"
    return $false
  }
  try {
    $null = docker compose version 2>$null
    if ($LASTEXITCODE -ne 0) { throw "no compose" }
  } catch {
    Err "Docker Compose v2 not found (need the 'docker compose' subcommand)."
    Write-Host "  Ensure Docker Desktop is running with the WSL2 backend."
    return $false
  }
  return $true
}

function Offer-InstallPrereqs {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Log "winget not available — install Docker Desktop + Ollama manually."
    return
  }
  $reply = if ($AssumeYes) { "y" } else { Read-Host "Install missing Docker Desktop + Ollama via winget? [y/N]" }
  if ($reply -match '^[yY]') {
    Log "Installing Docker Desktop via winget…"
    winget install -e --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
    Log "Installing Ollama via winget…"
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    Log "Prerequisites installed. Restart Docker Desktop if it is not running, then re-run .\install.ps1."
  } else {
    Log "Skipping auto-install. Install Docker Desktop + Ollama manually, then re-run."
  }
}

function Detect-Gpu {  # prints: nvidia | amd | none
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { return "nvidia" }
  # AMD on Windows: no reliable rocm-smi; check for the HIP SDK install marker.
  $hipSdk = Get-ChildItem "C:\Program Files\AMD ROCm*\bin" -ErrorAction SilentlyContinue
  if ($hipSdk) { return "amd" }
  return "none"
}

# --- 2. .env scaffold with a generated secret --------------------------------
function Gen-Secret {
  # 32 random hex bytes (matches install.sh's openssl rand -hex 32 length).
  $bytes = New-Object byte[] 32
  (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
  return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Scaffold-Env {
  if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Log "Created .env from .env.example."
  }
  $envContent = Get-Content .env -Raw
  if ($envContent -match 'replace-with-a-long-random-secret') {
    $secret = Gen-Secret
    $envContent = $envContent -replace 'LIVEKIT_API_SECRET=.*', "LIVEKIT_API_SECRET=$secret"
    Set-Content .env $envContent
    Log "Generated a random LIVEKIT_API_SECRET in .env."
  } else {
    Log ".env already has a LIVEKIT_API_SECRET — leaving it untouched."
  }
}

# --- 3. Model selection ------------------------------------------------------
function Prompt-Models {
  param([string]$Gpu)
  switch ($Gpu) {
    "nvidia" { $defaultModel = "fast" }
    "amd"    { $defaultModel = "fast" }
    default  { $defaultModel = "floor" }
  }
  Log ""
  Log "Recommended LLM: $defaultModel (best default for this machine)."
  Log "Available: fast (snappier), better (more thoughtful), floor (weakest hardware)."
  if ($AssumeYes) {
    $script:InstallModels = $defaultModel
    $script:ModelLabels = $defaultModel
  } else {
    $reply = Read-Host "Which models to install (comma list, e.g. fast,better)? [$defaultModel]"
    $script:InstallModels = if ($reply) { $reply.Trim() } else { $defaultModel }
    $labels = Read-Host "Aliases (comma list, same order; blank for defaults)?"
    $script:ModelLabels = if ($labels) { $labels.Trim() } else { $script:InstallModels }
  }
  Log "Will install: $script:InstallModels"
}

# Set or replace an env key in a content string (top-level — not nested, so
# PowerShell scoping is predictable). Used by Write-ModelEnv.
function Set-EnvKey($content, $key, $value) {
  if ($content -match "(?m)^$key=") {
    $content = $content -replace "(?m)^$key=.*", "$key=$value"
  } else {
    $content = $content.TrimEnd() + "`n$key=$value`n"
  }
  return $content
}

function Write-ModelEnv {
  $envContent = Get-Content .env -Raw
  $envContent = Set-EnvKey $envContent "REHEARSAL_MODEL_CHOICES" $script:InstallModels
  $envContent = Set-EnvKey $envContent "NEXT_PUBLIC_REHEARSAL_MODEL_LABELS" $script:ModelLabels
  $defaultChoice = ($script:InstallModels -split ",")[0].Trim()
  $envContent = Set-EnvKey $envContent "REHEARSAL_DEFAULT_MODEL" $defaultChoice
  Set-Content .env $envContent
}

# --- 4. Plan + confirmation --------------------------------------------------
function Print-Plan {
  param([string]$Gpu, [string]$Models)
  Log ""
  Log "================ Rehearsal setup plan ================"
  Log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  Log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  Log "GPU vendor detected: $Gpu"
  Log "Models to install: $Models"
  Log "Install guide: INSTALLATION.md (prereqs, platform notes, download sizes)"
  if ($Gpu -eq "nvidia") {
    Log "STT placement: CPU-ONNX by default (STT_FORCE_CPU=1, VRAM-safe). GPU STT is"
    Log "  opt-in after the co-residency matrix passes (docker compose --profile stt-gpu)."
  } else {
    Log "No NVIDIA GPU detected. STT runs on CPU-ONNX."
  }
  Log "================================================="
}

function Confirm {
  if ($AssumeYes) { return $true }
  $reply = Read-Host "Proceed with build + model pull? [y/N]"
  return ($reply -match '^[yY]')
}

# Locate Git Bash, preferring it over the System32 WSL launcher (see Build-AndPull).
function Find-GitBash {
  foreach ($p in @(
      "$env:ProgramFiles\Git\bin\bash.exe",
      "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
      "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe")) {
    if (Test-Path $p) { return $p }
  }
  # Fall back to a PATH bash only if it is NOT the WSL launcher.
  $cmd = Get-Command bash -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -notlike "*\System32\bash.exe") { return $cmd.Source }
  return $null
}

# --- 5. Build + first-run model pull + boot ----------------------------------
function Build-AndPull {
  Log "Building images (first run pulls several GB + bakes the STT model)…"
  # PowerShell does NOT throw on a native command's non-zero exit (even under
  # ErrorActionPreference=Stop), so every docker step must be gated on $LASTEXITCODE
  # explicitly — otherwise a failed build sails through to "the stack is up".
  docker compose build
  if ($LASTEXITCODE -ne 0) { Err "Image build failed (docker compose build)."; exit 1 }
  Log "Starting ollama to pull + pin the selected models…"
  docker compose up -d ollama
  if ($LASTEXITCODE -ne 0) { Err "Failed to start the ollama service."; exit 1 }
  $env:INSTALL_MODELS = $script:InstallModels
  $env:REHEARSAL_DEFAULT_MODEL = ($script:InstallModels -split ",")[0].Trim()
  # pull-and-pin is a bash script that drives `docker compose exec`. Run it under
  # Git Bash (native Windows; its `docker` is Docker Desktop's CLI). Avoid the WSL
  # launcher at System32\bash.exe, which runs inside a WSL distro with a different
  # cwd/paths and needs Docker Desktop WSL integration enabled.
  $bash = Find-GitBash
  if (-not $bash) {
    Err "Git Bash not found — required to run ollama/pull-and-pin.sh."
    Log "Install Git for Windows (winget install -e --id Git.Git), then re-run .\install.ps1."
    exit 1
  }
  & $bash ./ollama/pull-and-pin.sh
  if ($LASTEXITCODE -ne 0) { Err "Model pull/pin failed."; exit 1 }
  # Write the model-choices env ONLY after pull-and-pin succeeds — so .env never
  # claims a model is installed before its tag is confirmed resident.
  Write-ModelEnv
  Log "Starting the full stack…"
  docker compose up -d
  if ($LASTEXITCODE -ne 0) { Err "Failed to start the full stack (docker compose up -d)."; exit 1 }
}

# --- main --------------------------------------------------------------------
$Gpu = Detect-Gpu
$dockerOk = Require-Docker
if (-not $dockerOk) {
  Offer-InstallPrereqs
  $dockerOk = Require-Docker
  if (-not $dockerOk) { exit 1 }
}
if ($Gpu -eq "nvidia" -and -not $SkipDoctor) {
  & (Join-Path $CheckoutDir "scripts\gpu-doctor.ps1") 2>$null  # advise-only; never blocks
}
Scaffold-Env
Prompt-Models -Gpu $Gpu
Print-Plan -Gpu $Gpu -Models $script:InstallModels
if (-not (Confirm)) {
  Log "Aborted — nothing built. Re-run .\install.ps1 when ready."
  exit 1
}
Build-AndPull
Log ""
Log "Done. The stack is up."
Log "  Start:  .\up.ps1 -d        (preflight + docker compose up -d)"
Log "  Stop:   .\down.ps1         (docker compose down)"
Log "  Logs:   docker compose logs -f agent"
Log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
Log "Install guide: INSTALLATION.md"
