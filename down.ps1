# down.ps1 — Windows stop wrapper (mirrors down.sh). Stops and removes the compose
# services (containers + default network), leaving named volumes (pulled models,
# caches) intact. Passes through $args to `docker compose down`.
#
#   .\down.ps1              # stop + remove containers
#   .\down.ps1 -v          # ALSO remove named volumes (models re-pull next boot)
#   .\down.ps1 --remove-orphans
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($args -contains "-v") {
  Write-Output "This also removes named volumes — pulled models + caches will re-download."
}
docker compose down @args
