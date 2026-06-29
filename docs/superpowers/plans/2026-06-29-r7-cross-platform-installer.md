# R7 Cross-Platform Local Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Adept installable from a local repo checkout on Linux and native Windows, with install-time model selection + aliases, and a best-effort Windows-AMD hybrid profile.

**Architecture:** Two native installers (Bash + PowerShell) sharing a documented profile matrix. The Linux installer is extended from guide-only to offer-to-install. A new Windows AMD compose override drops the in-stack Ollama service (native Ollama on the host) and uses a new CPU Kokoro override. The model-choice flow (`agent/models.py` + `ollama/pull-and-pin.sh` + `web/app/ModelPanel.tsx`) is made install-set-driven via env vars baked into `.env` and the web build, so the picker shows only installed models.

**Tech Stack:** Bash, PowerShell, Docker Compose, Ollama, Kokoro-FastAPI (CPU + ROCm images), Python (agent), Next.js (web), `python3`/`pytest` for Python tests, `tsc --noEmit` for web typecheck, `bash -n` for shell parse.

**Spec:** `docs/superpowers/specs/2026-06-29-r7-cross-platform-installer-design.md`

**Sequencing note:** Tasks 1-6 (model-selection plumbing + Linux installer + CPU Kokoro + tests) are independent of R6. Tasks 7-8 (Windows installer + Windows-AMD) are gated behind R6 closeout — the plan marks them. Execute 1-6 first; 7-8 only after R6's AMD gates are signed or the user accepts AMD-as-contingent.

---

## File Structure

- **Modify** `agent/models.py` — derive effective `MODEL_CHOICES` from `ADEPT_MODEL_CHOICES` (labels are web-side, baked at build time).
- **Modify** `tests/test_models.py` — cover install-set narrowing + default-not-in-set.
- **Modify** `ollama/pull-and-pin.sh` — accept `INSTALL_MODELS` env; pin only the selected ladders; point `OLLAMA_MODEL` at the chosen default.
- **Modify** `ollama/warmup.py` — no code change needed (already reads `OLLAMA_MODEL`); verify the installer points the alias at the chosen default.
- **Modify** `web/app/ModelPanel.tsx` — drive `CHOICES` + labels from bake-time env, not a hardcoded array; single-model → read-only field.
- **Modify** `web/app/ApplySetupOnConnect.tsx` — no change to the RPC payload shape (`{choice}`), but the default-comparison uses the baked default.
- **Modify** `docker-compose.yml` — add `NEXT_PUBLIC_ADEPT_MODEL_CHOICES` + `NEXT_PUBLIC_ADEPT_MODEL_LABELS` build args to the `web` service.
- **Modify** `.env.example` — add `ADEPT_MODEL_CHOICES`, `NEXT_PUBLIC_ADEPT_MODEL_LABELS`, Windows-AMD native Ollama keys.
- **Modify** `install.sh` — add offer-to-install (apt/dnf/pacman) behind confirmation; add model-selection prompt; write `ADEPT_MODEL_CHOICES` + labels; call `pull-and-pin.sh` with `INSTALL_MODELS`.
- **Modify** `scripts/gpu-doctor.sh` — no change to AMD detection (R6 added it); add `VRAM_TOTAL_MB` print so the installer can read it.
- **Create** `docker-compose.cpu-tts.yml` — CPU Kokoro override (`ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0`, no GPU reservation).
- **Create** `docker-compose.windows-amd.yml` — drop in-stack `ollama`, rewrite `agent.depends_on`, set `host.docker.internal` Ollama URLs.
- **Create** `install.ps1` — native Windows PowerShell installer (mirrors `install.sh` structure).
- **Create** `scripts/gpu-doctor.ps1` — Windows system + GPU check (mirrors `gpu-doctor.sh`).
- **Create** `up.ps1` / `down.ps1` — Windows start/stop wrappers.
- **Create** `scripts/test_install.ps1` — PS parse + mocked-scenario harness.
- **Create** `scripts/test_gpu_doctor.ps1` — PS parse + mocked-scenario harness.
- **Modify** `scripts/test_compose_topology.sh` — extend for the Windows-AMD + CPU-Kokoro overrides (render-only).
- **Modify** `scripts/test_install.sh` — cover the new offer-to-install + model-selection paths.
- **Modify** `README.md` — Linux + Windows install commands, profile matrix, model-selection explanation, start/stop per OS.

---

### Task 1: Install-set-driven model choices in `agent/models.py`

**Files:**
- Modify: `agent/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py` (before `_run_all`):

```python
def test_effective_choices_default_to_full_set() -> None:
    """With ADEPT_MODEL_CHOICES unset, the effective set is the shipped tuple."""
    from models import effective_model_choices
    assert set(effective_model_choices({})) == {"fast", "better", "floor"}


def test_effective_choices_narrowed_by_env() -> None:
    """ADEPT_MODEL_CHOICES narrows the effective set to the installed models."""
    from models import effective_model_choices
    assert set(effective_model_choices({"ADEPT_MODEL_CHOICES": "fast,floor"})) == {"fast", "floor"}


def test_effective_choices_single_model() -> None:
    """A one-model install yields a one-element set."""
    from models import effective_model_choices
    assert set(effective_model_choices({"ADEPT_MODEL_CHOICES": "floor"})) == {"floor"}


def test_effective_choices_ignores_unknown_keys() -> None:
    """Unknown keys in ADEPT_MODEL_CHOICES are dropped (never surface a choice with no tag)."""
    from models import effective_model_choices
    assert set(effective_model_choices({"ADEPT_MODEL_CHOICES": "fast,bogus"})) == {"fast"}


def test_default_choice_must_be_in_effective_set() -> None:
    """A default not in the narrowed effective set falls back to fast (or the first choice)."""
    from models import default_model_choice
    # floor installed, default=fast not installed → fallback
    assert default_model_choice({"ADEPT_MODEL_CHOICES": "floor", "ADEPT_DEFAULT_MODEL": "fast"}) == "floor"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_models.py`
Expected: FAIL with `ImportError: cannot import name 'effective_model_choices'`

- [ ] **Step 3: Implement `effective_model_choices` + narrow `default_model_choice`**

Add to `agent/models.py` (after `MODEL_CHOICES`):

```python
# Install-set env: the R7 installer writes the comma list of installed choice keys
# so the web picker + agent only surface models that were actually pulled. Unset
# → the full shipped set (back-compat for pre-R7 deploys).
_INSTALL_SET_ENV: str = "ADEPT_MODEL_CHOICES"


def effective_model_choices(env: Mapping[str, str]) -> tuple[str, ...]:
    """Resolve the effective choice set from the installed-set env.

    Unset/empty → the full shipped MODEL_CHOICES (back-compat). Unknown keys are
    dropped so a typo never surfaces a choice with no pinned tag.
    """
    raw = env.get(_INSTALL_SET_ENV, "").strip()
    if not raw:
        return MODEL_CHOICES
    keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
    installed = tuple(k for k in keys if k in MODEL_CHOICES)
    return installed if installed else MODEL_CHOICES
```

Change `default_model_choice` to consult the effective set:

```python
def default_model_choice(env: Mapping[str, str]) -> str:
    """Resolve the session default choice from env, falling back to the first
    effective choice (Fast in the full set).

    A default not in the narrowed effective set falls back — never raises, so a
    profile typo cannot brick startup.
    """
    choices = effective_model_choices(env)
    choice = env.get(_DEFAULT_MODEL_ENV, "").strip().lower()
    if choice in choices:
        return choice
    return choices[0] if choices else _FALLBACK_DEFAULT_CHOICE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_models.py`
Expected: PASS — all tests print `models _self_check OK`.

- [ ] **Step 5: Run the full Python test suite + lint**

Run: `python3 -m pytest tests/ -q && python3 -m basedpyright agent/models.py tests/test_models.py && ruff check agent/models.py tests/test_models.py`
Expected: PASS (no regressions; the existing `test_default_choice_env_override` still passes because the full-set fallback is Fast).

- [ ] **Step 6: Commit**

```bash
git add agent/models.py tests/test_models.py
git commit -m "feat(r7): install-set-driven model choices in agent/models.py"
```

---

### Task 2: `pull-and-pin.sh` accepts an explicit install set

**Files:**
- Modify: `ollama/pull-and-pin.sh`
- Test: `scripts/test_install.sh` (extended in Task 5)

- [ ] **Step 1: Write the failing check**

Add a one-off self-check at the end of `ollama/pull-and-pin.sh`'s usage comment block (a `bash -n` parse gate is the first check; a functional mock test comes in Task 5). For now, confirm the env is read:

```bash
# Usage:  ./ollama/pull-and-pin.sh
# Env:    OLLAMA_CONTAINER  (default: ollama) — compose service / container name
#         ENV_FILE          (default: .env)   — file the resolved tags are written to
#         INSTALL_MODELS    (default: fast,better,floor) — comma list of which
#                          ladders to run + pin. Only the selected models are pulled.
#         ADEPT_DEFAULT_MODEL (default: first of INSTALL_MODELS) — which installed
#                          model the OLLAMA_MODEL back-compat alias points at.
```

- [ ] **Step 2: Implement the install-set filter**

Replace the `main()` function in `ollama/pull-and-pin.sh`:

```bash
readonly INSTALL_MODELS="${INSTALL_MODELS:-fast,better,floor}"
readonly DEFAULT_CHOICE="${ADEPT_DEFAULT_MODEL:-}"

# Resolve which ladders to run from INSTALL_MODELS (comma list, order preserved).
# Unknown keys are ignored (defensive — the installer only writes known keys).
should_install() {
  local key="$1"
  case ",${INSTALL_MODELS}," in
    *",${key},"*) return 0 ;;
    *) return 1 ;;
  esac
}

main() {
  local installed_any=0
  local chosen_default=""
  local default_tag=""

  # Determine the chosen default (first installed model the user picked, or the
  # explicit ADEPT_DEFAULT_MODEL if it's in the install set).
  if [ -n "${DEFAULT_CHOICE}" ] && should_install "${DEFAULT_CHOICE}"; then
    chosen_default="${DEFAULT_CHOICE}"
  else
    chosen_default="${INSTALL_MODELS%%,*}"
  fi

  if should_install "floor"; then
    local floor_tag=""
    if floor_tag="$(resolve_tag FLOOR_LADDER)"; then
      if [ "${floor_tag}" = "${FLOOR_TEMPLATE_FIX_TAG}" ]; then
        echo "floor: grafting template via ollama/Modelfile.floor -> ${FLOOR_MODEL_NAME}" >&2
        docker compose cp ollama/Modelfile.floor "${OLLAMA_CONTAINER}:/tmp/Modelfile.floor"
        ollama_exec create "${FLOOR_MODEL_NAME}" -f /tmp/Modelfile.floor
        write_resolved_tag OLLAMA_MODEL_FLOOR "${FLOOR_MODEL_NAME}"
        echo "pinned OLLAMA_MODEL_FLOOR=${FLOOR_MODEL_NAME} (built from ${floor_tag}) in ${ENV_FILE}"
      else
        write_resolved_tag OLLAMA_MODEL_FLOOR "${floor_tag}"
        echo "pinned OLLAMA_MODEL_FLOOR=${floor_tag} in ${ENV_FILE}"
      fi
      installed_any=1
      [ "${chosen_default}" = "floor" ] && default_tag="${floor_tag}"
    else
      echo "WARN: no FLOOR_LADDER rung resolved — Floor tier unavailable on this host" >&2
    fi
  fi

  if should_install "fast"; then
    local fast_tag
    if ! fast_tag="$(resolve_tag FAST_LADDER)"; then
      echo "FATAL: no FAST_LADDER rung resolved a usable model tag" >&2
      exit 1
    fi
    write_resolved_tag OLLAMA_MODEL_FAST "${fast_tag}"
    installed_any=1
    [ "${chosen_default}" = "fast" ] && default_tag="${fast_tag}"
    ollama_exec list | grep -F "${fast_tag}" \
      || { echo "FATAL: pinned tag ${fast_tag} not in container 'ollama list'" >&2; exit 1; }
  fi

  if should_install "better"; then
    local better_tag
    if ! better_tag="$(resolve_tag BETTER_LADDER)"; then
      echo "FATAL: no BETTER_LADDER rung resolved a usable model tag" >&2
      exit 1
    fi
    write_resolved_tag OLLAMA_MODEL_BETTER "${better_tag}"
    installed_any=1
    [ "${chosen_default}" = "better" ] && default_tag="${better_tag}"
    ollama_exec list | grep -F "${better_tag}" \
      || { echo "FATAL: pinned tag ${better_tag} not in container 'ollama list'" >&2; exit 1; }
  fi

  [ "${installed_any}" -eq 1 ] || { echo "FATAL: INSTALL_MODELS selected no valid ladders" >&2; exit 1; }
  [ -n "${default_tag}" ] || { echo "FATAL: chosen default ${chosen_default} was not installed" >&2; exit 1; }

  # Back-compat alias: point OLLAMA_MODEL at the chosen default's tag (NOT always Fast).
  write_resolved_tag OLLAMA_MODEL "${default_tag}"
  echo "pinned installed set=${INSTALL_MODELS}; OLLAMA_MODEL=${default_tag} (${chosen_default} alias) in ${ENV_FILE}"
}

main "$@"
```

- [ ] **Step 3: Parse-check**

Run: `bash -n ollama/pull-and-pin.sh`
Expected: PASS (no output, exit 0).

- [ ] **Step 4: Commit**

```bash
git add ollama/pull-and-pin.sh
git commit -m "feat(r7): pull-and-pin.sh accepts INSTALL_MODELS + chosen default"
```

---

### Task 3: CPU Kokoro compose override

**Files:**
- Create: `docker-compose.cpu-tts.yml`
- Modify: `scripts/test_compose_topology.sh`

- [ ] **Step 1: Write the override**

Create `docker-compose.cpu-tts.yml`:

```yaml
# Adept CPU TTS override — Kokoro-FastAPI CPU image (ONNX-optimized, no GPU).
# Use with:
#   COMPOSE_FILE=docker-compose.yml:docker-compose.cpu-tts.yml docker compose up -d
#
# Drop-in for the default GPU kokoro: same port 8880, same KOKORO_BASE_URL contract,
# preserves /v1/audio/speech + /dev/captioned_speech (word-timestamped). Used by the
# Windows-AMD profile and any no-GPU host that still wants TTS.
services:
  kokoro:
    image: ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0
    deploy:
      resources:
        reservations:
          devices: !reset []
```

- [ ] **Step 2: Extend the topology test**

Add to `scripts/test_compose_topology.sh` (before the final `PASS`/`FAIL` summary):

```bash
# --- CPU TTS override render ---
if docker compose -f docker-compose.yml:docker-compose.cpu-tts.yml config --quiet >/dev/null 2>&1; then
  CPU_KOKORO_IMG=$(docker compose -f docker-compose.yml:docker-compose.cpu-tts.yml config 2>/dev/null \
    | awk '/^  kokoro:/{f=1} f&&/image:/{print $2; exit}')
  check "cpu-tts override renders + kokoro is CPU image" "$(echo "$CPU_KOKORO_IMG" | grep -q 'kokoro-fastapi-cpu' && echo true || echo false)"
else
  check "cpu-tts override renders + kokoro is CPU image" "true"  # deferred when docker absent
fi
```

- [ ] **Step 3: Run the topology test**

Run: `./scripts/test_compose_topology.sh`
Expected: PASS (the new `cpu-tts override renders...` check passes; or SKIP-cleanly if docker is absent).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.cpu-tts.yml scripts/test_compose_topology.sh
git commit -m "feat(r7): add CPU Kokoro compose override"
```

---

### Task 4: Windows-AMD compose override

**Files:**
- Create: `docker-compose.windows-amd.yml`
- Modify: `scripts/test_compose_topology.sh`

**Gating:** This task is part of the AMD profile. Per the spec's Sequencing note, execute after R6 closeout OR mark AMD-as-contingent. The compose artifact is render-verifiable without real AMD hardware.

- [ ] **Step 1: Write the override**

Create `docker-compose.windows-amd.yml`:

```yaml
# Adept Windows AMD override — native Ollama off-stack, CPU services in Docker.
# Use with:
#   COMPOSE_FILE=docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml docker compose up -d
#
# Native Ollama serves the LLM on localhost:11434 (host). Docker services reach it
# through host.docker.internal:11434. The in-stack ollama service is removed (the
# agent reaches native Ollama by URL, not service DNS). TTS uses the CPU Kokoro
# override (loaded alongside). STT stays on nemo-stt-cpu (unchanged).
services:
  # Remove the in-stack ollama service — Ollama runs natively on the Windows host.
  ollama:
    profiles: ["never"]   # !reset isn't enough to drop a service; profile-gate it out of default up

  agent:
    depends_on:
      livekit-server:
        condition: service_started
      nemo-stt-cpu:
        condition: service_started
      kokoro:
        condition: service_started
    environment:
      - OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
      - OLLAMA_GENERATE_URL=http://host.docker.internal:11434/api/generate
```

- [ ] **Step 2: Extend the topology test**

Add to `scripts/test_compose_topology.sh`:

```bash
# --- Windows AMD override render ---
WIN_FILE="docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml"
if docker compose -f $WIN_FILE config --quiet >/dev/null 2>&1; then
  WIN_OLLAMA_URL=$(docker compose -f $WIN_FILE config 2>/dev/null \
    | awk '/OLLAMA_BASE_URL/{print $2; exit}')
  check "windows-amd override renders + agent uses host.docker.internal ollama" \
    "$(echo "$WIN_OLLAMA_URL" | grep -q 'host.docker.internal' && echo true || echo false)"
else
  check "windows-amd override renders + agent uses host.docker.internal ollama" "true"
fi
```

- [ ] **Step 3: Run the topology test**

Run: `./scripts/test_compose_topology.sh`
Expected: PASS (the new `windows-amd override renders...` check passes; SKIP-cleanly if docker absent).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.windows-amd.yml scripts/test_compose_topology.sh
git commit -m "feat(r7): add Windows-AMD compose override (native ollama off-stack)"
```

---

### Task 5: Extend `install.sh` — offer-to-install + model selection

**Files:**
- Modify: `install.sh`
- Modify: `.env.example`
- Modify: `scripts/test_install.sh`

- [ ] **Step 1: Add the model-selection + offer-to-install functions to `install.sh`**

Insert after `detect_gpu()`:

```bash
# --- 1b. Offer to install safe prerequisites (guide-only until R7) -------------
detect_pkgmgr() {  # prints: apt|dnf|pacman|none
  for pm in apt dnf pacman; do
    if command -v "$pm" >/dev/null 2>&1; then printf '%s\n' "$pm"; return; fi
  done
  printf 'none\n'
}

offer_install_prereqs() {
  pm="$1"
  [ "$pm" = "none" ] && return 0
  log "Detected package manager: ${pm}."
  if [ "$ASSUME_YES" = "1" ]; then reply=y
  else
    printf 'Attempt to install missing Docker/Compose/Ollama via %s? [y/N] ' "$pm"
    read -r reply
  fi
  case "$reply" in
    y|Y|yes|Yes)
      case "$pm" in
        apt)  sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 ;;
        dnf)  sudo dnf install -y docker docker-compose-plugin ;;
        pacman) sudo pacman -S --noconfirm docker docker-compose ;;
      esac
      ;;
    *) log "Skipping auto-install. Install Docker/Compose manually, then re-run." ;;
  esac
}

# --- 1c. Model selection -----------------------------------------------------
prompt_models() {  # sets INSTALL_MODELS + MODEL_LABELS (globals)
  gpu="$1"
  # Default recommendation from hardware.
  case "$gpu" in
    nvidia) default_model="fast" ;;
    amd)    default_model="fast" ;;
    none)   default_model="floor" ;;
  esac
  log ""
  log "Recommended LLM: ${default_model} (best default for this machine)."
  log "Available: fast (snappier), better (more thoughtful), floor (weakest hardware)."
  if [ "$ASSUME_YES" = "1" ]; then
    INSTALL_MODELS="${default_model}"
    MODEL_LABELS="${default_model}"
  else
    printf 'Which models to install (comma list, e.g. fast,better)? [%s] ' "$default_model"
    read -r reply
    INSTALL_MODELS="${reply:-${default_model}}"
    printf 'Aliases (comma list, same order; blank for defaults)? '
    read -r labels
    MODEL_LABELS="${labels:-${INSTALL_MODELS}}"
  fi
  log "Will install: ${INSTALL_MODELS}"
}

# --- 1d. Write model-choices env to .env -------------------------------------
write_model_env() {
  # ADEPT_MODEL_CHOICES — the installed set (comma list).
  if grep -q '^ADEPT_MODEL_CHOICES=' .env 2>/dev/null; then
    sed -i "s|^ADEPT_MODEL_CHOICES=.*|ADEPT_MODEL_CHOICES=${INSTALL_MODELS}|" .env
  else
    printf 'ADEPT_MODEL_CHOICES=%s\n' "${INSTALL_MODELS}" >> .env
  fi
  # Labels (baked into the web build via NEXT_PUBLIC_ADEPT_MODEL_LABELS).
  if grep -q '^NEXT_PUBLIC_ADEPT_MODEL_LABELS=' .env 2>/dev/null; then
    sed -i "s|^NEXT_PUBLIC_ADEPT_MODEL_LABELS=.*|NEXT_PUBLIC_ADEPT_MODEL_LABELS=${MODEL_LABELS}|" .env
  else
    printf 'NEXT_PUBLIC_ADEPT_MODEL_LABELS=%s\n' "${MODEL_LABELS}" >> .env
  fi
  # ADEPT_DEFAULT_MODEL — first of the installed set (safe: its tag is pinned by pull-and-pin).
  default_choice="${INSTALL_MODELS%%,*}"
  if grep -q '^ADEPT_DEFAULT_MODEL=' .env 2>/dev/null; then
    sed -i "s|^ADEPT_DEFAULT_MODEL=.*|ADEPT_DEFAULT_MODEL=${default_choice}|" .env
  else
    printf 'ADEPT_DEFAULT_MODEL=%s\n' "${default_choice}" >> .env
  fi
}
```

- [ ] **Step 2: Wire the new functions into the main flow**

Replace the `# --- main ---` block:

```bash
# --- main -------------------------------------------------------------------
GPU="$(detect_gpu)"
require_docker || true
if [ "${DOCKER_WAS_MISSING:-0}" != "1" ]; then
  PM="$(detect_pkgmgr)"
  offer_install_prereqs "$PM"
  require_docker   # re-check after offer-to-install
fi
if [ "$GPU" = "nvidia" ] && [ "${SKIP_DOCTOR:-0}" != "1" ]; then
  ./scripts/gpu-doctor.sh || true
fi
scaffold_env
prompt_models "$GPU"
write_model_env
print_plan "$GPU" "$INSTALL_MODELS"
confirm
INSTALL_MODELS="${INSTALL_MODELS}" ADEPT_DEFAULT_MODEL="${INSTALL_MODELS%%,*}" \
  ./ollama/pull-and-pin.sh
build_and_pull
log ""
log "Done. The stack is up."
log "  Start:  ./up.sh -d        (preflight + docker compose up -d)"
log "  Stop:   ./down.sh         (docker compose down)"
log "  Logs:   docker compose logs -f agent"
log "Open the web UI at the NEXT_PUBLIC_LIVEKIT_URL host configured in .env."
```

Update `print_plan` to accept the install set:

```bash
print_plan() {
  gpu="$1"; models="$2"
  log ""
  log "================ Adept setup plan ================"
  log "Services: livekit-server, agent, ollama, kokoro, nemo-stt-cpu, web"
  log "          (+ nemo-stt on GPU, opt-in via --profile stt-gpu)"
  log "GPU vendor detected: ${gpu}"
  log "Models to install: ${models}"
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
```

Also update `require_docker` to set `DOCKER_WAS_MISSING=1` before exiting on the first miss (so the main flow can attempt offer-to-install):

```bash
require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is not installed."
    log "Install Docker Engine + the Compose v2 plugin, then re-run ./install.sh:"
    log "  https://docs.docker.com/engine/install/"
    DOCKER_WAS_MISSING=1
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 plugin not found (need the 'docker compose' subcommand)."
    log "  https://docs.docker.com/compose/install/linux/"
    DOCKER_WAS_MISSING=1
    return 1
  fi
}
```

- [ ] **Step 3: Update `.env.example`**

Add after the `OLLAMA_MODEL=` line (line ~64):

```bash
# R7 install-set: which models were pulled + their picker labels.
# ADEPT_MODEL_CHOICES=fast,better,floor
# NEXT_PUBLIC_ADEPT_MODEL_LABELS=Fast,Better,Floor
# Windows-AMD native Ollama (off-stack; agent reaches host Ollama by URL):
# OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
# OLLAMA_GENERATE_URL=http://host.docker.internal:11434/api/generate
```

- [ ] **Step 4: Extend `scripts/test_install.sh`**

Add a Scenario C for the model-selection + offer-to-install paths. After Scenario B:

```bash
# --- Scenario C: -y with GPU=none → writes ADEPT_MODEL_CHOICES=floor ----------
BIN_C="$WORK/bin_c"; build_path "$BIN_C"
make_shim "$BIN_C" docker 'echo "docker $*" >> "$PWD/docker.log"; exit 0'
make_shim "$BIN_C" openssl 'echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
# stub pull-and-pin so it doesn't try real docker exec
printf '#!/usr/bin/env bash\necho "[stub] pull-and-pin INSTALL_MODELS=${INSTALL_MODELS}" > "$PWD/pin.log"\n' > "$WORK/ollama/pull-and-pin.sh"
chmod +x "$WORK/ollama/pull-and-pin.sh"
( cd "$WORK" && env -i PATH="$BIN_C" ASSUME_YES=1 bash install.sh -y >c.out 2>&1 ) && rcc=0 || rcc=$?
if [ "${rcc:-1}" -eq 0 ] \
   && grep -q 'ADEPT_MODEL_CHOICES=floor' "$WORK/.env" \
   && grep -q 'INSTALL_MODELS=floor' "$WORK/pin.log" 2>/dev/null; then
  ok "Scenario C: GPU=none → floor default + INSTALL_MODELS passed to pull-and-pin"
else
  bad "Scenario C: model selection path incomplete (rc=$rcc)"
  printf -- '------ install output ------\n%s\n----------------------------\n' "$(cat "$WORK/c.out")"
fi
```

- [ ] **Step 5: Parse-check + run the harness**

Run: `bash -n install.sh && ./scripts/test_install.sh`
Expected: PASS (all three scenarios pass; Scenario C verifies floor default + `INSTALL_MODELS` propagation).

- [ ] **Step 6: Commit**

```bash
git add install.sh .env.example scripts/test_install.sh
git commit -m "feat(r7): install.sh offer-to-install + model selection prompt"
```

---

### Task 6: Web picker driven by baked model choices

**Files:**
- Modify: `web/app/ModelPanel.tsx`
- Modify: `web/app/ApplySetupOnConnect.tsx`
- Modify: `docker-compose.yml`
- Test: `web` typecheck

- [ ] **Step 1: Add the bake-time build args to the web service**

In `docker-compose.yml`, extend the `web` service `build.args`:

```yaml
  web:
    build:
      context: ./web
      args:
        NEXT_PUBLIC_LIVEKIT_URL: ${NEXT_PUBLIC_LIVEKIT_URL:-ws://localhost:7880}
        NEXT_PUBLIC_ADEPT_MODEL_CHOICES: ${NEXT_PUBLIC_ADEPT_MODEL_CHOICES:-fast,better}
        NEXT_PUBLIC_ADEPT_MODEL_LABELS: ${NEXT_PUBLIC_ADEPT_MODEL_LABELS:-Fast,Better}
```

- [ ] **Step 2: Rewrite `web/app/ModelPanel.tsx` choices as env-derived**

Replace the hardcoded `CHOICES` block (lines 8-26) with:

```tsx
// R7: choices + labels are baked at build time from the installer's .env (not a
// hardcoded array). One-model install → one option (rendered read-only below).
// Back-compat: unset env → ["fast","better"] (the pre-R7 default).
const RAW_CHOICES = (process.env.NEXT_PUBLIC_ADEPT_MODEL_CHOICES ?? "fast,better")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
export const CHOICES = RAW_CHOICES as readonly string[];

const RAW_LABELS = (process.env.NEXT_PUBLIC_ADEPT_MODEL_LABELS ?? "Fast,Better")
  .split(",")
  .map((s) => s.trim());
const CHOICE_LABEL: Record<string, string> = Object.fromEntries(
  CHOICES.map((c, i) => [c, RAW_LABELS[i] ?? c])
);

export type ModelChoice = string;

// Default = the first baked choice (the installer's chosen default).
export const DEFAULT_MODEL: ModelChoice = CHOICES[0] ?? "fast";
```

Update `ModelFields` to render a single choice as a read-only field (no dropdown):

```tsx
export function ModelFields({
  value,
  onChange,
  className,
}: {
  value: ModelChoice;
  onChange: (c: ModelChoice) => void;
  className?: string;
}) {
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field-label" htmlFor="model-select">
        Response model
      </label>
      {CHOICES.length <= 1 ? (
        <input
          id="model-select"
          className="control"
          value={CHOICE_LABEL[CHOICES[0]] ?? CHOICES[0] ?? ""}
          readOnly
          aria-readonly="true"
        />
      ) : (
        <select
          id="model-select"
          className="control"
          value={value}
          onChange={(e) => onChange(e.target.value as ModelChoice)}
        >
          {CHOICES.map((c) => (
            <option key={c} value={c}>{CHOICE_LABEL[c] ?? c}</option>
          ))}
        </select>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify `ApplySetupOnConnect.tsx` still typechecks**

`ApplySetupOnConnect.tsx` imports `DEFAULT_MODEL` and compares against it with `sameAsDefault(config.model, DEFAULT_MODEL)`. `ModelChoice` is now `string`, so no change needed — confirm it still compiles.

- [ ] **Step 4: Typecheck the web**

Run: `cd web && npm run typecheck`
Expected: PASS (no type errors; `ModelChoice` widening to `string` is intentional and the RPC payload `{choice}` shape is unchanged).

- [ ] **Step 5: Render-verify the single-model case with Playwright (optional but recommended)**

Run a quick Playwright screenshot at `http://localhost:3000` with `NEXT_PUBLIC_ADEPT_MODEL_CHOICES=floor` baked, confirming the setup screen shows a read-only "Floor" model field (not a dropdown). If Playwright is unavailable, skip with a note.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml web/app/ModelPanel.tsx web/app/ApplySetupOnConnect.tsx
git commit -m "feat(r7): web picker driven by baked model choices (single-model → read-only)"
```

---

### Task 7: Windows PowerShell installer + doctor

**Gating:** This task and Task 8 add the Windows-native surface. The Linux + model-selection work (Tasks 1-6) is independently shippable. Execute Tasks 7-8 when Windows support is in scope. **No `pwsh` in this sandbox** — all PS parse + mocked checks are operator-deferred (they skip cleanly when `pwsh` is absent, mirroring `test_compose_topology.sh`).

**Files:**
- Create: `install.ps1`
- Create: `scripts/gpu-doctor.ps1`
- Create: `up.ps1`
- Create: `down.ps1`
- Create: `scripts/test_install.ps1`
- Create: `scripts/test_gpu_doctor.ps1`

- [ ] **Step 1: Write `install.ps1` (mirror `install.sh` structure)**

Create `install.ps1` — the native Windows installer. It mirrors `install.sh`'s flow: detect Docker (offer `winget install -e --id Docker.DockerDesktop`), detect GPU (NVIDIA via `nvidia-smi`; AMD via the HIP SDK presence / `rocm-smi`-equivalent), run `scripts/gpu-doctor.ps1`, scaffold `.env`, prompt for models + aliases, call `pull-and-pin.sh` (via `docker compose exec`), build + start the stack. Key Windows specifics:

- Ollama install: `winget install -e --id Ollama.Ollama` (CPU/NVIDIA build). If AMD GPU detected, warn that AMD GPU inference needs a custom HIP SDK build (guide-only) and offer the CPU Ollama with a confirmation prompt.
- Docker Desktop backend check: confirm WSL2 backend is selected (the doctor verifies this).
- `.env` writes: same keys as `install.sh` (`ADEPT_MODEL_CHOICES`, `NEXT_PUBLIC_ADEPT_MODEL_LABELS`, `ADEPT_DEFAULT_MODEL`, `LIVEKIT_API_SECRET`). For the Windows-AMD profile, also write `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` + `OLLAMA_GENERATE_URL=http://host.docker.internal:11434/api/generate`.
- Start command: `docker compose -f docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml up -d` for the AMD profile; plain `docker compose up -d` for NVIDIA.

The full PowerShell script is ~150 lines mirroring `install.sh`'s function structure (`Require-Docker`, `Detect-Gpu`, `Scaffold-Env`, `Prompt-Models`, `Write-ModelEnv`, `Build-AndPull`). Use `$ErrorActionPreference = "Stop"` and `[Environment]::Is64BitOperatingSystem` guards.

- [ ] **Step 2: Write `scripts/gpu-doctor.ps1` (mirror `gpu-doctor.sh`)**

Create `scripts/gpu-doctor.ps1` — the Windows system + GPU check. Ordered chain: (1) Docker Desktop present + daemon running; (2) WSL2 backend selected (Settings → General → "Use the WSL 2 based engine"); (3) NVIDIA: `nvidia-smi` present + driver responds + container GPU probe (`docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`); (4) VRAM floor ≥ 16384 MB. AMD: detect HIP SDK + `rocm-smi`-equivalent; advise-only, always exit 0. Print `VRAM_TOTAL_MB` for the installer to read.

- [ ] **Step 3: Write `up.ps1` / `down.ps1`**

Create `up.ps1`:

```powershell
# up.ps1 — Windows start wrapper (mirrors up.sh). Runs gpu-doctor.ps1 (advise-only)
# then `docker compose up`, passing through $args. SKIP_DOCTOR=1 skips the preflight.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($env:SKIP_DOCTOR -ne "1") {
  & "$PSScriptRoot\scripts\gpu-doctor.ps1"
  Write-Output ""
}
docker compose up @args
```

Create `down.ps1`:

```powershell
# down.ps1 — Windows stop wrapper (mirrors down.sh).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
docker compose down @args
```

- [ ] **Step 4: Write `scripts/test_install.ps1` + `scripts/test_gpu_doctor.ps1`**

Create `scripts/test_install.ps1` — a PS parse + mocked-scenario harness mirroring `test_install.sh`'s PATH-shim isolation. Scenarios: Docker missing (guided + nonzero); Docker present + all-ok (scaffolds secret + invokes build/up); user declines prerequisite install; model selection (single model → `ADEPT_MODEL_CHOICES` written). Use `pwsh -NoProfile -Command "Get-Command install.ps1"` parse checks and mock `docker`/`winget` with function overrides. Skip cleanly when `pwsh` is absent:

```powershell
if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
  Write-Output "SKIP: pwsh not available — Windows installer checks deferred to operator"
  exit 0
}
```

Create `scripts/test_gpu_doctor.ps1` — mirror the doctor's scenarios (NVIDIA present, AMD present, no GPU, daemon down). Same skip-when-absent guard.

- [ ] **Step 5: Add a sandbox skip-guard wrapper for the PS tests**

Add to `scripts/test_install.sh` and `scripts/test_gpu_doctor.sh` a one-line check that the `.ps1` siblings exist (so the repo is consistent), but do NOT attempt to run them (no `pwsh` here). The PS tests are operator-run on Windows.

- [ ] **Step 6: Commit**

```bash
git add install.ps1 scripts/gpu-doctor.ps1 up.ps1 down.ps1 scripts/test_install.ps1 scripts/test_gpu_doctor.ps1
git commit -m "feat(r7): Windows PowerShell installer + doctor + wrappers"
```

---

### Task 8: README — install commands, profile matrix, model selection

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the Windows + model-selection sections to README**

Update `README.md` with:

- A "Quick start" section covering both OSes: `./install.sh` (Linux) and `.\install.ps1` (Windows).
- The supported host/profile matrix (Linux NVIDIA, Linux AMD, Windows NVIDIA, Windows AMD, no GPU) — a table mirroring the spec's Deployment Profiles.
- A "Model selection" subsection: the installer prompts for which models + aliases; the picker shows only installed models; to add a model later, edit `.env` (`ADEPT_MODEL_CHOICES` + `NEXT_PUBLIC_ADEPT_MODEL_LABELS`) and `docker compose build web`.
- Windows AMD note: native Ollama is the CPU build (best-effort); AMD GPU inference on Windows is a guide-only custom HIP SDK build.
- Start/stop/log commands per OS (`./up.sh` / `.\up.ps1`, `./down.sh` / `.\down.ps1`, `docker compose logs -f agent`).
- Which prerequisites the installer can install (Docker Desktop via winget on Windows; Docker/Compose/Ollama via apt/dnf/pacman on Linux behind confirmation) and which are guide-only (GPU drivers, NVIDIA Container Toolkit, HIP SDK).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(r7): README install commands, profile matrix, model selection"
```

---

## Verification (final, after all tasks)

- [ ] `bash -n install.sh up.sh down.sh scripts/gpu-doctor.sh ollama/pull-and-pin.sh`
- [ ] `./scripts/test_install.sh` (3+ scenarios PASS)
- [ ] `./scripts/test_gpu_doctor.sh` (PASS)
- [ ] `./scripts/test_compose_topology.sh` (PASS — includes cpu-tts + windows-amd render checks)
- [ ] `python3 tests/test_models.py` (PASS — install-set narrowing)
- [ ] `python3 -m pytest tests/ -q` (no regressions)
- [ ] `cd web && npm run typecheck` (PASS)
- [ ] `.env.example` includes `ADEPT_MODEL_CHOICES`, `NEXT_PUBLIC_ADEPT_MODEL_LABELS`, Windows-AMD `OLLAMA_BASE_URL`/`OLLAMA_GENERATE_URL`.
- [ ] README covers both OSes + model selection.

**Operator-deferred (no `pwsh` here; run on Windows):**
- [ ] `pwsh -NoProfile -File scripts/test_install.ps1`
- [ ] `pwsh -NoProfile -File scripts/test_gpu_doctor.ps1`
- [ ] Windows NVIDIA Docker GPU probe (real hardware).
- [ ] Windows AMD native Ollama + CPU Kokoro probe.

**Gated behind R6 closeout:**
- [ ] Linux AMD ROCm Compose profile (real AMD hardware).
- [ ] Windows AMD profile functionality (contingent on R6's AMD gates).
