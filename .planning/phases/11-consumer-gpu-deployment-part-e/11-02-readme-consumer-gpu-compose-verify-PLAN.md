---
plan: 11-02
title: README Consumer-GPU rewrite (delete the Proxmox two-layer section entirely, replace with one nvidia-ctk + --gpus all + gpu-doctor flow — no VM/Proxmox content) + docker compose config verification (default vs --profile stt-gpu) + 11-DEPLOY-VERIFY.md operator gate
phase: 11
wave: 2
depends_on: [11-01]
autonomous: false
requirements: [DEPLOY-04, DEPLOY-05]
files_modified:
  - README.md
  - scripts/test_compose_topology.sh
  - .planning/phases/11-consumer-gpu-deployment-part-e/11-DEPLOY-VERIFY.md
---

# Plan 11-02: README Consumer-GPU rewrite + compose-topology verification + operator gate

## User Story

**As** a user reading the docs to get started on my own machine, **I want** the README to
describe a single straightforward `docker compose` setup (install the NVIDIA Container Toolkit,
prove `--gpus all` works, run `./up.sh`) with NO Proxmox/VM/vfio content at all, and a default
`docker compose up` that boots the VRAM-safe CPU-ONNX STT out of the box, **so that** I am not
misled into homelab-only steps and I know exactly how to opt into the GPU path or the degraded
path.

## Context

This is the **docs + verification half** of Phase 11, building on the `gpu-doctor.sh`/`up.sh`
from 11-01. It (1) rewrites the README's GPU section, (2) adds a sandbox compose-topology check
proving the default and `--profile stt-gpu` graphs are valid and that the default brings up
CPU-STT (no GPU-STT, no GPU reservation on the always-on STT), and (3) writes the unsigned
operator gate `11-DEPLOY-VERIFY.md`.

## README rewrite (DELETE L33-91 — the `## GPU passthrough` block, both `### Layer 1`/`### Layer
2` subsections, the `### Diagnosing` table, and the closing Proxmox blockquote — and replace
with one section)

Keep `## Quick start` (L7-31) — but update its `docker compose up` mention to also point at
`./up.sh` (the doctor-wrapped entrypoint). Replace everything from `## GPU passthrough` (L33)
through the Proxmox blockquote at L91 with a new single section. **There must be ZERO
remaining occurrences of `Proxmox`, `vfio`, `PCIe`, `Layer 1`, `Layer 2`, `two-layer`, or
"inside the VM" in the README after this edit** — grep them to confirm.

### New `## GPU setup (NVIDIA Container Toolkit)` section — required content
- One-paragraph framing: the three model containers (`ollama`, `nemo-stt` [GPU profile],
  `kokoro`) need an NVIDIA GPU on the machine running `docker compose`; STT also has an off-GPU
  CPU-ONNX path so the **default boots VRAM-safe without the GPU STT**.
- **Install the NVIDIA Container Toolkit** + configure the Docker runtime (the three commands:
  `apt-get install -y nvidia-container-toolkit`, `nvidia-ctk runtime configure
  --runtime=docker`, `systemctl restart docker`). This is the ONLY host step — there is no VM
  or passthrough layer.
- **Verify (operator gate):** `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04
  nvidia-smi` must print the GPU table from inside a container.
- **Preflight:** `./up.sh` runs `scripts/gpu-doctor.sh` first and prints OK or an exact remedy
  + a copyable env snippet, then `docker compose up`. Mention `SKIP_DOCTOR=1`.
- **Default vs GPU STT:** `docker compose up` (or `./up.sh`) = CPU-ONNX STT (safe default,
  `STT_FORCE_CPU=1`). Opt into GPU STT with `docker compose --profile stt-gpu up` AND
  `STT_FORCE_CPU=0` + `STT_HEADROOM_MEASURED=1` only after `10-PLACEMENT-VERIFY.md` passes
  (link it). Keep this consistent with `.env.example` L93-103 — do NOT contradict the P10 gate.
- **Degraded path:** on a sub-spec/non-NVIDIA host, the doctor recommends `STT_FORCE_CPU=1` +
  the Fast `OLLAMA_MODEL` and the stack still comes up usable; ollama/kokoro still need a GPU
  (documented v1.1 limitation).
- **Keep the failure-mode table** (the two rows at L84-87) — they are still the two common
  errors; reword the "Layer 2" reference to "the toolkit step above" (no Layer wording).
- **No-hung-`up` note:** first `up` builds/pulls multi-GB GPU images + bakes the STT model;
  watch `docker compose ps` health (`start_period` 180s for GPU STT / 30s for CPU STT), it is
  not hung.

Do NOT add any VM/Proxmox note — `docker compose` on the user's machine is the only supported
deployment. Do NOT touch `## LiveKit self-host networking` (L93+) or `## Serving other LAN
devices` (L110+) beyond the section boundary. The `> Speech-to-text…` callout (L39-44) content
should survive (move it into the new section or keep as a callout) — its facts (port 8000,
baked `.nemo`, resident) are still true for the GPU STT.

## Compose-topology verification — `scripts/test_compose_topology.sh`
Pure host bash, NO Docker daemon needed (uses `docker compose config`, which only parses):
1. `docker compose config` (default) succeeds AND the rendered config shows `nemo-stt-cpu` as a
   service while `nemo-stt` is ABSENT (it's profile-gated). Assert the always-on STT
   (`nemo-stt-cpu`) has NO `devices`/`driver: nvidia` reservation block.
2. `docker compose --profile stt-gpu config` succeeds AND now INCLUDES `nemo-stt` WITH the
   `driver: nvidia` + `capabilities: [gpu]` reservation.
3. `ollama` and `kokoro` always carry the GPU reservation in both renders (spec baseline).
4. Guard: `command -v docker` — if Docker isn't installed in the sandbox, SKIP with a clear
   "deferred to operator" message (still exit 0 so it doesn't block; record as skipped). If
   `docker compose config` is available, run for real.

(Use `docker compose config --format json` + a `python3 -c` JSON assertion if available; else
grep the YAML render. Keep it robust to either.)

## `11-DEPLOY-VERIFY.md` (unsigned operator gate)
Front-matter `status: pending-operator`, `phase: 11-consumer-gpu-deployment-part-e`,
`requirement_ids: [DEPLOY-04, DEPLOY-05]`, a `harness_note` stating the sandbox has no GPU/no
Docker daemon so every real-boot gate is deferred and NONE are marked passed by the executor.
**The verify file must contain NO Proxmox/VM/vfio language** — the gates run on the machine the
user runs `docker compose` on (a consumer host with an RTX 5090), not a VM.
Gates (each with an empty operator result table to sign):
- **G1 — Toolkit proof:** `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04
  nvidia-smi` prints the GPU table inside a container on the consumer host.
- **G2 — Default boot:** `./up.sh` (or `docker compose up -d`) brings the full stack to
  `healthy` (`livekit-server`, `agent`, `ollama`, `nemo-stt-cpu`, `kokoro`, `web`) with NO
  `nemo-stt` (CPU-STT default); end-to-end a browser session transcribes + replies.
- **G3 — GPU STT opt-in:** `docker compose --profile stt-gpu up -d` (+ `STT_FORCE_CPU=0`,
  `STT_HEADROOM_MEASURED=1`) brings `nemo-stt` healthy on the GPU and the agent routes to it
  (cross-reference 10-PLACEMENT-VERIFY G7 co-residency).
- **G4 — Doctor: all-OK host:** `scripts/gpu-doctor.sh` on the real GPU prints `OK: GPU ready`
  + the GPU snippet, exits 0.
- **G5 — Doctor: toolkit-missing:** with the toolkit uninstalled/misconfigured, the doctor
  prints the `nvidia-ctk runtime configure` remedy (the real `could not select device driver`
  string) + the degraded snippet, exits 0, and the stack still comes up CPU-degraded.
- **G6 — Doctor: sub-spec/non-NVIDIA:** on a <16 GB or non-NVIDIA host, the doctor recommends
  `STT_FORCE_CPU=1` + Fast model; `docker compose up` (no profile) comes up usable for STT
  (and flags ollama/kokoro need a GPU).
- **G7 — No-hung-`up`:** first boot's multi-GB build/pull + STT model bake surfaces via
  `docker compose ps` health transitions, not a silent hang.

## Tasks
1. Rewrite `README.md` L33-91 per the spec above; update the `## Quick start` `up` line to
   mention `./up.sh`; preserve LiveKit/LAN sections.
2. Add `scripts/test_compose_topology.sh` (the 4 checks; Docker-optional skip guard).
3. Write `11-DEPLOY-VERIFY.md` (7 unsigned gates, empty result tables).

## Acceptance (sandbox)
- `bash -n scripts/test_compose_topology.sh` clean; the script runs (real or skip) and exits 0.
- If `docker compose` is present: default config has `nemo-stt-cpu` (no GPU reservation) and no
  `nemo-stt`; `--profile stt-gpu` config adds `nemo-stt` with the GPU reservation.
- README renders: `grep -iE 'proxmox|vfio|pcie|layer 1|layer 2|two-layer|inside the vm'
  README.md` returns NOTHING; a single GPU setup section (no VM note); LiveKit/LAN sections
  intact.
- `11-DEPLOY-VERIFY.md` exists with `status: pending-operator` and 7 unsigned gates.

## Frozen / do-not-touch
- `docker-compose.yml` is NOT modified (the topology already matches the spec from P10 —
  this plan only VERIFIES it). If a real gap is found, surface it as a deviation, don't
  silently edit.
- `agent/*`, `stt/*`, `.env*`, `livekit.yaml` unchanged.
