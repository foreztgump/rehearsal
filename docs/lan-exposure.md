# LAN exposure — serving Rehearsal to other devices on your LAN

**Status:** planned procedure, validated design, **not yet live-tested**. The
host-side stack (Linux NVIDIA / Windows NVIDIA / Windows AMD) is working; this
document is the runbook for the next step: opening it to a phone or second
laptop on the same LAN without sending anything to the WAN.

This consolidates the pieces that already ship (`certs/README.md`,
`proxy/Caddyfile`) with the missing `docker-compose.proxy.yml` and the per-OS
override `-f` flags. It is the companion to the Windows AMD install field
report ([`windows-amd-install-field-report.md`](windows-amd-install-field-report.md))
and supersedes the one-line pointer in `README.md`.

---

## Why this is not just "change one setting"

A raw LAN IP (e.g. `https://192.168.x.x`) is **not a secure context** in browser
terms, so `navigator.mediaDevices` is `undefined` and the mic **cannot be
requested** — voice practice is impossible over plain HTTP to a LAN IP.
`localhost` *is* a secure context (that is why the same-box install needs no
TLS), but a LAN device is not. So LAN exposure requires **TLS**, which requires
a per-deployment cert + a TLS reverse proxy. There is no shortcut.

The repo's design (`certs/README.md` + `proxy/Caddyfile`) uses **mkcert** to mint
a LAN-only cert and **Caddy** to terminate TLS on `443` (web shell) and `7443`
(LiveKit signaling, `wss`). Nothing leaves the LAN; never forward these to the
WAN.

---

## The three `.env` settings (the actual answer to "what do I change")

All three must change from the `localhost` / `127.0.0.1` defaults to the host's
**LAN IP**:

| Key | Role | Default | LAN value |
| --- | --- | --- | --- |
| `LAN_BIND_IP` | Interface every published port binds to (incl. `7882/udp` WebRTC media) | `127.0.0.1` | host LAN IP |
| `LIVEKIT_NODE_IP` | ICE host candidate LiveKit advertises for WebRTC **media** (audio) | `127.0.0.1` | host LAN IP |
| `NEXT_PUBLIC_LIVEKIT_URL` | WS endpoint the browser connects to — **baked into the web build at build time** | `ws://localhost:7880` | `wss://<lan-ip>:7443` |

**Critical:** because `NEXT_PUBLIC_LIVEKIT_URL` is baked into the Next.js bundle,
changing it requires `docker compose build web` — just restarting the web
container is not enough.

Find the host LAN IP:
```powershell
# Windows
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.InterfaceAlias -notmatch "Loopback|vEthernet|WSL|docker" -and
  $_.IPAddress -notmatch "^169.254" } | Select-Object -First 1).IPAddress
```
```bash
# Linux
ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -v '^127\.\|^169\.254'
```

---

## Prerequisites (one-time, per client device)

Do this on **every device that will use the mic** (the phone/laptop you open the
app from), not just the server:

1. Install mkcert (see https://github.com/FiloSottile/mkcert#installation).
2. `mkcert -install` — adds mkcert's CA to the system/browser trust stores.

For a **phone** or second laptop, you must copy the CA to that device and trust
it manually. Find the CA path with `mkcert -CAROOT` (it prints a directory;
copy `rootCA.pem` from it).

- **iOS:** AirDrop/email `rootCA.pem` to the phone → tap it → Settings →
  Profile Downloaded → install → Settings → General → About → Certificate
  Trust Settings → enable it.
- **Android:** copy `rootCA.pem` → Settings → Security → Encryption &
  Credentials → Install a certificate → CA certificate.
- **Another Windows laptop:** `mkcert -install` on that laptop directly (if it
  has mkcert), or double-click `rootCA.pem` → Install Certificate → Local
  Machine → Trusted Root.

---

## Phase-by-phase runbook

### Phase 1 — Find the host LAN IP + install mkcert (on the host)
Run the IP command above; note the LAN IP and the hostname (`$env:COMPUTERNAME`
on Windows, `hostname` on Linux). Install mkcert on the host and run
`mkcert -install`.

### Phase 2 — Mint the LAN cert
From the repo root, mint a cert covering the LAN IP, hostname, and localhost
(so the host itself keeps working over `https://localhost`):
```bash
mkcert -cert-file certs/lan.pem -key-file certs/lan-key.pem \
  <lan-ip> <lan-hostname> localhost 127.0.0.1
```
This writes `certs/lan.pem` + `certs/lan-key.pem` (gitignored — per-deployment,
never commit or reuse across machines).

### Phase 3 — Update `.env` (the three settings) + rebuild web
Set the three keys above to the host LAN IP (with
`NEXT_PUBLIC_LIVEKIT_URL=wss://<lan-ip>:7443`), then **rebuild the web bundle**:
```bash
docker compose <your -f flags> build web
```
The rebuild is mandatory because `NEXT_PUBLIC_LIVEKIT_URL` is baked in.

### Phase 4 — Trust the mkcert CA on each client device
Follow the per-device steps in the Prerequisites section above. Do this on
every device that will use the mic. Skipping this = the page loads but the mic
never works.

### Phase 5 — Bring up the stack with the proxy override
The `docker-compose.proxy.yml` defines the Caddy service (mounts the Caddyfile +
certs, publishes 443 + 7443). Add it alongside your base + platform overrides:

```bash
# Linux NVIDIA
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d

# Linux AMD (ROCm)
docker compose -f docker-compose.yml -f docker-compose.amd.yml -f docker-compose.proxy.yml up -d
```
```powershell
# Windows AMD — explicit -f flags (the COMPOSE_FILE colon form fails on Windows;
# see the Windows AMD field report, Bug #2)
docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml `
  -f docker-compose.cpu-tts.yml -f docker-compose.proxy.yml up -d
```

### Phase 6 — Open from the LAN device + verify
On the client device (with the CA trusted), open `https://<lan-ip>/`. You should
see the Rehearsal UI and the secure-context line; the mic permission prompt
should appear when you start a session. Speak a phrase and confirm a full
round-trip (STT transcript → LLM response → TTS audio).

If `navigator.mediaDevices` is `undefined`, the page is not in a secure context:
check the cert is trusted on that device and that you loaded the `https://` URL
(not `http://`).

---

## Security scope

- The cert is **per-deployment and LAN-only**. Never forward 443/7443 to the WAN.
- Re-mint per deployment; do not copy cert material between machines.
- Keep firewall rules LAN-only. The design pins `rtc.node_ip` with
  `use_external_ip:false` so LiveKit does **no STUN/WAN egress** — do not change
  that for a LAN-only deploy.

---

## Known gaps (from the Windows AMD field report)

1. **`docker-compose.proxy.yml` was missing** — the `proxy/Caddyfile` header told
   operators to "add a `proxy` service to docker-compose.yml" by hand, with no
   actual service block shipped. The new `docker-compose.proxy.yml` fixes this.
2. **`COMPOSE_FILE` colon separator fails on Windows** — the override headers
   and `INSTALLATION.md` show `COMPOSE_FILE=…:…:…`; on Windows use `;` or, as
   above, explicit `-f` flags.
3. **No live test yet** — this runbook is the design; it needs a real LAN
   bring-up (phone + laptop) to validate before it is called supported. The
   validation matrix below is the bar.

## Validation matrix for "LAN exposure works"

| Axis | Values to cover |
| --- | --- |
| Host OS | Linux NVIDIA; Windows AMD (proxy + AMD + CPU-TTS overrides) |
| Client device | phone (iOS/Android); laptop (Windows/Mac) |
| Secure context | mic permission prompted; `navigator.mediaDevices` defined |
| WebRTC media | full audio round-trip from the LAN device (not just signaling) |
| Cert trust | mkcert CA trusted on the client; no browser cert warning |
| `NEXT_PUBLIC_LIVEKIT_URL` | rebuilt into web bundle; `wss` to 7443 works |
| No WAN egress | `use_external_ip:false` confirmed; `7882/udp` LAN-reachable |
