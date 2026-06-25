---
phase: 01-foundation-infrastructure
plan: 01-01
subsystem: infra
tags: [docker-compose, nvidia-gpu, livekit, caddy, mkcert, nextjs, tls, secure-context]

requires: []
provides:
  - Six-service docker-compose.yml (livekit-server, agent, ollama, whisper, kokoro, web) + caddy proxy
  - GPU reservations on the 3 model services (ollama, whisper, kokoro)
  - LAN-only port binding discipline via LAN_BIND_IP (no WAN exposure)
  - mkcert TLS reverse proxy (Caddy) terminating 443 -> web:3000 + 7443 LiveKit WS vhost
  - Minimal Next.js standalone web shell proving navigator.mediaDevices secure-context probe
  - uv-based agent placeholder Dockerfile (extended in 01-03)
  - Two-layer GPU passthrough operator documentation (Proxmox->VM, VM->container)
affects: [01-02, 01-03, phase-02-voice-loop]

tech-stack:
  added:
    - "docker-compose (6 services + caddy proxy)"
    - "livekit/livekit-server:v1.10.0"
    - "ollama/ollama:0.6.8"
    - "fedirz/faster-whisper-server (pinned by digest)"
    - "ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.4"
    - "caddy:2.8"
    - "next@16.2.9, react@19.2.7, react-dom@19.2.7"
    - "ghcr.io/astral-sh/uv:python3.12-bookworm-slim (agent base)"
  patterns:
    - "All image tags pinned (no bare :latest; whisper pinned by sha256 digest)"
    - "Published ports bound to LAN_BIND_IP only (default 127.0.0.1) — never 0.0.0.0/WAN"
    - "GPU via deploy.resources.reservations.devices with capabilities: [gpu]"
    - "Next.js output: standalone for minimal multi-stage runtime image"
    - "Secure-context probe pattern: read navigator.mediaDevices without calling getUserMedia"

key-files:
  created:
    - docker-compose.yml
    - .env.example
    - .gitignore
    - agent/Dockerfile
    - certs/.gitkeep
    - certs/README.md
    - proxy/Caddyfile
    - README.md
    - web/package.json
    - web/next.config.mjs
    - web/app/layout.tsx
    - web/app/page.tsx
    - web/app/SecureContextProbe.tsx
    - web/Dockerfile
    - web/tsconfig.json
  modified: []

key-decisions:
  - "Pinned livekit v1.10.0, ollama 0.6.8, kokoro v0.2.4; whisper latest-cuda pinned by sha256 digest (AGENTS.md: never guess/float tags)"
  - "LiveKit booted with --dev built-in devkey at this boundary; real livekit.yaml + ICE config deferred to 01-03"
  - "LAN_BIND_IP env var (default 127.0.0.1) gates every published port — enforces PERF-03 LAN-only discipline declaratively"
  - "Caddy 7443 TLS vhost added now to pre-front the LiveKit WS endpoint for Phase 2 wss://"
  - "web/next-env.d.ts gitignored (build-regenerated); tsconfig.json committed"

patterns-established:
  - "Pin every container image tag; pin floating tags by digest"
  - "Every published port binds to LAN_BIND_IP — no 0.0.0.0 host binds"
  - "GPU services declare deploy.resources.reservations.devices with capabilities: [gpu]"

requirements-completed: [DEPLOY-01, PERF-03, PERF-02]

duration: 22 min
completed: 2026-06-25
status: complete
---

# Phase 01 Plan 01-01: Docker Compose stack + GPU passthrough + HTTPS-on-LAN Summary

**Six-service GPU Compose stack (LiveKit/Ollama/Whisper/Kokoro/agent/web) with pinned tags, LAN-only port binds, a mkcert Caddy TLS proxy, and a Next.js shell proving `navigator.mediaDevices` in a secure context.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-06-25T03:41:00Z
- **Completed:** 2026-06-25T04:03:01Z
- **Tasks:** 4
- **Files created:** 17 (incl. lockfile + public/.gitkeep)

## Accomplishments
- `docker compose config` validates a 7-service manifest (6 core + caddy proxy) with GPU reservations on exactly the 3 model services and every port bound LAN-only via `LAN_BIND_IP`.
- Minimal Next.js (16.2.9 / React 19.2.7) standalone shell builds clean (`next build` exit 0, `.next/standalone/server.js` produced) and renders a secure-context PASS/FAIL probe reading `navigator.mediaDevices` — with no `getUserMedia` call in `web/app`.
- mkcert TLS reverse proxy (Caddy 2.8) terminating 443 → web:3000 plus a 7443 TLS vhost pre-fronting the LiveKit WS endpoint for Phase 2; `certs/README.md` documents the full CA-trust + per-deploy cert-mint procedure.
- README documents the two-layer GPU passthrough chain (Proxmox→VM vfio, VM→container NVIDIA Container Toolkit) with `nvidia-ctk runtime configure --runtime=docker`, both named failure strings, and the container-layer verification command.

## Task Commits

1. **Task 01-01-1: Scaffold compose stack, env, gitignore, agent placeholder** - `273f838` (feat)
2. **Task 01-01-2: Two-layer GPU passthrough documentation** - `daa7ce3` (docs)
3. **Task 01-01-3: Minimal Next.js secure-context shell** - `1e2cc97` (feat)
4. **Task 01-01-4: Caddy mkcert TLS reverse proxy + CA-trust** - `79cac2b` (feat)

## Files Created/Modified
- `docker-compose.yml` - 6 core services + caddy proxy, GPU reservations, LAN-only binds, `adept` bridge net
- `.env.example` + `.gitignore` - Ollama/LiveKit env template; ignores `.env`, cert keys, web build artifacts
- `agent/Dockerfile` - uv-based placeholder (no livekit deps yet; extended in 01-03)
- `proxy/Caddyfile` - mkcert TLS on 443 → web:3000 + 7443 LiveKit WS vhost
- `certs/README.md` + `certs/.gitkeep` - mkcert CA-trust + per-deploy cert-mint procedure
- `README.md` - two-layer GPU passthrough + toolkit setup + verification commands
- `web/` - Next.js standalone shell: `package.json`, `next.config.mjs`, `app/layout.tsx`, `app/page.tsx`, `app/SecureContextProbe.tsx`, `Dockerfile`, `tsconfig.json`

## Decisions Made
- Resolved the plan's `vX.x`/`0.6.x` tag placeholders to concrete pinned tags verified via `docker manifest inspect` (livekit v1.10.0, ollama 0.6.8, kokoro v0.2.4); whisper `latest-cuda` pinned by sha256 digest per AGENTS.md "never guess/float tags".
- LiveKit booted with `--dev` (built-in devkey) at this boundary; the real `livekit.yaml` + ICE config is 01-03's job — keeps the stack bootable now without pre-empting later config.
- Added the Caddy `:7443` LiveKit WS TLS vhost now (cheap, no cost) so Phase 2 `wss://` is ready without re-touching the proxy.

## Deviations from Plan

None - plan executed exactly as written. (Tag-placeholder resolution and digest-pinning are the plan's own instruction to pin real tags, not a deviation.)

## Issues Encountered
- **`npm install` transient node_modules loss:** the first web install timed out at 120s mid-run and a subsequent build wiped `node_modules`; a clean re-`npm install` restored it and `next build` then succeeded (exit 0). No code change required — environmental, not a plan defect.

## Authentication Gates
None.

## Operator Gates (daemon/hardware required — could not run in this sandbox)

This execution environment has **no Docker daemon socket access** (`docker ps`
denied; not in the `docker` group, sudo needs a password) and mkcert is not
installed. Registry/client checks (`docker manifest inspect`, `docker compose
config`) and the Next.js build all ran and passed. The following acceptance
gates are daemon/hardware/operator actions to run on the Proxmox VM and a real
LAN device — record their output when run:

- `docker compose build agent` and `docker compose up` (all six services boot; agent runs the placeholder CMD) — DEPLOY-01 boot proof.
- `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` prints the GPU table — Layer-2 passthrough gate.
- `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000` returns 200 after `docker compose up web`.
- After `mkcert -install` + minting `certs/lan.pem`/`lan-key.pem` and `docker compose up proxy web`: load `https://<lan-ip>/` on a CA-trusted LAN device → shows "secure context: mediaDevices defined".

(GPU hardware is present in this sandbox — `nvidia-smi -L` shows an RTX 5090 — but the container runtime cannot be exercised without daemon access.)

## User Setup Required
None - no external service accounts required. Operator must install the NVIDIA Container Toolkit and mkcert on the deployment VM/client (documented in `README.md` and `certs/README.md`).

## Next Phase Readiness
- Compose skeleton, GPU reservations, TLS proxy, and secure-context shell are in place — ready for **01-02** (Ollama model pin + flash-attn/KV-quant + VRAM validation).
- The agent image is a uv placeholder; 01-03 extends it with `livekit-agents` deps + weights bake and the real `livekit.yaml`/ICE config.
- All four operator gates above should be run on the actual Proxmox VM before declaring the boundary fully proven.

## Self-Check: PASSED
- `docker compose config` exits 0; enumerates 7 services (6 core + proxy).
- `grep -c 'capabilities: [gpu]'` = 3 (ollama, whisper, kokoro).
- `.env.example` contains the three Ollama env vars; `.env` is gitignored (`git check-ignore .env` → `.env`).
- `next build` exits 0; `.next/standalone/server.js` exists; `grep -r getUserMedia web/app` → empty; `navigator.mediaDevices` referenced in `app/SecureContextProbe.tsx`.
- `proxy/Caddyfile` references `certs/lan.pem`, `certs/lan-key.pem`, `reverse_proxy web:3000`; `certs/README.md` documents `mkcert -install` + the cert-mint command.
- No `0.0.0.0:` host binds in `docker-compose.yml` (LAN-only via `LAN_BIND_IP`).
- 4 task commits present (`273f838`, `daa7ce3`, `1e2cc97`, `79cac2b`).

---
*Phase: 01-foundation-infrastructure*
*Completed: 2026-06-25*
