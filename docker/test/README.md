# Local OpenProject test instances

Spin up real OpenProject Community Edition instances locally to verify the MCP
client's runtime behaviour across identifier modes — the behaviour the offline
`tools/api-check/` symbol check cannot prove.

We run every supported minor's latest patch (all-in-one images, each bundles
PostgreSQL + memcached) — 16.0 through 17.8 as of this pin (16 versions total).
The version-specific API behavior that actually matters to this client:

| minor range | why it matters |
|-------------|-----------------|
| 16.0–16.5   | classic baseline (no displayId, no semantic); emoji reactions and project phase definitions don't exist as routes at all until 16.1 (reminders exist since 16.0); documents PATCH doesn't exist until 16.6; the `entity` HAL link key (time/cost entries) doesn't exist until 16.6, only `workPackage` does |
| 16.6        | classic baseline with documents PATCH and the `entity` link key now present |
| 17.0–17.3   | workspaces (17.0); storages' `forbiddenFileNameCharacters` field (17.1); sprints/meetings/user-schedule domains (17.3) |
| 17.4        | displayId field introduced, semantic identifiers still off |
| 17.5–17.8   | project-based semantic identifiers active + workspaces (favorites); 17.7 makes user working-times generally available (no longer feature-flag-gated) |

`targetVersions` (multi-value successor to `version`) and
`Setting::WorkPackageMultipleVersions` (which gates whether more than one
`target_versions` entry can be written; reading is never gated) already exist
in 17.7, not first in 17.8 — verified directly against the pinned 17.7
sources (`associated_resources :target_versions` in
`work_package_representer.rb`, `Setting::WorkPackageMultipleVersions` in its
own model file). What IS 17.8-specific: on 17.7 the setting's own `.active?`
additionally requires an experimental `OpenProject::FeatureDecisions` flag
this project does not enable, so setting `Setting.work_package_multiple_versions`
alone does not actually activate multi-value writes there; 17.8 drops that
extra gate. `op-17-8` is still the only container this project seeds a
target_versions fixture against — `seed.rb` verifies the setting actually
reached the requested state after writing it (not just that the write call
succeeded) and skips the multi-version fixture with a clear warning if not,
rather than seeding data the server would reject.

The `openproject/openproject:17.8.0` image ships
`Setting::WorkPackageMultipleVersions` with `default: true`
(`config/constants/settings/definition.rb`) there, not off by default as
might be assumed. `seed.rb` always forces it to a known state (`false` unless
`SEED_MULTI_VERSIONS=1`, `true` when it is) rather than trusting the image's
default, so `op-17-8` can exercise both the setting-disabled and
setting-enabled write paths across separate `up.sh` invocations — no separate
dedicated container needed. See `SEED_MULTI_VERSIONS=1 docker/test/up.sh 178`
below.

Exact per-minor patch pins live in `compose.yml` and `tools/api-check/fetch-sources.sh`'s
`VERSIONS` array — check those directly rather than trusting a copy of the pin
list here, since they're the actual source of truth and this table would drift.

## Usage

```bash
docker/test/up.sh           # every version (16.0-17.8), in batches of 5
docker/test/up.sh all 3     # every version, 3 concurrent instances per batch
docker/test/up.sh 17        # only 17.5.x
docker/test/up.sh 174       # only 17.4.x
docker/test/up.sh 16        # only 16.6.x
docker/test/up.sh 176       # only 17.6.x
docker/test/up.sh 177       # only 17.7.x
docker/test/up.sh 178       # only 17.8.x
SEED_MULTI_VERSIONS=1 docker/test/up.sh 178
                             # only 17.8.x with Setting::WorkPackageMultipleVersions forced on
# ... and 160-165/170-173 for every other pinned minor -- see up.sh's own
# usage comment for the full list.

# up.sh prints a ready-to-run block per instance, e.g.:
OPENPROJECT_BASE_URL=http://localhost:8175 \
OPENPROJECT_API_TOKEN=<captured> \
OPENPROJECT_TEST_PROJECT=TST \
uv run pytest -m integration -v

docker/test/down.sh         # stop, keep volumes (fast re-up)
docker/test/down.sh --purge # also drop volumes
```

"all" mode brings instances up in sequential BATCHES (default 5 concurrent),
not all 16 at once — that would exhaust a small Docker VM's memory. Each batch
is brought up, waited on, seeded, printed, and torn down (volumes kept)
before the next starts.

## Nextcloud storage fixture (seeded on every instance)

For the `storages`/`project_storages` MCP tools, every `up.sh`
invocation — single-version and every "all" batch — also brings up a
`nextcloud` service (plain `nextcloud:30-apache` image, SQLite backend,
non-interactive install via `NEXTCLOUD_ADMIN_USER`/`NEXTCLOUD_ADMIN_PASSWORD`
env vars — the password is generated once into the same gitignored `.env` as
`SECRET_KEY_BASE`), shared across every OpenProject instance in that batch.
This used to be an opt-in `nc` suffix mode (`177nc`) available only for 17.7;
it's unconditional now, closing a real gap where the storages/project_storages
read-tool tests silently skipped on every other version even though nothing
about them was actually 17.7-specific.

`seed.rb` then creates a `Storages::NextcloudStorage` row (host
`http://nextcloud/`, reachable via Compose's default service-name DNS) and a
`Storages::ProjectStorage` row linking it to the `TST` project with
`project_folder_mode: "inactive"`, via `save(validate: false)` — this
deliberately bypasses OpenProject's live host-reachability/
`integration_openproject`-app-installed probe
(`NextcloudCompatibleHostValidator`), so the fixture is deterministic and
does not depend on the Nextcloud container actually finishing its own setup.

**What this fixture supports**: `GET /api/v3/storages`,
`GET /api/v3/storages/{id}`, `GET /api/v3/project_storages`,
`GET /api/v3/project_storages/{id}` all return a real row.

**What this fixture deliberately does NOT support**: a live,
OAuth-authenticated "connected" storage —
no browser-driven OAuth handshake happens, so `configured?` stays false and
`storage_files` browsing does not work against it. If deeper write/browsing
testing is ever wanted, that needs a real interactive OAuth round-trip
(installing the "OpenProject Integration" app inside the Nextcloud container
via its admin UI or `occ`, then completing the OAuth exchange through a
browser) — treated as a known, explicitly out-of-scope gap, not a bug.

**Any `PATCH` to this storage always 422s**: the seeded `host:
"http://nextcloud/"` is plain HTTP on a non-localhost hostname, which
OpenProject's core `SecureContextUriValidator` always rejects — and PATCH
re-validates the whole model, not just the fields the request touched, so
even a name-only rename fails with `url_not_secure_context`. This is not a
version regression or a client bug; see `CLAUDE.md`'s "Known API quirks" for
the full explanation. Write tests against this storage should assert the
expected `InvalidInputError`, not a successful update.

**File link fixtures**: with the `Storages::ProjectStorage` row above in
place, `up.sh` also seeds two `Storages::FileLink` rows
(`save(validate: false)`, same bypass as the storage rows — no live
Nextcloud file actually exists at either fabricated `origin_id`):
`seed-file-link-persistent.txt` (read/deny-only,
`tests/integration/test_write_denials.py` targets this one and never deletes
it) and `seed-file-link-deletable.txt` (consumed by
`tests/integration/test_storages.py::test_delete_file_link_deletes_seeded_link`,
which actually calls `delete_file_link` and destroys it — a repeat `up.sh`
reseeds it via `find_or_create`, since deleting it is the whole point
of that test). This is what gives `delete_file_link`'s successful-delete
path deterministic live coverage; previously it only ran when a file link
happened to already exist, which the default seed never provides.

**First boot takes several minutes** (migrations + asset precompile). `up.sh`
waits on the container healthcheck, not a fixed sleep. Each instance needs
~1–2 GB RAM, so five all-in-one containers at once can exhaust a small Docker
VM (a default ~4 GB Colima VM will start marking containers unhealthy). On such
machines, bring them up and test one at a time — `up.sh 16`, then `up.sh 174`,
then `up.sh 17`, then `up.sh 176`, then `up.sh 177` — instead of `up.sh` (all
five).

## What seeding does

`seed.rb` (run via `rails runner` by `up.sh`, idempotent) creates an admin API
token (printed once so `up.sh` can capture it) and a project `tst`. A freshly
created project is bare, so the seed also: sets `workspace_type`, enables every
project module, assigns all work-package types, adds the admin as a member with a
work-package-capable role, creates one work package, and — on 17.5+ only —
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

## Note: semantic identifiers require an UPPERCASE project identifier

In semantic mode OpenProject only accepts uppercase project identifiers
(`[A-Z0-9_]`). A lowercase identifier such as `tst` is fine in classic mode but,
once semantic mode is switched on, produces an inconsistent alias state whose
`GET /api/v3/work_packages/{id}` single-fetch endpoint 500s (`No route matches
action:"show"`). The seed script therefore uppercases the project identifier
(`tst` → `TST`) before allocating semantic ids, which makes both the numeric and
the `TST-N` single-fetch paths return 200.

This was originally mistaken for an upstream OpenProject bug; it is not — a
lowercase-vs-uppercase identifier in semantic mode is the trigger, and the seed
handles it. The MCP itself is unaffected either way (it surfaces any server-side
failure as `[server_error]`).
