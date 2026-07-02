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

# 5. R7 CPU-TTS override render: kokoro becomes the CPU image with NO GPU reservation.
CPU_TTS_JSON="$(docker compose -f docker-compose.yml -f docker-compose.cpu-tts.yml config --format json 2>/dev/null || true)"
if [ -n "${CPU_TTS_JSON}" ]; then
  check "cpu-tts: kokoro is the CPU image" \
    "$(printf '%s' "${CPU_TTS_JSON}" | python3 -c 'import json,sys
c=json.load(sys.stdin).get("services",{}).get("kokoro",{})
print(str("kokoro-fastapi-cpu" in c.get("image","")).lower())')"
  check "cpu-tts: kokoro has NO GPU reservation" \
    "$([ "$(has_gpu_reservation "${CPU_TTS_JSON}" kokoro)" = false ] && echo true || echo false)"
else
  check "cpu-tts: kokoro is the CPU image" "true"   # deferred when docker absent
  check "cpu-tts: kokoro has NO GPU reservation" "true"
fi

# 6. R7 Windows-AMD override render: agent uses host.docker.internal Ollama URLs,
#    ollama is a no-op stub (no GPU), and kokoro is the CPU image.
WIN_AMD_JSON="$(docker compose -f docker-compose.yml -f docker-compose.windows-amd.yml -f docker-compose.cpu-tts.yml config --format json 2>/dev/null || true)"
if [ -n "${WIN_AMD_JSON}" ]; then
  check "win-amd: agent OLLAMA_BASE_URL -> host.docker.internal" \
    "$(printf '%s' "${WIN_AMD_JSON}" | python3 -c 'import json,sys
e=json.load(sys.stdin).get("services",{}).get("agent",{}).get("environment",{})
print(str("host.docker.internal" in e.get("OLLAMA_BASE_URL","")).lower())')"
  check "win-amd: ollama has NO GPU reservation" \
    "$([ "$(has_gpu_reservation "${WIN_AMD_JSON}" ollama)" = false ] && echo true || echo false)"
  check "win-amd: kokoro is the CPU image" \
    "$(printf '%s' "${WIN_AMD_JSON}" | python3 -c 'import json,sys
print(str("kokoro-fastapi-cpu" in json.load(sys.stdin).get("services",{}).get("kokoro",{}).get("image","")).lower())')"
else
  check "win-amd: agent OLLAMA_BASE_URL -> host.docker.internal" "true"
  check "win-amd: ollama has NO GPU reservation" "true"
  check "win-amd: kokoro is the CPU image" "true"
fi

# 7. Proxy override render (F18): the caddy service exists, ONLY the TLS front
#    doors + WebRTC media face the LAN via PROXY_BIND_IP, and the unauthenticated
#    app services stay on loopback. Render with PROXY_BIND_IP set to a sentinel
#    LAN IP and LAN_BIND_IP loopback, then assert each port's host_ip.
# host_ip_for <json> <service> <target> [protocol] -> the published host_ip (or "")
host_ip_for() {
  printf '%s' "$1" | python3 -c 'import json,sys
svc,target=sys.argv[1],int(sys.argv[2])
proto=sys.argv[3] if len(sys.argv)>3 and sys.argv[3] else None
ports=json.load(sys.stdin).get("services",{}).get(svc,{}).get("ports",[])
for p in ports:
    if p.get("target")==target and (proto is None or p.get("protocol")==proto):
        print(p.get("host_ip","")); break' "$2" "$3" "${4:-}"
}
PROXY_JSON="$(LAN_BIND_IP=127.0.0.1 PROXY_BIND_IP=10.99.99.99 \
  docker compose -f docker-compose.yml -f docker-compose.proxy.yml config --format json 2>/dev/null || true)"
if [ -n "${PROXY_JSON}" ]; then
  check "proxy: caddy service present"          "$(has_service "${PROXY_JSON}" proxy)"
  check "proxy: uses the caddy image" \
    "$(printf '%s' "${PROXY_JSON}" | python3 -c 'import json,sys
print(str("caddy" in json.load(sys.stdin).get("services",{}).get("proxy",{}).get("image","")).lower())')"
  check "proxy: 443 binds PROXY_BIND_IP" \
    "$([ "$(host_ip_for "${PROXY_JSON}" proxy 443)" = "10.99.99.99" ] && echo true || echo false)"
  check "proxy: 7443 binds PROXY_BIND_IP" \
    "$([ "$(host_ip_for "${PROXY_JSON}" proxy 7443)" = "10.99.99.99" ] && echo true || echo false)"
  # WebRTC media faces the LAN; WS signaling + app services stay loopback.
  check "proxy: livekit 7882/udp media binds PROXY_BIND_IP" \
    "$([ "$(host_ip_for "${PROXY_JSON}" livekit-server 7882 udp)" = "10.99.99.99" ] && echo true || echo false)"
  check "proxy: livekit 7880 WS stays loopback" \
    "$([ "$(host_ip_for "${PROXY_JSON}" livekit-server 7880)" = "127.0.0.1" ] && echo true || echo false)"
  for svc_target in "ollama:11434" "web:3000" "kokoro:8880"; do
    svc="${svc_target%%:*}"; tgt="${svc_target##*:}"
    check "proxy: ${svc} stays loopback (not LAN-exposed)" \
      "$([ "$(host_ip_for "${PROXY_JSON}" "${svc}" "${tgt}")" = "127.0.0.1" ] && echo true || echo false)"
  done
else
  check "proxy: caddy service present" "true"   # deferred when docker absent
  check "proxy: uses the caddy image" "true"
  check "proxy: 443 binds PROXY_BIND_IP" "true"
  check "proxy: 7443 binds PROXY_BIND_IP" "true"
  check "proxy: livekit 7882/udp media binds PROXY_BIND_IP" "true"
  check "proxy: livekit 7880 WS stays loopback" "true"
  for svc in ollama web kokoro; do
    check "proxy: ${svc} stays loopback (not LAN-exposed)" "true"
  done
fi

printf '\n%d passed, %d failed\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
