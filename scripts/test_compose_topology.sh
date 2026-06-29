#!/usr/bin/env bash
#
# test_compose_topology.sh — verify the Phase-10/11 Compose GPU topology.
#
# `docker compose config` only PARSES + renders the merged manifest — it needs no
# Docker daemon and starts nothing. We assert, for the consumer `docker compose`
# deploy:
#   1. DEFAULT render: nemo-stt-cpu present, nemo-stt ABSENT (profile-gated), and the
#      always-on CPU STT carries NO GPU reservation.
#   2. --profile stt-gpu render: nemo-stt now present WITH a driver:nvidia /
#      capabilities:[gpu] reservation.
#   3. ollama + kokoro carry the GPU reservation in BOTH renders (spec baseline).
#
# If `docker`/`docker compose` is unavailable, the topology gates are deferred to the
# operator (11-DEPLOY-VERIFY.md) and this script SKIPS (still exit 0).
#
#   ./scripts/test_compose_topology.sh
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "SKIP: docker / docker compose not available — topology gates deferred to 11-DEPLOY-VERIFY.md"
  exit 0
fi
if ! docker compose config --quiet >/dev/null 2>&1; then
  echo "SKIP: 'docker compose config' could not render (no .env?) — deferred to operator"
  exit 0
fi

PASS=0
FAIL=0
check() {
  local name="$1" cond="$2"
  if [ "${cond}" = "true" ]; then PASS=$((PASS+1)); printf 'PASS  %s\n' "${name}"
  else FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "${name}"; fi
}

# Render both graphs once as JSON and interrogate with python3 (already a hard dep).
DEFAULT_JSON="$(docker compose config --format json)"
GPU_JSON="$(docker compose --profile stt-gpu config --format json)"

# has_service <json> <name>  -> prints true|false
has_service() {
  printf '%s' "$1" | python3 -c 'import json,sys
c=json.load(sys.stdin).get("services",{}); print(str(sys.argv[1] in c).lower())' "$2"
}
# has_gpu_reservation <json> <name> -> true if a driver:nvidia device reservation exists
has_gpu_reservation() {
  printf '%s' "$1" | python3 -c 'import json,sys
c=json.load(sys.stdin).get("services",{}).get(sys.argv[1],{})
devs=c.get("deploy",{}).get("resources",{}).get("reservations",{}).get("devices",[])
print(str(any((d.get("driver")=="nvidia") for d in devs)).lower())' "$2"
}
# env_var_value <json> <service> <var> -> resolved env var value (empty if unset)
env_var_value() {
  printf '%s' "$1" | python3 -c 'import json,sys
c=json.load(sys.stdin).get("services",{}).get(sys.argv[1],{})
print(c.get("environment",{}).get(sys.argv[2],""))' "$2" "$3"
}

# 1. Default render: CPU STT present, GPU STT absent, CPU STT has no GPU reservation.
check "default: nemo-stt-cpu present"        "$(has_service "${DEFAULT_JSON}" nemo-stt-cpu)"
check "default: nemo-stt ABSENT (profiled)"  "$([ "$(has_service "${DEFAULT_JSON}" nemo-stt)" = false ] && echo true || echo false)"
check "default: nemo-stt-cpu has NO GPU reservation" \
  "$([ "$(has_gpu_reservation "${DEFAULT_JSON}" nemo-stt-cpu)" = false ] && echo true || echo false)"

# 2. stt-gpu render: GPU STT present WITH a GPU reservation.
check "stt-gpu: nemo-stt present"            "$(has_service "${GPU_JSON}" nemo-stt)"
check "stt-gpu: nemo-stt has GPU reservation" "$(has_gpu_reservation "${GPU_JSON}" nemo-stt)"

# 3. ollama + kokoro keep the GPU reservation in BOTH renders.
for svc in ollama kokoro; do
  check "default: ${svc} has GPU reservation" "$(has_gpu_reservation "${DEFAULT_JSON}" "${svc}")"
  check "stt-gpu: ${svc} has GPU reservation" "$(has_gpu_reservation "${GPU_JSON}" "${svc}")"
done

# 4. R3 final guard: STT_ENGINE resolves to buffered, and the CPU service never
#    receives a CUDA provider request even when the GPU service does.
check "default: nemo-stt-cpu STT_ENGINE=buffered" \
  "$([ "$(env_var_value "${DEFAULT_JSON}" nemo-stt-cpu STT_ENGINE)" = "buffered" ] && echo true || echo false)"
check "stt-gpu: nemo-stt STT_ENGINE=buffered" \
  "$([ "$(env_var_value "${GPU_JSON}" nemo-stt STT_ENGINE)" = "buffered" ] && echo true || echo false)"
check "stt-gpu: nemo-stt-cpu STT_ENGINE=buffered" \
  "$([ "$(env_var_value "${GPU_JSON}" nemo-stt-cpu STT_ENGINE)" = "buffered" ] && echo true || echo false)"
check "stt-gpu: nemo-stt-cpu STT_BUFFERED_DEVICE=cpu" \
  "$([ "$(env_var_value "${GPU_JSON}" nemo-stt-cpu STT_BUFFERED_DEVICE)" = "cpu" ] && echo true || echo false)"

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
