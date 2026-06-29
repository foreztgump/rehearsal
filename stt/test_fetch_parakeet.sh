#!/usr/bin/env bash
# Sandbox check for fetch_parakeet_onnx.sh verify_bundle (no network/download).
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/fetch_parakeet_onnx.sh"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

for file_name in encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt; do
  printf 'x\n' > "${tmp_dir}/${file_name}"
done
verify_bundle "${tmp_dir}"

rm "${tmp_dir}/tokens.txt"
if ( verify_bundle "${tmp_dir}" ) 2>/dev/null; then
  echo "FAIL: missing tokens.txt must fail verify_bundle" >&2
  exit 1
fi

hash_fixture="${tmp_dir}/hash-fixture"
printf 'hash me\n' > "${hash_fixture}"
expected_hash="$(sha256sum "${hash_fixture}" | awk '{print $1}')"
verify_archive_hash "${hash_fixture}" "${expected_hash}"
if ( verify_archive_hash "${hash_fixture}" "not-the-hash" ) 2>/dev/null; then
  echo "FAIL: mismatched archive hash must fail verify_archive_hash" >&2
  exit 1
fi

echo "test_fetch_parakeet OK (verify_bundle present + missing-file)" >&2

archive_dir="${tmp_dir}/archive-src/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
mkdir -p "${archive_dir}"
for file_name in encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt; do
  printf 'x\n' > "${archive_dir}/${file_name}"
done
test_archive="${tmp_dir}/bundle.tar.bz2"
tar -cjf "${test_archive}" -C "${tmp_dir}/archive-src" sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8
test_hash="$(sha256sum "${test_archive}" | awk '{print $1}')"
fake_bin="${tmp_dir}/bin"
mkdir -p "${fake_bin}"
cat > "${fake_bin}/curl" <<EOF
#!/usr/bin/env bash
cp "${test_archive}" "\${@: -1}"
EOF
chmod +x "${fake_bin}/curl"
target_dir="${tmp_dir}/full-run"
env BUNDLE_SHA256="${test_hash}" PATH="${fake_bin}:${PATH}" bash "${SCRIPT_DIR}/fetch_parakeet_onnx.sh" "${target_dir}"
verify_bundle "${target_dir}"
echo "test_fetch_parakeet OK (full script path + exit trap)" >&2
