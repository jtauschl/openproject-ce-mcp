#!/usr/bin/env bash
#
# Stop the local OpenProject test instances.
#   docker/test/down.sh            # stop containers, keep volumes (fast re-up)
#   docker/test/down.sh --purge    # also drop volumes (clean slate)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "${1:-}" = "--purge" ]; then
  docker compose down -v
  echo "Containers and volumes removed."
else
  docker compose down
  echo "Containers stopped; volumes kept. Use --purge to remove them."
fi
