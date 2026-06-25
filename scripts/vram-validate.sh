#!/usr/bin/env bash
#
# vram-validate.sh — prove STT+LLM+TTS co-reside under the 16GB VRAM floor and
# that the q8_0 KV cache quant actually engages for the pinned Gemma 4 tag.
#
# Procedure (PERF-02 proof, success criterion 3):
#   1. warm all three models resident (ollama/warmup.py)
#   2. drive a short CONCURRENT load (overlapping LLM completions + 1 whisper +
#      1 kokoro) while sampling nvidia-smi used-VRAM at peak
#   3. assert peak used-VRAM < 16384 MB with headroom
#   4. inspect ollama logs for flash-attn / KV-quant engagement; FAIL LOUDLY if
#      q8_0 silently fell back to F16 (the STATE.md blocker)
#   5. assert exactly the 3 GPU processes (ollama, whisper, kokoro) — NO
#      embedder / vector-store process (PERF-02)
#
# Run from the host against the running stack:  ./scripts/vram-validate.sh
# Env: OLLAMA_CONTAINER (default ollama), VRAM_LIMIT_MB (default 16384),
#      VRAM_HEADROOM_MB (default 1024), CONCURRENT_LLM (default 3).
set -euo pipefail

readonly VRAM_LIMIT_MB="${VRAM_LIMIT_MB:-16384}"
readonly VRAM_HEADROOM_MB="${VRAM_HEADROOM_MB:-1024}"
readonly VRAM_CEILING_MB=$((VRAM_LIMIT_MB - VRAM_HEADROOM_MB))
readonly CONCURRENT_LLM="${CONCURRENT_LLM:-3}"
readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
readonly WHISPER_BASE_URL="${WHISPER_BASE_URL:-http://127.0.0.1:8000}"
readonly KOKORO_BASE_URL="${KOKORO_BASE_URL:-http://127.0.0.1:8880}"
readonly EXPECTED_GPU_PROCS=3
readonly SAMPLE_INTERVAL_SECONDS=0.3
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }

require_tag() {
  [ -n "${OLLAMA_MODEL:-}" ] || {
    # Source .env if OLLAMA_MODEL not already exported.
    [ -f "${REPO_ROOT}/.env" ] && { set -a; . "${REPO_ROOT}/.env"; set +a; }
  }
  [ -n "${OLLAMA_MODEL:-}" ] || fail "OLLAMA_MODEL unset — run ollama/pull-and-pin.sh first"
}

warm_models() {
  echo "warming all three models resident..." >&2
  python3 "${REPO_ROOT}/ollama/warmup.py"
}

# Background a concurrent load while the caller samples VRAM.
drive_load() {
  local index
  for index in $(seq 1 "${CONCURRENT_LLM}"); do
    curl -s "${OLLAMA_BASE_URL}/api/generate" \
      -d "{\"model\":\"${OLLAMA_MODEL}\",\"prompt\":\"Count to twenty slowly.\",\"think\":false,\"options\":{\"num_predict\":128}}" \
      >/dev/null &
  done
  python3 "${REPO_ROOT}/ollama/warmup.py" >/dev/null &
  wait
}

peak_vram_during_load() {
  local peak=0 used
  drive_load &
  local load_pid=$!
  while kill -0 "${load_pid}" 2>/dev/null; do
    used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' ')"
    [ -n "${used}" ] && [ "${used}" -gt "${peak}" ] && peak="${used}"
    sleep "${SAMPLE_INTERVAL_SECONDS}"
  done
  wait "${load_pid}"
  echo "${peak}"
}

assert_kv_quant_engaged() {
  echo "checking ollama logs for flash-attn / q8_0 KV engagement..." >&2
  local logs
  logs="$(docker compose logs "${OLLAMA_CONTAINER}" 2>/dev/null || docker logs "${OLLAMA_CONTAINER}" 2>/dev/null || true)"
  [ -n "${logs}" ] || fail "could not read ollama container logs to verify KV quant"

  # A silent F16 fallback emits a warning that flash-attn/KV-quant was not used.
  if echo "${logs}" | grep -iqE 'flash.?attention.*(disabled|not enabled|unavailable)|kv.?cache.*f16.*fallback|requested .*q8_0.*falling back'; then
    fail "q8_0 KV cache fell back to F16 (gemma4 off the flash-attn allowlist) — 16GB budget broken. Fall back to a smaller num_ctx or the gemma3:4b-it-qat rung."
  fi
  if echo "${logs}" | grep -iqE 'flash.?attention.*enabl|kv.?cache.?type.*q8_0|using q8_0'; then
    echo "q8_0 KV engaged" >&2
    return 0
  fi
  fail "could not confirm q8_0 KV engaged in ollama logs (no positive flash-attn/q8_0 marker found)"
}

assert_three_gpu_procs() {
  local proc_count
  proc_count="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . || true)"
  [ "${proc_count}" -eq "${EXPECTED_GPU_PROCS}" ] \
    || fail "expected ${EXPECTED_GPU_PROCS} GPU processes (ollama, whisper, kokoro), found ${proc_count} — an embedder/vector-store process may be present (PERF-02 violation)"
  echo "GPU processes: ${proc_count} (ollama, whisper, kokoro — no embedder/vector store)" >&2
}

record_state() {
  local peak="$1"
  local state_file="${REPO_ROOT}/.planning/STATE.md"
  [ -f "${state_file}" ] || return 0
  echo "  (peak VRAM ${peak} MB + q8_0 engagement recorded to STATE.md by the operator run)" >&2
}

main() {
  require_tag
  command -v nvidia-smi >/dev/null || fail "nvidia-smi not found"
  warm_models

  assert_kv_quant_engaged
  assert_three_gpu_procs

  local peak
  peak="$(peak_vram_during_load)"
  echo "peak used-VRAM under concurrent load: ${peak} MB (ceiling ${VRAM_CEILING_MB} MB)"
  [ "${peak}" -lt "${VRAM_CEILING_MB}" ] \
    || fail "peak VRAM ${peak} MB >= ceiling ${VRAM_CEILING_MB} MB — does not fit the 16GB floor with headroom"

  record_state "${peak}"
  echo "PASS: STT+LLM+TTS co-resident at ${peak} MB < ${VRAM_LIMIT_MB} MB; q8_0 KV engaged."
}

main "$@"
