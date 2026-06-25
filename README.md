# Adept — Near-Real-Time Voice Persona Trainer

Voice-first, local-first web app for spoken practice with a configurable AI expert
persona. Self-hosted on a single 16GB-VRAM GPU via Docker Compose. See
[`.planning/PROJECT.md`](.planning/PROJECT.md) for full scope.

## Quick start

```bash
cp .env.example .env          # then edit secrets / LAN_BIND_IP
docker compose up             # builds + boots all six services
```

All published ports bind to `LAN_BIND_IP` (default `127.0.0.1`) — set it to the
VM's LAN IP to serve real LAN devices. Nothing is forwarded to the WAN.

## GPU passthrough

The three model containers (`ollama`, `whisper`, `kokoro`) need the GPU. On a
Proxmox homelab this is a **two-layer passthrough chain** — both layers must work,
in order, before any model container sees the GPU.

### Layer 1 — Proxmox host → VM (PCIe / vfio)

The physical GPU is passed through to the guest VM via PCIe passthrough (vfio).
This is host-level Proxmox configuration done outside this repo. **Verify it before
touching Docker:** inside the VM, this must already succeed and print the GPU table:

```bash
nvidia-smi
```

If `nvidia-smi` fails inside the VM, the GPU is not passed through to the guest yet
— fix the Proxmox vfio passthrough first. Docker cannot bridge a GPU the VM can't
see.

### Layer 2 — VM → container (NVIDIA Container Toolkit)

With `nvidia-smi` working in the VM, install the NVIDIA Container Toolkit so Docker
can hand the GPU to containers, then point the Docker runtime at it:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the container layer end-to-end (this is the operator gate for this task —
record the output):

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

It must print the same GPU table from inside a container. Once it does, both layers
are good and `docker compose up` will give the model services the GPU via the
`deploy.resources.reservations.devices` block in `docker-compose.yml`.

### Diagnosing the two common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `could not select device driver "nvidia" with capabilities: [[gpu]]` | NVIDIA Container Toolkit missing / Docker runtime not configured (Layer 2) | Run the `nvidia-ctk runtime configure --runtime=docker` step above, restart Docker |
| `capabilities is required` (compose error) | A GPU service is missing `capabilities: [gpu]` in its reservation block | Ensure each model service's `devices` entry includes `capabilities: [gpu]` |

> This repo does **not** alter host configuration. Layer 1 (Proxmox vfio) and the
> toolkit install in Layer 2 are operator steps; the compose manifest only *reserves*
> the GPU once both layers are in place.

## LiveKit self-host networking (ICE / firewall)

LiveKit runs fully self-hosted (no LiveKit Cloud, ever). Its config lives in
[`livekit.yaml`](livekit.yaml): the server signals on TCP **7880** (fronted by
Caddy TLS on 7443 for `wss://`), accepts ICE/TCP fallback on **7881**, and muxes
**all** WebRTC media UDP over a single port **7882** (udp mux — one firewall rule
instead of a 10k range).

**Advertised IP (critical):** WebRTC only works if the server advertises a
LAN-reachable IP as its ICE host candidate. We pin it explicitly with
`--node-ip` (sourced from `LIVEKIT_NODE_IP` in `.env`) rather than
`use_external_ip: true`, because the latter reaches out to a public STUN server
to discover its IP — outbound WAN traffic that violates the local-first
invariant. Set `LIVEKIT_NODE_IP` to the VM's LAN IP (e.g. `192.168.1.50`); the
default `127.0.0.1` is local-only and media will not reach other LAN devices.

**Firewall (open inbound on the VM, LAN-only — no WAN forward):**

| Port | Proto | Purpose |
|------|-------|---------|
| 7882 | UDP   | WebRTC media (udp mux) — required for audio to flow |
| 7881 | TCP   | ICE/TCP fallback when UDP is blocked |
| 7443 | TCP   | LiveKit signaling over TLS (Caddy → 7880) |

Open these for LAN sources only. Do **not** port-forward any of them from the
WAN — all traffic stays on the local network.

## HTTPS on the LAN (secure context for the mic)

`navigator.mediaDevices` is only defined in a secure context. The Caddy proxy
terminates a mkcert-minted LAN-trusted TLS cert — see [`certs/README.md`](certs/README.md)
for the CA-trust + cert-mint procedure.
