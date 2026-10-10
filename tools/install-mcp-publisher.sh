#!/usr/bin/env bash
# Dependabot cannot track a release binary, so the version and its checksum
# are pinned here and bumped by hand.
set -euo pipefail

target_dir="${1:?usage: install-mcp-publisher.sh <target-dir>}"

version="1.8.1"
sha256="a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc"
archive="$target_dir/mcp-publisher_linux_amd64.tar.gz"

curl -fsSL -o "$archive" \
    "https://github.com/modelcontextprotocol/registry/releases/download/v${version}/mcp-publisher_linux_amd64.tar.gz"
echo "${sha256}  ${archive}" | sha256sum -c -
tar -xzf "$archive" -C "$target_dir" mcp-publisher
rm "$archive"
