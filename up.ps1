# up.ps1 — Windows start wrapper (mirrors up.sh). Runs gpu-doctor.ps1 (advise-only)
# then `docker compose up`, passing through $args. SKIP_DOCTOR=1 skips the preflight.
#
#   .\up.ps1              # preflight, then docker compose up
#   .\up.ps1 -d          # detached
#   $env:SKIP_DOCTOR=1; .\up.ps1 -d   # skip the preflight (CI / repeat boots)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($env:SKIP_DOCTOR -ne "1") {
  & "$PSScriptRoot\scripts\gpu-doctor.ps1"
  Write-Output ""
}

# STT placement preflight (advise-only; mirrors up.sh). When .env selects GPU STT
# (STT_FORCE_CPU=0 + STT_HEADROOM_MEASURED=1) but the opt-in 'stt-gpu' profile is
# not enabled, the agent fails to reach nemo-stt with a cryptic 'Connection error.'
# and hangs on "Listening to you..." (field report). Warn, never block.
function Warn-SttProfile {
  if (-not (Test-Path .env)) { return }
  $envText = Get-Content .env -Raw
  if ($envText -notmatch '(?m)^\s*STT_FORCE_CPU=0\s*$')        { return }
  if ($envText -notmatch '(?m)^\s*STT_HEADROOM_MEASURED=1\s*$') { return }
  if (",$($env:COMPOSE_PROFILES)," -like "*,stt-gpu,*")        { return }
  Write-Host "WARN: .env selects GPU STT (STT_FORCE_CPU=0 + STT_HEADROOM_MEASURED=1) but the" -ForegroundColor Yellow
  Write-Host "      'stt-gpu' profile is not enabled — the agent will fail to reach nemo-stt" -ForegroundColor Yellow
  Write-Host "      ('Connection error.'). Enable it, e.g.:  `$env:COMPOSE_PROFILES='stt-gpu'; .\up.ps1 -d" -ForegroundColor Yellow
}
Warn-SttProfile

docker compose up @args
