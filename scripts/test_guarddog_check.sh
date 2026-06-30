#!/usr/bin/env bash
#
# test_guarddog_check.sh - sandbox harness for scripts/guarddog-check.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

readonly -a NEEDED_TOOLS=(bash cat chmod dirname env grep ln mkdir mktemp mv rm sed sort tr python3)

build_path() {
  local dir="$1" tool path
  mkdir -p "$dir"
  for tool in "${NEEDED_TOOLS[@]}"; do
    path="$(type -P "$tool")" && ln -sf "$path" "$dir/$tool"
  done
}

make_shim() {
  local dir="$1" name="$2" body="$3"
  printf '#!/usr/bin/env bash\n%s\n' "$body" >"$dir/$name"
  chmod +x "$dir/$name"
}

install_success_shims() {
  local dir="$1"
  make_shim "$dir" timeout 'shift; exec "$@"'
  make_shim "$dir" uvx '
out="${*: -1}"
case "$out" in
  *package.json)
    printf "%s\n" "{\"issues\":0,\"errors\":{},\"results\":{},\"risk_score\":{\"label\":\"no_risks_detected\"},\"risks\":[]}" ;;
  *)
    printf "%s\n" "[]" ;;
esac
'
}

if bash -n scripts/guarddog-check.sh 2>/dev/null; then
  ok "guarddog-check.sh parses"
else
  bad "guarddog-check.sh syntax"
fi

BIN_MISSING="$WORK/bin-missing"
build_path "$BIN_MISSING"
install_success_shims "$BIN_MISSING"
rm -f "$BIN_MISSING/uvx"
if env -i PATH="$BIN_MISSING" SECURITY_REPORT_DIR="$WORK/reports-missing" bash scripts/guarddog-check.sh >"$WORK/missing.out" 2>&1; then
  bad "missing uvx must fail"
else
  grep -q "missing required tool: uvx" "$WORK/missing.out" \
    && ok "missing uvx gives clear guidance" \
    || { bad "missing uvx output not clear"; cat "$WORK/missing.out"; }
fi

BIN_BAD="$WORK/bin-bad"
build_path "$BIN_BAD"
install_success_shims "$BIN_BAD"
make_shim "$BIN_BAD" uvx '
printf "%s\n" "{\"issues\":1,\"errors\":{},\"results\":{\"threat-network-exfiltration\":[{\"location\":\"pkg/a.py:1\",\"message\":\"exfil\"}]},\"risk_score\":{\"label\":\"high_risk\"},\"risks\":[]}"
'
if env -i PATH="$BIN_BAD" SECURITY_REPORT_DIR="$WORK/reports-bad" bash scripts/guarddog-check.sh >"$WORK/bad.out" 2>&1; then
  bad "malicious GuardDog finding must fail"
else
  grep -q "GuardDog found blocking malicious-package signals" "$WORK/bad.out" \
    && ok "malicious GuardDog finding blocks" \
    || { bad "malicious GuardDog finding did not block"; cat "$WORK/bad.out"; }
fi

BIN_WARN="$WORK/bin-warn"
build_path "$BIN_WARN"
install_success_shims "$BIN_WARN"
make_shim "$BIN_WARN" uvx '
printf "%s\n" "{\"issues\":1,\"errors\":{},\"results\":{\"capability-filesystem-read\":[{\"location\":\"pkg/a.py:1\",\"message\":\"read\"}]},\"risk_score\":{\"label\":\"low\"},\"risks\":[]}"
'
if env -i PATH="$BIN_WARN" SECURITY_REPORT_DIR="$WORK/reports-warn" bash scripts/guarddog-check.sh >"$WORK/warn.out" 2>&1; then
  grep -q "GuardDog reported non-blocking supply-chain signals" "$WORK/warn.out" \
    && ok "capability GuardDog finding warns only" \
    || { bad "capability GuardDog warning absent"; cat "$WORK/warn.out"; }
else
  bad "capability GuardDog finding must not fail"
  cat "$WORK/warn.out"
fi

BIN_OK="$WORK/bin-ok"
build_path "$BIN_OK"
install_success_shims "$BIN_OK"
if env -i PATH="$BIN_OK" SECURITY_REPORT_DIR="$WORK/reports-ok" bash scripts/guarddog-check.sh >"$WORK/ok.out" 2>&1; then
  if [ -s "$WORK/reports-ok/guarddog/agent-requirements.json" ] \
     && [ -s "$WORK/reports-ok/guarddog/stt-requirements.json" ] \
     && [ -s "$WORK/reports-ok/guarddog/stt-requirements-cpu.json" ] \
     && [ -s "$WORK/reports-ok/guarddog/npm-direct.json" ]; then
    ok "success path writes expected reports"
  else
    bad "success path did not write expected reports"
    find "$WORK/reports-ok" -type f -maxdepth 2 -print 2>/dev/null || true
  fi
else
  bad "all-shim success path failed"
  cat "$WORK/ok.out"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
