# API source-check

Four tools that keep this MCP honest against the OpenProject API:

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

- **`error_keys.py`** — lists, per entity and pinned version, every attribute a
  rejected write can name in an error (`_embedded.details.attribute`), the message
  templates that quote a value, and the `errors.add` sites with a computed name.
  The client judges a server error by that attribute (`app/policies/error_fields.py`);
  the committed snapshot `error_keys.json` records what the sources said, and
  `tests/test_error_keys_oracle.py` requires every attribute in the table or waived.

## Version floors

`floor_catalog.py` lists every version floor of the server (a `call_version_gated` call or a hand-built "requires
OpenProject X.Y" message) with the OpenProject routes behind it and the first release whose source has each. `check_api.py`
turns every route and every behaviour proof (`BEHAVIOUR_ROUTES`: a symbol that marks a version a description names) into an
assumption (absent before its release, present from then on), so a floor the pinned sources do
not bear out fails the matrix (it proves that the symbol exists from the release on, not that it is exactly the verb and
path an adapter calls); the sort and group column floors (`COLUMN_FLOORS`) are checked the same way where a source
symbol is known, and two (`sprint`, `backlog_bucket`) carry a `gap` instead. `tests/unit/test_version_floor_catalog.py` runs
in CI without the sources and ties the services, the tool descriptions and the tool rows of `docs/tools.md` to the
catalog: a version a description names that is no floor of the tool is a behaviour change and sits in
`NOT_A_ROUTE_FLOOR` with what it changes. A floor above its newest route needs a `reason`.

## Representer snapshot

`representer_locations.py` reads a Ruby representer and says where it renders each name: `property`, `link`,
`embedded`, `link-member:<link>` (a member of a link object, e.g. `displayId` of the work package `parent`) or
`value-member:<property>` (`raw`, `html`, `format` of a formattable property). It reads these DSL forms of the pinned
sources: `property` and its date and duration variants, the schema macros (`schema`, `schema_with_allowed_*`,
`schema_property`), `associated_resource(s)`, `associated_visible_resource(s)`, `associated_project`,
`polymorphic_resource`, `resource(s)`, `resource_link`, `link`/`links` blocks (a bare link keeps its rel as written,
`link :auth_source` renders `auth_source`), `link_without_resource`, `associated_user_link`, `self_link`,
`collection`, `embedded`, `custom_field_injector`, `def _type`, `embedded: true`, custom `link: ->` lambdas, and
Enterprise conditions (`if:`, `show_if:`, `skip_render:`, `render_if:`, `cache_if:`). A macro line whose name is
computed (`property setting`, `property :"copy_#{id}"`) declares nothing readable; the snapshot lists it under
`unparsed` for its path so a guard has to waive it knowingly. `check_field_completeness.py` filters the output to the
macros it always knew; a golden test compares the two over every representer file of every pinned version.

How to read the snapshot. For a representer path, a link and a version: if `link-member:<link>|*` covers the
version, the members listed for it are known and any other member read needs a waiver; otherwise the members are
exactly the ones listed for that version; if none is listed, they are `href` and `title` (`LINK_OBJECT_MEMBERS`). `*`
is written when a helper, a factory, `resource_link`, a `do` lambda, a raw `sql:` link or anything other than hash
literals builds the link object (a blacklist of constructions, not a proof: a link built by a helper call in one
branch of an `if` is not detected). Link members come from the hash literals, the options on the macro line (`method:`)
and, in a SQL representer, from the DSL's own rule (`href`, a `title` unless `title: -> {}`, every other option). `customField*` is a wildcard name for the
custom field properties and links that `custom_field_injector` adds at runtime. A patch file that an engine applies
shows up twice (as its own path and as `<engine.rb>#extend_api_response:<representer>`); a patch applied through
`included` or `prepend`, and the parse-only `nested` blocks, are not followed. A property whose getter builds a
`Formattable` itself gets no `value-member` entries. The BCF API (`modules/bim/.../bcf`) is not API v3 and is left out.

`check_adapter_reads.py --write` regenerates `representer_fields.json`: per representer path (a `*representer*.rb` file, a base class under an API subtree that declares fields such as
`lib/api/decorators/collection.rb`, or `<engine.rb>#extend_api_response:<representer>` for the fields an engine adds
inline or through a patch module) every (location, wire name) with the pinned versions that render it. `--check` regenerates and diffs, and is a release step:
CI cannot read the sources, but it asserts that the snapshot header equals the pinned versions and tags of
`fetch-sources.sh`, so a bumped pin without a regeneration fails. It also prints representers that end before the
newest pinned version and a basename that continues at another path.

## Which keys the client reads

`adapter_reads.py` is a small abstract interpreter over the source tree of the client. It follows a response body from
where it enters the code to every `.get("k")`, `["k"]` and `"k" in x` on it, and reports each read with its path from
the body (`("_links", "project")`, key `href`). A body enters at a transport call (`get_json`, `post_json`,
`patch_json`, `delete_json`, `post_multipart`; `request_raw` returns no body), at a port method or record field that
holds one, and at a function parameter a row binds to a body. `wire_sources.py` lists the members that can hold a body:
every Protocol method return and parameter, and every dataclass, Protocol or TypedDict field, whose declared type is
`Any`, `object` or a container of them (callbacks included) must be classified there as a body or as request-side, or
its test fails; the parameters are declared member by member (`_WIRE_PARAMETERS`, `_REQUEST_PARAMETERS`), with no
default. A parameter or return declared only as a class of the package is an object and carries no origin; a scalar, a
union with a raw mapping and `Any` keep the provenance of what was handed to them, because an `Any` value may have been.
Types come from annotations, never from variable names; a type variable or an alias is resolved, never taken as a class.
Reads that start from an external call are invisible except the JSON decode entry points; see the limits in the module
docstring.

A helper is summarised once and checked per caller, so `link_title(x)` is read against the link each caller passes; a
function a row binds (a normalizer) keeps its own reads. What the model cannot follow is a finding, not a skip, and a
value it loses stays tied to the parameters it came from, so a helper only counts against the callers that bind a body to
them. A finding is reported once, at the place it happens:

- `unresolved`: a call into unknown code with a body as argument, `.items()`, `setdefault`, a dynamic key, `match` on a
  body, a body held on `self` or stored in a literal container, a recursive call chain (no partial summary of a cycle is
  used), a body nested deeper than the path cap;
- `unsupported`: code the model does not analyse (a def under a module-level statement, a nested class, `global`);
- `unclassified`: a read on a value of unknown origin, such as the parameter of a nested function;
- `unbound`: a function that reads a parameter no caller binds to a body and no row binds, directly or through callers
  that are themselves unbound.

`check()` compares a read with the snapshot for the representers of a row (`Row(compose, embedded, waivers,
conditional)`): `ok`, `partial` (some pinned versions only), `missing` (a key no pinned version renders), `gated`
(rendered only for an Enterprise token, so never on Community), `open` (the link's members are unreadable), `opaque`
(below what the snapshot holds), `ambiguous` (a membership test on a property, which may be a substring test) and
`waived`; `stale_entries` reports waivers and conditional entries no read needs, and `apply_exemptions` matches findings
to per-finding exemptions (kind, function, reason pattern and the text of the source line, with an occurrence number
when the same line text occurs more than once in a function). The five-adapter crosswalk test (`tests/test_adapter_reads_crosswalk.py`) is the acceptance table with the
first version that renders each partial key; none of its reads is `missing` or `gated`.
`python tools/api-check/adapter_reads.py [--src tree] [--findings]` prints the counts of a tree.

## Usage

```bash
tools/api-check/fetch-sources.sh        # clone OP source for each version; re-run anytime to sync sparse-checkout paths

python tools/api-check/error_keys.py --check   # the error-attribute snapshot against the sources; --write rewrites it

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
query-filter key from `client.py` and checks each across all 17 versions, so no
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
`op-sources/<version>/`, one level above this repo (the shared umbrella
directory) — not part of this repo, so nothing to gitignore here.
`OPENPROJECT_SOURCES_DIR` moves that directory for the fetch script and all
three check scripts alike (for example from a worktree elsewhere), and
`OPENPROJECT_SOURCES_REPO` replaces the upstream repository, which the unit
tests use to exercise the script against a local repository. Two
different refresh cases:
- **Widened `SPARSE_PATHS`** (a new `Assumption` needs a subtree not yet
  fetched): just re-run the script. For a version already cloned, it now runs
  `git sparse-checkout set --no-cone` again with the current `SPARSE_PATHS`,
  which pulls in any newly-added path in place (the clones use
  `--filter=blob:none`, so git lazily fetches only the newly-needed blobs) —
  no deletion needed.
- **Bumped pinned tag** (a `VERSIONS` entry now points at a different release):
  `sparse-checkout set` does not move the checked-out commit, only which paths
  are populated from it. Delete the corresponding `op-sources/<version>/`
  directory (in the umbrella directory) and re-run so it re-clones at the new
  tag. The check scripts enforce this: every pinned version must be checked
  out at exactly its pinned tag (`op_sources.py` reads the `VERSIONS` list
  and asks `git describe --tags --exact-match`), otherwise they stop with
  exit code 2 before auditing anything. Directories under `op-sources/` that
  are not pinned versions are ignored.

## What it does and does not catch

- **Catches:** a path/field/filter the client uses being renamed or removed in a
  version (symbol no longer present where expected).
- **Does NOT catch:** a symbol that still exists but whose *behaviour* changed.
  That requires running a real instance — see [`docker/test/`](../../docker/test/).

## Pinned versions

`fetch-sources.sh` clones the latest patch of every minor release from 16.0 to
17.9 (`VERSIONS` array), so the check runs as a **version matrix**: each symbol's
presence is shown across all 17 columns, pinpointing exactly which release
introduced or dropped it. As of this writing:

```
16.0  16.1  16.2  16.3  16.4  16.5  16.6  17.0  17.1  17.2  17.3  17.4  17.5  17.6  17.7  17.8  17.9
```

The matrix confirms that of every API symbol the client uses, only `displayId`
(and the semantic-identifier model) changed across this range — both introduced
in **17.4** (`present_from="17.4"`); everything else is stable back to 16.0.

Bump / extend the `VERSIONS` array as new releases land, then re-run all
scripts. A symbol that appears or disappears in an unexpected version fails the
check until its `present_from`/`expect` allowlist is updated.

## Maintaining the assumptions

Each checked symbol is an `Assumption` in `check_api.py`. Known, intentional
version differences are encoded inline via the `expect` field, e.g. `displayId`
and the semantic-identifier model are expected **absent** in 16.6:

```python
Assumption("displayId field", "field", "displayId", subtree="lib/api/v3/work_packages", expect={"16.6": False})
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
currently 17.9). Each field a CE representer declares is classified:

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
