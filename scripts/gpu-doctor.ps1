# gpu-doctor.ps1 — preflight GPU "doctor" for the Windows consumer docker compose deploy.
#
# Mirrors scripts/gpu-doctor.sh. Runs an ORDERED chain of host checks BEFORE
# `docker compose up` and, on any problem, prints the EXACT remedy. NON-BLOCKING
# ADVISE: always exits 0 so .\up.ps1 proceeds; its only job is to make GPU/driver/
# toolkit/VRAM problems legible. It NEVER writes .env and NEVER switches anything
# at runtime.
#
# Ordered chain (each step: detect -> on fail, print remedy + keep going):
#   1. Docker Desktop running + daemon responds
#   2. WSL2 backend selected (GPU support is WSL2-only on Windows)
#   3. nvidia-smi present + driver responds (NVIDIA only)
#   4. NVIDIA Container GPU probe (docker run --gpus all)
#   5. VRAM floor >= 16384 MB
#
# Run directly:        .\scripts\gpu-doctor.ps1
# Run via the wrapper: .\up.ps1           (runs this first, then docker compose up)
#
# Env overrides (single-sourced floors — match gpu-doctor.sh):
#   VRAM_FLOOR_MB        (default 16384)
#   CUDA_FLOOR           (default 12.8)
#   TOOLKIT_PROBE_IMAGE  (default nvidia/cuda:12.4.0-base-ubuntu22.04)
[CmdletBinding()]
param()
$ErrorActionPreference = "Continue"   # advise-only: never stop on errors
Set-Location $PSScriptRoot\..

$VRAM_FLOOR_MB = if ($env:VRAM_FLOOR_MB) { [int]$env:VRAM_FLOOR_MB } else { 16384 }
$CUDA_FLOOR    = if ($env:CUDA_FLOOR) { [double]$env:CUDA_FLOOR } else { 12.8 }
$TOOLKIT_PROBE_IMAGE = if ($env:TOOLKIT_PROBE_IMAGE) { $env:TOOLKIT_PROBE_IMAGE } else { "nvidia/cuda:12.4.0-base-ubuntu22.04" }

$Degraded = $false
$GpuVendor = "none"

function Ok($msg)     { Write-Output "OK: $msg" }
function Advise($msg) { Write-Output "ADVISE: $msg"; $script:Degraded = $true }
function Hr           { Write-Output "----------------------------------------------------------------------" }

function Detect-GpuVendor {
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $script:GpuVendor = "nvidia" }
  elseif (Test-Path "C:\Program Files\AMD ROCm*\bin") { $script:GpuVendor = "amd" }
  else { $script:GpuVendor = "none" }
}

# --- Step 1: Docker Desktop running + daemon responds -------------------------
function Check-DockerDaemon {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Advise "`docker` not found — Docker Desktop is not installed or not on PATH."
    Write-Output "  Fix: install Docker Desktop (winget install -e --id Docker.DockerDesktop)."
    return
  }
  try {
    $null = docker info 2>$null
    if ($LASTEXITCODE -ne 0) { throw "daemon down" }
  } catch {
    Advise "Docker daemon is not running."
    Write-Output "  Fix: start Docker Desktop, then re-run. Ensure it is set to the WSL2 backend."
    return
  }
  Ok "Docker daemon is running."
}

# --- Step 2: WSL2 backend (GPU support is WSL2-only on Windows) ----------------
function Check-Wsl2Backend {
  # Docker Desktop stores the backend choice in settings.json; WSL2 is the default.
  # A reliable programmatic check is not exposed; advise if docker info lacks WSL.
  try {
    $info = docker info 2>$null
    if ($info -match "WSL") {
      Ok "WSL2 backend detected (Docker info mentions WSL)."
    } else {
      Advise "Could not confirm WSL2 backend from `docker info`."
      Write-Output "  Fix: Docker Desktop -> Settings -> General -> 'Use the WSL 2 based engine'."
      Write-Output "       GPU support on Windows is WSL2-backend-only."
    }
  } catch {
    Advise "Could not query `docker info` for the WSL2 backend."
  }
}

# --- Step 3: nvidia-smi present + driver responds -----------------------------
function Check-NvidiaSmi {
  if ($script:GpuVendor -ne "nvidia") {
    Advise "Skipping NVIDIA checks (no nvidia-smi on PATH)."
    return
  }
  try {
    $null = nvidia-smi 2>$null
    if ($LASTEXITCODE -ne 0) { throw "smi failed" }
  } catch {
    Advise "`nvidia-smi` is installed but the driver did not respond."
    Write-Output "  Fix: reinstall the NVIDIA Windows driver (includes WSL2 GPU Paravirtualization),"
    Write-Output "       run `wsl --update`, and reboot."
    return
  }
  Ok "nvidia-smi present and the driver responds."
}

# --- Step 4: NVIDIA Container GPU probe ---------------------------------------
function Check-Toolkit {
  if ($script:GpuVendor -ne "nvidia") { return }
  $probe = docker run --rm --gpus all $TOOLKIT_PROBE_IMAGE nvidia-smi 2>&1
  if ($LASTEXITCODE -eq 0) {
    Ok "NVIDIA container GPU probe succeeded — a container can see the GPU."
    return
  }
  if ($probe -match "could not select device driver") {
    Advise "GPU not reachable from a container — NVIDIA Container Toolkit missing."
  } else {
    Advise "GPU not reachable from a container (`docker run --gpus all` failed)."
  }
  Write-Output "  Fix: install the NVIDIA Container Toolkit inside the WSL2 distro:"
  Write-Output "       sudo apt-get install -y nvidia-docker2 && sudo systemctl restart docker"
}

# --- Step 5: VRAM floor -------------------------------------------------------
function Check-VramFloor {
  if ($script:GpuVendor -ne "nvidia") { return }
  $vram = (nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
  if (-not $vram) {
    Advise "Could not read VRAM from nvidia-smi."
    return
  }
  $vramMb = [int]$vram
  Write-Output "VRAM_TOTAL_MB=$vramMb"   # the installer can read this
  if ($vramMb -ge $VRAM_FLOOR_MB) {
    Ok "VRAM ${vramMb} MB >= ${VRAM_FLOOR_MB} MB floor."
  } else {
    Advise "VRAM ${vramMb} MB is below the ${VRAM_FLOOR_MB} MB floor."
    Write-Output "  The stack runs but may not co-fit ollama + kokoro + GPU STT; use CPU STT."
  }
}

# --- main --------------------------------------------------------------------
Detect-GpuVendor
Hr
Check-DockerDaemon
Hr
Check-Wsl2Backend
Hr
Check-NvidiaSmi
Hr
Check-Toolkit
Hr
Check-VramFloor
Hr
if ($Degraded) {
  Write-Output "GPU doctor: one or more checks flagged (ADVISE above). Proceeding (advise-only)."
} else {
  Write-Output "GPU doctor: all checks passed."
}
exit 0   # always exit 0 (advise-only)
