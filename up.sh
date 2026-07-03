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

# STT placement preflight (advise-only). When .env selects GPU STT
# (STT_FORCE_CPU=0 + STT_HEADROOM_MEASURED=1) the agent connects to the GPU
# `nemo-stt` service — but that service is behind the opt-in `stt-gpu` profile. If
# the profile is not enabled, every STT connect fails with a cryptic
# `Connection error.` and the agent hangs on "Listening to you..." (field report).
# Warn (never block) so the operator adds the profile before it bites.
warn_stt_profile() {
  [ -f .env ] || return 0
  grep -Eq '^[[:space:]]*STT_FORCE_CPU=0([[:space:]]|$)'        .env || return 0
  grep -Eq '^[[:space:]]*STT_HEADROOM_MEASURED=1([[:space:]]|$)' .env || return 0
  case ",${COMPOSE_PROFILES:-}," in *,stt-gpu,*) return 0 ;; esac
  printf '%s\n' "WARN: .env selects GPU STT (STT_FORCE_CPU=0 + STT_HEADROOM_MEASURED=1) but the" \
                "      'stt-gpu' profile is not enabled — the agent will fail to reach nemo-stt" \
                "      ('Connection error.'). Enable it, e.g.:  COMPOSE_PROFILES=stt-gpu ./up.sh $*" ""
}
warn_stt_profile "$@"

exec docker compose up "$@"
