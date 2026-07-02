# Windows AMD install — field report

**Date:** 2026-07-02
**Host:** Alienware Aurora R12, Windows 11 25H2 (build 26200), 64 GB RAM, ~143 GB free
**GPU:** AMD Radeon RX 6600 XT (gfx1032 / RDNA2), **8 GB VRAM**
**Profile used:** `docker-compose.yml` + `docker-compose.windows-amd.yml` + `docker-compose.cpu-tts.yml`
**Result:** 6/6 services up; agent registered with LiveKit; full voice round-trip works in the browser over `http://localhost:3000`.

This is the record of the first real Windows AMD bring-up. Windows AMD is
documented in `INSTALLATION.md` as **best effort / manual**, and this report
confirms why: the one-liner installer does **not** handle the AMD path, so the
operator must run a sequence of manual steps. It captures every bug found, the
environment gotchas, and the fixes (some already applied in-repo).

Companion to the (since-superseded) NVIDIA report at commit `942fb99`; this one
covers the AMD topology only.

---

## TL;DR

- The Windows AMD design is **architecturally different** from NVIDIA: the LLM
  runs in **native host Ollama** (not a container), and only the CPU services
  (LiveKit, agent, CPU TTS, CPU STT, web) run in Docker. The agent reaches host
  Ollama over `host.docker.internal:11434`.
- `install.ps1` **cannot** be used end-to-end on AMD: its `Build-AndPull` runs
  plain `docker compose build/up` (no AMD overrides) and its model pull runs
  `docker compose exec ollama ollama pull` into the in-container Ollama, but the
  AMD override replaces `ollama` with an `alpine:3.21` **sleep stub that has no
  `ollama` binary**. The pull would fail with "command not found." AMD is manual.
- The RX 6600 XT (gfx1032) is **off Ollama's ROCm support list**, so native
  Ollama runs the LLM on **CPU** by default. The one performance lever is
  Ollama's **Vulkan backend** (`OLLAMA_LLM_LIBRARY=vulkan`), which does
  accelerate gfx1032. Verified via `ollama ps` (`PROCESSOR` = GPU).
- Three real bugs were found and fixed in-repo (see below); four more
  documentation/tooling gaps are logged for follow-up.

---

## The working path (repeatable)

1. **Install native Ollama** on the host: `winget install -e --id Ollama.Ollama`.
   Close + reopen PowerShell so `ollama` is on `PATH`.
2. **Force Vulkan** so gfx1032 gets GPU acceleration (ROCm does not cover it):
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_LLM_LIBRARY", "vulkan", "User")
   [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
   Get-Process ollama* | Stop-Process -Force; Start-Process ollama
   ```
3. **Pull the model into native Ollama** (not the container):
   `ollama pull evalengine/unbound-e2b:latest` (~1.6 GB). Verify with
   `ollama list` and `ollama ps` (`PROCESSOR` column shows GPU).
4. **Clone** the repo (`git clone https://github.com/foreztgump/rehearsal.git`),
   `cd rehearsal`.
5. **Scaffold `.env`**: `Copy-Item .env.example .env`; generate a random
   `LIVEKIT_API_SECRET` (32 random hex bytes) and write it into `.env`.
6. **Set the model config in `.env`** to match the single pulled model (see
   Bug #3 — the commented defaults make this easy to get wrong):
   ```
   REHEARSAL_MODEL_CHOICES=fast
   NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=Fast
   REHEARSAL_DEFAULT_MODEL=fast
   OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest
   OLLAMA_MODEL=evalengine/unbound-e2b:latest
   ```
7. **Build + start** the stack with the AMD + CPU-TTS overrides (use `-f` flags,
   not `COMPOSE_FILE=…:…` — see Bug #2):
   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml `
     -f docker-compose.cpu-tts.yml build
   docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml `
     -f docker-compose.cpu-tts.yml up -d
   ```
   Apply the **port-collision fix** (Bug #1) to `docker-compose.windows-amd.yml`
   before `up` (add `ports: !reset []` under the `ollama` stub) or the stub's
   `11434` publish collides with native Ollama.
8. **Verify**: `docker compose … ps` (6 services up, `ollama` = `alpine` with no
   published port, `nemo-stt-cpu` healthy); `docker compose … logs --tail=80
   agent` (look for `registered worker`); `docker compose … exec agent python -c
   "import urllib.request,json; d=json.loads(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read()); print([m['name'] for m in d['models']])"`
   (should print `['evalengine/unbound-e2b:latest']`).
9. Open `http://localhost:3000` in Chrome/Edge, pick a persona, and speak. First
   turn is slow (cold model/STT/TTS warmup); later turns are faster.

---

## Bugs found (symptom → root cause → fix)

### 1. Port collision: `ollama` stub publishes 11434, colliding with native Ollama — **FIXED in-repo**
- **Symptom:** `docker compose … up -d` fails:
  `Error response from daemon: ports are not available … listen tcp4
  127.0.0.1:11434: bind: Only one usage of each socket address …`.
- **Root cause:** `docker-compose.windows-amd.yml` resets the stub's
  **devices** (`devices: !reset []`) but **not its `ports`**. The base
  `docker-compose.yml` still publishes `${LAN_BIND_IP:-127.0.0.1}:11434:11434`
  for the `ollama` service. On Windows AMD that port is owned by the real,
  native host Ollama — so the stub's host bind collides and the whole stack
  refuses to start.
- **Fix:** add `ports: !reset []` to the `ollama` stub in
  `docker-compose.windows-amd.yml`. The stub serves nothing; the agent reaches
  host Ollama **outbound** via `host.docker.internal:11434` (not a host bind), so
  dropping the port publish is correct. Applied in-repo.
- **Scope:** every Windows AMD user. Without this fix the stack cannot start.

### 2. `COMPOSE_FILE=…:…:…` colon separator fails on Windows — **DOC gap**
- **Symptom:** `$env:COMPOSE_FILE = "docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml"; docker compose …`
  errors:
  `CreateFile D:\AI\rehearsal\docker-compose.yml:docker-compose.windows-amd.yml:docker-compose.cpu-tts.yml: The filename, directory name, or volume label syntax is incorrect.`
- **Root cause:** on Windows the `COMPOSE_FILE` **path separator is `;`**, not
  `:`, because `:` collides with drive letters (the install dir here was
  `D:\AI\rehearsal`, and `D:` is what made the colon ambiguous). Compose treated
  the entire colon-joined string as a single filename.
- **Fix (workaround):** use explicit `-f` flags on every command instead of
  `COMPOSE_FILE` — works on every platform/version and avoids the separator
  question entirely.
- **Doc fix needed:** `INSTALLATION.md` and the override-file headers
  (`docker-compose.amd.yml`, `docker-compose.windows-amd.yml`,
  `docker-compose.cpu-tts.yml`) all show `COMPOSE_FILE=…:…:…` with colons. On
  Windows these should use `;` or, better, show the `-f` form. Update the
  Windows AMD section of `INSTALLATION.md` and the override headers.
- **Scope:** every Windows user who follows the documented `COMPOSE_FILE` form.

### 3. `.env` model-config defaults are commented, easy to mis-set — **DOC gap**
- **Symptom:** after scaffolding `.env` from `.env.example`, narrowing to a
  single installed model leaves `REHEARSAL_MODEL_CHOICES` and
  `NEXT_PUBLIC_REHEARSAL_MODEL_LABELS` **still commented**, and
  `REHEARSAL_DEFAULT_MODEL` unset. A naive `-replace` (or manual edit) matches
  the text after the `# ` prefix and leaves the comment in place.
- **Why it matters:** with these unset, `agent/models.py`'s
  `effective_model_choices()` falls back to the **full** shipped set
  `("fast","better","floor")`. The web picker then surfaces choices whose
  `OLLAMA_MODEL_BETTER`/`OLLAMA_MODEL_FLOOR` tags are empty, and picking one
  crashes the agent with "OLLAMA_MODEL_BETTER is not set."
- **Fix (operator):** when narrowing to one model, write all five as
  **uncommented** active lines (see the working path above). The installer's
  `Set-EnvKey` handles this correctly, but the manual AMD path has no such
  helper — operators must do it by hand.
- **Tooling fix suggested:** ship a `scripts/set-env.ps1` (and `.sh`) helper
  that the manual AMD path can call, mirroring the installer's `Set-EnvKey`,
  so hand-editing `.env` is not the documented step.
- **Scope:** any manual (non-installer) path, which is exactly the Windows AMD path.

### 4. `gpu-doctor.ps1` has no AMD branch — **TOOLING gap**
- **Symptom:** the probe reported the GPU as `none`, and on this host
  `gpu-doctor.ps1` would skip all GPU checks and only advise on Docker/WSL2.
- **Root cause:** `Detect-Gpu` keys off `nvidia-smi` or an `AMD ROCm*` install
  marker. There is no AMD-specific path on Windows (no ROCm on Windows for this
  card; Vulkan is the backend, not ROCm). So AMD hosts get no GPU preflight.
- **Fix suggested:** add an AMD branch that detects the Vulkan-capable adapter
  (via `Win32_VideoController` name match for `AMD|Radeon`) and, at minimum,
  advises that the LLM runs in native Ollama with `OLLAMA_LLM_LIBRARY=vulkan`.
  The CUDA floor and VRAM floor checks are NVIDIA-specific and should be
  skipped on AMD.
- **Scope:** all Windows AMD users.

### 5. Installer never loads the AMD overrides — **DESIGN gap (by intent, but under-documented)**
- **Symptom:** running `irm …/install.ps1 | iex` on an AMD box runs
  `docker compose build/up` with no AMD overrides. The base compose reserves
  NVIDIA devices (`driver: nvidia`) on `ollama`, `kokoro`, and `nemo-stt`, which
  on an AMD-only box either error or start with no usable GPU — not the
  intended Windows AMD topology.
- **Root cause:** `install.ps1`'s `Build-AndPull` hardcodes plain
  `docker compose build/up`. The AMD topology requires the
  `windows-amd.yml` + `cpu-tts.yml` overrides, which the installer never sets.
- **Status:** this is the intentional "manual until validated" gate from
  `INSTALLATION.md` / `CHANGELOG.md` (R6). This field report is the validation.
  **Fix:** teach `install.ps1` to detect AMD (via `Win32_VideoController` or the
  existing `Detect-Gpu`) and, on AMD, branch to the manual path: install native
  Ollama, pull the model into host Ollama, set `.env`, and `up` with the
  override `-f` flags. Until then, AMD stays manual and the docs must say so
  prominently (currently a single "best effort" line).
- **Scope:** all Windows AMD users trying the one-liner.

---

## Environment gotchas (AMD-specific)

### G1. The RX 6600 XT is gfx1032 — off Ollama's ROCm list
Ollama's ROCm backend targets gfx1030 (6800/6900), gfx1100 (7900), etc. The 6600
XT is gfx1032 and logs `amdgpu is not supported`. Native Ollama falls back to
**CPU** by default. Vulkan (`OLLAMA_LLM_LIBRARY=vulkan`) is the only GPU lever
on this card and it works. Verify with `ollama ps` after a real `ollama run` —
the `PROCESSOR` column should show GPU, not `100% CPU`.

### G2. Vulkan env vars must be permanent + Ollama restarted
Setting `$env:OLLAMA_LLM_LIBRARY="vulkan"` in one PowerShell session only
affects processes started from that session. Ollama on Windows runs as a
background tray app, so after the next restart/reboot it silently falls back to
CPU. Make them user-level permanent (`[Environment]::SetEnvironmentVariable(...,
"User")`) and restart Ollama so the background process picks them up. Re-verify
with `ollama ps` after the restart.

### G3. `Win32_VideoController.AdapterRAM` wraps at 4 GB
The probe reported **4 GB** for an 8 GB card. `AdapterRAM` is a `uint32` that
wraps at 4 GB. `gpu-doctor.ps1` dodges this on NVIDIA by using `nvidia-smi`, but
there's no AMD equivalent wired in. Any AMD VRAM check must use a different
source (e.g. `Get-CimInstance Win32_VideoController` is unreliable above 4 GB;
consider the DXGI adapter info or the AMD driver's own query).

### G4. Browser probe via `Get-Command` misses Chrome/Edge
The probe reported "NOT FOUND" for Chrome and Edge that are installed. They're
not on `PATH` on Windows. Functionally fine (Chrome/Edge work), but any
browser-detection helper should check the standard install paths or registry,
not `Get-Command`.

### G5. `host.docker.internal` resolves from the agent container
The critical Windows-AMD seam held on the first try: from inside the `agent`
container, `http://host.docker.internal:11434/api/tags` returned the model list.
No extra `extra_hosts` config was needed (Docker Desktop injects
`host.docker.internal` automatically). This is worth a regression check in any
future AMD CI, since Linux Docker does not provide `host.docker.internal` by
default and a Linux-built compose could break it.

### G6. WSL status output is spaced-out (UTF-16 artifact)
`wsl --status`/`wsl --version` output arrived as `D e f a u l t ...` spaced
characters. Cosmetic encoding artifact, but it can break naive parsing in any
helper that shells out to `wsl`. Strip/tolerate it if parsing programmatically.

### G7. First-turn LLM latency is high (cold load)
Agent logs showed `llm_ttft_ms ~6500-6700` with `"over_budget": ["llm_ttft"]`
during prewarm. This is the cold Vulkan model load; the first real utterance is
similarly slow, later turns are faster once the model is resident. Not a bug —
but on an 8 GB Vulkan card, do not expect the sub-second P50 the 16 GB NVIDIA
target aims for. Worth surfacing to the user in the UI or install output.

### G8. `PyTorch was not found` warning in agent logs
Harmless: `[transformers] PyTorch was not found. Models won't be available...`.
The agent doesn't use the transformer models that need PyTorch here. Noisy but
not a defect.

---

## Recommendations — making Windows AMD first-class

**Must-do (correctness):**
1. **Ship the `ports: !reset []` fix** (done) — without it the AMD stack cannot
   start at all (Bug #1).
2. **Fix the `COMPOSE_FILE` colon docs for Windows** (Bug #2): switch the
   Windows AMD section of `INSTALLATION.md` and the override headers to `;` or,
   better, to explicit `-f` flags.
3. **Teach `install.ps1` the AMD branch** (Bug #5): detect AMD, install native
   Ollama, pull the model into host Ollama, set `.env`, and `up` with the
   override `-f` flags. Until then, the Windows AMD section must prominently say
   "do NOT use the one-liner; follow the manual path."

**Should-do (fewer support tickets):**
4. **Ship a `set-env.ps1` helper** (Bug #3) so the manual `.env` narrowing is
   not hand-editing.
5. **Add an AMD branch to `gpu-doctor.ps1`** (Bug #4): detect the Vulkan-capable
   adapter and advise the native-Ollama + Vulkan path.
6. **Document the Vulkan + permanent-env-var dance** (G1–G2) in the Windows AMD
   section, including the `ollama ps` verification step.
7. **Fix the 4 GB VRAM wrap and browser detection** (G3–G4) if any AMD
   preflight is added.

**Nice-to-have:**
8. **Pin and document the recommended model for 8 GB Vulkan cards.** `fast`
   (`evalengine/unbound-e2b:latest`, ~1.6 GB) fits trivially and works. `better`
   (~5.3 GB) is too tight for 8 GB to risk first. `floor` is the fallback.
9. **Add a Windows AMD CI cell** (or at least a manual validation matrix entry)
   so the AMD topology cannot regress, especially the `host.docker.internal`
   seam (G5).

---

## Validation matrix for "Windows AMD works"

Test these before calling Windows AMD supported (not best-effort):

| Axis | Values to cover |
| --- | --- |
| Entry point | manual path (this report); future installer AMD branch |
| AMD GPU | gfx1032 (Vulkan-only, this report); gfx1100 (7900, ROCm-listed) if available |
| VRAM | 8 GB (this report); 16 GB+ if available |
| Compose file spec | `-f` flags (this report); `COMPOSE_FILE` with `;` (Bug #2 follow-up) |
| Native Ollama backend | Vulkan (this report); CPU fallback (gfx off ROCm, no Vulkan) |
| Model | fast (this report); floor (weak GPU); better (16 GB+ only) |
| `host.docker.internal` reachability | from agent container to host Ollama (G5) |
| Browser | Chrome (this report); Edge; Firefox not recommended (loopback ICE) |
