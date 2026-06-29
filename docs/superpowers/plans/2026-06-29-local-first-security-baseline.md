# Local-First Security Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-first security baseline that checks source cleanliness, dependency vulnerabilities, and non-source artifact provenance before public source access.

**Architecture:** Keep this as one Bash orchestrator plus one provenance document. The script runs existing package-manager checks, OSV-Scanner, Syft, Grype, and Gitleaks, writes local reports under `security/reports/`, and fails on blocking findings. Provenance is a committed Markdown document that records upstreams and known pinning gaps.

**Tech Stack:** Bash, npm, uvx/pip-audit, OSV-Scanner, Syft, Grype, Gitleaks, optional ShellCheck, Markdown.

---

## File Structure

- Modify `.gitignore`: ignore generated security reports.
- Create `scripts/security-check.sh`: local security orchestrator.
- Create `scripts/test_security_check.sh`: isolated PATH shim test harness.
- Create `SECURITY_PROVENANCE.md`: committed source/provenance evidence.
- Modify `README.md`: short public-trust section.

No CI files. No release signing. No VirusTotal automation.

## Task 1: Test Harness And Report Ignore

**Files:**
- Modify: `.gitignore`
- Create: `scripts/test_security_check.sh`

- [ ] **Step 1: Write the failing test harness**

Add this file:

```bash
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
```

- [ ] **Step 2: Ignore generated report files**

Append this to `.gitignore`:

```gitignore

# Local security scan reports
security/reports/
```

- [ ] **Step 3: Run test to verify it fails before implementation**

Run:

```bash
./scripts/test_security_check.sh
```

Expected: FAIL because `scripts/security-check.sh` does not exist yet or does not parse.

- [ ] **Step 4: Commit**

```bash
git add .gitignore scripts/test_security_check.sh
git commit -m "test: add local security check harness"
```

## Task 2: Security Check Script

**Files:**
- Create: `scripts/security-check.sh`
- Test: `scripts/test_security_check.sh`

- [ ] **Step 1: Implement the local orchestrator**

Create `scripts/security-check.sh`:

```bash
#!/usr/bin/env bash
#
# security-check.sh - local-first source/dependency security baseline.
set -euo pipefail
cd "$(dirname "$0")/.."

readonly REPO_ROOT="$PWD"
readonly REPORT_DIR="${SECURITY_REPORT_DIR:-security/reports}"
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
    osv-scanner) printf 'install: https://google.github.io/osv-scanner/installation/\n' ;;
    syft) printf 'install: https://github.com/anchore/syft#installation\n' ;;
    grype) printf 'install: https://github.com/anchore/grype#installation\n' ;;
    gitleaks) printf 'install: https://github.com/gitleaks/gitleaks#installing\n' ;;
    uvx) printf 'install uv: https://docs.astral.sh/uv/getting-started/installation/\n' ;;
    npm) printf 'install Node/npm: https://nodejs.org/\n' ;;
    python3) printf 'install Python 3: https://www.python.org/downloads/\n' ;;
    *) printf 'install %s from its upstream package.\n' "$1" ;;
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

def severity_is_blocking(value):
    return str(value or "").lower() in {"high", "critical"}

def recursive_blocking_count(value):
    count = 0
    for obj in walk(value):
        for key, val in obj.items():
            if str(key).lower() == "severity" and severity_is_blocking(val):
                count += 1
    return count

if kind == "npm":
    vulns = list((data.get("vulnerabilities") or {}).values())
    total = len(vulns)
    blocking = sum(1 for vuln in vulns if severity_is_blocking(vuln.get("severity")))
elif kind == "pip":
    total = sum(len(dep.get("vulns") or []) for dep in data.get("dependencies") or [])
    # pip-audit JSON does not provide normalized severity, so any Python advisory blocks.
    blocking = total
elif kind == "grype":
    matches = data.get("matches") or []
    total = len(matches)
    blocking = sum(
        1
        for match in matches
        if severity_is_blocking((match.get("vulnerability") or {}).get("severity"))
    )
elif kind == "osv":
    total = 0
    for obj in walk(data):
        vulns = obj.get("vulnerabilities") if isinstance(obj, dict) else None
        if isinstance(vulns, list):
            total += len(vulns)
    blocking = recursive_blocking_count(data)
else:
    total = 0
    blocking = recursive_blocking_count(data)

print(blocking if metric == "blocking" else total)
PY
}

evaluate_json_report() {
  local kind="$1" label="$2" file="$3" rc="$4"
  local total blocking
  total="$(json_metric "$kind" total "$file")"
  blocking="$(json_metric "$kind" blocking "$file")"

  if [ "$blocking" -gt 0 ]; then
    block "${label}: ${blocking} blocking vulnerabilities (${total} total). See ${file}"
    return 0
  fi
  if [ "$total" -gt 0 ]; then
    warn "${label}: ${total} non-blocking/unknown vulnerabilities. See ${file}"
    return 0
  fi
  if [ "$rc" -ne 0 ]; then
    block "${label}: command failed without parseable vulnerabilities. See ${file}"
    return 0
  fi
  pass "${label}: clean"
}

run_npm_checks() {
  info "== npm dependency checks =="
  (cd web && npm ci)
  pass "npm ci"

  local audit_report="${REPORT_DIR}/npm-audit.json"
  local audit_rc=0
  set +e
  (cd web && npm audit --omit=dev --json >"${REPO_ROOT}/${audit_report}")
  audit_rc=$?
  set -e
  evaluate_json_report npm "npm audit production dependencies" "$audit_report" "$audit_rc"

  local signature_report="${REPORT_DIR}/npm-signatures.json"
  (cd web && npm audit signatures --json >"${REPO_ROOT}/${signature_report}")
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
  if gitleaks detect --source . --no-banner --redact --report-format json --report-path "$report"; then
    pass "Gitleaks secret scan"
  else
    block "Gitleaks found verified or likely secrets. See ${report}"
  fi
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
    -g '!web/node_modules/**' -g '!web/.next/**' -g '!security/reports/**' -g '!docs/**' \
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
  mkdir -p "$REPORT_DIR"
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
```

- [ ] **Step 2: Make the scripts executable**

Run:

```bash
chmod +x scripts/security-check.sh scripts/test_security_check.sh
```

- [ ] **Step 3: Run the shim test**

Run:

```bash
./scripts/test_security_check.sh
```

Expected: PASS, including:

```text
PASS: security-check.sh parses
PASS: missing OSV-Scanner gives clear guidance
PASS: success path writes expected reports
PASS: missing optional shellcheck warns only
```

- [ ] **Step 4: Run syntax checks on touched shell files**

Run:

```bash
bash -n scripts/security-check.sh scripts/test_security_check.sh
```

Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/security-check.sh scripts/test_security_check.sh
git commit -m "chore: add local security check script"
```

## Task 3: Provenance Document

**Files:**
- Create: `SECURITY_PROVENANCE.md`

- [ ] **Step 1: Write the provenance document**

Create `SECURITY_PROVENANCE.md`:

````markdown
# Security Provenance

This project is distributed as source. Users build and run it locally.

This document tracks non-source artifacts and dependency inputs that deserve extra
provenance scrutiny before public access.

## Current Trust Claim

- Source is scanned locally with `./scripts/security-check.sh`.
- npm dependencies are installed from `web/package-lock.json` with registry integrity metadata.
- Python dependencies are currently resolved from requirement ranges and scanned at runtime.
- Docker images are tag-pinned but not digest-pinned.
- Model artifacts are fetched from named upstreams; some revisions still default to `main`.

## Known Pinning Gaps

| Area | Current state | Smallest next step |
| --- | --- | --- |
| Python packages | Requirement ranges in `agent/`, `stt/`, and `requirements-dev.txt`. | Generate per-runtime hash lockfiles with `uv pip compile --generate-hashes` if exact Python artifact traceability becomes required. |
| Docker images | Tags are pinned; digests are not pinned. | Replace tags with `tag@sha256:<digest>` after the public baseline is green. |
| Hugging Face STT revision | `STT_MODEL_REVISION` defaults to `main` unless overridden. | Pin a commit SHA in `.env.example` after final model choice is frozen. |
| Ollama community models | Some ladder entries use `:latest` or remote GGUF references. | Record resolved model manifests during install or replace with immutable references when Ollama exposes a stable one for the target source. |
| Vendored browser assets | Assets are committed under `web/public/vendor/`; upstream/version is known from project research. | Add per-file checksums if those files change again. |

## Docker Images

| Image | Where used | Upstream | Pin status | Notes |
| --- | --- | --- | --- | --- |
| `livekit/livekit-server:v1.10.1` | `docker-compose.yml` | https://hub.docker.com/r/livekit/livekit-server | tag-pinned | Self-hosted LiveKit server. |
| `ollama/ollama:0.30.10` | `docker-compose.yml` | https://hub.docker.com/r/ollama/ollama | tag-pinned | Gemma 4 support; local model server. |
| `ghcr.io/remsky/kokoro-fastapi-gpu:v0.5.0-cu128` | `docker-compose.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | NVIDIA CUDA 12.8 TTS image. |
| `ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0` | `docker-compose.cpu-tts.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | CPU TTS override. |
| `ghcr.io/remsky/kokoro-fastapi-rocm:v0.5.0` | `docker-compose.amd.yml` | https://github.com/remsky/Kokoro-FastAPI | tag-pinned | AMD ROCm TTS override. |
| `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` | `agent/Dockerfile` | https://github.com/astral-sh/uv | tag-pinned | Agent base image. |
| `nvcr.io/nvidia/nemo:25.11` | `stt/Dockerfile`, `stt/Dockerfile.cpu` export stage | https://catalog.ngc.nvidia.com/orgs/nvidia/containers/nemo | tag-pinned | NeMo/STT build and GPU runtime base. |
| `python:3.11-slim` | `stt/Dockerfile.cpu` runtime stage | https://hub.docker.com/_/python | tag-pinned | CPU STT runtime base. |
| `node:24-bookworm-slim` | `web/Dockerfile` | https://hub.docker.com/_/node | tag-pinned | Next.js build/runtime base. |
| `alpine:3.21` | `docker-compose.windows-amd.yml` | https://hub.docker.com/_/alpine | tag-pinned | Windows AMD Ollama no-op stub. |

## Downloaded Model And Tarball Artifacts

| Artifact | Where used | Upstream | Pin/check status | Notes |
| --- | --- | --- | --- | --- |
| `nvidia/parakeet-tdt-0.6b-v2` | `STT_MODEL`, GPU buffered STT | https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 | revision env exists; default is `main` | Baked into STT image with `huggingface_hub.snapshot_download`. |
| `nvidia/nemotron-speech-streaming-en-0.6b` | legacy streaming ONNX export source | https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b | revision env exists; default is `main` | Legacy/manual comparison path. |
| `sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2` | `stt/fetch_parakeet_onnx.sh` | https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2 | sha256 checked in script | Expected sha256: `157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad`. |

## Ollama Model Ladders

| Choice | Source tags | Pin/check status | Notes |
| --- | --- | --- | --- |
| Fast | `evalengine/unbound-e2b:latest`, fallback `gemma4:e2b` | tag resolved during install; build verified by `ollama/verify-build.sh` when operator runs it | Community first rung, official fallback. |
| Better | `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest`, fallback `gemma4:e4b` | tag resolved during install; build verified by `ollama/verify-build.sh` when operator runs it | Community first rung, official fallback. |
| Floor | `hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M`, `hf.co/bartowski/mlabonne_Qwen3-1.7B-abliterated-GGUF:Q4_K_M`, fallback `qwen3.5:2b-q4_K_M` | tag resolved during install | First rung is rebuilt as `adept-floor` with the local Modelfile template fix. |

## Vendored Browser Assets

| Path | Upstream | Version/status | Notes |
| --- | --- | --- | --- |
| `web/public/vendor/three/` | https://github.com/mrdoob/three.js | Three.js r0.180.0 per stack research | Vendored to avoid CDN runtime dependency. |
| `web/public/vendor/three/addons/libs/draco/` | https://github.com/mrdoob/three.js/tree/dev/examples/jsm/libs/draco | version bundled with Three.js r0.180.0 | Includes `draco_decoder.wasm`; treat as vendored binary. |
| `web/public/vendor/talkinghead/` | https://github.com/met4citizen/TalkingHead | TalkingHead 1.7.0 / HeadAudio path per stack research | Vendored to avoid CDN runtime dependency. |

## Local Check Command

Run before public access:

```bash
./scripts/security-check.sh
```

Reports are written to `security/reports/` and are intentionally ignored by git.
````

- [ ] **Step 2: Commit**

```bash
git add SECURITY_PROVENANCE.md
git commit -m "docs: add security provenance"
```

## Task 4: README Public Trust Note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README section**

Add this after the existing "Development checks" section:

````markdown
## Local security baseline

Before public source access, run the local security baseline:

```bash
./scripts/security-check.sh
```

It checks npm dependencies, Python dependencies, OSV advisories, a Syft SBOM,
Grype vulnerabilities, and tracked-source secrets. Reports are written to
`security/reports/` and are not committed.

The provenance record for Docker images, vendored browser assets, model downloads,
and known pinning gaps is [`SECURITY_PROVENANCE.md`](SECURITY_PROVENANCE.md).
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document local security baseline"
```

## Task 5: Verification Pass

**Files:**
- Verify: `.gitignore`
- Verify: `scripts/security-check.sh`
- Verify: `scripts/test_security_check.sh`
- Verify: `SECURITY_PROVENANCE.md`
- Verify: `README.md`

- [ ] **Step 1: Run shell syntax checks**

Run:

```bash
bash -n scripts/security-check.sh scripts/test_security_check.sh
```

Expected: no output, exit 0.

- [ ] **Step 2: Run sandbox test**

Run:

```bash
./scripts/test_security_check.sh
```

Expected: all scenarios pass.

- [ ] **Step 3: Run existing shell harnesses that are not GPU/network dependent**

Run:

```bash
./scripts/test_install.sh
./scripts/test_gpu_doctor.sh
./stt/test_fetch_parakeet.sh
```

Expected: all pass. If unrelated local installer changes fail, stop and report that they predate this security-baseline work.

- [ ] **Step 4: Try the real security script**

Run:

```bash
./scripts/security-check.sh
```

Expected in this sandbox: it may fail early with clear missing-tool guidance because `osv-scanner`, `syft`, `grype`, or `gitleaks` may not be installed.

Expected on a prepared local machine: the script runs to completion, writes reports under `security/reports/`, fails on high/critical dependency findings or verified secrets, and summarizes moderate/unknown findings.

- [ ] **Step 5: Confirm generated reports are ignored**

Run:

```bash
git status --short security/reports
```

Expected: no tracked output.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short
```

Expected: only intended changes remain, with unrelated pre-existing user edits left untouched.

- [ ] **Step 7: Commit any verification-only doc fixes**

If verification forced minor doc wording fixes, commit only those files:

```bash
git add README.md SECURITY_PROVENANCE.md
git commit -m "docs: clarify local security baseline"
```
