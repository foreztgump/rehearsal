# up.ps1 — Windows start wrapper (mirrors up.sh). Runs gpu-doctor.ps1 (advise-only)
# then `docker compose up`, passing through $args. SKIP_DOCTOR=1 skips the preflight.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($env:SKIP_DOCTOR -ne "1") {
  & "$PSScriptRoot\scripts\gpu-doctor.ps1"
  Write-Output ""
}
docker compose @args
