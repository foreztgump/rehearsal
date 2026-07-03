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
#   5. CUDA/driver floor >= 12.8 (Blackwell / kokoro cu128)
#   6. VRAM floor >= 16384 MB
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
$CUDA_FLOOR    = if ($env:CUDA_FLOOR) { "$env:CUDA_FLOOR" } else { "12.8" }
$TOOLKIT_PROBE_IMAGE = if ($env:TOOLKIT_PROBE_IMAGE) { $env:TOOLKIT_PROBE_IMAGE } else { "nvidia/cuda:12.4.0-base-ubuntu22.04" }

$Degraded = $false
$GpuVendor = "none"

function Ok($msg)     { Write-Output "OK: $msg" }
function Advise($msg) { Write-Output "ADVISE: $msg"; $script:Degraded = $true }
function Hr           { Write-Output "----------------------------------------------------------------------" }

function Detect-GpuVendor {
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $script:GpuVendor = "nvidia"; return }
  # AMD: the ROCm marker only exists on ROCm-listed cards. Consumer RDNA cards run the
  # LLM via native Ollama's Vulkan backend and have NO marker — also match the adapter
  # name so the Vulkan-only AMD path is detected (else it mis-reports as 'none').
  if (Test-Path "C:\Program Files\AMD ROCm*\bin") { $script:GpuVendor = "amd"; return }
  try {
    $amd = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match "AMD|Radeon" }
    if ($amd) { $script:GpuVendor = "amd"; return }
  } catch { }
  $script:GpuVendor = "none"
}

# --- Step 1: Docker Desktop running + daemon responds -------------------------
function Check-DockerDaemon {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Advise "'docker' not found — Docker Desktop is not installed or not on PATH."
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
      Advise "Could not confirm WSL2 backend from 'docker info'."
      Write-Output "  Fix: Docker Desktop -> Settings -> General -> 'Use the WSL 2 based engine'."
      Write-Output "       GPU support on Windows is WSL2-backend-only."
    }
  } catch {
    Advise "Could not query 'docker info' for the WSL2 backend."
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
    Advise "'nvidia-smi' is installed but the driver did not respond."
    Write-Output "  Fix: reinstall the NVIDIA Windows driver (includes WSL2 GPU Paravirtualization),"
    Write-Output "       run 'wsl --update', and reboot."
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
    Advise "GPU not reachable from a container — Docker Desktop's WSL2 GPU mount is not active."
  } else {
    Advise "GPU not reachable from a container ('docker run --gpus all' failed)."
  }
  # F21: on Docker Desktop + WSL2 the GPU integration ships WITH Docker Desktop — you
  # cannot apt-install a container runtime into the docker-desktop distro, the old
  # apt package is deprecated, and restarting a Linux docker service does not apply.
  # The real remedy (mirrors INSTALLATION.md) is: update the Windows NVIDIA driver,
  # then reset the WSL2 GPU mount.
  Write-Output "  Fix: update the Windows NVIDIA driver (CUDA >= 12.8), then reset WSL2 + Docker Desktop:"
  Write-Output "       wsl --update; wsl --shutdown"
  Write-Output "       then restart Docker Desktop (or reboot) so the GPU mount is re-created."
}

# --- Step 5: CUDA/driver floor (mirror gpu-doctor.sh check_cuda_floor) ---------
# nvidia-smi's header reports the MAX CUDA the installed driver supports. kokoro's
# ...-cu128 image needs CUDA >= 12.8; a lower driver fails `up` with a cryptic runc
# "unsatisfied condition: cuda>=12.8" — advise the driver update up front instead.
function Check-CudaFloor {
  if ($script:GpuVendor -ne "nvidia") { return }
  $cuda = (nvidia-smi --query-gpu=cuda_version --format=csv,noheader 2>$null | Select-Object -First 1)
  if ($cuda) { $cuda = $cuda.Trim() }
  # Older drivers reject/omit the cuda_version query field — fall back to the header.
  # Newer Windows drivers can label it "CUDA UMD Version" instead.
  if (-not $cuda -or $cuda -notmatch '^[0-9]+(\.[0-9]+)?$') {
    $m = (nvidia-smi 2>$null | Select-String -Pattern 'CUDA(?: UMD)? Version:\s*([0-9]+\.[0-9]+)')
    if ($m) { $cuda = $m.Matches[0].Groups[1].Value } else { $cuda = $null }
  }
  if (-not $cuda) {
    Advise "Could not read the driver's CUDA version (need >= $CUDA_FLOOR)."
    Write-Output "  Fix: update your NVIDIA driver; kokoro needs CUDA >= $CUDA_FLOOR (Blackwell)."
    return
  }
  # [version] compares major.minor numerically (so 12.10 > 12.8, unlike string sort).
  $have  = [version]($(if ($cuda -match '\.') { $cuda } else { "$cuda.0" }))
  $floor = [version]($(if ($CUDA_FLOOR -match '\.') { $CUDA_FLOOR } else { "$CUDA_FLOOR.0" }))
  if ($have -ge $floor) {
    Ok "Driver supports CUDA $cuda (>= $CUDA_FLOOR)."
  } else {
    Advise "Driver supports CUDA $cuda, but kokoro needs CUDA >= $CUDA_FLOOR (Blackwell/sm_120)."
    Write-Output "  Fix: update your NVIDIA driver to one that advertises CUDA >= $CUDA_FLOOR."
  }
}

# --- Step 6: VRAM floor -------------------------------------------------------
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

# --- AMD branch (Vulkan-only; no ROCm on Windows for consumer RDNA cards) ------
# Consumer AMD (e.g. RX 6600 XT / gfx1032) is off Ollama's ROCm list, so the LLM
# runs in NATIVE host Ollama via the Vulkan backend — NOT in a container. The
# NVIDIA CUDA/VRAM floors do not apply; advise the native-Ollama + Vulkan path
# instead (field report Bug #4). VRAM is deliberately NOT read from
# Win32_VideoController here: its AdapterRAM wraps at 4 GB and under-reports 8 GB
# cards (field report G3).
function Check-AmdVulkan {
  $adapter = $null
  try {
    $adapter = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -match "AMD|Radeon" } | Select-Object -First 1
  } catch { }
  if ($adapter) {
    Ok "AMD/Radeon adapter detected: $($adapter.Name)."
  } else {
    Advise "AMD ROCm marker found but no Radeon adapter enumerated."
  }
  Write-Output "  Windows AMD topology: the LLM runs in NATIVE host Ollama (Vulkan), not a"
  Write-Output "  container; only the CPU services run in Docker. To get GPU acceleration on"
  Write-Output "  RDNA cards off Ollama's ROCm list, force the Vulkan backend (permanent + restart):"
  Write-Output '    [Environment]::SetEnvironmentVariable("OLLAMA_LLM_LIBRARY","vulkan","User")'
  Write-Output "    Get-Process ollama* | Stop-Process -Force; Start-Process ollama"
  Write-Output "  Verify with 'ollama ps' (PROCESSOR column should show GPU). See INSTALLATION.md."
}

# --- main --------------------------------------------------------------------
Detect-GpuVendor
Hr
Check-DockerDaemon
Hr
Check-Wsl2Backend
Hr
switch ($script:GpuVendor) {
  "nvidia" {
    Check-NvidiaSmi
    Hr
    Check-Toolkit
    Hr
    Check-CudaFloor
    Hr
    Check-VramFloor
    Hr
  }
  "amd" {
    Check-AmdVulkan
    Hr
  }
  default {
    Advise "No NVIDIA driver and no AMD adapter detected — no GPU acceleration."
    Write-Output "  The stack still boots on CPU (ollama + kokoro), but will not hit the live-voice"
    Write-Output "  latency target. See INSTALLATION.md 'No Supported GPU'."
    Hr
  }
}
if ($Degraded) {
  Write-Output "GPU doctor: one or more checks flagged (ADVISE above). Proceeding (advise-only)."
} else {
  Write-Output "GPU doctor: all checks passed."
}
exit 0   # always exit 0 (advise-only)
