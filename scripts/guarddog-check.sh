#!/usr/bin/env bash
#
# guarddog-check.sh - optional deep supply-chain scan for malicious package signals.
set -euo pipefail
cd "$(dirname "$0")/.."

readonly REPORT_DIR_INPUT="${SECURITY_REPORT_DIR:-security/reports}"
readonly REPORT_DIR="${REPORT_DIR_INPUT}/guarddog"
readonly SCAN_TIMEOUT_SECONDS="${GUARDDOG_TIMEOUT_SECONDS:-180}"
mkdir -p "$REPORT_DIR"

PASS=0
WARN=0
FAIL=0

info() { printf '%s\n' "$*"; }
pass() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf 'WARN: %s\n' "$*"; }
block() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }

require_tools() {
  local missing=0 cmd
  for cmd in uvx timeout python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      block "missing required tool: ${cmd}"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ]
}

guarddog() {
  timeout "$SCAN_TIMEOUT_SECONDS" uvx --from guarddog guarddog "$@"
}

json_metric() {
  local metric="$1" file="$2"
  python3 - "$metric" "$file" <<'PY'
import json
import sys

metric, path = sys.argv[1:3]

BLOCK_RULES = {
    "threat-network-exfiltration",
    "threat-network-dns-exfil",
    "threat-network-exfil-sysinfo",
    "threat-network-exfil-messenger",
    "threat-runtime-keylogging",
    "threat-network-reverse-shell",
    "threat-process-cryptomining",
    "threat-setup-network-in-install",
    "threat-npm-preinstall-script",
    "threat-npm-dependency-confusion",
}

with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)

def nonempty(value):
    return value not in (None, {}, [], "", 0)

def risky(obj):
    score = obj.get("risk_score") if isinstance(obj.get("risk_score"), dict) else {}
    return score.get("label") in {"medium_risk", "high_risk"}

blocking = 0
signals = 0
errors = 0

for obj in walk(data):
    results = obj.get("results")
    if isinstance(results, dict):
        for rule, value in results.items():
            if nonempty(value):
                signals += 1
                if rule in BLOCK_RULES and risky(obj):
                    blocking += 1

    scan_errors = obj.get("errors")
    if isinstance(scan_errors, dict):
        errors += len([value for value in scan_errors.values() if nonempty(value)])

print({"blocking": blocking, "signals": signals, "errors": errors}[metric])
PY
}

evaluate_report() {
  local label="$1" file="$2" rc="$3"
  local blocking signals errors
  if ! blocking="$(json_metric blocking "$file" 2>/dev/null)" \
     || ! signals="$(json_metric signals "$file" 2>/dev/null)" \
     || ! errors="$(json_metric errors "$file" 2>/dev/null)"; then
    if [ "$rc" -ne 0 ]; then
      warn "${label}: GuardDog failed or timed out before writing valid JSON. See ${file}"
    else
      block "${label}: GuardDog wrote invalid JSON. See ${file}"
    fi
    return 0
  fi

  if [ "$blocking" -gt 0 ]; then
    block "${label}: GuardDog found blocking malicious-package signals. See ${file}"
  elif [ "$signals" -gt 0 ]; then
    warn "${label}: GuardDog reported non-blocking supply-chain signals. See ${file}"
  elif [ "$errors" -gt 0 ] || [ "$rc" -ne 0 ]; then
    warn "${label}: GuardDog completed with scanner errors/timeouts but no findings. See ${file}"
  else
    pass "${label}: clean"
  fi
}

run_pypi_manifest_scan() {
  local manifest="$1" report="$2" label="$3" rc=0
  set +e
  guarddog pypi verify --output-format=json "$manifest" >"$report"
  rc=$?
  set -e
  evaluate_report "$label" "$report" "$rc"
}

write_npm_targets() {
  python3 - <<'PY'
import json

package = json.load(open("web/package.json", encoding="utf-8"))
lock = json.load(open("web/package-lock.json", encoding="utf-8"))
packages = lock.get("packages") or {}

for name in sorted((package.get("dependencies") or {}).keys()):
    lock_key = f"node_modules/{name}"
    version = (packages.get(lock_key) or {}).get("version")
    if version:
        print(f"{name}\t{version}")
PY
}

run_npm_direct_scan() {
  local report="${REPORT_DIR}/npm-direct.json"
  local tmp="${report}.tmp"
  local name version rc item_report

  printf '[' >"$tmp"
  local first=1
  while IFS=$'\t' read -r name version; do
    [ -n "$name" ] || continue
    item_report="${REPORT_DIR}/npm-$(printf '%s' "$name" | tr '@/ ' '---')-${version}.json"
    rc=0
    set +e
    guarddog npm scan "$name" --version "$version" --output-format=json >"$item_report"
    rc=$?
    set -e

    [ "$first" -eq 1 ] || printf ',' >>"$tmp"
    first=0
    python3 - "$name" "$version" "$rc" "$item_report" >>"$tmp" <<'PY'
import json
import sys

name, version, rc, path = sys.argv[1:5]
try:
    with open(path, encoding="utf-8") as handle:
        result = json.load(handle)
except Exception as exc:
    result = {"errors": {"guarddog": str(exc)}, "results": {}}
json.dump({"dependency": name, "version": version, "rc": int(rc), "result": result}, sys.stdout)
PY
  done < <(write_npm_targets)
  printf ']\n' >>"$tmp"
  mv "$tmp" "$report"
  evaluate_report "GuardDog npm direct dependency scan" "$report" 0
}

main() {
  info "== GuardDog deep supply-chain scan =="
  require_tools || exit 1

  run_pypi_manifest_scan agent/requirements.txt "${REPORT_DIR}/agent-requirements.json" "GuardDog agent Python scan"
  run_pypi_manifest_scan stt/requirements.txt "${REPORT_DIR}/stt-requirements.json" "GuardDog STT Python scan"
  run_pypi_manifest_scan stt/requirements-cpu.txt "${REPORT_DIR}/stt-requirements-cpu.json" "GuardDog CPU STT Python scan"
  run_npm_direct_scan

  printf '\nguarddog-check summary: %d passed, %d warnings, %d failed\n' "$PASS" "$WARN" "$FAIL"
  [ "$FAIL" -eq 0 ]
}

main "$@"
