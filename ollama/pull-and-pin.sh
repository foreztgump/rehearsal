#!/usr/bin/env bash
#
# pull-and-pin.sh — resolve BOTH response-model tags via per-model fallback
# ladders and pin them.
#
# Runs each model's decision ladder against the running ollama container, then
# writes the winning tags to .env so the rest of the stack consumes resolved tags
# (no hardcoded gemma tag anywhere else). Three named ladders (first rung that pulls
# AND appears in `ollama list` wins):
#
#   FAST_LADDER  (pins OLLAMA_MODEL_FAST — the picker default, LLM-02):
#     1. evalengine/unbound-e2b:latest   uncensored on-device Gemma 4 E2B finetune
#     2. gemma4:e2b                       stock E2B fallback rung (LLM-05 fallback)
#
#   BETTER_LADDER (pins OLLAMA_MODEL_BETTER — the "more thoughtful" option):
#     1. defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest
#                                         Heretic abliteration of Gemma 4 E4B (~5.3GB)
#     2. gemma4:e4b                       stock E4B fallback rung (LLM-05 fallback)
#
#   FLOOR_LADDER (pins OLLAMA_MODEL_FLOOR — the ~6GB tier's small model, v1.2 R2):
#     1. hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M
#          abliterated Qwen3-4B-Instruct-2507 (~2.5GB) — NON-thinking by construction
#          (no <think> leak), dual-provenance (huihui-ai abliterate + mradermacher GGUF).
#          NB: this GGUF's bundled Ollama template is broken — when it wins, main() grafts
#          the correct Qwen3-2507 template via ollama/Modelfile.floor + `ollama create` and
#          pins the built model `rehearsal-floor` instead of the raw GGUF.
#     2. hf.co/bartowski/mlabonne_Qwen3-1.7B-abliterated-GGUF:Q4_K_M
#          smaller abliterated fallback (~1.1GB; mlabonne+bartowski) for tight 6GB cards
#     3. qwen3.5:2b-q4_K_M
#          first-party non-abliterated LAST RESORT (operator-accepted; content-filtered,
#          so the persona is no longer the sole guardrail on this tier)
#
# OLLAMA_MODEL is ALSO pinned to the resolved Fast tag as a back-compat alias so
# existing readers (warmup.py / vram-validate.sh / kb/distill.py / Modelfile) keep
# working unchanged (RESEARCH §7.3).
#
# Usage:  ./ollama/pull-and-pin.sh
# Env:    OLLAMA_CONTAINER  (default: ollama) — compose service / container name
#         ENV_FILE          (default: .env)   — file the resolved tags are written to
#         INSTALL_MODELS    (default: fast,better,floor) — comma list of which
#                          ladders to run + pin. Only the selected models are pulled.
#         REHEARSAL_DEFAULT_MODEL (default: first of INSTALL_MODELS) — which installed
#                          model the OLLAMA_MODEL back-compat alias points at.
set -euo pipefail

readonly FAST_LADDER=(
  "evalengine/unbound-e2b:latest"
  "gemma4:e2b"
)
readonly BETTER_LADDER=(
  "defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest"
  "gemma4:e4b"
)
# FLOOR_LADDER (pins OLLAMA_MODEL_FLOOR — the ~6GB tier's small model, v1.2 R2). Rungs 1-2
# are ABLITERATED small Qwen3 so the persona stays the sole guardrail across tiers (D8);
# rung 1 (Qwen3-4B-Instruct-2507 abliterated) is non-thinking by construction, which also
# satisfies the hot-path thinking-OFF rule. Rung 3 is the first-party qwen3.5:2b-q4_K_M
# last resort — non-abliterated/content-filtered (operator-accepted). The resolved tag is
# still gated by ollama/verify-build.sh (template + thinking-off artifact scan) at the R2 GPU test.
readonly FLOOR_LADDER=(
  "hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M"
  "hf.co/bartowski/mlabonne_Qwen3-1.7B-abliterated-GGUF:Q4_K_M"
  "qwen3.5:2b-q4_K_M"
)
# When rung 1's GGUF wins, its bundled Ollama chat template is broken, so we graft the correct
# Qwen3-2507 template (ollama/Modelfile.floor) via `ollama create` and pin the BUILT model below
# instead of the raw GGUF (see main()). The 1.7B / qwen3.5 fallback rungs are pinned as-is.
readonly FLOOR_MODEL_NAME="rehearsal-floor"
readonly FLOOR_TEMPLATE_FIX_TAG="hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M"
readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly ENV_FILE="${ENV_FILE:-.env}"
readonly INSTALL_MODELS="${INSTALL_MODELS:-fast,better,floor}"
readonly DEFAULT_CHOICE="${REHEARSAL_DEFAULT_MODEL:-}"
# F20 supply chain. OLLAMA_BASE_URL: host-published ollama port, used to read each
# resolved model's manifest digest from /api/tags (models[].digest — Ollama API) so a
# mutable :latest that silently repoints is DETECTABLE (the recorded sha256 changes).
readonly OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
# The per-build behavioral gate (template + thinking-off scan). Overridable so the
# sandbox test can stub it; a missing script degrades to "gate skipped" (WARN), never
# a hard failure — the gate hardens the default path, it must not brick a valid pull.
readonly VERIFY_BUILD_SCRIPT="${VERIFY_BUILD_SCRIPT:-$(dirname "$0")/verify-build.sh}"

# Resolve which ladders to run from INSTALL_MODELS (comma list, order preserved).
# Unknown keys are ignored (defensive — the installer only writes known keys).
should_install() {
  local key="$1"
  case ",${INSTALL_MODELS}," in
    *",${key},"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Run an ollama CLI command inside the model container.
ollama_exec() {
  docker compose exec -T "${OLLAMA_CONTAINER}" ollama "$@"
}

# Pin the resolved tag into ENV_FILE under the given env KEY (replace existing
# "<KEY>=" line, else append). Parameterized so one writer serves every pinned var.
write_resolved_tag() {
  local key="$1" tag="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${tag}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${tag}" >>"${ENV_FILE}"
  fi
}

# Record the manifest digest of a resolved tag under "<KEY>_DIGEST=" in ENV_FILE
# (F20). Reads models[].digest from the ollama /api/tags list (Ollama API) via the
# host-published port and normalizes to a sha256:-prefixed value. A mutable :latest
# tag alone is not a pin — this sha256 is what makes an upstream repoint detectable
# (the recorded digest changes on the next install). Best-effort: if the digest can't
# be read (older ollama / curl unavailable) it WARNs and skips — never blocks a pull.
record_digest() {
  local key="$1" tag="$2" digest
  digest="$(curl -s "${OLLAMA_BASE_URL}/api/tags" 2>/dev/null | python3 -c '
import sys, json
tag = sys.argv[1]
try:
    models = json.load(sys.stdin).get("models", [])
except Exception:
    sys.exit(0)
for m in models:
    if m.get("name") == tag or m.get("model") == tag:
        d = m.get("digest") or ""
        if d:
            print(d if d.startswith("sha256:") else "sha256:" + d)
        break
' "${tag}" 2>/dev/null)" || true
  if [ -n "${digest}" ]; then
    write_resolved_tag "${key}_DIGEST" "${digest}"
    echo "recorded ${key}_DIGEST=${digest} in ${ENV_FILE}" >&2
  else
    echo "WARN: could not read manifest digest for ${tag} — ${key}_DIGEST left unset" >&2
  fi
}

# Run the per-build behavioral gate (verify-build.sh) on a COMMUNITY rung before it is
# accepted (F20). Returns 0 to ACCEPT the tag, non-zero to REJECT (caller advances to
# the next ladder rung — the stock fallback). A missing gate script is a SKIP (accept
# with a WARN) so the gate hardens the default path without bricking a valid pull.
# NB: the FLOOR ladder deliberately does NOT call this — its rung-1 GGUF ships a broken
# template ON PURPOSE and is only sane AFTER the Modelfile graft, so gating it pre-graft
# would wrongly reject every floor install (see main()).
verify_or_skip() {
  local tag="$1" stock="${2:-}"
  if [ ! -x "${VERIFY_BUILD_SCRIPT}" ]; then
    echo "verify: ${VERIFY_BUILD_SCRIPT} not executable — skipping behavioral gate for ${tag}" >&2
    return 0
  fi
  echo "verify: gating ${tag} via $(basename "${VERIFY_BUILD_SCRIPT}")..." >&2
  if "${VERIFY_BUILD_SCRIPT}" "${tag}" "${stock}"; then
    return 0
  fi
  echo "verify: ${tag} FAILED the behavioral gate — advancing to the next (stock) rung" >&2
  return 1
}

# Walk the named ladder (passed by name via a nameref): pull each rung, confirm it
# is present in `ollama list`, and echo the first that resolves. Same per-rung
# pull→confirm-present discipline as the single-model original.
#
# F20: when "$2" == verify, each rung is additionally run through verify_or_skip AFTER
# it is confirmed present; a gate FAIL advances to the next rung (the stock fallback),
# exactly as verify-build.sh's header prescribes. The LAST rung is treated as the
# operator-accepted stock floor and is NOT gated (it is the fallback of last resort).
resolve_tag() {
  local -n ladder="$1"
  local do_verify="${2:-}"
  local tag idx=0 last=$(( ${#ladder[@]} - 1 ))
  for tag in "${ladder[@]}"; do
    echo "ladder: attempting pull of ${tag}" >&2
    if ollama_exec pull "${tag}" >&2; then
      # Confirm the tag is actually present before pinning it.
      if ollama_exec list | awk '{print $1}' | grep -qx "${tag}"; then
        if [ "${do_verify}" = "verify" ] && [ "${idx}" -lt "${last}" ]; then
          # Gate community rungs; hand verify-build the next rung as the stock diff.
          if ! verify_or_skip "${tag}" "${ladder[$((idx + 1))]}"; then
            idx=$((idx + 1)); continue
          fi
        fi
        echo "${tag}"
        return 0
      fi
      echo "ladder: ${tag} pulled but not present in 'ollama list' — next rung" >&2
    else
      echo "ladder: ${tag} did not resolve — next rung" >&2
    fi
    idx=$((idx + 1))
  done
  return 1
}

main() {
  local installed_any=0
  local chosen_default=""
  local default_tag=""
  local first_installed_tag=""   # fallback if the chosen default's ladder fails

  # Determine the chosen default (explicit REHEARSAL_DEFAULT_MODEL if it's in the
  # install set, else the first model in INSTALL_MODELS).
  if [ -n "${DEFAULT_CHOICE}" ] && should_install "${DEFAULT_CHOICE}"; then
    chosen_default="${DEFAULT_CHOICE}"
  else
    chosen_default="${INSTALL_MODELS%%,*}"
  fi

  if should_install "floor"; then
    local floor_tag=""
    if floor_tag="$(resolve_tag FLOOR_LADDER)"; then
      if [ "${floor_tag}" = "${FLOOR_TEMPLATE_FIX_TAG}" ]; then
        # Rung-1 GGUF won but its bundled template is broken — graft the correct
        # Qwen3-2507 template (ollama/Modelfile.floor) and pin the BUILT model.
        echo "floor: grafting template via ollama/Modelfile.floor -> ${FLOOR_MODEL_NAME}" >&2
        docker compose cp ollama/Modelfile.floor "${OLLAMA_CONTAINER}:/tmp/Modelfile.floor"
        ollama_exec create "${FLOOR_MODEL_NAME}" -f /tmp/Modelfile.floor
        write_resolved_tag OLLAMA_MODEL_FLOOR "${FLOOR_MODEL_NAME}"
        echo "pinned OLLAMA_MODEL_FLOOR=${FLOOR_MODEL_NAME} (built from ${floor_tag}) in ${ENV_FILE}"
        floor_tag="${FLOOR_MODEL_NAME}"
      else
        write_resolved_tag OLLAMA_MODEL_FLOOR "${floor_tag}"
        echo "pinned OLLAMA_MODEL_FLOOR=${floor_tag} in ${ENV_FILE}"
      fi
      record_digest OLLAMA_MODEL_FLOOR "${floor_tag}"
      installed_any=1
      [ -z "${first_installed_tag}" ] && first_installed_tag="${floor_tag}"
      [ "${chosen_default}" = "floor" ] && default_tag="${floor_tag}"
    else
      echo "WARN: no FLOOR_LADDER rung resolved — Floor tier unavailable on this host" >&2
    fi
  fi

  if should_install "fast"; then
    local fast_tag
    if fast_tag="$(resolve_tag FAST_LADDER verify)"; then
      write_resolved_tag OLLAMA_MODEL_FAST "${fast_tag}"
      record_digest OLLAMA_MODEL_FAST "${fast_tag}"
      installed_any=1
      [ -z "${first_installed_tag}" ] && first_installed_tag="${fast_tag}"
      [ "${chosen_default}" = "fast" ] && default_tag="${fast_tag}"
      ollama_exec list | grep -F "${fast_tag}" \
        || { echo "FATAL: pinned tag ${fast_tag} not in container 'ollama list'" >&2; exit 1; }
    else
      echo "WARN: no FAST_LADDER rung resolved — Fast tier unavailable on this host" >&2
    fi
  fi

  if should_install "better"; then
    local better_tag
    if better_tag="$(resolve_tag BETTER_LADDER verify)"; then
      write_resolved_tag OLLAMA_MODEL_BETTER "${better_tag}"
      record_digest OLLAMA_MODEL_BETTER "${better_tag}"
      installed_any=1
      [ -z "${first_installed_tag}" ] && first_installed_tag="${better_tag}"
      [ "${chosen_default}" = "better" ] && default_tag="${better_tag}"
      ollama_exec list | grep -F "${better_tag}" \
        || { echo "FATAL: pinned tag ${better_tag} not in container 'ollama list'" >&2; exit 1; }
    else
      echo "WARN: no BETTER_LADDER rung resolved — Better tier unavailable on this host" >&2
    fi
  fi

  [ "${installed_any}" -eq 1 ] || { echo "FATAL: INSTALL_MODELS selected no valid ladders (all tiers failed to pull)" >&2; exit 1; }

  # If the chosen default's ladder failed, fall back to the first installed model
  # (with a WARN) so a partial install set still boots — never leave .env with a
  # default whose tag is unset (the floor-path landmine).
  if [ -z "${default_tag}" ]; then
    echo "WARN: chosen default ${chosen_default} did not install — falling back to the first installed model" >&2
    default_tag="${first_installed_tag}"
  fi

  # Back-compat alias: point OLLAMA_MODEL at the chosen default's tag (NOT always Fast).
  write_resolved_tag OLLAMA_MODEL "${default_tag}"
  echo "pinned installed set=${INSTALL_MODELS}; OLLAMA_MODEL=${default_tag} in ${ENV_FILE}"
}

main "$@"
