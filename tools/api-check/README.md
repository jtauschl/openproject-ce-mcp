# API source-check

Three tools that keep this MCP honest against the OpenProject API:

- **`check_api.py`** — verifies, offline, that the API symbols the client depends
  on (paths, fields, filters) still exist in each OpenProject version. Guards
  against silent breakage when OpenProject renames or removes part of its API —
  the failure mode the first semantic-identifier resolver hit (it relied on the
  `subject_or_id` filter, which exists but does not match the project-based
  `displayId` form).
- **`check_coverage.py`** — reports how much of the Community Edition API the
  client covers, combining the source inventory, the client's used resources,
  and an optional live CE probe. Writes `COVERAGE.md`.
- **`check_field_completeness.py`** — the reverse direction from `check_api.py`:
  enumerates every data-bearing field a CE representer declares for a checked
  resource and reports which ones this client has never modeled at all, instead
  of verifying fields it already depends on still exist. Writes
  `FIELD_COMPLETENESS.md`.

## Usage

```bash
tools/api-check/fetch-sources.sh        # clone OP source for each version; re-run anytime to sync sparse-checkout paths

python tools/api-check/check_api.py     # curated version matrix; exit 1 on unexpected drift
python tools/api-check/check_api.py --verbose   # also list matching symbols
python tools/api-check/check_api.py --all       # auto-map EVERY resource + filter the client uses

# Coverage: set OPENPROJECT_BASE_URL / OPENPROJECT_API_TOKEN to enable the live
# CE probe (a CE instance), otherwise the live column is skipped.
python tools/api-check/check_coverage.py          # coverage matrix to stdout
python tools/api-check/check_coverage.py --write  # also (re)write COVERAGE.md

python tools/api-check/check_field_completeness.py             # untriaged findings + summary tally; exit 1 if any
python tools/api-check/check_field_completeness.py --verbose   # full per-field table, all statuses
python tools/api-check/check_field_completeness.py --write     # also (re)write FIELD_COMPLETENESS.md
```

`--all` is the **full** version map: it auto-extracts every endpoint resource and
query-filter key from `client.py` and checks each across all 14 versions, so no
access is missed as the client grows. It flags anything introduced after 16.0
(e.g. `workspaces` from 17.0 — used by the favorite tools — and `project_phases`
from 16.1). Resources whose v3 API lives in a separate module engine
(`documents`, `file_links`, `grids`, `job_statuses`, `time_entries`) are reported
as `module` rather than source-verified: `fetch-sources.sh` does fetch each
module's `lib/api/v3` subtree, but this tool doesn't parse per-module
route/representer files, only the top-level `lib/api/v3` tree — they are CE
and verified at runtime instead (see `docker/test/`). The curated default run
(without `--all`) stays the pass/fail gate; `--all` is the exhaustive audit.
Maintain `RESOURCE_ALIASES` / `FILTER_ALIASES` / `MODULE_RESOURCES` when a name
doesn't line up.

`check_coverage.py` classifies each of OpenProject's ~76 v3 resources as
**covered**, **GAP (CE)** (a plain top-level CE resource we don't use yet),
**subresource** (reached via a parent path), **enterprise**, or **internal**.
The CE/Enterprise split is not cleanly derivable from source (heterogeneous
feature-flag / `EnterpriseToken` guards), so a curated `CLASSIFICATION` table in
the script reconciles edge cases and the live probe is the tie-breaker. Update
that table when a resource is reclassified.

`fetch-sources.sh` makes shallow, sparse clones (only the API subtrees) into
`.op-sources/<version>/`, which is gitignored. Two different refresh cases:
- **Widened `SPARSE_PATHS`** (a new `Assumption` needs a subtree not yet
  fetched): just re-run the script. For a version already cloned, it now runs
  `git sparse-checkout set --no-cone` again with the current `SPARSE_PATHS`,
  which pulls in any newly-added path in place (the clones use
  `--filter=blob:none`, so git lazily fetches only the newly-needed blobs) —
  no deletion needed.
- **Bumped pinned tag** (a `VERSIONS` entry now points at a different release):
  `sparse-checkout set` does not move the checked-out commit, only which paths
  are populated from it. Delete the corresponding `.op-sources/<version>/`
  directory and re-run so it re-clones at the new tag.

## What it does and does not catch

- **Catches:** a path/field/filter the client uses being renamed or removed in a
  version (symbol no longer present where expected).
- **Does NOT catch:** a symbol that still exists but whose *behaviour* changed.
  That requires running a real instance — see [`docker/test/`](../../docker/test/).

## Pinned versions

`fetch-sources.sh` clones the latest patch of every minor release from 16.0 to
17.6 (`VERSIONS` array), so the check runs as a **version matrix**: each symbol's
presence is shown across all 14 columns, pinpointing exactly which release
introduced or dropped it. As of this writing:

```
16.0  16.1  16.2  16.3  16.4  16.5  16.6  17.0  17.1  17.2  17.3  17.4  17.5  17.6
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

## `check_field_completeness.py` — the reverse-drift guard

Checks six resources (work_package, user, category, project, version,
membership) against a single pinned source version (`SOURCE_VERSION`,
currently 17.6). Each field a CE representer declares is classified:

- **COVERED** — modeled on the resource's `Summary`/`Detail` dataclass(es) in
  `models.py`.
- **EXCLUDED** — deliberately not modeled, per a curated, reason-bearing
  `FieldExclusion` entry in `check_field_completeness.py` (Enterprise-only,
  large embedded object, custom-field-pending, or other internal/write-only
  field).
- **UNTRIAGED** — neither of the above: real drift requiring a decision (add a
  model field, or add a `FieldExclusion` with a reason). Exit code reflects
  only this — a green run (exit 0) is a claim that every upstream field has
  been consciously triaged, not that everything is exposed; a nonzero exit
  with a clearly documented `FIELD_COMPLETENESS.md` untriaged list is a valid,
  expected state, not necessarily a failure to fix before committing.

**Catches:** a new upstream field on a checked resource that's neither modeled
nor recorded in `EXCLUSIONS` — the class of drift `check_api.py` structurally
cannot see, since it only ever checks symbols someone already thought to add.

**Does NOT catch:** behaviour/semantics changes; dynamically-injected custom
fields (`customFieldN`, never statically declared in source — the utility that
injects them per-installation, `custom_field_injector.rb`, is DB-config-driven,
not source-derivable); module-`prepend` conditional fields (e.g. Backlogs'
`position`/`story_points` patches on work packages — deferred, not checked);
Enterprise gating (confirmed not reliably derivable from source — only one
inline `EnterpriseToken.allows_to?(...)` guard exists tree-wide across the
fetched subtree, on an unrelated resource — so Enterprise exclusions are
hand-curated against this server's own documented EE-only list, not grepped);
runtime-hidden fields (`app/policies/hidden_fields.py`'s `OPENPROJECT_HIDE_*`
mechanism is an orthogonal axis — it can only hide/reveal a field that's
already a declared dataclass field, so a modeled-but-runtime-hidden field
still counts as COVERED here, not UNTRIAGED).

**A resource's field set can span more than one file — this composition is
hand-curated, not auto-resolved.** CE representers use Ruby inheritance and
module `include` to declare fields across files (e.g. `user` pulls in
`principal_representer.rb` via `UserRepresenter < PrincipalRepresenter`;
`work_package` pulls in two mixin files, `attachable_representer_mixin.rb` and
`timestamped_representer.rb`). Each `ResourceCheck.source_files` tuple in
`check_field_completeness.py` was built by manually reading its representer's
own `class ... < ...`/`include ...` lines and following any that themselves
declare `property`/`date_property`/etc. macros (a module that only provides
the macro *DSL*, like `API::Decorators::DateProperty`, is not a field source
and is not listed). If OpenProject changes a checked resource's base class or
adds/removes a field-bearing mixin, `source_files` must be manually
re-verified — the tool does not parse Ruby class/include graphs itself. The
same maintenance discipline applies to `NAVIGATION_LINKS` (which HAL `link`
declarations are pure navigation/action affordances vs. genuine single-value
data relations, like `category`'s `link :defaultAssignee` or `user`'s
`link :auth_source`) — an unrecognized link defaults to being treated as a
candidate data field (surfacing as UNTRIAGED) rather than being silently
ignored, so a real new data-only link can never go permanently unnoticed the
way a blanket "all links are navigation" rule would allow.
