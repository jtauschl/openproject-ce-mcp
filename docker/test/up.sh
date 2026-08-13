#!/usr/bin/env bash
#
# Bring up local OpenProject test instances, wait until healthy, seed them, and
# print copy-paste env blocks for running the integration tests.
#
# Usage:
#   docker/test/up.sh            # all five versions (16.6 + 17.4 + 17.5 + 17.6 + 17.7)
#   docker/test/up.sh 16         # only 16.6
#   docker/test/up.sh 174        # only 17.4
#   docker/test/up.sh 17         # only 17.5
#   docker/test/up.sh 176        # only 17.6
#   docker/test/up.sh 177        # only 17.7
#   docker/test/up.sh 177nc      # 17.7 + the Nextcloud storage fixture
#
# On a small Docker VM (~4 GB) five all-in-one containers can exhaust memory;
# bring them up one at a time (16, then 174, then 17, then 176, then 177) if
# that happens.
#
# First boot takes several minutes (migrations + asset precompile). The script
# waits on the container healthcheck, not a fixed sleep.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Stable secret across restarts, generated once into a gitignored .env.
if [ ! -f .env ]; then
    {
        echo "SECRET_KEY_BASE=$(openssl rand -hex 64)"
        echo "NEXTCLOUD_ADMIN_PASSWORD=$(openssl rand -hex 24)"
    } >.env
    echo "generated docker/test/.env"
fi

WITH_NEXTCLOUD=0
case "${1:-all}" in
16)
    SERVICES=(op-16-6)
    SEMANTIC=("op-16-6:0")
    ;;
174)
    SERVICES=(op-17-4)
    SEMANTIC=("op-17-4:0")
    ;; # displayId present, semantic off
17 | 175)
    SERVICES=(op-17-5)
    SEMANTIC=("op-17-5:1")
    ;;
176)
    SERVICES=(op-17-6)
    SEMANTIC=("op-17-6:1")
    ;;
177)
    SERVICES=(op-17-7)
    SEMANTIC=("op-17-7:1")
    ;;
177nc)
    SERVICES=(op-17-7 nextcloud)
    SEMANTIC=("op-17-7:1")
    WITH_NEXTCLOUD=1
    ;;
all | "")
    SERVICES=(op-16-6 op-17-4 op-17-5 op-17-6 op-17-7)
    SEMANTIC=("op-16-6:0" "op-17-4:0" "op-17-5:1" "op-17-6:1" "op-17-7:1")
    ;;
*)
    echo "usage: up.sh [16|174|17|176|177|177nc|all]" >&2
    exit 2
    ;;
esac

echo "Starting: ${SERVICES[*]} (first boot can take >5 min)…"
docker compose up -d "${SERVICES[@]}"

if [ "$WITH_NEXTCLOUD" = "1" ]; then
    echo -n "Waiting for nextcloud to become healthy"
    nc_cid="$(docker compose ps -q nextcloud)"
    nc_healthy=0
    for _ in $(seq 1 60); do
        nc_state="$(docker inspect -f '{{.State.Health.Status}}' "$nc_cid" 2>/dev/null || echo starting)"
        if [ "$nc_state" = "healthy" ]; then
            echo " ok"
            nc_healthy=1
            break
        fi
        echo -n "."
        sleep 10
    done
    [ "$nc_healthy" = "1" ] || echo " TIMEOUT (continuing — seed.rb's storage fixture does not require a live connection)"
fi

wait_healthy() {
    local svc="$1" cid
    cid="$(docker compose ps -q "$svc")"
    echo -n "Waiting for $svc to become healthy"
    for _ in $(seq 1 120); do
        local state
        state="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)"
        if [ "$state" = "healthy" ]; then
            echo " ok"
            return 0
        fi
        echo -n "."
        sleep 10
    done
    echo " TIMEOUT"
    return 1
}

port_for() {
    case "$1" in
    op-16-6) echo 8166 ;;
    op-17-4) echo 8174 ;;
    op-17-5) echo 8175 ;;
    op-17-6) echo 8176 ;;
    op-17-7) echo 8177 ;;
    *)
        echo "unknown service: $1" >&2
        return 2
        ;;
    esac
}

for entry in "${SEMANTIC[@]}"; do
    svc="${entry%%:*}"
    semantic="${entry#*:}"
    port="$(port_for "$svc")"
    wait_healthy "$svc"
    seed_nextcloud=0
    [ "$WITH_NEXTCLOUD" = "1" ] && [ "$svc" = "op-17-7" ] && seed_nextcloud=1
    echo "Seeding $svc (SEED_SEMANTIC=$semantic, SEED_NEXTCLOUD_STORAGE=$seed_nextcloud)…"
    seed_output="$(docker compose exec -T -e SEED_SEMANTIC="$semantic" -e SEED_NEXTCLOUD_STORAGE="$seed_nextcloud" "$svc" \
        bundle exec rails runner - <seed.rb)"
    echo "$seed_output"
    token="$(sed -n 's/^SEED: API_TOKEN=//p' <<<"$seed_output" | tail -1)"
    restricted_token="$(sed -n 's/^SEED: RESTRICTED_API_TOKEN=//p' <<<"$seed_output" | tail -1)"
    if [ -z "$token" ]; then
        echo "WARNING: could not capture API token for $svc — check seed output above." >&2
        continue
    fi
    if [ -z "$restricted_token" ]; then
        echo "WARNING: could not capture restricted API token for $svc — check seed output above." >&2
    fi
    # Project identifier matches seed.rb: uppercase in semantic mode, lowercase otherwise
    test_project="$([ "$semantic" = "1" ] && echo "TST" || echo "tst")"
    cat <<EOF

# --- $svc (port $port) -------------------------------------------------
OPENPROJECT_BASE_URL=http://localhost:$port \\
OPENPROJECT_API_TOKEN=$token \\
OPENPROJECT_RESTRICTED_API_TOKEN=$restricted_token \\
OPENPROJECT_TEST_PROJECT=$test_project \\
OPENPROJECT_DOCKER_SERVICE=$svc \\
uv run pytest -m integration -v
EOF
done

echo
echo "Done. Tear down with docker/test/down.sh (add --purge to drop volumes)."
