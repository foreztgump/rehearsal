#!/usr/bin/env bash
#
# pull-and-pin.sh — resolve the Adept LLM tag via the fallback ladder and pin it.
#
# Runs the decision ladder from 01-RESEARCH.md against the running ollama
# container, then writes the winning tag to .env as OLLAMA_MODEL so the rest of
# the stack consumes a single resolved tag (no hardcoded gemma tag anywhere
# else). Ladder rungs (first that pulls wins):
#   1. gemma4:e4b-it-q4_K_M   target quant for the tight 16GB floor
#   2. gemma4:e4b             9.6GB full weights + q8_0 KV cache
#   3. gemma3:4b-it-qat       ~3.3GB guaranteed-headroom safe floor
#
# Usage:  ./ollama/pull-and-pin.sh
# Env:    OLLAMA_CONTAINER  (default: ollama) — compose service / container name
#         ENV_FILE          (default: .env)   — file the resolved tag is written to
set -euo pipefail

readonly LADDER=(
  "gemma4:e4b-it-q4_K_M"
  "gemma4:e4b"
  "gemma3:4b-it-qat"
)
readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly ENV_FILE="${ENV_FILE:-.env}"

# Run an ollama CLI command inside the model container.
ollama_exec() {
  docker compose exec -T "${OLLAMA_CONTAINER}" ollama "$@"
}

# Pin the resolved tag into ENV_FILE (replace existing OLLAMA_MODEL= line).
write_resolved_tag() {
  local tag="$1"
  if grep -q '^OLLAMA_MODEL=' "${ENV_FILE}"; then
    sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=${tag}|" "${ENV_FILE}"
  else
    printf 'OLLAMA_MODEL=%s\n' "${tag}" >>"${ENV_FILE}"
  fi
}

resolve_tag() {
  local tag
  for tag in "${LADDER[@]}"; do
    echo "ladder: attempting pull of ${tag}" >&2
    if ollama_exec pull "${tag}" >&2; then
      # Confirm the tag is actually present before pinning it.
      if ollama_exec list | awk '{print $1}' | grep -qx "${tag}"; then
        echo "${tag}"
        return 0
      fi
      echo "ladder: ${tag} pulled but not present in 'ollama list' — next rung" >&2
    else
      echo "ladder: ${tag} did not resolve — next rung" >&2
    fi
  done
  return 1
}

main() {
  local resolved
  if ! resolved="$(resolve_tag)"; then
    echo "FATAL: no ladder rung resolved a usable model tag" >&2
    exit 1
  fi

  write_resolved_tag "${resolved}"
  echo "pinned OLLAMA_MODEL=${resolved} in ${ENV_FILE}"

  # Final confirmation the pinned tag is resident in the container.
  ollama_exec list | grep -F "${resolved}" \
    || { echo "FATAL: pinned tag ${resolved} not in container 'ollama list'" >&2; exit 1; }
}

main "$@"
