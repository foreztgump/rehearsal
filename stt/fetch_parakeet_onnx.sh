#!/usr/bin/env bash
#
# Download + verify the pinned sherpa-onnx Parakeet-tdt-0.6b-v2 int8 bundle.
# Build-time download, offline after.
set -euo pipefail

readonly BUNDLE_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2"
readonly BUNDLE_SHA256="${BUNDLE_SHA256:-157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad}"
readonly REQUIRED_FILES=(encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt)

fail() { echo "fetch_parakeet_onnx: $*" >&2; exit 1; }

verify_bundle() {
  local dir="$1" name
  for name in "${REQUIRED_FILES[@]}"; do
    [ -s "${dir}/${name}" ] || fail "missing/empty ${dir}/${name}"
  done
}

verify_archive_hash() {
  local archive="$1" expected="${2:-${BUNDLE_SHA256}}" actual
  actual="$(sha256sum "${archive}" | awk '{print $1}')"
  [ "${actual}" = "${expected}" ] || fail "sha256 mismatch for ${archive}: ${actual}"
}

main() {
  [ "$#" -eq 1 ] || fail "usage: fetch_parakeet_onnx.sh <target_dir>"
  local target="$1" archive
  mkdir -p "${target}"
  archive="$(mktemp)"
  trap 'rm -f "${archive:-}"' EXIT
  echo "fetch_parakeet_onnx: downloading pinned bundle..." >&2
  curl -fsSL "${BUNDLE_URL}" -o "${archive}"
  verify_archive_hash "${archive}"
  tar -xj -C "${target}" --strip-components=1 -f "${archive}"
  verify_bundle "${target}"
  echo "fetch_parakeet_onnx: OK -> ${target}" >&2
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
