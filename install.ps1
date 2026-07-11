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
#   .\install.ps1 -Expressive   # also build + enable expressive voice (Chatterbox)
#   $env:ASSUME_YES=1; .\install.ps1
[CmdletBinding()]
param(
  [switch]$Yes,
  [switch]$SkipDoctor,
  [switch]$Expressive
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
# Opt-in expressive voice (Chatterbox). OFF unless -Expressive or INSTALL_EXPRESSIVE=1.
if ($Expressive) { $env:INSTALL_EXPRESSIVE = "1" }
$script:InstallExpressive = ($env:INSTALL_EXPRESSIVE -eq "1")

# Model-default + readiness tunables (single-sourced; mirror install.sh).
# VramSmallMb: NVIDIA cards at/below this default to the smaller Floor model.
# ReadyTimeoutS/ReadyPollS: bound the post-`up` wait for the agent to register.
$VramSmallMb   = if ($env:VRAM_SMALL_MB)   { [int]$env:VRAM_SMALL_MB }   else { 8192 }
$VramFloorMb   = if ($env:VRAM_FLOOR_MB)   { [int]$env:VRAM_FLOOR_MB }   else { 16384 }
$ReadyTimeoutS = if ($env:READY_TIMEOUT_S) { [int]$env:READY_TIMEOUT_S } else { 180 }
$ReadyPollS    = if ($env:READY_POLL_S)    { [int]$env:READY_POLL_S }    else { 5 }

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
  # AMD on Windows: the HIP SDK marker only exists on ROCm-listed cards. Consumer
  # RDNA cards (e.g. RX 6600 XT / gfx1032) run the LLM via native Ollama's Vulkan
  # backend and have NO ROCm marker — so ALSO match the adapter name so the
  # Vulkan-only AMD path is detected (field report: else it mis-detects as 'none'
  # and the one-liner silently runs the wrong NVIDIA topology).
  $hipSdk = Get-ChildItem "C:\Program Files\AMD ROCm*\bin" -ErrorAction SilentlyContinue
  if ($hipSdk) { return "amd" }
  try {
    $amd = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match "AMD|Radeon" }
    if ($amd) { return "amd" }
  } catch { }
  return "none"
}

# Total VRAM in MB for the primary NVIDIA GPU, or $null if unknown. Win32_VideoController
# is NOT used here — its AdapterRAM is a uint32 that WRAPS at 4 GB (field report G3),
# so it under-reports 8 GB cards as 4 GB. nvidia-smi is authoritative on NVIDIA.
function Detect-NvidiaVramMb {
  if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { return $null }
  $vram = (nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
  if ($vram) { $vram = "$vram".Trim() }
  if ($vram -match '^[0-9]+$') { return [int]$vram }
  return $null
}

# Windows AMD is a DIFFERENT topology (native host Ollama + Vulkan; only the CPU
# services run in Docker). install.ps1 cannot drive it end-to-end: its Build-AndPull
# runs plain `docker compose build/up` (no AMD overrides) and pulls into the
# in-container Ollama, which the AMD override replaces with an alpine sleep stub that
# has no `ollama` binary. So on AMD we DETECT + GUIDE (print the exact manual steps)
# and STOP — never silently run the wrong NVIDIA topology (field report Bug #5).
function Show-AmdGuidanceAndExit {
  Write-Host ""
  Write-Host "================ Windows AMD detected — manual path ================" -ForegroundColor Yellow
  Write-Host "The one-line installer does NOT drive the AMD topology. On AMD the LLM runs"
  Write-Host "in NATIVE host Ollama (Vulkan-accelerated), and only the CPU services run in"
  Write-Host "Docker (the in-stack ollama is a no-op stub). Follow these steps:"
  Write-Host ""
  Write-Host "  1. Install native Ollama, then reopen PowerShell so 'ollama' is on PATH:"
  Write-Host "       winget install -e --id Ollama.Ollama"
  Write-Host "  2. Force the Vulkan backend so RDNA cards off Ollama's ROCm list get GPU"
  Write-Host "     acceleration (make it permanent + restart Ollama so the tray app picks it up):"
  Write-Host '       [Environment]::SetEnvironmentVariable("OLLAMA_LLM_LIBRARY","vulkan","User")'
  Write-Host '       [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN","1","User")'
  Write-Host "       Get-Process ollama* | Stop-Process -Force; Start-Process ollama"
  Write-Host "  3. Pull the model into NATIVE Ollama (not the container), then verify GPU use:"
  Write-Host "       ollama pull evalengine/unbound-e2b:latest"
  Write-Host "       ollama ps        # PROCESSOR column should show GPU, not 100% CPU"
  Write-Host "  4. Scaffold .env (copy .env.example to .env; set a random LIVEKIT_API_SECRET"
  Write-Host "     and the single-model config — see INSTALLATION.md 'Windows AMD')."
  Write-Host "  5. From the checkout, build + start with the AMD + CPU-TTS overrides (use -f"
  Write-Host "     flags; the COMPOSE_FILE colon form fails on Windows):"
  Write-Host "       cd `"$CheckoutDir`""
  Write-Host "       docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml ``"
  Write-Host "         -f docker-compose.cpu-tts.yml up -d --build"
  Write-Host ""
  Write-Host "Full walkthrough + verification: INSTALLATION.md ('Windows AMD')."
  Write-Host "===================================================================" -ForegroundColor Yellow
  exit 0
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
  param([string]$Gpu, [Nullable[int]]$VramMb)
  switch ($Gpu) {
    "nvidia" {
      # Pick by VRAM: cards at/below VramSmallMb can't comfortably co-fit the Better
      # tier, so default them to the smaller Floor model (field report rec #5). Unknown
      # VRAM keeps the historical Fast default.
      if ($null -ne $VramMb -and $VramMb -le $VramSmallMb) {
        $defaultModel = "floor"
        Log ""
        Log "Detected $VramMb MB VRAM (<= $VramSmallMb MB) — defaulting to the smaller Floor model."
      } else {
        $defaultModel = "fast"
        if ($null -ne $VramMb) { Log ""; Log "Detected $VramMb MB VRAM — defaulting to the Fast model." }
      }
    }
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

# Expressive-voice opt-in (Chatterbox), mirrors install.sh prompt_expressive. GPU-only,
# large build, exceeds the latency budget — so it is prompted unless already opted in
# (flag/env) or accepting the plan non-interactively. Force-disabled off NVIDIA.
function Prompt-Expressive {
  param([string]$Gpu)
  if ($Gpu -ne "nvidia") {
    if ($script:InstallExpressive) { Log "Expressive voice needs an NVIDIA GPU (none detected) — disabling it." }
    $script:InstallExpressive = $false
    return
  }
  if ($script:InstallExpressive) { return }
  if ($AssumeYes) { return }
  $reply = Read-Host "Install expressive voice (Chatterbox)? ~19GB extra build, +4.3GB VRAM, exceeds the P50<1.0s budget [y/N]"
  $script:InstallExpressive = ($reply -match '^(y|Y)')
}

# Write the expressive-voice env, mirrors install.sh write_expressive_env. Bakes the
# web picker flag and (when on) the COMPOSE_PROFILES=expressive that up.sh honors.
function Write-ExpressiveEnv {
  $want = if ($script:InstallExpressive) { "1" } else { "0" }
  $envContent = Get-Content .env -Raw
  $envContent = Set-EnvKey $envContent "NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE" $want
  if ($want -eq "1") {
    if ($envContent -match "(?m)^COMPOSE_PROFILES=") {
      if ($envContent -notmatch "(?m)^COMPOSE_PROFILES=.*expressive") {
        $envContent = $envContent -replace "(?m)^COMPOSE_PROFILES=(.*)", 'COMPOSE_PROFILES=$1,expressive'
      }
    } else {
      $envContent = Set-EnvKey $envContent "COMPOSE_PROFILES" "expressive"
    }
  } else {
    # Drop the profile line only when it is exactly the expressive profile.
    $envContent = $envContent -replace "(?m)^COMPOSE_PROFILES=expressive`r?`n", ""
  }
  Set-Content .env $envContent
}

# CPU override layering for no-GPU hosts (F19, mirrors install.sh layer_cpu_overrides).
# On Docker Desktop without an NVIDIA GPU, the base compose's ollama nvidia reservation
# makes `docker compose up` dead-end; persist a COMPOSE_FILE layering the cpu-llm +
# cpu-tts overrides so every later compose call runs ollama + kokoro on CPU. Only on
# GPU=none, only when COMPOSE_FILE is absent (idempotent). NB: AMD on Windows uses the
# separate windows-amd override (native host Ollama), so this targets 'none'.
function Layer-CpuOverrides {
  param([string]$Gpu)
  if ($Gpu -ne "none") { return }
  $envContent = Get-Content .env -Raw
  if ($envContent -match "(?m)^COMPOSE_FILE=") {
    Log "COMPOSE_FILE already set in .env — leaving it untouched."
    return
  }
  # ';'-separated on Windows per Compose's COMPOSE_PATH_SEPARATOR default.
  $cpuStack = "docker-compose.yml;docker-compose.cpu-llm.yml;docker-compose.cpu-tts.yml"
  $envContent = Set-EnvKey $envContent "COMPOSE_FILE" $cpuStack
  Set-Content .env $envContent
  Log "No NVIDIA GPU — layered CPU overrides via COMPOSE_FILE in .env (ollama + kokoro on CPU)."
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
  if ($script:InstallExpressive) {
    Log "Expressive voice: ENABLED (Chatterbox) — large extra build + ~4.3GB VRAM;"
    Log "  voice-to-voice P50 EXCEEDS the 1.0s budget by design when expressive is used."
  } else {
    Log "Expressive voice: off (Kokoro only). Re-run with -Expressive to add it later."
  }
  Log "Install guide: INSTALLATION.md (prereqs, platform notes, download sizes)"
  if ($Gpu -eq "nvidia") {
    Log "STT placement: CPU-ONNX by default (STT_FORCE_CPU=1, VRAM-safe). GPU STT is"
    Log "  opt-in after the co-residency matrix passes (docker compose --profile stt-gpu)."
  } else {
    Log "No NVIDIA GPU detected ($Gpu). STT runs on CPU-ONNX; the installer layers the"
    Log "  CPU overrides (cpu-llm + cpu-tts) so ollama + kokoro run on CPU and the stack"
    Log "  BOOTS — but CPU inference will NOT hit the P50<1.0s latency target."
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
  # Expressive-voice env is written BEFORE the build so the web image bakes the
  # correct NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE flag.
  Write-ExpressiveEnv
  # PowerShell does NOT throw on a native command's non-zero exit (even under
  # ErrorActionPreference=Stop), so every docker step must be gated on $LASTEXITCODE
  # explicitly — otherwise a failed build sails through to "the stack is up".
  if ($script:InstallExpressive) {
    Log "Building images incl. expressive voice (Chatterbox — large first build)…"
    docker compose --profile expressive build
  } else {
    Log "Building images (first run pulls several GB + bakes the STT model)…"
    docker compose build
  }
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

# --- 6. Health-gate the finish line ------------------------------------------
# `docker compose up -d` returns when containers are CREATED, not when the agent has
# warmed models + registered as a LiveKit worker — so poll until the agent logs
# "registered worker" (bounded by ReadyTimeoutS). On timeout ADVISE, don't fail: a
# slow cold warmup on a sub-16GB card is expected (mirrors install.sh wait_for_ready).
function Wait-ForReady {
  param([string]$Gpu, [Nullable[int]]$VramMb)
  Log ""
  Log "Waiting for the agent to warm models + register (up to ${ReadyTimeoutS}s)…"
  $waited = 0
  while ($waited -lt $ReadyTimeoutS) {
    $logs = docker compose logs --tail=200 agent 2>$null
    if ($logs -match "registered worker") {
      Log "Agent registered — ready to talk. Open the web UI (see NEXT_PUBLIC_LIVEKIT_URL in .env)."
      return
    }
    Start-Sleep -Seconds $ReadyPollS
    $waited += $ReadyPollS
  }
  Log "Agent not registered after ${ReadyTimeoutS}s — the model may still be warming."
  if ($Gpu -ne "nvidia" -or ($null -ne $VramMb -and $VramMb -lt $VramFloorMb)) {
    Log "  On CPU / sub-16GB GPUs the first turn is slow while STT/LLM/TTS warm — this is expected."
  }
  Log "  Watch progress: docker compose logs -f agent   (look for 'registered worker')."
}

# --- main --------------------------------------------------------------------
$Gpu = Detect-Gpu
# Windows AMD is a different topology this installer can't drive — detect + guide, stop.
if ($Gpu -eq "amd") { Show-AmdGuidanceAndExit }
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
Layer-CpuOverrides -Gpu $Gpu
$VramMb = Detect-NvidiaVramMb
Prompt-Models -Gpu $Gpu -VramMb $VramMb
Prompt-Expressive -Gpu $Gpu
Print-Plan -Gpu $Gpu -Models $script:InstallModels
if (-not (Confirm)) {
  Log "Aborted — nothing built. Re-run .\install.ps1 when ready."
  exit 1
}
Build-AndPull
Wait-ForReady -Gpu $Gpu -VramMb $VramMb
Log ""
Log "Done. The stack is up."
Log "  Start:  .\up.ps1 -d        (preflight + docker compose up -d)"
Log "  Stop:   .\down.ps1         (docker compose down)"
Log "  Logs:   docker compose logs -f agent"
Log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
Log "Install guide: INSTALLATION.md"
