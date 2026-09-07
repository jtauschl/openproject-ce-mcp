#!/usr/bin/env bash
#
# Bring up local OpenProject test instances, wait until healthy, seed them, and
# print copy-paste env blocks for running the integration tests.
#
# Usage:
#   docker/test/up.sh            # every minor 16.0-17.8 (16 versions), in
#                                 # batches of 5 concurrent instances (see
#                                 # "all" mode below)
#   docker/test/up.sh all 3      # every minor, 3 concurrent instances per batch
#   docker/test/up.sh 160        # only 16.0
#   docker/test/up.sh 161        # only 16.1
#   docker/test/up.sh 162        # only 16.2
#   docker/test/up.sh 163        # only 16.3
#   docker/test/up.sh 164        # only 16.4
#   docker/test/up.sh 165        # only 16.5
#   docker/test/up.sh 16         # only 16.6
#   docker/test/up.sh 170        # only 17.0
#   docker/test/up.sh 171        # only 17.1
#   docker/test/up.sh 172        # only 17.2
#   docker/test/up.sh 173        # only 17.3
#   docker/test/up.sh 174        # only 17.4
#   docker/test/up.sh 17         # only 17.5
#   docker/test/up.sh 176        # only 17.6
#   docker/test/up.sh 177        # only 17.7
#   docker/test/up.sh 178        # only 17.8
#   SEED_MULTI_VERSIONS=1 docker/test/up.sh 178
#                                 # only 17.8, with Setting::WorkPackageMultipleVersions
#                                 # forced on (default: false when unset -- see
#                                 # seed_and_print()'s own comment for why this
#                                 # forcing exists rather than trusting the
#                                 # image's own default). Only meaningful with
#                                 # the "178" mode above -- SEED_MULTI_VERSIONS
#                                 # is read from this script's own environment,
#                                 # not per-ALL_ENTRIES-entry, so setting it
#                                 # alongside "all"/other single-version modes
#                                 # passes it to every seeded instance
#                                 # regardless of version, not a targeted
#                                 # per-version toggle. Harmless there: the
#                                 # underlying Setting::WorkPackageMultipleVersions
#                                 # module already exists on 17.7 too (not
#                                 # 17.8-exclusive), but 17.7's own .active?
#                                 # additionally requires an experimental
#                                 # OpenProject::FeatureDecisions flag this
#                                 # project doesn't enable -- seed.rb verifies
#                                 # the setting actually took effect and skips
#                                 # the multi-version fixture with a warning
#                                 # if not, rather than seeding data the server
#                                 # would reject.
#
# The Nextcloud storage fixture is now seeded unconditionally alongside every
# instance this script brings up -- every mode above (including "all" and its
# batches) gets a `nextcloud` container and a seeded Storages::NextcloudStorage
# row on every OpenProject instance. There is no separate "nc" suffix mode
# any more (removed: 177nc/178nc are gone, since every mode now does what
# they used to do) -- this costs one extra container's worth of boot time/RAM
# per batch (Nextcloud is shared across every instance in a batch, not one
# per instance), in exchange for the storages/project_storages read-tool
# tests never needing to be skipped.
#
# "all" mode brings up instances in sequential BATCHES rather than all 16 at
# once -- 16 concurrent all-in-one containers would exhaust a small Docker
# VM's memory. Batch size defaults to 5 and is overridable as a second
# argument (`up.sh all <n>`); each batch is brought up, waited on, seeded,
# printed, and torn down (volumes kept) before the next batch starts. Batch
# size 1 effectively means "one instance fully sequential" -- the safest,
# slowest option on a very small VM.
#
# First boot takes several minutes per instance (migrations + asset
# precompile). The script waits on each container's healthcheck, not a fixed
# sleep.
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

# Full ordered version list, oldest first -- "all" mode batches through this.
# Each entry is "service:semantic" (semantic identifiers active from 17.5 on).
ALL_ENTRIES=(
    "op-16-0:0" "op-16-1:0" "op-16-2:0" "op-16-3:0" "op-16-4:0" "op-16-5:0" "op-16-6:0"
    "op-17-0:0" "op-17-1:0" "op-17-2:0" "op-17-3:0" "op-17-4:0"
    "op-17-5:1" "op-17-6:1" "op-17-7:1" "op-17-8:1"
)

port_for() {
    case "$1" in
    op-16-0) echo 8160 ;;
    op-16-1) echo 8161 ;;
    op-16-2) echo 8162 ;;
    op-16-3) echo 8163 ;;
    op-16-4) echo 8164 ;;
    op-16-5) echo 8165 ;;
    op-16-6) echo 8166 ;;
    op-17-0) echo 8170 ;;
    op-17-1) echo 8171 ;;
    op-17-2) echo 8172 ;;
    op-17-3) echo 8173 ;;
    op-17-4) echo 8174 ;;
    op-17-5) echo 8175 ;;
    op-17-6) echo 8176 ;;
    op-17-7) echo 8177 ;;
    op-17-8) echo 8178 ;;
    *)
        echo "unknown service: $1" >&2
        return 2
        ;;
    esac
}

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

wait_nextcloud_healthy() {
    echo -n "Waiting for nextcloud to become healthy"
    local nc_cid nc_healthy=0
    nc_cid="$(docker compose ps -q nextcloud)"
    for _ in $(seq 1 60); do
        local nc_state
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
}

# Seeds one already-healthy instance and prints its copy-paste env block.
# Nextcloud is always seeded (see the top-of-file note) -- no on/off switch.
# SEED_MULTI_VERSIONS is read from up.sh's own environment (default 0, e.g.
# `SEED_MULTI_VERSIONS=1 docker/test/up.sh 178`) -- OpenProject 17.8.0 ships
# Setting::WorkPackageMultipleVersions with default: true (verified live,
# 2026-09-07, against config/constants/settings/definition.rb in the actual
# image), so seed.rb always forces the setting to a known state rather than
# trusting the fresh-install default: false unless SEED_MULTI_VERSIONS=1,
# true when it is. No separate dedicated container is needed for this --
# both states are exercised on the same op-17-8 service/volume across
# separate up.sh invocations.
seed_and_print() {
    local svc="$1" semantic="$2" port multi_versions="${SEED_MULTI_VERSIONS:-0}"
    port="$(port_for "$svc")"
    echo "Seeding $svc (SEED_SEMANTIC=$semantic, SEED_NEXTCLOUD_STORAGE=1, SEED_FILE_LINK=1, SEED_MULTI_VERSIONS=$multi_versions)…"
    local seed_output
    seed_output="$(docker compose exec -T -e SEED_SEMANTIC="$semantic" -e SEED_NEXTCLOUD_STORAGE=1 \
        -e SEED_FILE_LINK=1 -e SEED_MULTI_VERSIONS="$multi_versions" "$svc" \
        bundle exec rails runner - <seed.rb)"
    echo "$seed_output"
    local token restricted_token
    token="$(sed -n 's/^SEED: API_TOKEN=//p' <<<"$seed_output" | tail -1)"
    restricted_token="$(sed -n 's/^SEED: RESTRICTED_API_TOKEN=//p' <<<"$seed_output" | tail -1)"
    if [ -z "$token" ]; then
        echo "WARNING: could not capture API token for $svc — check seed output above." >&2
        return 0
    fi
    if [ -z "$restricted_token" ]; then
        echo "WARNING: could not capture restricted API token for $svc — check seed output above." >&2
    fi
    # Project identifier matches seed.rb: uppercase in semantic mode, lowercase otherwise
    local test_project
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
}

# Brings up, waits on, and seeds a fixed set of services plus a shared
# Nextcloud container -- used both by single-version mode and by each batch
# of "all" mode.
bring_up_batch() {
    local entries=("$@")
    local services=(nextcloud)
    for entry in "${entries[@]}"; do
        services+=("${entry%%:*}")
    done

    echo "Starting: ${services[*]} (first boot can take >5 min)…"
    docker compose up -d "${services[@]}"

    wait_nextcloud_healthy

    for entry in "${entries[@]}"; do
        local svc="${entry%%:*}" semantic="${entry#*:}"
        wait_healthy "$svc"
        seed_and_print "$svc" "$semantic"
    done
}

MODE="${1:-all}"

if [ "$MODE" = "all" ] || [ -z "$MODE" ]; then
    BATCH_SIZE="${2:-5}"
    case "$BATCH_SIZE" in
    '' | *[!0-9]*)
        echo "usage: up.sh all [batch-size:integer]" >&2
        exit 2
        ;;
    esac
    echo "Running all ${#ALL_ENTRIES[@]} versions in batches of $BATCH_SIZE…"
    total=${#ALL_ENTRIES[@]}
    i=0
    while [ "$i" -lt "$total" ]; do
        batch=("${ALL_ENTRIES[@]:$i:$BATCH_SIZE}")
        echo
        echo "=== Batch starting at index $i: ${batch[*]%%:*} ==="
        bring_up_batch "${batch[@]}"
        i=$((i + BATCH_SIZE))
        if [ "$i" -lt "$total" ]; then
            echo "Tearing down this batch before starting the next (volumes kept)…"
            docker compose down --remove-orphans >/dev/null
        fi
    done
    echo
    echo "Done. Tear down the final batch with docker/test/down.sh (add --purge to drop volumes)."
    exit 0
fi

case "$MODE" in
160) ENTRIES=("op-16-0:0") ;;
161) ENTRIES=("op-16-1:0") ;;
162) ENTRIES=("op-16-2:0") ;;
163) ENTRIES=("op-16-3:0") ;;
164) ENTRIES=("op-16-4:0") ;;
165) ENTRIES=("op-16-5:0") ;;
16) ENTRIES=("op-16-6:0") ;;
170) ENTRIES=("op-17-0:0") ;;
171) ENTRIES=("op-17-1:0") ;;
172) ENTRIES=("op-17-2:0") ;;
173) ENTRIES=("op-17-3:0") ;;
174) ENTRIES=("op-17-4:0") ;; # displayId present, semantic off
17 | 175) ENTRIES=("op-17-5:1") ;;
176) ENTRIES=("op-17-6:1") ;;
177) ENTRIES=("op-17-7:1") ;;
178) ENTRIES=("op-17-8:1") ;;
*)
    echo "usage: up.sh [all [batch-size]|160|161|162|163|164|165|16|170|171|172|173|174|17|176|177|178]" >&2
    exit 2
    ;;
esac

bring_up_batch "${ENTRIES[@]}"

echo
echo "Done. Tear down with docker/test/down.sh (add --purge to drop volumes)."
