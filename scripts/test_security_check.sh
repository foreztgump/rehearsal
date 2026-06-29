#!/usr/bin/env bash
#
# test_security_check.sh - sandbox harness for scripts/security-check.sh.
# Uses isolated PATH shims so no real scanner, registry, or network call runs.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

readonly -a NEEDED_TOOLS=(bash cat dirname env find grep mkdir printf sed tr python3)

build_path() {
  local dir="$1" tool path
  mkdir -p "$dir"
  for tool in "${NEEDED_TOOLS[@]}"; do
    path="$(command -v "$tool")" && ln -sf "$path" "$dir/$tool"
  done
}

make_shim() {
  local dir="$1" name="$2" body="$3"
  printf '#!/usr/bin/env bash\n%s\n' "$body" >"$dir/$name"
  chmod +x "$dir/$name"
}

install_success_shims() {
  local dir="$1"
  make_shim "$dir" npm '
case "$*" in
  "ci") exit 0 ;;
  "audit --omit=dev --json") printf "%s\n" "{\"auditReportVersion\":2,\"vulnerabilities\":{}}" ;;
  "audit signatures --json") printf "%s\n" "{\"invalid\":[],\"missing\":[]}" ;;
  *) echo "unexpected npm args: $*" >&2; exit 2 ;;
esac
'
  make_shim "$dir" uvx 'printf "%s\n" "{\"dependencies\":[],\"fixes\":[]}"'
  make_shim "$dir" osv-scanner 'printf "%s\n" "{\"results\":[]}"'
  make_shim "$dir" syft 'printf "%s\n" "{\"bomFormat\":\"CycloneDX\",\"components\":[]}"'
  make_shim "$dir" grype 'printf "%s\n" "{\"matches\":[]}"'
  make_shim "$dir" gitleaks '
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--report-path" ]; then out="$2"; shift 2; else shift; fi
done
[ -n "$out" ] && printf "%s\n" "[]" >"$out"
exit 0
'
}

bash -n scripts/security-check.sh && ok "security-check.sh parses" || bad "security-check.sh syntax"

BIN_MISSING="$WORK/bin-missing"
build_path "$BIN_MISSING"
install_success_shims "$BIN_MISSING"
rm -f "$BIN_MISSING/osv-scanner"
if env -i PATH="$BIN_MISSING" SECURITY_REPORT_DIR="$WORK/reports-missing" bash scripts/security-check.sh >"$WORK/missing.out" 2>&1; then
  bad "missing required scanner must fail"
else
  if grep -q "missing required tool: osv-scanner" "$WORK/missing.out"; then
    ok "missing OSV-Scanner gives clear guidance"
  else
    bad "missing OSV-Scanner output not clear"
    cat "$WORK/missing.out"
  fi
fi

BIN_OK="$WORK/bin-ok"
build_path "$BIN_OK"
install_success_shims "$BIN_OK"
if env -i PATH="$BIN_OK" SECURITY_REPORT_DIR="$WORK/reports-ok" bash scripts/security-check.sh >"$WORK/ok.out" 2>&1; then
  if [ -s "$WORK/reports-ok/source.cdx.json" ] \
     && [ -s "$WORK/reports-ok/npm-audit.json" ] \
     && [ -s "$WORK/reports-ok/pip-audit.json" ] \
     && [ -s "$WORK/reports-ok/osv-scanner.json" ] \
     && [ -s "$WORK/reports-ok/grype-source.json" ] \
     && [ -s "$WORK/reports-ok/gitleaks.json" ]; then
    ok "success path writes expected reports"
  else
    bad "success path did not write expected reports"
    find "$WORK/reports-ok" -type f -maxdepth 1 -print 2>/dev/null || true
  fi
  grep -q "WARN: shellcheck not installed" "$WORK/ok.out" \
    && ok "missing optional shellcheck warns only" \
    || bad "missing optional shellcheck warning absent"
else
  bad "all-shim success path failed"
  cat "$WORK/ok.out"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
