#!/usr/bin/env bash
#
# up.sh — the doctor-wrapped entrypoint for the consumer `docker compose` deploy.
#
# Runs scripts/gpu-doctor.sh (preflight GPU/driver/toolkit/VRAM checks, advise-only)
# and then hands off to `docker compose up`, passing through any args you give it
# (e.g. -d, a service name). Passthrough args land AFTER the hardcoded `up`
# subcommand below, so root-level flags like `--profile` can't be passed here —
# opt into a profile via the COMPOSE_PROFILES env var, which Compose reads natively.
# The doctor never blocks — it always exits 0 — so `up` always proceeds; you've just
# SEEN the advice first.
#
#   ./up.sh                              # preflight, then docker compose up
#   ./up.sh -d                           # detached
#   COMPOSE_PROFILES=stt-gpu ./up.sh -d  # opt into the stt-gpu profile
#   SKIP_DOCTOR=1 ./up.sh -d             # skip the preflight (CI / repeat boots)
set -euo pipefail

cd "$(dirname "$0")"

if [ "${SKIP_DOCTOR:-0}" != "1" ]; then
  ./scripts/gpu-doctor.sh
  printf '\n'
fi

exec docker compose up "$@"
