---
phase: 14
plan: 14-07
slug: install-bootstrap-clean-stop
depends_on: []
status: ready
files_modified:
  - down.sh                      # NEW — clean stop
  - install.sh                   # NEW — one-command bootstrap
  - scripts/test_install.sh      # NEW — PATH-shim scenario tests
  - README.md                    # install / start / stop docs
requirements: [DEPLOY-06, DEPLOY-07]
---

# Plan 14-07 — Install Bootstrap + Clean Stop

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. Shell scripts follow the repo's existing
> test style: `bash -n` syntax checks + PATH-shim scenario tests (mirror
> `scripts/test_gpu_doctor.sh`). Guide missing prerequisites — never auto-install.

**Goal:** A new user runs one script, confirms a plan, and ends with a running stack +
clear start/stop instructions; a missing prerequisite yields an actionable message, not
a hang. Plus a documented clean stop.

**Architecture:** `install.sh` reuses the existing pieces — `scripts/gpu-doctor.sh`
(advise-only preflight), `.env.example` (scaffold source), `ollama/pull-and-pin.sh`
(first-run model pull), `up.sh`/`docker compose` (boot). It detects OS/Docker/GPU,
scaffolds `.env` with a generated `LIVEKIT_API_SECRET`, prints a plan and confirms,
builds + pulls, then prints start/stop. `down.sh` wraps `docker compose down`.

**Tech Stack:** POSIX-ish bash, Docker Compose v2, the existing 7-service stack.

**Current state (vs PRD §2):** Confirmed — neither `install.sh` nor `down.sh` exists.
`up.sh` (doctor-wrapped `docker compose up`), `scripts/gpu-doctor.sh` (4-step NVIDIA
preflight, exit 0), `ollama/pull-and-pin.sh` (model ladders → pins tags into `.env`),
and `.env.example` (`LIVEKIT_API_SECRET=replace-with-a-long-random-secret`) all exist.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: `install.sh` is `curl|sh`-compatible and ships
in-repo (hosted URL is a later flip); it **guides** missing Docker/driver/toolkit (the
README already documents the toolkit apt commands) and never auto-installs; pin image
tags (the compose file already pins). Secret generation must be portable (no GNU-only
tools assumed).

---

## Task 1: `down.sh` (clean stop) + bash -n

**Files:**
- Create: `down.sh`

- [ ] **Step 1: Write `down.sh`**

```bash
#!/usr/bin/env bash
#
# down.sh — clean stop for the Adept stack. Stops and removes the compose services
# (containers + default network), leaving named volumes (pulled models, caches) intact.
#
#   ./down.sh             # stop + remove containers
#   ./down.sh -v          # ALSO remove named volumes (models re-pull next boot)
#   ./down.sh --remove-orphans
#
# Surfaced by install.sh's closing message and the README.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "-v" ]; then
  printf 'This also removes named volumes — pulled models + caches will re-download.\n'
fi

exec docker compose down "$@"
```

- [ ] **Step 2: Make executable + syntax-check**

Run:
```bash
chmod +x down.sh
bash -n down.sh
```
Expected: no output (valid syntax).

- [ ] **Step 3: Commit**

```bash
git add down.sh
git commit -m "feat(14-07): add down.sh clean-stop wrapper (DEPLOY-07)"
```

---

## Task 2: `install.sh` (detect → scaffold → plan → build → pull → start/stop)

**Files:**
- Create: `install.sh`

**Interfaces:**
- Consumes: `scripts/gpu-doctor.sh`, `.env.example`, `ollama/pull-and-pin.sh`,
  `docker compose`.
- Produces: a scaffolded `.env` (generated secret), a built + model-pulled, running
  stack, and printed start/stop commands.

- [ ] **Step 1: Write `install.sh`**

```bash
#!/usr/bin/env bash
#
# install.sh — one-command bootstrap for the Adept local-first voice stack.
# curl|sh-compatible. Detects OS + Docker/Compose + GPU vendor, scaffolds .env with a
# generated LIVEKIT_API_SECRET, prints a setup plan and confirms, builds images +
# pulls/pins models, then prints exact start/stop commands. Missing prerequisites are
# GUIDED with the right per-OS commands — never auto-installed.
#
#   ./install.sh            # interactive
#   ./install.sh -y         # accept the plan non-interactively (CI / repeat)
#   ASSUME_YES=1 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

ASSUME_YES="${ASSUME_YES:-0}"
[ "${1:-}" = "-y" ] && ASSUME_YES=1

log() { printf '%s\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; }

# --- 1. Prerequisites: guide, do not auto-install ---------------------------
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    log "Install Docker Engine + the Compose v2 plugin, then re-run ./install.sh:"
    log "  https://docs.docker.com/engine/install/"
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 plugin not found (need the 'docker compose' subcommand)."
    log "  https://docs.docker.com/compose/install/linux/"
    exit 1
  fi
}

detect_gpu() {  # prints: nvidia | amd | none
  if command -v nvidia-smi >/dev/null 2>&1; then printf 'nvidia\n'
  elif command -v rocm-smi >/dev/null 2>&1; then printf 'amd\n'
  else printf 'none\n'; fi
}

# --- 2. .env scaffold with a generated secret -------------------------------
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 48 /dev/urandom | base64 | tr -d '\n/+= '
  fi
}

scaffold_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    log "Created .env from .env.example."
  fi
  if grep -q 'replace-with-a-long-random-secret' .env; then
    secret="$(gen_secret)"
    # Portable in-place edit (BSD vs GNU sed -i differ) via temp file.
    sed "s|^LIVEKIT_API_SECRET=.*|LIVEKIT_API_SECRET=${secret}|" .env > .env.tmp
    mv .env.tmp .env
    log "Generated a random LIVEKIT_API_SECRET in .env."
  else
    log ".env already has a LIVEKIT_API_SECRET — leaving it untouched."
  fi
}

# --- 3. Plan + confirmation -------------------------------------------------
print_plan() {
  gpu="$1"
  log ""
  log "================ Adept setup plan ================"
  log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  log "GPU vendor detected: ${gpu}"
  if [ "$gpu" = "nvidia" ]; then
    log "STT placement: CPU-ONNX by default (STT_FORCE_CPU=1, VRAM-safe). GPU STT is"
    log "  opt-in after the co-residency matrix passes (docker compose --profile stt-gpu)."
    log "VRAM budget: 16 GB target — ollama + kokoro resident (scripts/vram-validate.sh)."
  else
    log "No NVIDIA GPU detected. STT runs on CPU-ONNX. The LLM + TTS still expect a GPU"
    log "  for real-time latency; without one the stack runs but will not hit P50<1.0s."
  fi
  log "================================================="
}

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  printf 'Proceed with build + model pull? [y/N] '
  read -r reply
  case "$reply" in
    y|Y|yes|Yes) return 0 ;;
    *) log "Aborted — nothing built. Re-run ./install.sh when ready."; exit 1 ;;
  esac
}

# --- 4. Build + first-run model pull + boot ---------------------------------
build_and_pull() {
  log "Building images (first run pulls several GB + bakes the STT model)…"
  docker compose build
  log "Starting ollama to pull + pin the two LLMs…"
  docker compose up -d ollama
  ./ollama/pull-and-pin.sh
  log "Starting the full stack…"
  docker compose up -d
}

# --- main -------------------------------------------------------------------
GPU="$(detect_gpu)"
require_docker
if [ "$GPU" = "nvidia" ] && [ "${SKIP_DOCTOR:-0}" != "1" ]; then
  ./scripts/gpu-doctor.sh || true   # advise-only; never blocks
fi
scaffold_env
print_plan "$GPU"
confirm
build_and_pull
log ""
log "Done. The stack is up."
log "  Start:  ./up.sh -d        (preflight + docker compose up -d)"
log "  Stop:   ./down.sh         (docker compose down)"
log "  Logs:   docker compose logs -f agent"
log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
```

- [ ] **Step 2: Make executable + syntax-check**

Run:
```bash
chmod +x install.sh
bash -n install.sh
```
Expected: no output (valid syntax).

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat(14-07): one-command install.sh (detect, scaffold, plan, build, pull) (DEPLOY-06)"
```

---

## Task 3: PATH-shim scenario tests (`scripts/test_install.sh`)

**Files:**
- Create: `scripts/test_install.sh`

**Interfaces:**
- Mirrors `scripts/test_gpu_doctor.sh`: a temp working dir + PATH shims; asserts
  behaviour + exit codes; no real Docker/GPU.

- [ ] **Step 1: Write the harness**

```bash
#!/usr/bin/env bash
#
# test_install.sh — sandbox checks for install.sh / down.sh. PATH-shims docker, nvidia-
# smi, openssl, and pull-and-pin so nothing real builds. Mirrors test_gpu_doctor.sh.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
REPO="$PWD"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'PASS: %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }

# 0) Syntax
bash -n install.sh && ok "install.sh parses" || bad "install.sh syntax"
bash -n down.sh    && ok "down.sh parses"    || bad "down.sh syntax"

# Build a throwaway working copy so we never touch the real .env / run real docker.
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp install.sh down.sh "$WORK"/
cp .env.example "$WORK"/
mkdir -p "$WORK/scripts" "$WORK/ollama"
# Stubs the script calls relative to repo root:
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/scripts/gpu-doctor.sh"
printf '#!/usr/bin/env bash\necho "[stub] pull-and-pin"\n' > "$WORK/ollama/pull-and-pin.sh"
chmod +x "$WORK/scripts/gpu-doctor.sh" "$WORK/ollama/pull-and-pin.sh"

# PATH shim dir
SHIM="$WORK/bin"; mkdir -p "$SHIM"
make_shim() { printf '#!/usr/bin/env bash\n%s\n' "$2" > "$SHIM/$1"; chmod +x "$SHIM/$1"; }

# --- Scenario A: Docker missing → guidance + non-zero ----------------------
# PATH with NO docker (and no nvidia-smi/rocm-smi → GPU=none, doctor skipped).
( cd "$WORK" && PATH="$SHIM:/usr/bin:/bin" ASSUME_YES=1 bash install.sh >a.out 2>&1 ) && rc=0 || rc=$?
if [ "${rc:-0}" -ne 0 ] && grep -qi "Docker is not installed" "$WORK/a.out"; then
  ok "Scenario A: missing Docker is guided + non-zero"
else
  bad "Scenario A: missing Docker not handled (rc=$rc)"
fi

# --- Scenario B: all-ok, -y → scaffolds secret + invokes build/up ----------
# docker stub logs its args; openssl stub yields a deterministic secret.
make_shim docker 'echo "docker $*" >> "$PWD/docker.log"; if [ "$1 $2" = "compose version" ]; then exit 0; fi; exit 0'
make_shim openssl 'echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
( cd "$WORK" && PATH="$SHIM:/usr/bin:/bin" ASSUME_YES=1 bash install.sh -y >b.out 2>&1 ) && rcb=0 || rcb=$?
if [ "${rcb:-1}" -eq 0 ] \
   && [ -f "$WORK/.env" ] \
   && ! grep -q 'replace-with-a-long-random-secret' "$WORK/.env" \
   && grep -q 'compose build' "$WORK/docker.log" \
   && grep -q 'compose up -d' "$WORK/docker.log"; then
  ok "Scenario B: secret scaffolded + build/up invoked"
else
  bad "Scenario B: bootstrap path incomplete (rc=$rcb)"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run the harness**

Run:
```bash
chmod +x scripts/test_install.sh
./scripts/test_install.sh
```
Expected: `PASS:` for syntax + Scenario A + Scenario B; final `N passed, 0 failed`;
exit 0. (If Scenario B's `docker compose version` probe needs adjusting to the stub,
refine the stub's arg-matching — the assertion is that `.env` gets a real secret and
`build` + `up -d` are invoked.)

- [ ] **Step 3: Commit**

```bash
git add scripts/test_install.sh
git commit -m "test(14-07): PATH-shim scenarios for install.sh (missing-docker, all-ok bootstrap)"
```

---

## Task 4: README install / start / stop docs + sign-off

**Files:**
- Modify: `README.md` (Quick start → one-command install; add a Stop section)

- [ ] **Step 1: Lead the Quick start with `install.sh`**

Replace the manual Quick start (README ~8-18) with the one-command path, keeping the
manual path as the "or, by hand" fallback:
```markdown
## Quick start

```bash
./install.sh            # detect + scaffold .env (generated secret) + plan + build + pull
# …confirm the plan when prompted; then it boots the stack and prints start/stop.
```

Already set up? Start and stop with:

```bash
./up.sh -d              # preflight (gpu-doctor) + docker compose up -d
./down.sh               # clean stop (docker compose down)
```

Prefer to do it by hand? `cp .env.example .env`, set a `LIVEKIT_API_SECRET`, then
`./up.sh`.
```

- [ ] **Step 2: Note the GPU-prerequisite guidance**

Add one line: if Docker/the NVIDIA toolkit is missing, `install.sh` prints the exact
install commands and exits — it never installs system packages for you (see the GPU
setup section for the toolkit apt commands).

- [ ] **Step 3: Re-run the harness + commit**

Run: `./scripts/test_install.sh`
Expected: `0 failed`.
```bash
git add README.md
git commit -m "docs(14-07): one-command install + clean-stop in README (DEPLOY-06/07)"
```

## Verification
**Self-checkable:**
- `bash -n install.sh down.sh` clean.
- `./scripts/test_install.sh` → `0 failed` (syntax + missing-docker guidance + all-ok
  secret-scaffold + build/up invocation).

**OPERATOR (clean machine, in 14-09 UAT):**
- Fresh checkout → `./install.sh` → confirm plan → stack runs; `.env` has a generated
  secret; `./down.sh` stops it. On a host missing Docker/toolkit, the message is
  actionable and the script exits non-zero rather than hanging.

## Artifacts this plan produces
- **NEW** `install.sh` — one-command bootstrap.
- **NEW** `down.sh` — clean stop.
- **NEW** `scripts/test_install.sh` — PATH-shim scenario tests.
- **MODIFIED** `README.md` — install / start / stop.
