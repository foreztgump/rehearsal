#!/usr/bin/env bash
#
# test_install.sh — sandbox checks for install.sh / down.sh. Runs install.sh under an
# ISOLATED PATH (only the shims + symlinked coreutils) so the host's REAL docker /
# nvidia-smi can never leak in — same isolation discipline as test_gpu_doctor.sh.
# Shims docker, openssl, and the gpu-doctor / pull-and-pin helpers so nothing real
# builds. No real Docker, no real GPU.
#
#   ./scripts/test_install.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
REPO="$PWD"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'PASS: %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }

# Coreutils install.sh / down.sh invoke by bare name. Symlinking ONLY these into the
# isolated PATH is what keeps the host's real docker/nvidia-smi out (their dirs are
# never on PATH). env + bash are needed because the stub helpers use a
# `#!/usr/bin/env bash` shebang that must resolve against this isolated PATH.
readonly -a NEEDED_TOOLS=(dirname cp grep sed mv head base64 tr cat env bash)

# 0) Syntax
bash -n install.sh && ok "install.sh parses" || bad "install.sh syntax"
bash -n down.sh    && ok "down.sh parses"    || bad "down.sh syntax"
# R7: confirm the Windows PowerShell siblings exist (no pwsh here to run them).
[ -f install.ps1 ]                && ok "install.ps1 present (PS parse deferred to operator)" || bad "install.ps1 missing"
[ -f scripts/gpu-doctor.ps1 ]     && ok "gpu-doctor.ps1 present (PS parse deferred to operator)" || bad "gpu-doctor.ps1 missing"
[ -f up.ps1 ]                     && ok "up.ps1 present" || bad "up.ps1 missing"
[ -f down.ps1 ]                   && ok "down.ps1 present" || bad "down.ps1 missing"

# Build a throwaway working copy so we never touch the real .env / run real docker.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp install.sh down.sh "$WORK"/
cp .env.example "$WORK"/
mkdir -p "$WORK/scripts" "$WORK/ollama"
# Stubs the script calls relative to its own dir (cd "$(dirname "$0")"):
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/scripts/gpu-doctor.sh"
printf '#!/usr/bin/env bash\necho "[stub] pull-and-pin"\n' > "$WORK/ollama/pull-and-pin.sh"
chmod +x "$WORK/scripts/gpu-doctor.sh" "$WORK/ollama/pull-and-pin.sh"

# make_shim <dir> <name> <body> — write an executable shim.
make_shim() { printf '#!/usr/bin/env bash\n%s\n' "$3" > "$1/$2"; chmod +x "$1/$2"; }

# build_path <dir> — populate <dir> with symlinked coreutils so it can be the SOLE
# PATH entry; callers then drop their scenario-specific shims alongside.
build_path() {
  local dir="$1" tool path
  mkdir -p "$dir"
  for tool in "${NEEDED_TOOLS[@]}"; do
    path="$(command -v "$tool")" && ln -sf "$path" "$dir/$tool"
  done
}

# --- Scenario A: Docker missing → guidance + non-zero ----------------------
# Isolated PATH with NO docker and NO nvidia-smi/rocm-smi (→ GPU=none, doctor skipped).
BIN_A="$WORK/bin_a"; build_path "$BIN_A"
( cd "$WORK" && env -i PATH="$BIN_A" ASSUME_YES=1 bash install.sh >a.out 2>&1 ) && rc=0 || rc=$?
if [ "${rc:-0}" -ne 0 ] && grep -qi "Docker is not installed" "$WORK/a.out"; then
  ok "Scenario A: missing Docker is guided + non-zero"
else
  bad "Scenario A: missing Docker not handled (rc=$rc)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/a.out")"
fi

# --- Scenario B: all-ok, -y → scaffolds secret + invokes build/up ----------
# Isolated PATH WITH a docker stub (logs its args) + an openssl stub (deterministic
# secret); still no nvidia-smi → GPU=none → doctor skipped.
BIN_B="$WORK/bin_b"; build_path "$BIN_B"
make_shim "$BIN_B" docker 'echo "docker $*" >> "$PWD/docker.log"; exit 0'
make_shim "$BIN_B" openssl 'echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
( cd "$WORK" && env -i PATH="$BIN_B" ASSUME_YES=1 bash install.sh -y >b.out 2>&1 ) && rcb=0 || rcb=$?
if [ "${rcb:-1}" -eq 0 ] \
   && [ -f "$WORK/.env" ] \
   && ! grep -q 'replace-with-a-long-random-secret' "$WORK/.env" \
   && grep -q 'compose build' "$WORK/docker.log" \
   && grep -q 'compose up -d' "$WORK/docker.log"; then
  ok "Scenario B: secret scaffolded + build/up invoked"
else
  bad "Scenario B: bootstrap path incomplete (rc=$rcb)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/b.out")"
fi

# --- Scenario C: -y with GPU=none → floor default + INSTALL_MODELS propagation ---
# Same isolated PATH as B (docker stub), still no nvidia-smi → GPU=none → floor
# default. Stubs pull-and-pin so it logs INSTALL_MODELS without a real container.
BIN_C="$WORK/bin_c"; build_path "$BIN_C"
make_shim "$BIN_C" docker 'echo "docker $*" >> "$PWD/docker.log"; exit 0'
make_shim "$BIN_C" openssl 'echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
printf '#!/usr/bin/env bash\necho "[stub] pull-and-pin INSTALL_MODELS=${INSTALL_MODELS}" > "$PWD/pin.log"\n' > "$WORK/ollama/pull-and-pin.sh"
chmod +x "$WORK/ollama/pull-and-pin.sh"
( cd "$WORK" && env -i PATH="$BIN_C" ASSUME_YES=1 bash install.sh -y >c.out 2>&1 ) && rcc=0 || rcc=$?
if [ "${rcc:-1}" -eq 0 ]    && grep -q 'ADEPT_MODEL_CHOICES=floor' "$WORK/.env"    && grep -q 'INSTALL_MODELS=floor' "$WORK/pin.log" 2>/dev/null; then
  ok "Scenario C: GPU=none → floor default + INSTALL_MODELS passed to pull-and-pin"
else
  bad "Scenario C: model selection path incomplete (rc=$rcc)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/c.out")"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
