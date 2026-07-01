# Local OpenProject test instances

Spin up real OpenProject Community Edition instances locally to verify the MCP
client's runtime behaviour across identifier modes — the behaviour the offline
`tools/api-check/` symbol check cannot prove.

We run the latest patch of each minor where the API changed in a way that
matters to this client (all-in-one images, each bundles PostgreSQL + memcached):

| service    | version | port | why this version |
|------------|---------|------|------------------|
| `op-16-6`  | 16.6.10 | 8166 | classic baseline (no displayId, no semantic) |
| `op-17-4`  | 17.4.1  | 8174 | displayId field introduced |
| `op-17-5`  | 17.5.1  | 8175 | semantic identifiers active + workspaces (favorites) |

## Usage

```bash
docker/test/up.sh           # all versions; waits until healthy, seeds, prints env
docker/test/up.sh 17        # only 17.5.1
docker/test/up.sh 174       # only 17.4.1
docker/test/up.sh 16        # only 16.6.10

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
token (printed once so `up.sh` can capture it) and a project `tst`. A freshly
created project is bare, so the seed also: sets `workspace_type`, enables every
project module, assigns all work-package types, adds the admin as a member with a
work-package-capable role, creates one work package, and — on 17.5 only —
switches the instance to semantic identifiers (allocating the `tst-<n>` ids). 16.6
and 17.4 stay classic on purpose; those are the backwards-compatibility paths.

`SECRET_KEY_BASE` is generated once into a gitignored `.env`; never commit it.

## The test

`tests/integration/test_semantic_identifiers.py` is mode-agnostic: it creates a
WP, reads its `display_id`, and branches — numeric ids resolve everywhere; the
semantic instance resolves `tst-<n>` references; the classic instances degrade a
project-prefixed reference to `NotFoundError`.

Run the full suite against a running instance with the env block `up.sh` prints,
e.g. `OPENPROJECT_BASE_URL=http://localhost:8175 OPENPROJECT_API_TOKEN=… OPENPROJECT_TEST_PROJECT=tst uv run pytest -m integration`.

## Known OpenProject issue (not the MCP)

On 17.5.1 with semantic identifiers **active**, OpenProject's own
`GET /api/v3/work_packages/{id}` single-fetch endpoint returns a 500 for
work packages that carry a semantic alias (`No route matches action:"show"` in
the server log). The collection endpoint and the classic mode are unaffected, and
the MCP surfaces it cleanly as a `[server_error]`. Because of this, run the
semantic-mode integration checks with awareness of the limitation; the classic
`op-16-6`/`op-17-4` instances exercise the full suite green.
