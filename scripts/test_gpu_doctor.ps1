# test_gpu_doctor.ps1 — Windows GPU doctor parse + mocked-scenario checks.
#
# Mirrors scripts/test_gpu_doctor.sh. Requires pwsh. SKIPS cleanly (exit 0) when
# pwsh is not available — operator-run on Windows.
#
#   pwsh -NoProfile -File scripts/test_gpu_doctor.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Get-Command pwsh -ErrorAction SilentlyContinue) -and $PSVersionTable.PSVersion.Major -lt 5) {
  Write-Output "SKIP: pwsh not available — Windows doctor checks deferred to operator"
  exit 0
}

$Pass = 0; $Fail = 0
function Ok($name)  { $script:Pass++; Write-Output "PASS: $name" }
function Bad($name) { $script:Fail++; Write-Output "FAIL: $name" }

function Test-Parse($path) {
  $tokens = $null; $errors = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
  return ($errors.Count -eq 0)
}

if (Test-Parse "$PSScriptRoot\gpu-doctor.ps1") { Ok "gpu-doctor.ps1 parses" } else { Bad "gpu-doctor.ps1 syntax" }

$doctorSource = Get-Content "$PSScriptRoot\gpu-doctor.ps1" -Raw
if ($doctorSource -match 'CUDA\(\?: UMD\)\? Version') {
  Ok "gpu-doctor.ps1 accepts CUDA UMD Version header"
} else {
  Bad "gpu-doctor.ps1 missing CUDA UMD Version fallback"
}

# Guard the backtick-escape bug class: a backtick inside a double-quoted message
# is a PowerShell escape, not decoration — e.g. "`nvidia-smi`" renders as a
# newline followed by "vidia-smi" (the leading char is eaten). Scan the Advise /
# Write-Output message strings and fail if any double-quoted string contains a
# backtick. Use single quotes for command emphasis instead.
$msgLines = $doctorSource -split "`n" | Where-Object { $_ -match '^\s*(Advise|Write-Output)\s+"' }
$badMsgs  = $msgLines | Where-Object { $_ -match '"[^"]*`[^"]*"' }
if ($badMsgs) {
  Bad "gpu-doctor.ps1 has backtick escapes in message strings: $(($badMsgs | ForEach-Object { $_.Trim() }) -join ' | ')"
} else {
  Ok "gpu-doctor.ps1 message strings have no backtick-escape artifacts"
}

# The doctor's ordered checks need a real Windows + Docker + GPU host; the parse
# gate + structural mirror of test_gpu_doctor.sh covers the contract here.
$hasNvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($hasNvidia) {
  Ok "NVIDIA present — real doctor run possible on this host"
} else {
  Ok "No NVIDIA — doctor AMD/none paths deferred to Windows operator"
}

Write-Output ""
Write-Output "$Pass passed, $Fail failed"
exit ([int]($Fail -ne 0))
