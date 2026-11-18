#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Build an EC2 runtime release archive from an allowlist of tracked files.

Usage:
  scripts/build-runtime-release.sh --output <archive.tar.gz> [--ref <git-ref>]

Options:
  --output  Destination .tar.gz path (required)
  --ref     Git commit, tag, or branch to archive (default: HEAD)
  --help    Show this help
EOF
}

output=""
ref="HEAD"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { echo "error: --output requires a value" >&2; exit 2; }
      output="$2"
      shift 2
      ;;
    --ref)
      [[ $# -ge 2 ]] || { echo "error: --ref requires a value" >&2; exit 2; }
      ref="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$output" ]] || { echo "error: --output is required" >&2; usage >&2; exit 2; }

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
resolved_ref="$(git rev-parse --verify "${ref}^{commit}")"

required_paths=(
  main.py
  requirements.txt
  config
  proto
  src
)

runtime_paths=(
  LICENSE
  main.py
  pyproject.toml
  requirements.txt
  audio
  config
  proto
  src
)

required_generated_paths=(
  src/generated/byova_common_pb2.py
  src/generated/byova_common_pb2_grpc.py
  src/generated/health_pb2.py
  src/generated/health_pb2_grpc.py
  src/generated/voicevirtualagent_pb2.py
  src/generated/voicevirtualagent_pb2_grpc.py
)

for path in "${required_paths[@]}"; do
  if ! git cat-file -e "${resolved_ref}:${path}" 2>/dev/null; then
    echo "error: required runtime path is missing at ${ref}: ${path}" >&2
    exit 1
  fi
done

archive_paths=()
for path in "${runtime_paths[@]}"; do
  if git cat-file -e "${resolved_ref}:${path}" 2>/dev/null; then
    archive_paths+=("$path")
  fi
done

mkdir -p "$(dirname "$output")"
output_dir="$(cd "$(dirname "$output")" && pwd -P)"
output_path="${output_dir}/$(basename "$output")"
temporary_archive="$(mktemp "${TMPDIR:-/tmp}/byova-runtime-release.XXXXXX")"
staging_root="$(mktemp -d "${TMPDIR:-/tmp}/byova-runtime-staging.XXXXXX")"

cleanup() {
  rm -f "$temporary_archive"
  rm -rf "$staging_root"
}
trap cleanup EXIT

git archive --format=tar "$resolved_ref" -- "${archive_paths[@]}" \
  | tar -xf - -C "$staging_root"

protoc_python=""
protoc_candidates=()
if [[ -n "${PYTHON:-}" ]]; then
  protoc_candidates+=("$PYTHON")
fi
protoc_candidates+=(
  "$repo_root/.venv/bin/python"
  "$repo_root/venv/bin/python"
  python3
  python
)

for candidate in "${protoc_candidates[@]}"; do
  if [[ "$candidate" == */* ]]; then
    [[ -x "$candidate" ]] || continue
  elif ! command -v "$candidate" >/dev/null 2>&1; then
    continue
  fi
  if "$candidate" -c 'import grpc_tools.protoc' >/dev/null 2>&1; then
    protoc_python="$candidate"
    break
  fi
done

if [[ -z "$protoc_python" ]]; then
  echo "error: grpcio-tools is required to build runtime protobuf modules" >&2
  exit 1
fi

proto_files=()
while IFS= read -r proto_file; do
  proto_files+=("$proto_file")
done < <(find "$staging_root/proto" -maxdepth 1 -type f -name '*.proto' -print | sort)

if [[ "${#proto_files[@]}" -eq 0 ]]; then
  echo "error: runtime release contains no protobuf definitions" >&2
  exit 1
fi

"$protoc_python" -m grpc_tools.protoc \
  -I"$staging_root/proto" \
  --python_out="$staging_root/src/generated" \
  --grpc_python_out="$staging_root/src/generated" \
  "${proto_files[@]}"

for path in "${required_generated_paths[@]}"; do
  if [[ ! -f "$staging_root/$path" ]]; then
    echo "error: generated runtime module is missing: $path" >&2
    exit 1
  fi
done

(
  cd "$staging_root"
  COPYFILE_DISABLE=1 tar --no-xattrs -cf - "${archive_paths[@]}"
) | gzip -n > "$temporary_archive"

archive_listing="$(tar -tzf "$temporary_archive")"
for path in "${required_paths[@]}"; do
  if ! grep -Eq "^${path}(/|$)" <<<"$archive_listing"; then
    echo "error: runtime archive is missing required path: ${path}" >&2
    exit 1
  fi
done
for path in "${required_generated_paths[@]}"; do
  if ! grep -Eq "^${path}$" <<<"$archive_listing"; then
    echo "error: runtime archive is missing generated module: $path" >&2
    exit 1
  fi
done

forbidden_pattern='(^|/)(tools|tests|docs)(/|$)|(^|/)(requirements-dev.txt|package.json|package-lock.json|npm-shrinkwrap.json|yarn.lock|pnpm-lock.yaml)$|(^|/)\._'
if grep -Eq "$forbidden_pattern" <<<"$archive_listing"; then
  echo "error: runtime archive contains development-only or npm manifest files" >&2
  grep -E "$forbidden_pattern" <<<"$archive_listing" >&2
  exit 1
fi

mv "$temporary_archive" "$output_path"
cleanup
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
  checksum="$(sha256sum "$output_path" | awk '{print $1}')"
else
  checksum="$(shasum -a 256 "$output_path" | awk '{print $1}')"
fi

echo "Runtime release: $output_path"
echo "Git commit: $resolved_ref"
echo "SHA-256: $checksum"
