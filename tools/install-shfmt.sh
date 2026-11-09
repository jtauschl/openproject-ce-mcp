#!/usr/bin/env bash
# Dependabot cannot track a release binary, so the version and its checksum are pinned here and bumped by hand
# together with required_shfmt_version in ./dev. The release publishes no checksum file: the value is the sha256 of the
# asset, and it equals the digest GitHub's release API reports for it. Both come from the same release, so the pin
# catches a changed or truncated download, not a compromised release.
set -euo pipefail

target_dir="${1:?usage: install-shfmt.sh <target-dir>}"

version="3.14.1"
sha256="76e77641faa025814b77f153b29796b8e6fa2fca03e0c76a691608b86c7ea7bf"

tmp="$(mktemp "$target_dir/.shfmt.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

curl -fsSL -o "$tmp" \
    "https://github.com/mvdan/sh/releases/download/v${version}/shfmt_v${version}_linux_amd64"
echo "${sha256}  ${tmp}" | sha256sum -c -
chmod +x "$tmp"
mv "$tmp" "$target_dir/shfmt"
