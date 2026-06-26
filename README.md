# Adept — Near-Real-Time Voice Persona Trainer

Voice-first, local-first web app for spoken practice with a configurable AI expert
persona. Self-hosted on a single 16GB-VRAM GPU via Docker Compose. See
[`.planning/PROJECT.md`](.planning/PROJECT.md) for full scope.

## Quick start

```bash
cp .env.example .env          # then set a LIVEKIT_API_SECRET
./up.sh                       # GPU preflight, then builds + boots all services
```

(`./up.sh` runs the GPU doctor then `docker compose up` — see
[GPU setup](#gpu-setup-nvidia-container-toolkit). Plain `docker compose up` works too.)

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

## GPU setup (NVIDIA Container Toolkit)

`docker compose up` on your own machine is the only supported deployment. The three
model containers — `ollama`, `kokoro`, and the GPU STT `nemo-stt` (opt-in, see below)
— need an NVIDIA GPU on that machine. STT also has an off-GPU CPU-ONNX path, so the
**default boots VRAM-safe without the GPU STT** and the only host step is installing
the NVIDIA Container Toolkit.

> **Speech-to-text:** STT runs Nemotron streaming ASR
> (`nvidia/nemotron-speech-streaming-en-0.6b`) behind a local websocket — a growing
> interim transcript while you speak, ~100 ms finalize after end-of-speech, with
> native punctuation/capitalization surfaced as-is. The model is **baked into the
> image at build time** (offline-capable, no first-run download) and stays resident
> for the life of the container. By default this runs **off-GPU** on CPU
> (`nemo-stt-cpu`); the GPU `nemo-stt` (port 8000) is opt-in.

### Install the toolkit (the only host step)

Install the NVIDIA Container Toolkit so Docker can hand the GPU to containers, then
point the Docker runtime at it:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the GPU is reachable from a container (this is the operator gate — record the
output):

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

It must print the GPU table from inside a container. Once it does, `docker compose up`
gives the model services the GPU via the `deploy.resources.reservations.devices`
blocks in `docker-compose.yml`.

### Preflight: `./up.sh`

`./up.sh` runs [`scripts/gpu-doctor.sh`](scripts/gpu-doctor.sh) first — it checks
driver → toolkit → CUDA version → VRAM in order and prints either `OK: GPU ready` or
an exact remedy plus a copy-paste env snippet, then runs `docker compose up`. It is
**advise-only** and never blocks; set `SKIP_DOCTOR=1 ./up.sh` to skip the preflight.

```bash
./up.sh            # preflight, then docker compose up
./up.sh -d         # detached
```

### Default (CPU STT) vs opt-in GPU STT

`docker compose up` (or `./up.sh`) brings up **CPU-ONNX STT** — the VRAM-safe default
(`STT_FORCE_CPU=1`). To run STT on the GPU, opt into the `stt-gpu` profile **and** flip
the placement flags — but only after the co-residency matrix in
[`10-PLACEMENT-VERIFY.md`](.planning/phases/10-vram-aware-stt-placement-part-c/10-PLACEMENT-VERIFY.md)
passes (set `STT_FORCE_CPU=0` + `STT_HEADROOM_MEASURED=1` in `.env`):

```bash
docker compose --profile stt-gpu up
```

On a sub-spec (<16 GB) or non-NVIDIA host, the doctor recommends staying on
`STT_FORCE_CPU=1` + the Fast `OLLAMA_MODEL` and the stack still comes up usable. Note:
`ollama` and `kokoro` always need a working NVIDIA GPU — a fully non-NVIDIA host can
run STT on CPU but not the LLM/TTS (a v1.1 limitation).

### Diagnosing the two common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `could not select device driver "nvidia" with capabilities: [[gpu]]` | NVIDIA Container Toolkit missing / Docker runtime not configured | Run the `nvidia-ctk runtime configure --runtime=docker` step above, restart Docker |
| `capabilities is required` (compose error) | A GPU service is missing `capabilities: [gpu]` in its reservation block | Ensure each model service's `devices` entry includes `capabilities: [gpu]` |

> The first `docker compose up` builds/pulls multi-GB GPU images and bakes the STT
> model — watch `docker compose ps` for health `starting → healthy` (`start_period`
> is 180 s for GPU STT, 30 s for CPU STT). It is **not** hung. This repo does not alter
> host configuration; the toolkit install above is the only operator step, and the
> compose manifest only *reserves* the GPU once it is in place.

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
