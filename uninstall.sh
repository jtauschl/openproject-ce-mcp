#!/usr/bin/env bash
# macOS / Linux — removes the local environment and, on request, the server entry
# from your MCP client configs. Your local .mcp.json is left untouched.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Remove the openproject entry from any client config it was registered in
# (keeps other servers and settings; backs up each file first). Best-effort:
# skip if no interpreter is available yet.
PYTHON_BIN=""
for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1; then PYTHON_BIN="$p"; break; fi
done
if [ -n "$PYTHON_BIN" ]; then
  "$PYTHON_BIN" configure_mcp.py --uninstall || true
fi

# Remove local build/dev artifacts and the API-source clones (large, gitignored).
rm -rf .venv .pytest_cache .ruff_cache .op-sources
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type d -name "*.egg-info" -prune -exec rm -rf {} +

echo
echo "Local environment removed (.venv, caches, .op-sources)."
echo "Your .mcp.json was left untouched."
echo "If you registered the server globally in a client, that entry was removed"
echo "above (a backup of each edited config was kept)."
