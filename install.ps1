# install.ps1 — one-command bootstrap for the Adept local-first voice stack on Windows.
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
Set-Location $PSScriptRoot

if ($Yes) { $env:ASSUME_YES = "1" }
$AssumeYes = ($env:ASSUME_YES -eq "1")

function Log($msg)  { Write-Output $msg }
function Err($msg)  { Write-Host "ERROR: $msg" -ForegroundColor Red }

# --- 1. Prerequisites: offer to install via winget, else guide ----------------
function Require-Docker {
  $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $dockerCmd) {
    Err "Docker Desktop is not installed."
    Log "Install Docker Desktop, then re-run .\install.ps1:"
    Log "  winget install -e --id Docker.DockerDesktop"
    return $false
  }
  try {
    $null = docker compose version 2>$null
    if ($LASTEXITCODE -ne 0) { throw "no compose" }
  } catch {
    Err "Docker Compose v2 not found (need the 'docker compose' subcommand)."
    Log "  Ensure Docker Desktop is running with the WSL2 backend."
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

function Write-ModelEnv {
  $envContent = Get-Content .env -Raw
  function Set-EnvKey($content, $key, $value) {
    if ($content -match "(?m)^$key=") {
      $content = $content -replace "(?m)^$key=.*", "$key=$value"
    } else {
      $content = $content.TrimEnd() + "`n$key=$value`n"
    }
    return $content
  }
  $envContent = Set-EnvKey $envContent "ADEPT_MODEL_CHOICES" $script:InstallModels
  $envContent = Set-EnvKey $envContent "NEXT_PUBLIC_ADEPT_MODEL_LABELS" $script:ModelLabels
  $defaultChoice = ($script:InstallModels -split ",")[0].Trim()
  $envContent = Set-EnvKey $envContent "ADEPT_DEFAULT_MODEL" $defaultChoice
  Set-Content .env $envContent
}

# --- 4. Plan + confirmation --------------------------------------------------
function Print-Plan {
  param([string]$Gpu, [string]$Models)
  Log ""
  Log "================ Adept setup plan ================"
  Log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  Log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  Log "GPU vendor detected: $Gpu"
  Log "Models to install: $Models"
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

# --- 5. Build + first-run model pull + boot ----------------------------------
function Build-AndPull {
  Log "Building images (first run pulls several GB + bakes the STT model)…"
  docker compose build
  Log "Starting ollama to pull + pin the selected models…"
  docker compose up -d ollama
  $env:INSTALL_MODELS = $script:InstallModels
  $env:ADEPT_DEFAULT_MODEL = ($script:InstallModels -split ",")[0].Trim()
  & ./ollama/pull-and-pin.sh
  Log "Starting the full stack…"
  docker compose up -d
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
  & "$PSScriptRoot\scripts\gpu-doctor.ps1" 2>$null  # advise-only; never blocks
}
Scaffold-Env
Prompt-Models -Gpu $Gpu
Write-ModelEnv
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
