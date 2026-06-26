#!/usr/bin/env bash
#
# verify-build.sh — per-build LLM-05 gate for a community GGUF response model.
#
# Run at PULL time (NOT agent startup — avoids boot-latency, per CONTEXT decision)
# after ollama/pull-and-pin.sh has made the tag resident. Mirrors the
# scripts/vram-validate.sh operator-gate shape (set -euo pipefail, a fail() helper,
# a main() that runs each check and prints one PASS line). Two checks:
#
#   Check A — chat-template BEHAVIORAL sanity. Heretic/abliterated community builds
#     most commonly fail with a malformed/missing chat template (RESEARCH §6). The
#     original structural scrape (`ollama show --template` for <start_of_turn> etc.)
#     is OBSOLETE on Ollama 0.30: the engine applies the template internally
#     (`--chat-template chatml --no-jinja`), so `show --template` returns a bare
#     `{{ .Prompt }}` for EVERY gemma4 tag incl. official stock — it would false-FAIL
#     all of them (Phase-8 Gate A finding). Check A now probes the BEHAVIOR instead:
#     a deterministic 3-turn /v1 conversation that must recall a fact from an earlier
#     user turn. Broken role-turn rendering => failed recall => FAIL.
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

# Check A — chat-template BEHAVIORAL sanity (multi-turn role tracking over /v1).
#
# WHY BEHAVIORAL, NOT `ollama show --template` (Phase-8 Gate A finding, Ollama
# 0.30.10): the structural scrape this check USED to do is OBSOLETE for gemma4.
# Ollama 0.30 applies the chat template INTERNALLY (the runner launches with
# `--chat-template chatml --no-jinja`), so `ollama show --template` returns a bare
# `{{ .Prompt }}` passthrough with NO `<start_of_turn>`/`<end_of_turn>` markers —
# for EVERY gemma4 tag, INCLUDING the official stock `gemma4:e2b`. The old scrape
# would therefore false-FAIL every gemma4 build. The malformed-template failure
# mode this check defends against (RESEARCH §6) now manifests as BROKEN ROLE
# TRACKING at inference, which a passthrough-template scrape cannot see anyway.
#
# Instead, drive a deterministic 3-turn conversation through the SAME /v1 chat path
# the live agent uses and assert the model recalls a fact stated in an earlier USER
# turn. A build whose role-turn rendering is broken (turns smeared together / roles
# not delimited) cannot reliably attribute and recall that fact.
check_template() {
  local tag="$1" stock="${2:-}"   # stock arg accepted for call-site compat; unused now
  echo "Check A: behavioral role-tracking probe for ${tag} (multi-turn /v1 recall)..." >&2
  [ -n "${stock}" ] && echo "Check A: (note) stock-template diff retired — see header; ${stock} ignored." >&2

  # Distinctive recall token so a generic answer cannot accidentally pass.
  curl -s "${OLLAMA_BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${tag}\",\"messages\":[
          {\"role\":\"system\",\"content\":\"You are a terse assistant. Answer in five words or fewer.\"},
          {\"role\":\"user\",\"content\":\"My access code is ZEBRA-7. Remember it.\"},
          {\"role\":\"assistant\",\"content\":\"Understood.\"},
          {\"role\":\"user\",\"content\":\"What is my access code?\"}
        ],\"max_tokens\":400,\"temperature\":0,\"reasoning_effort\":\"none\"}" \
    | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception as e:
    sys.stderr.write("no JSON from /v1 (model failed to load / serve?): " + str(e) + "\n")
    sys.exit(1)
if "choices" not in d:
    sys.stderr.write("/v1 returned an error, not a completion: " + repr(d)[:200] + "\n")
    sys.exit(1)
msg = d["choices"][0]["message"]
out = (msg.get("content") or "") + " " + (msg.get("reasoning") or "")
if "ZEBRA-7" not in out.upper():
    sys.stderr.write("role tracking FAILED — model did not recall the earlier-turn fact; "
                     "got: " + repr((msg.get("content") or "")[:160]) + "\n")
    sys.exit(1)
' \
    || fail "broken role-turn rendering for ${tag} — multi-turn recall failed (chat template not applied correctly). Fall back to the stock rung."
  echo "Check A: ${tag} role tracking OK (recalled the earlier-turn fact)" >&2
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
