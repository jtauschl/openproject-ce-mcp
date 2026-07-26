# Domain migration runbook

<p align="center">
  <img src="../img/architecture.jpg" alt="Five modular server layers connected by a guarded bidirectional request flow." width="960">
</p>

Step-by-step process for migrating one more still-flat `client.py` domain into
the layered `app/` architecture described in [architecture.md](architecture.md).
Written so it can be handed to a fresh session (human or agent) as a
self-contained starting brief — see "Prompt for a fresh session" at the
bottom for a ready-to-paste version.

Ten domains are migrated so far: Versions (pilot), Projects, Memberships,
News, Documents, Wiki Pages, Categories, Views, Grids, Sprints. ~25 remain, all
still flat in `client.py`. This runbook distills what each of those ten
migrations actually needed, including mistakes found and fixed along the
way — follow it literally, don't re-derive the process from scratch.

## 0. Pick the next domain

Prefer a domain that:

- is project-scoped only (depends on the already-migrated Project resolution,
  not the still-flat work-package resolution machinery) — check
  `client.py` for whether the domain's methods call
  `_resolve_work_package_id`/`_work_package_ref` anywhere; if so, defer it
  until Work Packages itself migrates. **Actually grep for the call, don't
  infer it from the domain's name or its apparent similarity to a
  work-package sub-resource** — the Sprints migration's own first-pass
  screening disqualified Boards for this reason without checking, and the
  claim was wrong (Boards scopes via a plain `_links.project` link, the
  same shape as Views/Documents, with zero `_work_package_ref` calls
  anywhere in its methods).
- is small-to-medium in `client.py` line count (rough guide: under ~150
  lines including its `normalize_*` methods)
- is named as a candidate in this doc's "Future split points" list in
  [architecture.md](architecture.md)

Grids was the last domain explicitly named as a "natural next pick" in this
doc and architecture.md; with it migrated, Sprints was picked via a fresh
screening against the three criteria above (not a pre-named shortlist) —
Reminders/Notifications/File Links were disqualified for calling
`_work_package_ref`/fetching a work package to derive project scope;
Statuses/Priorities/Types are global lookups with no project link or
allowlist enforcement at all; TimeEntryActivities is a scan-all-projects
fallback shape entangled with `list_projects`/work-package form probing.
Boards was screened too and found NOT disqualified by the work-package
criterion (it scopes via a plain `_links.project` link, same shape as
Views/Documents) — it simply wasn't the domain picked this round, and
remains a plausible future candidate. With Sprints now migrated, the next
domain needs its own fresh evaluation against the three criteria above; the
~25 remaining still-flat domains haven't been individually screened yet.
Project Lifecycle Phases already migrated as part of Projects (its three
`client.py` methods delegate to `self._project_service`) — it is not a
separate still-flat candidate, despite looking like one from its own
top-level methods.

## 1. Read the real source before planning

Do not trust a plan's summary of "the established pattern" — read, in this
order, immediately before writing anything:

1. The domain's current flat implementation in `client.py` (its `list_*`/
   `get_*`/`create_*`/`update_*`/`delete_*` methods, its `normalize_*`
   methods, and any `_ensure_*_payload_allowed`/`_*_payload_allowed`
   helpers).
2. The closest already-migrated sibling's full four-layer implementation
   (port, adapter, policy, service) — pick by shape, not recency: a
   full-CRUD domain should model on Memberships/Projects/Versions, a
   read+update-only domain on Documents, a domain with no `/form` endpoint
   on News.
3. `src/openproject_ce_mcp/app/policies/scope.py` — confirms the exact
   allowlist/masking primitives available (`ensure_project_link_allowed`,
   `ensure_project_write_link_allowed`, `project_link_payload_allowed`,
   `payload_allowed`).
4. `src/openproject_ce_mcp/app/services/project_scoped_list.py` — if the new
   domain does client-side "fetch everything, then filter by resolved
   project ref" list filtering (as opposed to a server-scoped or
   project-href-scoped list), reuse this module's `trim_text`/
   `resolve_project_filter_candidates`/`summary_matches_project_candidates`
   instead of copying them into the new service. Two domains (News,
   Documents) independently duplicated this exact logic before it was
   extracted — don't add a third copy.
5. `grep -rl "<domain_name>" tests/unit/` for an EXISTING client-level test
   file exercising the domain's still-flat `client.py` methods end-to-end
   (e.g. `test_versions_and_sprints.py` for Versions/Sprints,
   `test_hidden_fields.py`'s per-entity tests) — these predate the
   migration, are not named after the new `app/` layer's conventions, and
   are trivial to miss if you only look for `test_app_*` files. They are a
   ready-made behavioral spec of the exact current behavior to preserve
   (read them before writing the new Adapter/Service, not after), and they
   must still pass unmodified once the facade delegates — do not delete or
   rewrite them. The Sprints migration's own plan missed
   `test_versions_and_sprints.py` entirely on the first pass; only a
   separate self-review step caught it.

**Verify, don't assume, on these two specific traps** (both cost real
rework in the Documents migration):

- **A duplicated private helper can itself have drifted from its real
  original.** Before copying a small helper (`_trim_text`,
  `_extract_formattable_text`, `_link_to_web_url`, etc.) from the sibling
  you're modeling on, diff its body against `client.py`'s actual
  module-level version, not just against the sibling's copy. `httpx_news_api.py`'s
  local `_extract_formattable_text` was missing a `.get("html")` fallback
  that `client.py`'s original and the Project/Version adapters all have —
  undetected through News' own migration and its post-implementation
  review, and would have propagated into Documents if copied verbatim.
- **An old domain's "double masking" of hidden fields is usually
  equivalent to the new Service-only pattern, but verify the predicate,
  don't assume.** If the old `client.py` code masks a field both via an
  outer `_apply_hidden_fields`/`apply_hidden_fields` object-stamp AND an
  inner `_visible_formattable_text`/hide-aware extraction at the field
  level, confirm both resolve to the same `field_hidden(entity, field_name,
  ...)` call with the same entity string before dropping the inner check
  in the new adapter (the new pattern: adapter extracts unconditionally,
  Service's `_stamp` is the sole masking point). If the two checks use
  DIFFERENT entity strings, that's a real bug in the old code to fix during
  the migration, not a pattern to preserve.

## 2. Implement the four layers

In this order (each depends only on the previous):

1. **Port** — `app/ports/<domain>_api.py`: a frozen `<Domain>Record`
   dataclass (`summary`, a `to_detail` field, `<parent>_link` for the raw
   HAL link the Policy layer needs) and a `<Domain>Api` Protocol. **This is
   the shape for a domain with both a list and a get endpoint returning a
   parent-linked resource — it is not universal, don't force-fit it.** A
   get-only, no-list domain (Wiki Pages) has exactly one method and one
   result shape, no separate `summary`/`detail` split at all (there's no
   list-row truncation to diverge from in the first place). A list-only
   domain with no single-item GET (Categories) has the Service synthesize
   `get()` by filtering `list()`'s results in Python, so the Record carries
   no `to_detail`. A domain whose raw payload carries no reliable
   identifier/title on its parent link (Grids) must carry the RAW link
   dict, not just an extracted href string, since the allowlist check needs
   more than `href` off it. Check the closest sibling BY SHAPE (per step 1
   above) for the actual Record fields to include, not this generic
   description. Make `to_detail` a **lazy callable**
   (`Callable[[], <Domain>Detail]`), not a precomputed field, whenever the
   domain's summary/detail normalizers apply different truncation limits to
   the same raw text — check by grepping whether the Service's `list()`
   path ever reads `.detail`; if it never does, eager computation wastes a
   second extraction pass on every list row (verify this in the ADAPTER,
   not just architecturally: an eager `detail` field built by re-running the
   summary's own `normalize_*` function on the raw payload a second time is
   just as wasteful as a needlessly lazy one — build it as a field-copy off
   the already-computed `summary` instead, e.g. `version_api.py`'s
   `summary_to_detail`; this exact double-normalization bug was found
   independently in both Views' and Sprints' adapters during the Sprints
   migration's step-6 audit). Only omit `commit_create`/`delete` from the
   Protocol if the OpenProject API genuinely has no such endpoint (verify
   against the API docs or an existing read-only/limited-CRUD note in
   `docs/claude.md` — don't assume from `client.py`'s current shape alone,
   since a missing write method there could just mean it was never
   implemented, not that it's impossible).
2. **Adapter** — `app/adapters/httpx_<domain>_api.py`: the concrete
   `Httpx<Domain>Api`, plus module-level `normalize_<domain>`/
   `normalize_<domain>_detail` HAL→model functions (pure translation, no
   hidden-field awareness — see the masking note above). **`_trim_text`/
   `_id_from_href`/`_link_title` are NOT to be locally duplicated anymore** —
   they were extracted into `app/adapters/_text.py` once the sixth domain
   (Wiki Pages) migrated (this project's own "unify once past the 3rd
   identical copy" convention), and every adapter since imports them from
   there (`from ._text import trim_text as _trim_text`, etc., plus
   `SUBJECT_LIMIT`). Diff the shared version against `client.py`'s real
   module-level original before trusting it, per the trap above, but reuse
   it — do not re-copy it locally. `_can_update_from_links`/
   `_delimit_user_content`/`_extract_formattable_text` (and
   `_normalize_validation_errors`) genuinely DO stay local, deliberately
   duplicated per adapter: these differ meaningfully between domains (see
   `httpx_grid_api.py`'s module docstring for a concrete example of how two
   adapters' versions diverge) and unifying them would silently change
   behavior, not just remove duplication. Two more package-root
   shared-kernel modules exist for the same reason, outside the adapter
   layer: `app/api_href.py` (an `api_href(relative_path, *, api_prefix)`
   helper, replacing what used to be a duplicated `_api_href` method per
   Service) and `app/form_result.py` (a shared `FormResult` dataclass,
   aliased under each domain's own `<Domain>FormResult` name in its port
   module). Check `app/{errors,pagination,api_href,form_result}.py` for an
   existing helper before writing a new one, the same way you'd check
   `_text.py` for adapter helpers.
3. **Policy** — `app/policies/<domain>_policy.py`: usually a one-line
   `<domain>_payload_allowed(payload, *, settings, project_id_to_identifier)`
   delegating to `scope.project_link_payload_allowed(payload,
   link_key=<key>, ...)`. Skip this file entirely if the domain never needs
   client-side list-filtering (e.g. Memberships fetches an already
   project-scoped href server-side and calls `ensure_project_link_allowed`/
   `ensure_project_write_link_allowed` directly in the Service instead).
4. **Service** — `app/services/<domain>_service.py`: depends on the Port's
   Protocol (never the concrete Adapter — this is enforced by
   `tests/test_architecture_boundaries.py`), the Policy, and
   `app/ports/project_ref.py`'s `ProjectRefResolver` seam (reuse the
   existing seam; do not build a dedicated Resolver unless the domain's id
   is a genuine semantic reference rather than an already-numeric id
   validated by `tools.py`). Only build a full `_WriteOutcome`/
   `_finalize_write` preview/commit state machine (Memberships/News/
   Versions style) if the domain has 2+ write actions sharing the same
   result shape; a domain with exactly one write method (update-only, like
   Documents) should stay a single flat method — a shared state machine for
   one call site is pure indirection.

## 3. Wire into `client.py`

- Add three alphabetically-sorted imports (adapter, port, service).
- In `OpenProjectClient.__init__`, construct `self._<domain>_api` and
  `self._<domain>_service`, next to an existing similar block.
- Replace each public method body (`list_<domain>`/`get_<domain>`/...) with
  a one-line delegation to `self._<domain>_service.*` — **signatures stay
  identical**, this is the facade guarantee.
- Delete the now-dead `normalize_<domain>`/`normalize_<domain>_detail`
  methods and any `_ensure_<domain>_payload_allowed`/
  `_<domain>_payload_allowed`/`_ensure_<domain>_write_payload_allowed`
  helpers from `client.py`.
- **`tools.py`/`server.py` need zero changes** — MCP tool registration is
  name/flag-based and domain-agnostic. If you find yourself editing either
  file, stop and re-check the plan.

## 4. Tests

- `tests/unit/test_app_httpx_<domain>_api.py` — adapter tests against
  `httpx.MockTransport`: list/get/commit_* request shape, the lazy-detail
  divergence (summary and detail must produce different lengths from the
  same long raw text), and the `.html`-fallback case if the domain has a
  formattable text field.
- `tests/unit/test_app_<domain>_service.py` — Service tests against a fake
  API: list (including project-candidate filtering and the domain's ACTUAL
  search-field set — check `client.py`'s original `post_filter`, don't
  assume it matches a sibling's), get (hidden-field masking, read
  allowlist), every write method (preview-without-commit, commit-with-mask,
  write-allowlist denial, hidden-field-write rejection). Include an
  entity-scope regression test (`get_<field>_hidden_by_<domain>_scope_not_project_scope`)
  proving masking is keyed to the domain's own entity string, not a
  same-named neighbor — this exact bug class (`entity="project"` instead of
  the domain's own name) has hit News and Documents' pre-migration code
  independently.
- `tests/test_architecture_boundaries.py` — add
  `test_<domain>_service_binds_the_api_param_to_<domain>_api_specifically`,
  a non-generalized pin that the Service's `api` param is typed exactly as
  the domain's Port Protocol, not the concrete Adapter.
- Remove any now-dead test in `tests/unit/test_text_and_shape_utils.py`
  that calls `client.normalize_<domain>*` directly (these no longer exist
  post-migration); re-anchor its assertion at the Service layer instead.
- `tests/integration/test_<domain>.py` — CRUD (or the subset the API
  supports) against a live instance. If the domain has no create endpoint
  but DOES have a `list_*` call, source an id via that list call and skip
  gracefully if the test project has none (don't fail the suite over
  missing fixture data you cannot create). **If the domain has neither a
  create endpoint NOR a list endpoint** (a get-only domain like Wiki
  Pages, where the single-item id is a known, stable, non-numeric slug
  rather than something discoverable via listing), there may be no
  practical way to source a live id at all — it is acceptable to skip
  writing this file rather than force a live test against a hardcoded or
  environment-specific id; confirm this explicitly rather than silently
  omitting the file with no note (Wiki Pages shipped with no
  `tests/integration/test_wiki_pages.py` at all, undocumented as a
  decision until this runbook entry).

Run `uv run pytest`, `uv run mypy src/openproject_ce_mcp`, `uv run ruff
check .`, `uv run ruff format --check .` — all four must be clean before
moving on.

## 5. Update `docs/architecture.md`

Extend the "Layered architecture (...)" heading and domain list, and add a
short note for anything genuinely new about this domain's shape (no
dedicated Resolver, lazy `to_detail`, a new write-state-machine shape,
etc.) — follow the style of the existing Versions/Projects/Memberships/
News/Documents entries. Update the domain count and the "Future split
points" list (remove the domain you just migrated, keep the rest current).

## 6. Post-implementation self-audit — scope this to ALL migrated domains, not just the new one

Run four review passes (in parallel, if using subagents) over
`app/{ports,adapters,policies,services}/*.py` for **every already-migrated
domain**, not only the one just added:

1. **Reuse/simplification** — duplicated logic across domains, especially
   near-identical wrapper files (a 3rd domain sharing an existing pattern
   is the signal that it's worth a shared helper, not still "just two
   similar files"). Also check whether the new domain reused existing
   seams/helpers correctly or reinvented something.
2. **Efficiency** — confirm the new `to_detail` is genuinely lazy and never
   called from a `list()` path; check for N+1 resolver calls; check for the
   eager-vs-lazy class of bug anywhere else.
3. **Security** — for every write/delete method: the write-enablement check
   and the mutating call happen only inside `if confirm:`; the write
   allowlist check uses the just-fetched resource's own project link, not
   a caller-supplied value; `list()` filters against the read allowlist
   before pagination truncates; every hidden-field write rejection happens
   before the field enters the payload; every href-derived URL construction
   has a same-origin check.
4. **Test-contract/altitude** — for every Service method that delegates a
   security-relevant check to an injected seam, is there a test asserting
   the seam receives the right arguments (not just that the return value
   looks right)? Is there an entity-scope regression test for hidden-field
   masking? Are write-allowlist-denial tests present for every write
   method, in every domain, not only the newest?

The reason to widen scope beyond the new domain: a narrow review only ever
sees ONE of several near-identical files at a time and cannot spot
cross-sibling duplication or a pre-existing gap in an older domain's test
file. This is how the Documents migration found — and fixed the same
session — that `document_policy.py`/`news_policy.py`/`version_policy.py`
were near-duplicates, that `document_service.py` had copy-pasted three
helpers from `news_service.py`, and that `VersionService` had zero
allowlist-denial tests for `get`/`update`/`delete` despite that gap
predating Documents entirely.

**Fix every real finding in the same session**, including in sibling
domains — don't file a follow-up ticket for something already understood
and cheap to fix now. Re-run the full test/mypy/ruff suite after fixes.

## 7. Close out

- Find and close the tracker ticket for this domain (search the tracker
  for the domain name; the bulk-created migration tickets follow the
  pattern "Migrate the `<Domain>` domain to the layered app/ architecture").
  Add a summary comment covering what was migrated, the self-audit scope
  and findings, and what was fixed as a result — don't just flip the
  status.
- Commit in logically separate commits (the migration itself; any
  unrelated-but-found bugfix like the `.html` fallback; any cross-sibling
  consolidation; any backfilled test coverage) rather than one large
  commit — this keeps `git log`/`git blame` useful for the next migration.
- Do not push without a separate, explicit go-ahead.

## Prompt for a fresh session

Paste this (or something equivalent) to start the next migration cold,
without needing this conversation's history:

> Migrate the next still-flat domain in `client.py` into the layered
> `app/` architecture, following `docs/architecture-migration-runbook.md`
> step by step. Pick the domain per step 0's criteria (project-scoped
> only, no work-package-resolution dependency, small-to-medium size) unless
> I tell you which one to use. Read the real source (step 1) before
> planning — do not trust any prior summary of "the established pattern."
> After implementing and testing the new domain, run the step 6
> post-implementation self-audit scoped across ALL already-migrated
> domains, not just the new one, and fix every real finding in the same
> session, including in sibling domains. Close out per step 7: tracker
> ticket with a summary comment, logically separate commits, no push
> without my explicit go-ahead.
