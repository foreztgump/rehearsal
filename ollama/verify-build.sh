#!/usr/bin/env bash
#
# verify-build.sh — per-build LLM-05 gate for a community GGUF response model.
#
# Run at PULL time (NOT agent startup — avoids boot-latency, per CONTEXT decision)
# after ollama/pull-and-pin.sh has made the tag resident. Mirrors the
# scripts/vram-validate.sh operator-gate shape (set -euo pipefail, a fail() helper,
# a main() that runs each check and prints one PASS line). Two checks:
#
#   Check A — chat-template STRUCTURAL sanity. Heretic/abliterated community builds
#     most commonly fail with a malformed/missing chat template (RESEARCH §6). A
#     non-empty-only test would PASS a malformed-but-nonempty template, so assert the
#     Gemma role-turn markers (<start_of_turn>/<end_of_turn> + user/model) are present
#     AND diff the build's template against the stock Gemma fallback rung to surface
#     structural drift.
#   Check B — thinking-off artifact scan. Drive a streamed /api/generate with
#     "think":false on a reasoning-bait prompt; FAIL on ANY reasoning marker in the
#     accumulated stream. A leaked marker would otherwise be SPOKEN ALOUD via TTS.
#
# Production-path equivalence (RESEARCH §3): the live agent suppresses thinking via
# the /v1 OpenAI-compat path with reasoning_effort="none" (agent/main.py), NOT
# /api/generate's "think":false. These are equivalent — both resolve to internal
# Think=false — so this /api/generate scan is an ACCEPTED equivalent mirror of the
# production suppression path, not a divergence.
#
# On a FAIL the operator drops to the stock rung (Fast→gemma4:e2b, Better→gemma4:e4b)
# via pull-and-pin.sh's ladder and re-runs. Operator-gated (real GPU), unsigned until
# run — same posture as the v1.0 VM gates.
#
# Usage:  ./ollama/verify-build.sh <tag> [stock-tag]
#   <tag>        the community build to gate (e.g. evalengine/unbound-e2b:latest)
#   [stock-tag]  optional stock Gemma fallback rung to diff Check A against
#                (e.g. gemma4:e2b / gemma4:e4b)
# Env:    OLLAMA_CONTAINER (default: ollama) — compose service / container name
#         OLLAMA_BASE_URL  (default: http://127.0.0.1:11434) — host-published port
set -euo pipefail

readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Run an ollama CLI command inside the model container (reused from pull-and-pin.sh).
ollama_exec() {
  docker compose exec -T "${OLLAMA_CONTAINER}" ollama "$@"
}

# Check A — chat-template STRUCTURAL sanity (role-turn markers + diff vs stock).
check_template() {
  local tag="$1" stock="$2" tmpl
  echo "Check A: chat-template structural sanity for ${tag}..." >&2
  tmpl="$(ollama_exec show --template "${tag}")" \
    || fail "could not read chat template for ${tag} (ollama show --template failed)"

  # (1) Assert the Gemma role-turn structure is present. A malformed-but-nonempty
  # template is the documented abliterated-build failure mode (RESEARCH §6) — a
  # non-empty-only test would let it pass.
  printf '%s' "${tmpl}" | grep -q '<start_of_turn>' \
    && printf '%s' "${tmpl}" | grep -q '<end_of_turn>' \
    && printf '%s' "${tmpl}" | grep -qE 'user|model' \
    || fail "malformed/missing chat template for ${tag} — no role-turn structure (<start_of_turn>/<end_of_turn>/user/model)"

  # (2) Diff against the stock Gemma template (when a stock rung is supplied) so
  # structural drift is visible. A drift that drops the role-turn structure already
  # failed above; a benign diff is surfaced for operator review.
  if [ -n "${stock}" ]; then
    echo "Check A: diffing ${tag} chat template against stock ${stock}..." >&2
    if diff <(printf '%s' "${tmpl}") <(ollama_exec show --template "${stock}"); then
      echo "Check A: ${tag} chat template identical to stock ${stock}" >&2
    else
      echo "NOTE: ${tag} chat-template diff vs stock ${stock} (review above) — role-turn structure intact" >&2
    fi
  fi
}

# Check B — thinking-off artifact scan over the accumulated streamed output.
check_artifacts() {
  local tag="$1"
  echo "Check B: thinking-off artifact scan for ${tag}..." >&2
  curl -s "${OLLAMA_BASE_URL}/api/generate" \
    -d "{\"model\":\"${tag}\",\"prompt\":\"Think step by step, then answer: what is 17*23?\",\"stream\":true,\"think\":false,\"options\":{\"num_predict\":256}}" \
    | python3 -c '
import sys, json
out = "".join(
    json.loads(line).get("response", "")
    for line in sys.stdin
    if line.strip()
)
markers = ["<think>", "</think>", "<|channel|>", "<|analysis|>",
           "<|message|>", "<|start|>", "<|end|>"]
hit = [m for m in markers if m in out]
if hit:
    sys.stderr.write("artifact markers present: " + ",".join(hit) + "\n")
    sys.exit(1)
' \
    || fail "${tag} leaked reasoning artifacts with think=false — fall back to the stock rung"
}

main() {
  [ $# -ge 1 ] || fail "usage: verify-build.sh <tag> [stock-tag]"
  local tag="$1" stock="${2:-}"

  check_template "${tag}" "${stock}"
  check_artifacts "${tag}"

  echo "PASS: ${tag} template sane + no reasoning-artifact leak (think=false)"
}

main "$@"
