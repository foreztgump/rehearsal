#!/usr/bin/env bash
#
# down.sh — clean stop for the Rehearsal stack. Stops and removes the compose services
# (containers + default network), leaving named volumes (pulled models, caches) intact.
#
#   ./down.sh             # stop + remove containers
#   ./down.sh -v          # ALSO remove named volumes (models re-pull next boot)
#   ./down.sh --remove-orphans
#
# Surfaced by install.sh's closing message and the README.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "-v" ]; then
  printf 'This also removes named volumes — pulled models + caches will re-download.\n'
fi

exec docker compose down "$@"
