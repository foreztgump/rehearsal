# LAN TLS certificates (mkcert) — OPTIONAL

**You do not need any of this for a local install.** `localhost` is already a
secure context, so the mic and WebRTC work over plain `http://localhost:3000` with
no certificates. See the Quick start in the top-level [`README.md`](../README.md).

This directory only matters when you want to serve the app to **other devices on
your LAN** (a phone, a second laptop). Those browsers reach the server over
`https://192.168.x.x`, and a raw LAN IP is **not** a secure context — so
`navigator.mediaDevices === undefined` and the mic can never be requested without
TLS. The steps below provide that secure context via a per-deployment, LAN-only
mkcert cert fronted by a TLS reverse proxy (see [`../proxy/Caddyfile`](../proxy/Caddyfile)).

The cert/key are **gitignored** (`certs/*.pem`, `certs/*-key.pem`) — they are
per-deployment and must never be committed or reused across deployments (a leaked
LAN cert is a MITM risk).

## One-time: trust the local CA on every client device

Install mkcert, then trust its CA. **Do this on every device that will use the
mic** (the laptop/phone you open the app from) — not just the server:

```bash
# Install mkcert (see https://github.com/FiloSottile/mkcert#installation)
mkcert -install
```

`mkcert -install` adds mkcert's local CA to the system/browser trust stores. On a
phone or a second laptop you must copy the CA (`mkcert -CAROOT` shows its path) to
that device and trust it manually.

## Mint the LAN cert

From the repo root, mint a cert covering the VM's LAN IP and hostname (plus
localhost for on-box testing). Replace `<lan-ip>` / `<lan-hostname>` with this
deployment's values:

```bash
mkcert -cert-file certs/lan.pem -key-file certs/lan-key.pem \
  <lan-ip> <lan-hostname> localhost 127.0.0.1
```

This writes `certs/lan.pem` and `certs/lan-key.pem`, which the proxy mounts
read-only at `/certs` (see `proxy/Caddyfile`).

## Bring it up and verify

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d proxy web
```

Then, on a LAN device **with the CA trusted**, open:

```
https://<lan-ip>/
```

You should see "Rehearsal — stack online" and the green line
**`secure context: mediaDevices defined`**. If it reads `undefined`, the page is
not in a secure context — check the cert is trusted on that device and that you
loaded the `https://` URL (not `http://`).

## Scope / security

- The cert is **per-deployment and LAN-only**. Never forward 443/7443 to the WAN.
- Re-mint per deployment; do not copy cert material between machines.
- `proxy/Caddyfile` also exposes a TLS vhost on `:7443` that fronts the LiveKit WS
  endpoint, so `wss://<lan-host>:7443` is ready for Phase 2.
