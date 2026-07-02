#!/usr/bin/env bash
#
# test_pull_and_pin.sh — sandbox checks for ollama/pull-and-pin.sh (F20 supply chain).
#
# pull-and-pin needs a live ollama container + real model pulls, so we run it under an
# ISOLATED PATH with STUBS for `docker` (fakes `compose exec ollama ollama …` +
# `compose cp`), `curl` (fakes /api/tags with controllable digests), and a stub
# verify-build.sh — same isolation discipline as test_install.sh. No real Docker,
# no real GPU, no network.
#
#   ./scripts/test_pull_and_pin.sh
#
# Covers the F20 additions:
#   1. each resolved tier records its manifest digest (<KEY>_DIGEST=sha256:…) from
#      /api/tags into ENV_FILE — the mutable :latest tag alone is no longer the pin.
#   2. verify-build.sh gates the FAST/BETTER community rungs; a FAIL falls through the
#      existing ladder to the stock rung (gemma4:e2b / gemma4:e4b).
#   3. the FLOOR path is UNCHANGED — its rung-1 GGUF (broken template by design) is
#      NOT verify-gated pre-graft, so the Modelfile graft → rehearsal-floor still wins.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf 'PASS: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }

bash -n ollama/pull-and-pin.sh && ok "pull-and-pin.sh parses" || bad "pull-and-pin.sh syntax"

readonly -a NEEDED_TOOLS=(dirname grep sed awk head cat env bash mkdir chmod tr sort printf)
build_path() {
  local dir="$1" tool path
  mkdir -p "$dir"
  for tool in "${NEEDED_TOOLS[@]}"; do
    path="$(command -v "$tool")" && ln -sf "$path" "$dir/$tool"
  done
  # python3 is used by pull-and-pin (digest extraction) and by the curl stub.
  path="$(command -v python3)" && ln -sf "$path" "$dir/python3"
}
make_shim() { printf '#!/usr/bin/env bash\n%s\n' "$3" > "$1/$2"; chmod +x "$1/$2"; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# A docker stub that fakes `docker compose exec -T ollama ollama <cmd>` + `compose cp`.
# PULL_FAIL_TAGS (space list) → those tags fail `pull`. Present tags come from
# LIST_TAGS. `create` always succeeds and appends the built model to a marker file.
docker_stub_body() {
  cat <<'STUB'
# args look like: compose exec -T ollama ollama <cmd> ... | compose cp SRC DST | compose up ...
argv=("$@")
# find the ollama subcommand (token after the service name "ollama")
sub=""; i=0
for a in "$@"; do
  if [ "$a" = "ollama" ] && [ -z "$sub" ] && [ "$i" -gt 0 ]; then
    # the token AFTER this "ollama" (the container/service) is the CLI verb…
    :
  fi
  i=$((i+1))
done
# Simpler: the CLI verb is the 5th arg for `compose exec -T ollama ollama <verb>`.
if [ "${1:-}" = "compose" ] && [ "${2:-}" = "exec" ]; then
  verb="${6:-}"; tag="${7:-}"
  case "$verb" in
    pull)
      for f in $PULL_FAIL_TAGS; do [ "$tag" = "$f" ] && { echo "pull failed: $tag" >&2; exit 1; }; done
      echo "pulled $tag" >&2; exit 0 ;;
    list)
      printf 'NAME\tID\tSIZE\tMODIFIED\n'
      for t in $LIST_TAGS; do printf '%s\tabc123\t1GB\tnow\n' "$t"; done
      exit 0 ;;
    create)
      echo "$tag" >> "$CREATE_LOG"; exit 0 ;;
    *) exit 0 ;;
  esac
fi
if [ "${1:-}" = "compose" ] && [ "${2:-}" = "cp" ]; then exit 0; fi
exit 0
STUB
}

# curl stub → fakes GET /api/tags returning a models[] array with a digest per LIST_TAGS.
curl_stub_body() {
  cat <<'STUB'
url=""
for a in "$@"; do case "$a" in http*/api/tags) url="$a";; esac; done
if [ -n "$url" ]; then
  python3 - "$LIST_TAGS" <<'PY'
import json, sys
tags = sys.argv[1].split()
models = [{"name": t, "model": t, "digest": "deadbeef%02d" % (i % 100) + "cafe"} for i, t in enumerate(tags)]
print(json.dumps({"models": models}))
PY
  exit 0
fi
exit 0
STUB
}

run_pin() {  # <bindir> <env_file> extra KEY=VAL env…
  local bindir="$1" envfile="$2"; shift 2
  ( cd "$REPO" && env -i PATH="$bindir" ENV_FILE="$envfile" \
      OLLAMA_BASE_URL="http://127.0.0.1:11434" \
      VERIFY_BUILD_SCRIPT="$WORK/verify-stub.sh" \
      "$@" bash ollama/pull-and-pin.sh >"$WORK/pin.out" 2>&1 )
}

# ---- Scenario 1: FAST happy path records a digest --------------------------
BIN1="$WORK/bin1"; build_path "$BIN1"
make_shim "$BIN1" docker "$(docker_stub_body)"
make_shim "$BIN1" curl "$(curl_stub_body)"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/verify-stub.sh"; chmod +x "$WORK/verify-stub.sh"
ENV1="$WORK/env1"; : > "$ENV1"
if run_pin "$BIN1" "$ENV1" \
      INSTALL_MODELS="fast" \
      PULL_FAIL_TAGS="" \
      LIST_TAGS="evalengine/unbound-e2b:latest" \
      CREATE_LOG="$WORK/create1.log" \
   && grep -q '^OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest$' "$ENV1" \
   && grep -q '^OLLAMA_MODEL_FAST_DIGEST=sha256:' "$ENV1"; then
  ok "Scenario 1: FAST resolved tag + manifest digest recorded to .env"
else
  bad "Scenario 1: digest not recorded"
  printf -- '--- env1 ---\n%s\n--- out ---\n%s\n' "$(cat "$ENV1")" "$(cat "$WORK/pin.out")"
fi

# ---- Scenario 2: verify FAIL on community rung falls to the stock rung ------
BIN2="$WORK/bin2"; build_path "$BIN2"
make_shim "$BIN2" docker "$(docker_stub_body)"
make_shim "$BIN2" curl "$(curl_stub_body)"
# verify stub FAILS for the community rung1, PASSES for the stock rung.
cat > "$WORK/verify-stub.sh" <<'VS'
#!/usr/bin/env bash
case "$1" in
  evalengine/*|defyma85/*) echo "FAIL: $1" >&2; exit 1 ;;
  *) echo "PASS: $1"; exit 0 ;;
esac
VS
chmod +x "$WORK/verify-stub.sh"
ENV2="$WORK/env2"; : > "$ENV2"
if run_pin "$BIN2" "$ENV2" \
      INSTALL_MODELS="fast" \
      PULL_FAIL_TAGS="" \
      LIST_TAGS="evalengine/unbound-e2b:latest gemma4:e2b" \
      CREATE_LOG="$WORK/create2.log" \
   && grep -q '^OLLAMA_MODEL_FAST=gemma4:e2b$' "$ENV2"; then
  ok "Scenario 2: verify-build FAIL on the community rung falls back to the stock rung"
else
  bad "Scenario 2: no stock fallback on verify FAIL"
  printf -- '--- env2 ---\n%s\n--- out ---\n%s\n' "$(cat "$ENV2")" "$(cat "$WORK/pin.out")"
fi

# ---- Scenario 3: FLOOR path is UNCHANGED (rung1 GGUF grafted, not verify-gated) --
BIN3="$WORK/bin3"; build_path "$BIN3"
make_shim "$BIN3" docker "$(docker_stub_body)"
make_shim "$BIN3" curl "$(curl_stub_body)"
# verify stub would FAIL the floor GGUF if it were (wrongly) gated pre-graft.
cat > "$WORK/verify-stub.sh" <<'VS'
#!/usr/bin/env bash
case "$1" in
  hf.co/*) echo "FAIL: $1 (broken template pre-graft)" >&2; exit 1 ;;
  *) echo "PASS: $1"; exit 0 ;;
esac
VS
chmod +x "$WORK/verify-stub.sh"
ENV3="$WORK/env3"; : > "$ENV3"
FLOOR_GGUF="hf.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF:Q4_K_M"
if run_pin "$BIN3" "$ENV3" \
      INSTALL_MODELS="floor" \
      PULL_FAIL_TAGS="" \
      LIST_TAGS="$FLOOR_GGUF rehearsal-floor" \
      CREATE_LOG="$WORK/create3.log" \
   && grep -q '^OLLAMA_MODEL_FLOOR=rehearsal-floor$' "$ENV3" \
   && [ -f "$WORK/create3.log" ] && grep -q 'rehearsal-floor' "$WORK/create3.log"; then
  ok "Scenario 3: FLOOR rung1 GGUF still grafted to rehearsal-floor (not verify-gated pre-graft)"
else
  bad "Scenario 3: floor graft path regressed"
  printf -- '--- env3 ---\n%s\n--- out ---\n%s\n' "$(cat "$ENV3")" "$(cat "$WORK/pin.out")"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
