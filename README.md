# Adept — Near-Real-Time Voice Persona Trainer

Voice-first, local-first web app for spoken practice with a configurable AI expert
persona. Self-hosted on a single 16GB-VRAM GPU via Docker Compose. See
[`.planning/PROJECT.md`](.planning/PROJECT.md) for full scope.

## Quick start

```bash
cp .env.example .env          # then set a LIVEKIT_API_SECRET
docker compose up             # builds + boots all services
```

Then open **http://localhost:3000** in **Chromium/Chrome** and click *Start
talking*. That's it — no certs, no TLS, no browser config.

Why it just works: `localhost` is a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts),
so the microphone and WebRTC are available over plain HTTP — no TLS needed for a
local install. The browser talks to the web shell (`http://localhost:3000`) and
LiveKit (`ws://localhost:7880`) directly.

> **Browser note:** Chromium/Chrome is recommended. Firefox blocks loopback
> (`127.0.0.1`) WebRTC candidates by default, so an on-box Firefox call to a
> localhost server fails ("could not establish pc connection") unless you set
> `media.peerconnection.ice.loopback=true` in `about:config` — a profile-wide
> change we don't recommend. Just use Chromium for the local install.

All published ports bind to `LAN_BIND_IP` (default `127.0.0.1`) — nothing is
forwarded to the WAN. To serve **other LAN devices** (not the same machine), see
[Serving other LAN devices (optional TLS)](#serving-other-lan-devices-optional-tls)
below.

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
[`livekit.yaml`](livekit.yaml): the server signals on TCP **7880**, accepts
ICE/TCP fallback on **7881**, and muxes **all** WebRTC media UDP over a single
port **7882** (udp mux — one firewall rule instead of a 10k range). For a local
install the browser reaches all of this over `localhost`; no firewall changes are
needed.

**Advertised IP:** WebRTC only works if the server advertises a browser-reachable
IP as its ICE host candidate. We pin it explicitly with `--node-ip` (sourced from
`LIVEKIT_NODE_IP` in `.env`) rather than `use_external_ip: true`, because the
latter reaches out to a public STUN server to discover its IP — outbound WAN
traffic that violates the local-first invariant. The default `127.0.0.1` is
correct for a local install; set it to the host's LAN IP only when serving other
LAN devices (next section).

## Serving other LAN devices (optional TLS)

Everything above is for a **local install** (browser on the same machine). To use
the app from **other devices on your LAN** (a phone, a second laptop), those
browsers reach the server over `https://<lan-ip>` — and unlike `localhost`, a raw
LAN IP is **not** a secure context, so the mic (`navigator.mediaDevices`) is
unavailable without TLS. This is the only scenario that needs certificates.

To set it up:

1. Set `LAN_BIND_IP`, `LIVEKIT_NODE_IP`, and `NEXT_PUBLIC_LIVEKIT_URL` in `.env`
   to the host's LAN IP (e.g. `192.168.1.50` / `wss://192.168.1.50:7443`).
2. Mint a LAN-trusted cert and trust the CA on every client device — see
   [`certs/README.md`](certs/README.md).
3. Add a TLS reverse proxy (e.g. Caddy) terminating `:443 → web:3000` and
   `:7443 → livekit-server:7880`, and open inbound LAN-only ports **7882/udp**,
   **7881/tcp**, **7443/tcp** (never port-forward any from the WAN).
