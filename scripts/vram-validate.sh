#!/usr/bin/env bash
#
# vram-validate.sh — prove STT+LLM+TTS co-reside under the 16GB VRAM floor and
# that the q8_0 KV cache quant actually engages for the pinned Gemma 4 tag.
#
# Procedure (PERF-02 proof, success criterion 3):
#   1. warm all three models resident (ollama/warmup.py)
#   2. drive a short CONCURRENT load (overlapping LLM completions + 1 nemo-stt +
#      1 kokoro) while sampling nvidia-smi used-VRAM at peak
#   3. assert peak used-VRAM < 16384 MB with headroom
#   4. inspect ollama logs for flash-attn / KV-quant engagement; FAIL LOUDLY if
#      q8_0 silently fell back to F16 (the STATE.md blocker)
#   5. assert exactly the 3 GPU processes (ollama, nemo-stt, kokoro) — NO
#      embedder / vector-store process (PERF-02)
#
# Run from the host against the running stack:  ./scripts/vram-validate.sh
#
# Phase-4 (04-03) KB-loaded re-check (PERF-02 re-validation): KB load is the
# peak-memory moment (the distilled brief lands in the frozen prefix and inflates
# the resident KV cache). Re-run WITH a brief-sized prefix resident:
#
#   ./scripts/vram-validate.sh --with-kb           # synthetic brief-sized proxy
#   KB_FIXTURE=/path/to/brief.txt ./scripts/vram-validate.sh --with-kb
#
# The synthetic prefix (sized to BRIEF_TOKEN_BUDGET) is the REPEATABLE proxy; the
# AUTHORITATIVE check is a real KB loaded via the agent UI on the VM, then
# nvidia-smi peak sampled (see 04-KB-VERIFY.md Proof D). All four assertions still
# fire in the KB mode; the default (no-flag) path is unchanged.
#
# Env: OLLAMA_CONTAINER (default ollama), VRAM_LIMIT_MB (default 16384),
#      VRAM_HEADROOM_MB (default 1024), CONCURRENT_LLM (default 3),
#      KB_FIXTURE (optional file whose text seeds the brief-sized prefix),
#      BRIEF_TOKEN_BUDGET (default 1500 — couple to agent/kb/distill.py),
#      CHARS_PER_TOKEN (default 4 — couple to agent/kb/parse.py).
set -euo pipefail

readonly VRAM_LIMIT_MB="${VRAM_LIMIT_MB:-16384}"
readonly VRAM_HEADROOM_MB="${VRAM_HEADROOM_MB:-1024}"
readonly VRAM_CEILING_MB=$((VRAM_LIMIT_MB - VRAM_HEADROOM_MB))
readonly CONCURRENT_LLM="${CONCURRENT_LLM:-3}"
readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
readonly NEMO_STT_BASE_URL="${NEMO_STT_BASE_URL:-http://127.0.0.1:8000}"
readonly KOKORO_BASE_URL="${KOKORO_BASE_URL:-http://127.0.0.1:8880}"
readonly EXPECTED_GPU_PROCS=3
readonly SAMPLE_INTERVAL_SECONDS=0.3
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# KB-loaded mode (04-03): off by default. Coupled to BRIEF_TOKEN_BUDGET (distill.py)
# and CHARS_PER_TOKEN (parse.py) so the synthetic prefix matches the real frozen-prefix
# brief footprint. KB_FIXTURE (optional) seeds the prefix from real brief text.
readonly BRIEF_TOKEN_BUDGET="${BRIEF_TOKEN_BUDGET:-1500}"
readonly CHARS_PER_TOKEN="${CHARS_PER_TOKEN:-4}"
KB_MODE=false
KB_FIXTURE="${KB_FIXTURE:-}"

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

# Build a brief-sized prefix (BRIEF_TOKEN_BUDGET × CHARS_PER_TOKEN chars) that
# stands in for the distilled KB brief resident in the frozen prefix. KB_FIXTURE,
# if set, seeds the text from a real brief; otherwise a fixed filler is repeated.
# This is the REPEATABLE proxy for the KB-loaded KV footprint — the authoritative
# check is a real KB loaded via the agent UI (04-KB-VERIFY.md Proof D).
kb_prefix() {
  local target_chars=$((BRIEF_TOKEN_BUDGET * CHARS_PER_TOKEN))
  local seed=""
  if [ -n "${KB_FIXTURE}" ]; then
    [ -f "${KB_FIXTURE}" ] || fail "KB_FIXTURE '${KB_FIXTURE}' not found"
    seed="$(tr -d '\n' < "${KB_FIXTURE}")"
  fi
  [ -n "${seed}" ] || seed="The learner's reference material grounds the coaching session. "
  local out=""
  while [ "${#out}" -lt "${target_chars}" ]; do
    out="${out}${seed}"
  done
  printf '%s' "${out:0:${target_chars}}"
}

# Background a concurrent load while the caller samples VRAM. In KB mode the
# generate prompts carry a brief-sized prefix so the peak sample is taken with the
# KB-loaded KV footprint resident (KB load = peak-memory moment, 04-03 Pattern F).
drive_load() {
  local index prefix=""
  if [ "${KB_MODE}" = "true" ]; then
    prefix="$(kb_prefix) "
  fi
  for index in $(seq 1 "${CONCURRENT_LLM}"); do
    curl -s "${OLLAMA_BASE_URL}/api/generate" \
      --data-raw "$(printf '{"model":"%s","prompt":%s,"think":false,"options":{"num_predict":128}}' \
        "${OLLAMA_MODEL}" "$(json_string "${prefix}Count to twenty slowly.")")" \
      >/dev/null &
  done
  python3 "${REPO_ROOT}/ollama/warmup.py" >/dev/null &
  wait
}

# JSON-encode a string (quotes + escapes) so a large brief prefix is a safe prompt
# value. Uses python3 (already a hard dependency via warmup.py).
json_string() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
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

  # NOTE: grep the captured logs via a here-string (`<<<`), NOT `echo "$logs" | grep -q`.
  # Under `set -o pipefail` with a large log, `grep -q` closes the pipe on first match,
  # the upstream `echo` takes SIGPIPE (exit 141), and pipefail propagates that 141 — so
  # a TRUE match read as a (non-zero) MISS. The here-string removes the pipe entirely.
  # (Latent bug surfaced when the 0.30.x engine bump enlarged the logs — Phase 8.)
  #
  # A silent F16 fallback emits a warning that flash-attn/KV-quant was not used.
  # (Negative-evidence guard: covers both 0.6.x and 0.30.x phrasings.)
  if grep -iqE 'flash.?attention.*(disabled|not enabled|unavailable)|flash_attn[ ]*=[ ]*disabled|kv.?cache.*f16.*fallback|requested .*q8_0.*falling back|cache.?type.*f16' <<< "${logs}"; then
    fail "q8_0 KV cache fell back to F16 (gemma4 off the flash-attn allowlist) — 16GB budget broken. Fall back to a smaller num_ctx or the gemma3:4b-it-qat rung."
  fi
  # Positive evidence. 0.6.x logged 'flash attention enabled' / 'kv cache type q8_0';
  # 0.30.x (Phase-8 engine bump) logs 'flash_attn = enabled', the per-cache
  # 'K (q8_0)' / 'V (q8_0)' buffer lines, and the runner cmd flags
  # '--cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on'. Accept any of them.
  if grep -iqE 'flash.?attention.*enabl|flash_attn[ ]*=[ ]*enabled|kv.?cache.?type.*q8_0|using q8_0|[KV] \(q8_0\)|cache-type-[kv][ ]+q8_0' <<< "${logs}"; then
    echo "q8_0 KV engaged" >&2
    return 0
  fi
  fail "could not confirm q8_0 KV engaged in ollama logs (no positive flash-attn/q8_0 marker found)"
}

assert_three_gpu_procs() {
  local proc_count
  proc_count="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . || true)"
  [ "${proc_count}" -eq "${EXPECTED_GPU_PROCS}" ] \
    || fail "expected ${EXPECTED_GPU_PROCS} GPU processes (ollama, nemo-stt, kokoro), found ${proc_count} — an embedder/vector-store process may be present (PERF-02 violation)"
  echo "GPU processes: ${proc_count} (ollama, nemo-stt, kokoro — no embedder/vector store)" >&2
}

record_state() {
  local peak="$1"
  local state_file="${REPO_ROOT}/.planning/STATE.md"
  [ -f "${state_file}" ] || return 0
  echo "  (peak VRAM ${peak} MB + q8_0 engagement recorded to STATE.md by the operator run)" >&2
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --with-kb) KB_MODE=true ;;
      *) fail "unknown argument: $1 (supported: --with-kb)" ;;
    esac
    shift
  done
  # KB_FIXTURE implies KB mode even without the flag.
  [ -n "${KB_FIXTURE}" ] && KB_MODE=true
  readonly KB_MODE
}

main() {
  parse_args "$@"
  require_tag
  command -v nvidia-smi >/dev/null || fail "nvidia-smi not found"
  if [ "${KB_MODE}" = "true" ]; then
    echo "KB-loaded mode: sampling peak VRAM with a ${BRIEF_TOKEN_BUDGET}-token brief-sized prefix resident (04-03 peak-memory re-check)." >&2
  fi
  warm_models

  assert_kv_quant_engaged
  assert_three_gpu_procs

  local peak
  peak="$(peak_vram_during_load)"
  echo "peak used-VRAM under concurrent load: ${peak} MB (ceiling ${VRAM_CEILING_MB} MB)"
  [ "${peak}" -lt "${VRAM_CEILING_MB}" ] \
    || fail "peak VRAM ${peak} MB >= ceiling ${VRAM_CEILING_MB} MB — does not fit the 16GB floor with headroom"

  record_state "${peak}"
  local mode_note="no-KB"
  [ "${KB_MODE}" = "true" ] && mode_note="KB-loaded"
  echo "PASS (${mode_note}): STT+LLM+TTS co-resident at ${peak} MB < ${VRAM_LIMIT_MB} MB; q8_0 KV engaged."
}

main "$@"
