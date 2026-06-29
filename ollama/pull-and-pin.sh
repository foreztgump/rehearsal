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
#          pins the built model `adept-floor` instead of the raw GGUF.
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
#         ADEPT_DEFAULT_MODEL (default: first of INSTALL_MODELS) — which installed
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
readonly FLOOR_MODEL_NAME="adept-floor"
readonly FLOOR_TEMPLATE_FIX_TAG="hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M"
readonly OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
readonly ENV_FILE="${ENV_FILE:-.env}"
readonly INSTALL_MODELS="${INSTALL_MODELS:-fast,better,floor}"
readonly DEFAULT_CHOICE="${ADEPT_DEFAULT_MODEL:-}"

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

# Walk the named ladder (passed by name via a nameref): pull each rung, confirm it
# is present in `ollama list`, and echo the first that resolves. Same per-rung
# pull→confirm-present discipline as the single-model original.
resolve_tag() {
  local -n ladder="$1"
  local tag
  for tag in "${ladder[@]}"; do
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
  local installed_any=0
  local chosen_default=""
  local default_tag=""
  local first_installed_tag=""   # fallback if the chosen default's ladder fails

  # Determine the chosen default (explicit ADEPT_DEFAULT_MODEL if it's in the
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
      installed_any=1
      [ -z "${first_installed_tag}" ] && first_installed_tag="${floor_tag}"
      [ "${chosen_default}" = "floor" ] && default_tag="${floor_tag}"
    else
      echo "WARN: no FLOOR_LADDER rung resolved — Floor tier unavailable on this host" >&2
    fi
  fi

  if should_install "fast"; then
    local fast_tag
    if fast_tag="$(resolve_tag FAST_LADDER)"; then
      write_resolved_tag OLLAMA_MODEL_FAST "${fast_tag}"
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
    if better_tag="$(resolve_tag BETTER_LADDER)"; then
      write_resolved_tag OLLAMA_MODEL_BETTER "${better_tag}"
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
