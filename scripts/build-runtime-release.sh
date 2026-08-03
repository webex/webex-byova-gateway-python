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
trap 'rm -f "$temporary_archive"' EXIT

git archive --format=tar "$resolved_ref" -- "${archive_paths[@]}" \
  | gzip -n > "$temporary_archive"

archive_listing="$(tar -tzf "$temporary_archive")"
for path in "${required_paths[@]}"; do
  if ! grep -Eq "^${path}(/|$)" <<<"$archive_listing"; then
    echo "error: runtime archive is missing required path: ${path}" >&2
    exit 1
  fi
done

forbidden_pattern='(^|/)(tools|tests|docs)(/|$)|(^|/)(package.json|package-lock.json|npm-shrinkwrap.json|yarn.lock|pnpm-lock.yaml)$|(^|/)\._'
if grep -Eq "$forbidden_pattern" <<<"$archive_listing"; then
  echo "error: runtime archive contains development-only or npm manifest files" >&2
  grep -E "$forbidden_pattern" <<<"$archive_listing" >&2
  exit 1
fi

mv "$temporary_archive" "$output_path"
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
  checksum="$(sha256sum "$output_path" | awk '{print $1}')"
else
  checksum="$(shasum -a 256 "$output_path" | awk '{print $1}')"
fi

echo "Runtime release: $output_path"
echo "Git commit: $resolved_ref"
echo "SHA-256: $checksum"
