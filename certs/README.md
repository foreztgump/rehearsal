# LAN TLS certificates (mkcert)

`navigator.mediaDevices` — and therefore the microphone — is only available in a
**secure context** (HTTPS or `localhost`). Serving the web UI over plain
`http://192.168.x.x` leaves `navigator.mediaDevices === undefined` and the mic can
never be requested. This directory holds the per-deployment, LAN-only TLS material
the Caddy proxy uses to provide that secure context.

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
docker compose up proxy web
```

Then, on a LAN device **with the CA trusted**, open:

```
https://<lan-ip>/
```

You should see "Adept — stack online" and the green line
**`secure context: mediaDevices defined`**. If it reads `undefined`, the page is
not in a secure context — check the cert is trusted on that device and that you
loaded the `https://` URL (not `http://`).

## Scope / security

- The cert is **per-deployment and LAN-only**. Never forward 443/7443 to the WAN.
- Re-mint per deployment; do not copy cert material between machines.
- `proxy/Caddyfile` also exposes a TLS vhost on `:7443` that fronts the LiveKit WS
  endpoint, so `wss://<lan-host>:7443` is ready for Phase 2.
