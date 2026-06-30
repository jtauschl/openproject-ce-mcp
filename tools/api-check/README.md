# API source-check

Two tools that keep this MCP honest against the OpenProject API:

- **`check_api.py`** — verifies, offline, that the API symbols the client depends
  on (paths, fields, filters) still exist in each OpenProject version. Guards
  against silent breakage when OpenProject renames or removes part of its API —
  the failure mode the first semantic-identifier resolver hit (it relied on the
  `subject_or_id` filter, which exists but does not match the project-based
  `displayId` form).
- **`check_coverage.py`** — reports how much of the Community Edition API the
  client covers, combining the source inventory, the client's used resources,
  and an optional live CE probe. Writes `COVERAGE.md`.

## Usage

```bash
tools/api-check/fetch-sources.sh        # clone OP source for each version (once)

python tools/api-check/check_api.py     # version matrix; exit 1 on unexpected drift
python tools/api-check/check_api.py --verbose   # also list matching symbols

# Coverage: set OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN to enable the live
# CE probe (a CE instance), otherwise the live column is skipped.
python tools/api-check/check_coverage.py          # coverage matrix to stdout
python tools/api-check/check_coverage.py --write  # also (re)write COVERAGE.md
```

`check_coverage.py` classifies each of OpenProject's ~53 v3 resources as
**covered**, **GAP (CE)** (a plain top-level CE resource we don't use yet),
**subresource** (reached via a parent path), **enterprise**, or **internal**.
The CE/Enterprise split is not cleanly derivable from source (heterogeneous
feature-flag / `EnterpriseToken` guards), so a curated `CLASSIFICATION` table in
the script reconciles edge cases and the live probe is the tie-breaker. Update
that table when a resource is reclassified.

`fetch-sources.sh` makes shallow, sparse clones (only the API subtrees) into
`.op-sources/<version>/`, which is gitignored. To refresh after bumping a pinned
tag, delete the corresponding directory and re-run.

## What it does and does not catch

- **Catches:** a path/field/filter the client uses being renamed or removed in a
  version (symbol no longer present where expected).
- **Does NOT catch:** a symbol that still exists but whose *behaviour* changed.
  That requires running a real instance — see [`docker/test/`](../../docker/test/).

## Pinned versions

`fetch-sources.sh` clones the latest patch of every minor release from 16.0 to
17.5 (`VERSIONS` array), so the check runs as a **version matrix**: each symbol's
presence is shown across all 13 columns, pinpointing exactly which release
introduced or dropped it. As of this writing:

```
16.0  16.1  16.2  16.3  16.4  16.5  16.6  17.0  17.1  17.2  17.3  17.4  17.5
```

The matrix confirms that of every API symbol the client uses, only `displayId`
(and the semantic-identifier model) changed across this range — both introduced
in **17.4** (`present_from="17.4"`); everything else is stable back to 16.0.

Bump / extend the `VERSIONS` array as new releases land, then re-run both
scripts. A symbol that appears or disappears in an unexpected version fails the
check until its `present_from`/`expect` allowlist is updated.

## Maintaining the assumptions

Each checked symbol is an `Assumption` in `check_api.py`. Known, intentional
version differences are encoded inline via the `expect` field, e.g. `displayId`
and the semantic-identifier model are expected **absent** in 16.6:

```python
Assumption("displayId field", "field", "displayId",
           subtree="lib/api/v3/work_packages",
           expect={"16.6": False})
```

When the report flags an `UNEXPECTED` difference:

- If the client genuinely needs a symbol that vanished → the client must change.
- If the difference is expected for that version → add/adjust the `expect` entry.

Note two source conventions the assumptions account for: endpoint paths are
checked against `lib/api/v3/utilities/path_helper.rb` (the canonical path list,
more robust than per-resource `*_api.rb` files), and response fields use the
Ruby property name (snake_case, e.g. `lock_version`) which the representer
renders as camelCase JSON (`lockVersion`).
