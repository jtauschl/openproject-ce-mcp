#!/usr/bin/env bash
#
# Fetch the OpenProject source at the versions we verify our API assumptions
# against. Clones are shallow + sparse (only the API-relevant subtrees) into a
# gitignored cache, so this stays fast and small. Read-only reference; never
# committed.
#
# Usage: tools/api-check/fetch-sources.sh
#
set -euo pipefail

REPO="https://github.com/opf/openproject.git"

# Pinned versions as "label:tag" pairs (latest patch of each minor from 16.0).
# Lets the API check map exactly which release changes a symbol the client uses.
# 16.x = classic numeric identifiers; 17.4 adds displayId; 17.5 adds semantic ids.
# Bump / extend when verifying newer releases.
VERSIONS=(
  "16.0:v16.0.1"
  "16.1:v16.1.1"
  "16.2:v16.2.2"
  "16.3:v16.3.2"
  "16.4:v16.4.1"
  "16.5:v16.5.1"
  "16.6:v16.6.10"
  "17.0:v17.0.7"
  "17.1:v17.1.4"
  "17.2:v17.2.4"
  "17.3:v17.3.4"
  "17.4:v17.4.1"
  "17.5:v17.5.1"
  "17.6:v17.6.0"
)

# Subtrees that hold the API v3 definitions, representers and query filters,
# plus the models/representers that define the enums and payload field names the
# constant check (check_api.py --constants) verifies.
SPARSE_PATHS=(
  "lib/api"
  "app/models/queries"
  "app/models/work_package"
  "/config/routes.rb"
  "/app/models/emoji_reaction.rb"   # EMOJI_MAP enum values
  "/app/models/version.rb"          # VERSION_STATUSES
  "modules/backlogs"                # Sprint model/representers (17.6+, see OPM-102)
)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_BASE="$ROOT/.op-sources"
mkdir -p "$DEST_BASE"

for entry in "${VERSIONS[@]}"; do
  ver="${entry%%:*}"
  tag="${entry#*:}"
  dest="$DEST_BASE/$ver"
  if [ -d "$dest/.git" ]; then
    echo "[$ver] already present ($(git -C "$dest" describe --tags 2>/dev/null || echo '?')), skipping. Remove $dest to refresh."
    continue
  fi
  echo "[$ver] cloning $tag (sparse, shallow) -> $dest"
  rm -rf "$dest"
  git -c advice.detachedHead=false clone --depth 1 --branch "$tag" \
    --filter=blob:none --sparse "$REPO" "$dest"
  # Non-cone mode so individual file paths (config/routes.rb) are allowed.
  git -C "$dest" sparse-checkout set --no-cone "${SPARSE_PATHS[@]}"
  echo "[$ver] done: $(git -C "$dest" describe --tags)"
done

echo
echo "Sources ready under $DEST_BASE/. Run: python tools/api-check/check_api.py"
