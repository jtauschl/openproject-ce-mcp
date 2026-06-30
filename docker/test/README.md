# Local OpenProject test instances

Spin up real OpenProject Community Edition instances locally to verify the MCP
client's runtime behaviour across identifier modes — the behaviour the offline
`tools/api-check/` symbol check cannot prove.

Two all-in-one containers (each bundles PostgreSQL + memcached):

| service    | version | port | identifier mode |
|------------|---------|------|-----------------|
| `op-16-6`  | 16.6    | 8166 | classic (numeric) |
| `op-17-5`  | 17.5    | 8175 | semantic (project-based, seeded) |

## Usage

```bash
docker/test/up.sh           # both versions; waits until healthy, seeds, prints env
docker/test/up.sh 17        # only 17.5
docker/test/up.sh 16        # only 16.6

# up.sh prints a ready-to-run block per instance, e.g.:
OPENPROJECT_BASE_URL=http://localhost:8175 \
OPENPROJECT_API_TOKEN=<captured> \
OPENPROJECT_TEST_PROJECT=TST \
uv run pytest -m integration -v

docker/test/down.sh         # stop, keep volumes (fast re-up)
docker/test/down.sh --purge # also drop volumes
```

**First boot takes several minutes** (migrations + asset precompile). `up.sh`
waits on the container healthcheck, not a fixed sleep. Each instance needs
~1–2 GB RAM; start just one (`up.sh 17`) if memory is tight.

## What seeding does

`seed.rb` (run via `rails runner` by `up.sh`, idempotent) creates an admin API
token (printed once so `up.sh` can capture it), a project `TST` with one work
package, and — on 17.5 only — switches the instance to semantic identifiers so
`displayId` becomes `TST-<n>`. 16.6 stays classic on purpose; that is the
backwards-compatibility path under test.

`SECRET_KEY_BASE` is generated once into a gitignored `.env`; never commit it.

## The test

`tests/integration/test_semantic_identifiers.py` is mode-agnostic: it creates a
WP, reads its `display_id`, and branches — numeric ids resolve on both versions;
the semantic instance resolves `TST-<n>` references; the classic instance
degrades a project-prefixed reference to `NotFoundError`.
