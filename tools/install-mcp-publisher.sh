#!/usr/bin/env bash
# Dependabot cannot track a release binary, so the version and its checksum
# are pinned here and bumped by hand: the newest release at least seven days old (the Dependabot cooldown of this
# project), its sha256 taken from the release asset's digest (`gh api repos/modelcontextprotocol/registry/releases/tags/vX
# --jq '.assets[] | select(.name == "mcp-publisher_linux_amd64.tar.gz") | .digest'`) and `mcp-publisher validate server.json`
# run with the new binary before the bump.
set -euo pipefail

target_dir="${1:?usage: install-mcp-publisher.sh <target-dir>}"

version="1.8.7"
sha256="00b21004149a4ce66f0782508ae4a2bce67d1bea395a8da0bd8028159fb59579"
archive="$target_dir/mcp-publisher_linux_amd64.tar.gz"

curl -fsSL -o "$archive" \
    "https://github.com/modelcontextprotocol/registry/releases/download/v${version}/mcp-publisher_linux_amd64.tar.gz"
echo "${sha256}  ${archive}" | sha256sum -c -
tar -xzf "$archive" -C "$target_dir" mcp-publisher
rm "$archive"
