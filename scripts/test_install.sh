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
readonly -a NEEDED_TOOLS=(dirname cp grep sed mv head base64 tr cat env bash mkdir chmod)

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
cp install.sh down.sh install.ps1 "$WORK"/
cp .env.example "$WORK"/
: > "$WORK/docker-compose.yml"
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
if [ "${rcc:-1}" -eq 0 ]    && grep -q 'REHEARSAL_MODEL_CHOICES=floor' "$WORK/.env"    && grep -q 'INSTALL_MODELS=floor' "$WORK/pin.log" 2>/dev/null; then
  ok "Scenario C: GPU=none → floor default + INSTALL_MODELS passed to pull-and-pin"
else
  bad "Scenario C: model selection path incomplete (rc=$rcc)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/c.out")"
fi

# --- Scenario D: curl|bash style outside a checkout clones then runs local installer ---
mkdir -p "$WORK/pipe"
BIN_D="$WORK/bin_d"; build_path "$BIN_D"
make_shim "$BIN_D" docker 'echo "docker $*" >> "$PWD/docker.log"; exit 0'
make_shim "$BIN_D" openssl 'echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
make_shim "$BIN_D" git '
echo "git $*" > "$PWD/git.log"
mkdir -p "$REHEARSAL_INSTALL_DIR/scripts" "$REHEARSAL_INSTALL_DIR/ollama"
cp "$SOURCE_INSTALL_SH" "$REHEARSAL_INSTALL_DIR/install.sh"
cp "$SOURCE_ENV_EXAMPLE" "$REHEARSAL_INSTALL_DIR/.env.example"
: > "$REHEARSAL_INSTALL_DIR/docker-compose.yml"
printf "#!/usr/bin/env bash\nexit 0\n" > "$REHEARSAL_INSTALL_DIR/scripts/gpu-doctor.sh"
printf "#!/usr/bin/env bash\necho clone-pull > \"\$PWD/pin.log\"\n" > "$REHEARSAL_INSTALL_DIR/ollama/pull-and-pin.sh"
chmod +x "$REHEARSAL_INSTALL_DIR/install.sh" "$REHEARSAL_INSTALL_DIR/scripts/gpu-doctor.sh" "$REHEARSAL_INSTALL_DIR/ollama/pull-and-pin.sh"
'
( cd "$WORK/pipe" && env -i PATH="$BIN_D" ASSUME_YES=1 REHEARSAL_INSTALL_DIR="$WORK/cloned" SOURCE_INSTALL_SH="$REPO/install.sh" SOURCE_ENV_EXAMPLE="$REPO/.env.example" bash -s -- -y < "$REPO/install.sh" >d.out 2>&1 ) && rcd=0 || rcd=$?
if [ "${rcd:-1}" -eq 0 ] \
   && grep -q 'clone https://github.com/foreztgump/rehearsal.git' "$WORK/pipe/git.log" \
   && grep -q 'compose build' "$WORK/cloned/docker.log" \
   && grep -q 'REHEARSAL_MODEL_CHOICES=floor' "$WORK/cloned/.env"; then
  ok "Scenario D: curl-style bootstrap clones then runs local installer"
else
  bad "Scenario D: curl-style bootstrap incomplete (rc=$rcd)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/pipe/d.out")"
fi

# --- Scenario E: Windows (MINGW) delegates to the PowerShell installer -------
# Mock uname → a Windows value and provide a pwsh stub. install.sh must hand off
# to install.ps1 (exec pwsh -File ./install.ps1 -Yes) and never reach the Linux
# prerequisite / plan path. No docker stub needed: delegation happens first.
BIN_E="$WORK/bin_e"; build_path "$BIN_E"
make_shim "$BIN_E" uname 'echo MINGW64_NT-10.0-26100'
make_shim "$BIN_E" pwsh  'echo "pwsh $*" > "$PWD/pwsh.log"; exit 0'
( cd "$WORK" && env -i PATH="$BIN_E" ASSUME_YES=1 bash install.sh -y >e.out 2>&1 ) && rce=0 || rce=$?
if [ "${rce:-1}" -eq 0 ] \
   && grep -q -- '-File ./install.ps1' "$WORK/pwsh.log" 2>/dev/null \
   && grep -q -- '-Yes' "$WORK/pwsh.log" 2>/dev/null \
   && ! grep -qi 'setup plan' "$WORK/e.out"; then
  ok "Scenario E: Windows delegates to install.ps1 (skips the Linux path)"
else
  bad "Scenario E: Windows delegation incomplete (rc=$rce)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/e.out")"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
