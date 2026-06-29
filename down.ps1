# down.ps1 — Windows stop wrapper (mirrors down.sh).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
docker compose @args
