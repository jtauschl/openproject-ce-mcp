#!/usr/bin/env bash
#
# Bring up local OpenProject test instances, wait until healthy, seed them, and
# print copy-paste env blocks for running the integration tests.
#
# Usage:
#   docker/test/up.sh            # both versions (16.6 + 17.5)
#   docker/test/up.sh 16         # only 16.6
#   docker/test/up.sh 17         # only 17.5
#
# First boot takes several minutes (migrations + asset precompile). The script
# waits on the container healthcheck, not a fixed sleep.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Stable secret across restarts, generated once into a gitignored .env.
if [ ! -f .env ]; then
  echo "SECRET_KEY_BASE=$(openssl rand -hex 64)" > .env
  echo "generated docker/test/.env"
fi

case "${1:-all}" in
  16) SERVICES=(op-16-6); SEMANTIC=("op-16-6:0") ;;
  17) SERVICES=(op-17-5); SEMANTIC=("op-17-5:1") ;;
  all|"") SERVICES=(op-16-6 op-17-5); SEMANTIC=("op-16-6:0" "op-17-5:1") ;;
  *) echo "usage: up.sh [16|17|all]" >&2; exit 2 ;;
esac

echo "Starting: ${SERVICES[*]} (first boot can take >5 min)…"
docker compose up -d "${SERVICES[@]}"

wait_healthy() {
  local svc="$1" cid
  cid="$(docker compose ps -q "$svc")"
  echo -n "Waiting for $svc to become healthy"
  for _ in $(seq 1 120); do
    local state
    state="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)"
    if [ "$state" = "healthy" ]; then echo " ok"; return 0; fi
    echo -n "."; sleep 10
  done
  echo " TIMEOUT"; return 1
}

declare -A PORT=( [op-16-6]=8166 [op-17-5]=8175 )

for entry in "${SEMANTIC[@]}"; do
  svc="${entry%%:*}"; semantic="${entry#*:}"
  wait_healthy "$svc"
  echo "Seeding $svc (SEED_SEMANTIC=$semantic)…"
  token="$(docker compose exec -T -e SEED_SEMANTIC="$semantic" "$svc" \
            bundle exec rails runner - < seed.rb \
            | sed -n 's/^SEED: API_TOKEN=//p' | tail -1)"
  if [ -z "$token" ]; then
    echo "WARNING: could not capture API token for $svc — check seed output above." >&2
    continue
  fi
  cat <<EOF

# --- $svc (port ${PORT[$svc]}) -------------------------------------------------
OPENPROJECT_BASE_URL=http://localhost:${PORT[$svc]} \\
OPENPROJECT_API_TOKEN=$token \\
OPENPROJECT_TEST_PROJECT=TST \\
uv run pytest -m integration -v
EOF
done

echo
echo "Done. Tear down with docker/test/down.sh (add --purge to drop volumes)."
