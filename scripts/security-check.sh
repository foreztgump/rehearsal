#!/usr/bin/env bash
#
# security-check.sh - local-first source/dependency security baseline.
set -euo pipefail
cd "$(dirname "$0")/.."

readonly REPORT_DIR_INPUT="${SECURITY_REPORT_DIR:-security/reports}"
mkdir -p "$REPORT_DIR_INPUT"
readonly REPORT_DIR="$(cd "$REPORT_DIR_INPUT" && pwd -P)"
readonly SBOM_FILE="${REPORT_DIR}/source.cdx.json"
PASS=0
WARN=0
FAIL=0

info() { printf '%s\n' "$*"; }
pass() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf 'WARN: %s\n' "$*"; }
block() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }

install_hint() {
  case "$1" in
    npm) printf 'install Node/npm: https://nodejs.org/\n' ;;
    uvx) printf 'install uv: https://docs.astral.sh/uv/getting-started/installation/\n' ;;
    python3) printf 'install Python 3: https://www.python.org/downloads/\n' ;;
    osv-scanner) printf 'install: https://google.github.io/osv-scanner/installation/\n' ;;
    syft) printf 'install: https://github.com/anchore/syft#installation\n' ;;
    grype) printf 'install: https://github.com/anchore/grype#installation\n' ;;
    gitleaks) printf 'install: https://github.com/gitleaks/gitleaks#installing\n' ;;
  esac
}

require_tools() {
  local missing=0 cmd
  for cmd in npm uvx python3 osv-scanner syft grype gitleaks; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      block "missing required tool: ${cmd}"
      install_hint "$cmd" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ]
}

json_metric() {
  local kind="$1" metric="$2" file="$3"
  python3 - "$kind" "$metric" "$file" <<'PY'
import json
import sys

kind, metric, path = sys.argv[1:4]
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

def blocking_severity(value):
    return str(value or "").lower() in {"high", "critical"}

def blocking_cvss_score(value):
    try:
        return float(value) >= 7.0
    except (TypeError, ValueError):
        return False

def recursive_blocking_count(value):
    return sum(
        1
        for obj in walk(value)
        for key, val in obj.items()
        if str(key).lower() == "severity" and blocking_severity(val)
    )

def osv_vulnerability_blocks(vuln):
    for obj in walk(vuln):
        for key, val in obj.items():
            name = str(key).replace("-", "_").lower()
            if name == "severity" and blocking_severity(val):
                return True
            if name in {"score", "max_severity", "max_severity_score"}:
                if blocking_severity(val) or blocking_cvss_score(val):
                    return True
    return False

if kind == "npm":
    vulns = list((data.get("vulnerabilities") or {}).values())
    total = len(vulns)
    blocking = sum(1 for vuln in vulns if blocking_severity(vuln.get("severity")))
elif kind == "pip":
    total = sum(len(dep.get("vulns") or []) for dep in data.get("dependencies") or [])
    # pip-audit JSON has no normalized severity, so any advisory blocks.
    blocking = total
elif kind == "grype":
    matches = data.get("matches") or []
    total = len(matches)
    blocking = sum(
        1
        for match in matches
        if blocking_severity((match.get("vulnerability") or {}).get("severity"))
    )
elif kind == "osv":
    vulns = []
    for obj in walk(data):
        found = obj.get("vulnerabilities")
        if isinstance(found, list):
            vulns.extend(found)
    total = len(vulns)
    blocking = sum(1 for vuln in vulns if osv_vulnerability_blocks(vuln))
else:
    total = 0
    blocking = recursive_blocking_count(data)

print(blocking if metric == "blocking" else total)
PY
}

evaluate_json_report() {
  local kind="$1" label="$2" file="$3" rc="$4"
  local total blocking
  if ! total="$(json_metric "$kind" total "$file" 2>/dev/null)" \
     || ! blocking="$(json_metric "$kind" blocking "$file" 2>/dev/null)"; then
    if [ "$rc" -ne 0 ]; then
      block "${label}: command failed without parseable vulnerabilities. See ${file}"
    else
      block "${label}: could not parse vulnerability report. See ${file}"
    fi
    return 0
  fi

  if [ "$blocking" -gt 0 ]; then
    block "${label}: ${blocking} blocking vulnerabilities (${total} total). See ${file}"
  elif [ "$total" -gt 0 ]; then
    warn "${label}: ${total} non-blocking/unknown vulnerabilities. See ${file}"
  elif [ "$rc" -ne 0 ]; then
    block "${label}: command failed without parseable vulnerabilities. See ${file}"
  else
    pass "${label}: clean"
  fi
}

run_npm_checks() {
  info "== npm dependency checks =="
  (cd web && npm ci)
  pass "npm ci"

  local audit_report="${REPORT_DIR}/npm-audit.json"
  local audit_rc=0
  set +e
  (cd web && npm audit --omit=dev --json >"$audit_report")
  audit_rc=$?
  set -e
  evaluate_json_report npm "npm audit production dependencies" "$audit_report" "$audit_rc"

  local signature_report="${REPORT_DIR}/npm-signatures.json"
  (cd web && npm audit signatures --json >"$signature_report")
  python3 - "$signature_report" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
invalid = data.get("invalid") or []
missing = data.get("missing") or []
if invalid or missing:
    print(f"invalid={len(invalid)} missing={len(missing)}", file=sys.stderr)
    raise SystemExit(1)
PY
  pass "npm audit signatures"
}

run_python_audit() {
  info "== Python dependency checks =="
  local report="${REPORT_DIR}/pip-audit.json"
  local rc=0
  set +e
  uvx --python 3.12 --from pip-audit pip-audit \
    -r agent/requirements.txt \
    -r stt/requirements.txt \
    -r stt/requirements-cpu.txt \
    -r requirements-dev.txt \
    --format json >"$report"
  rc=$?
  set -e
  evaluate_json_report pip "pip-audit resolved Python dependencies" "$report" "$rc"
}

run_osv() {
  info "== OSV source/lockfile scan =="
  local report="${REPORT_DIR}/osv-scanner.json"
  local rc=0
  set +e
  osv-scanner -r . --format json >"$report"
  rc=$?
  set -e
  evaluate_json_report osv "OSV-Scanner recursive scan" "$report" "$rc"
}

run_sbom_and_grype() {
  info "== SBOM + Grype scan =="
  syft . \
    --exclude './web/node_modules/**' \
    --exclude './web/.next/**' \
    --exclude './security/reports/**' \
    --exclude './.planning/**' \
    -o cyclonedx-json >"$SBOM_FILE"
  pass "Syft source SBOM: ${SBOM_FILE}"

  local report="${REPORT_DIR}/grype-source.json"
  local rc=0
  set +e
  grype "sbom:${SBOM_FILE}" -o json >"$report"
  rc=$?
  set -e
  evaluate_json_report grype "Grype source SBOM scan" "$report" "$rc"
}

run_gitleaks() {
  info "== secret scan =="
  local report="${REPORT_DIR}/gitleaks.json"
  local config="${REPORT_DIR}/gitleaks.toml"
  write_gitleaks_config "$config"
  if gitleaks detect --source . --config "$config" --no-banner --redact --report-format json --report-path "$report"; then
    pass "Gitleaks secret scan"
  else
    block "Gitleaks found verified or likely secrets. See ${report}"
  fi
}

write_gitleaks_config() {
  cat >"$1" <<'TOML'
title = "voice-trainer security-check gitleaks config"

[extend]
useDefault = true

[[allowlists]]
description = "repository paths excluded from the local security baseline"
paths = [
  '''(^|/)\.planning/''',
  '''(^|/)security/reports/''',
  '''(^|/)web/node_modules/''',
  '''(^|/)web/\.next/''',
  '''(^|/)\.env(\..*)?$''',
  '''(^|/)certs/.*\.pem$''',
]
TOML
}

run_shellcheck_if_present() {
  info "== shell scan =="
  if ! command -v shellcheck >/dev/null 2>&1; then
    warn "shellcheck not installed; skipping optional shell lint"
    return 0
  fi

  mapfile -t shell_files < <(
    find . \
      -path './web/node_modules' -prune -o \
      -path './web/.next' -prune -o \
      -path './security/reports' -prune -o \
      -type f -name '*.sh' -print
  )
  if [ "${#shell_files[@]}" -eq 0 ]; then
    warn "no shell files found"
    return 0
  fi
  shellcheck "${shell_files[@]}"
  pass "ShellCheck"
}

run_pattern_scan() {
  info "== suspicious pattern scan =="
  if ! command -v rg >/dev/null 2>&1; then
    warn "rg not installed; skipping suspicious-pattern scan"
    return 0
  fi

  local report="${REPORT_DIR}/suspicious-patterns.txt"
  set +e
  rg -n \
    -g '*.sh' -g '*.py' -g '*.ts' -g '*.tsx' \
    -g '!web/node_modules/**' -g '!web/.next/**' \
    -g '!security/reports/**' -g '!docs/**' \
    -g '!scripts/security-check.sh' \
    'curl .*\|.*(sh|bash)|wget .*\|.*(sh|bash)|eval \$|base64 -d|nc -e|/dev/tcp|chmod 777' \
    . >"$report"
  local rc=$?
  set -e
  case "$rc" in
    0) block "suspicious source patterns found. See ${report}" ;;
    1) rm -f "$report"; pass "suspicious-pattern scan" ;;
    *) block "suspicious-pattern scan failed. See ${report}" ;;
  esac
}

main() {
  require_tools || exit 1
  run_npm_checks
  run_python_audit
  run_osv
  run_sbom_and_grype
  run_gitleaks
  run_shellcheck_if_present
  run_pattern_scan

  printf '\nsecurity-check summary: %d passed, %d warnings, %d failed\n' "$PASS" "$WARN" "$FAIL"
  [ "$FAIL" -eq 0 ]
}

main "$@"
