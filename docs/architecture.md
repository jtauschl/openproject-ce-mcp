# Architecture

<p align="center">
  <img src="../img/architecture.jpg" alt="Five modular server layers connected by a guarded bidirectional request flow." width="960">
</p>

OpenProject CE MCP is intentionally small and flat. The codebase keeps transport, validation, policy checks, OpenProject API access, and MCP exposure in a few narrow layers instead of spreading them across many abstractions.

## Layout

```text
src/openproject_ce_mcp/
├── config.py             environment loading, validation, and safe defaults
├── client.py             OpenProject API client facade: auth, timeouts, most domains'
│                         pagination/normalization/error mapping, plus one-line
│                         delegations to app/ for the Versions and Projects domains
│                         (see below)
├── retry_transport.py    HTTP retry with backoff for transient failures
├── models.py             compact dataclasses returned to MCP clients
├── tools.py              validated MCP tool handlers
├── server.py             FastMCP server bootstrap and lifecycle management
├── setup_cli.py          the interactive `configure` command
├── doctor.py             the `doctor` diagnostics command
└── app/                  layered architecture -- see "Layered architecture" below
    ├── errors.py         shared exception types (re-exported from client.py)
    ├── pagination.py     shared pagination-envelope helpers (re-exported from client.py)
    ├── policies/         pure, no-I/O scope/allowlist/hidden-field checks
    ├── transport/        HttpxTransport (the only module here that imports httpx)
    ├── ports/            narrow per-domain API port Protocols
    ├── adapters/         concrete HTTP implementations of those ports
    ├── resolvers/        semantic-reference-to-id resolution + shared query logic
    └── services/         per-domain Application Services (orchestration + preview/confirm)
```

## Layers

### `config.py`

- Parses environment variables into an immutable `Settings` object.
- Applies safe defaults: project scope is fail-closed (empty/unset `OPENPROJECT_READ_PROJECTS`/`WRITE_PROJECTS` denies all project-scoped access, regardless of the write-category flags below), explicit page limits apply, and every mutation always requires `confirm=true` — there is no way to skip that confirmation.
- Centralizes scope interpretation for:
  - read gating
  - scoped write enablement
  - project read/write allowlists
  - hidden field configuration

### `client.py`

- Owns all OpenProject HTTP access.
- Maps HTTP and transport failures into project-specific exceptions.
- Normalizes HAL/JSON payloads into compact dataclasses from `models.py`.
- Implements write previews, form validation, and final confirmed writes.
- Enforces the runtime policy model:
  - read gate
  - scoped write gates
  - read/write project scoping
  - hidden field masking and write rejection

This is the main policy boundary of the project.

### `models.py`

- Defines the response shapes returned by the MCP tools.
- Keeps tool responses stable and compact.
- Decouples MCP-facing output from raw OpenProject payloads.

### `tools.py`

- Exposes MCP tools on top of the client.
- Validates and normalizes user input before it reaches the client.
- Translates internal exceptions into MCP-safe tool errors.

### `server.py`

- Wires FastMCP to the tool set.
- Creates the shared app context and client lifecycle.
- Keeps startup and shutdown logic isolated from domain code.

## Layered architecture (Versions, Projects, Memberships, News, Documents, Wiki Pages, Categories, Views, Grids, Sprints, Boards, Actions & Capabilities, Roles, Users, Groups)

`client.py` stays the small, flat facade described above for most domains, but fifteen
domains have been migrated into `app/` for a stricter layered structure: Versions
(`list_versions`, `get_version`, `create_version`, `update_version`,
`delete_version` — the original pilot, validating the pattern), Projects
(`list_projects`, `get_project`, `create_project`, `update_project`,
`delete_project`, `copy_project`, `get_project_admin_context`,
`get_project_configuration`, `add_project_favorite`/`remove_project_favorite`,
`list_project_phase_definitions`, `get_project_phase_definition`,
`get_project_phase` — the second migration, applying the pilot's lessons to a
domain every other domain's resolvers depend on), Memberships
(`list_project_memberships`, `get_membership`, `create_membership`,
`update_membership`, `delete_membership` — the third migration, the smallest
full-CRUD domain, coupled to Projects only through the pre-existing
`ProjectRefResolver` seam), News (`list_news`, `get_news`, `create_news`,
`update_news`, `delete_news` — the fourth migration, structurally close to
Memberships but with no `/form` endpoint, so its Service's preview/commit state
machine has no validation-error branch, and its `list()` fetches the single
global `news` collection client-side-filtered against the allowlist and an
optional project/search predicate, rather than a server-paginated
project-scoped endpoint), and Documents (`list_documents`, `get_document`,
`update_document` — the fifth migration, and the first **PATCH-only** domain: the
OpenProject v3 API exposes no create/delete endpoint for documents, so
`DocumentService.update()` is a single flat preview/commit method with no shared
`_WriteOutcome`/`_finalize_write` state machine at all — a state machine with
exactly one call site would add indirection with no reuse benefit. `update_document`
also takes no `project` parameter, so unlike News' create/update it never calls
`resolve_project_ref`; the write-allowlist check runs directly against the
already-fetched document's own `_links.project`), and Wiki Pages (`get_wiki_page`
— the sixth migration, and the first **get-only, single-shape** domain: OpenProject
v3 exposes neither a collection endpoint nor create/update/delete for wiki pages, so
`WikiPageApi` has exactly one method and `WikiPageService` has exactly one method
with no preview/commit state machine at all. `WikiPageRecord` carries no separate
`summary` shape and no lazy `to_detail` either — unlike every prior migration, there
is no list endpoint to produce list-row-truncated rows in the first place, so the
usual `to_detail`-laziness rationale doesn't apply. `WikiPageService` also has no
`ProjectRefResolver` seam and no dedicated policy file: `get_wiki_page` takes no
`project` parameter to resolve, and with no list to client-side-filter, `get()` calls
`scope_policy.ensure_project_link_allowed` directly on the already-fetched record's
own `project_link`), and Categories (`list_categories`, `get_category` — the
seventh migration, and the first **list-only API where the Service synthesizes
`get`**: the OpenProject v3 API exposes no single-category GET, so `CategoryApi`
has exactly one method (`list_for_project`) and `CategoryService.get()` calls its
own `list()` and filters by id in Python, exactly mirroring the pre-migration
`client.py` behavior. `CategoryRecord` carries neither a lazy `to_detail` (there is
no `normalize_category_detail` — one shape only) nor a `project_link` (an
individual category payload carries no own `project` HAL link, only
`defaultAssignee`); the project scope comes entirely from the caller-supplied
`project_ref`, so the read allowlist is enforced once, inside
`resolve_project_ref` itself, rather than per-record like Documents/Memberships.
Categories also has no dedicated policy file, for the same no-list-filtering-needed
reason as Wiki Pages), and Views (`list_views`, `get_view` — the eighth migration,
and the first domain with a **nullable project link**: a view need not belong to
any project at all. `list_views` is client-side fetch-all-then-filter (reusing
`project_scoped_list.py`'s `resolve_project_filter_candidates`/
`summary_matches_project_candidates`, same shape as Documents/News), but the
per-record allowlist check calls `scope_policy.ensure_project_link_allowed`/
`payload_allowed` directly rather than through a dedicated `view_policy.py`
wrapper — no new Policy code was needed, since `ensure_project_link_allowed`
already produces the correct deny-when-restricted-and-unlinked outcome for a
`None` link (an empty project-candidate set never matches a restrictive scope).
`ViewRecord.detail` is a precomputed field, not a lazy `to_detail` thunk, despite
having a separate detail shape: `normalize_view_detail` reuses every field from
`normalize_view` verbatim and adds exactly one extra field (`links`), with no
second/different truncation limit applied anywhere — there is nothing expensive
to defer), and Grids (`list_grids`, `get_grid`, `create_grid`, `update_grid`,
`delete_grid` — the ninth migration, and the first **full-CRUD** domain since
Memberships (every domain migrated in between was read-only or update-only). Grids
has its own dedicated `grid_policy.py` (unlike every no-policy-file domain since
Wiki Pages) because of a domain-specific carve-out: a grid scoped to
`/my/page` (the current user's own dashboard) is always allowed, read or
write, regardless of `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS`
— checked before any allowlist logic runs. `GridRecord` carries the raw
`scope` HAL link dict (not just the extracted href string), since the
allowlist check and `scope.project_candidates()` both read more than just
`href` off it. `list_grids`' `scope` parameter is a server-side exact-match
filter (narrowing, not a security boundary) — the per-item allowlist check
still runs client-side on every returned element regardless of whether a
filter was passed; unlike Documents/News/Views, Grids never resolves a
project ref at all, since `scope` is a raw href passed straight through), and
Sprints (`list_sprints`, `list_project_sprints`, `get_sprint` — the tenth
migration, and the first domain with **two list entry points**: `list()`
hits the global `sprints` endpoint (client-side allowlist + search filtering
only, no `project` parameter at all — unlike every other client-side-filtered
list, it never resolves a project ref); `list_for_project()` hits the
project-scoped `projects/{id}/sprints` endpoint, but still filters
client-side afterward, since a sprint shared into a project via Backlogs
sharing can be *defined* by a different, possibly disallowed project.
Because `SprintSummary`'s project-ish fields are named
`defining_workspace_id`/`defining_workspace` (not `project_id`/`project`),
`project_scoped_list.py`'s `summary_matches_project_candidates` (whose
Protocol requires the latter names) isn't used here — and isn't needed
anyway, since neither list method does client-side project-*candidate*
matching. Sprints has its own dedicated `sprint_policy.py` (unlike Views,
which needed none) because its allowlist check has two genuinely different
branches: a full `_embedded.definingWorkspace` payload (checked via
`scope.project_candidates(payload=...)`) when the API embeds one, or a raw
`_links.definingWorkspace` link (checked via
`scope.ensure_project_link_allowed`) otherwise — including a link
synthesized from the embedded object's own `_links.self` when only the
embedded form is present. `SprintRecord` carries both the resolved link and
the raw embedded payload for this reason. `SprintDetail` is a bare subclass
of `SprintSummary` with zero added fields, an even stronger case for eager
(non-lazy) `detail` computation than Views' one-extra-field detail. Sprints'
`url` field is a **web UI URL** (`base_url` + `sprints/{id}`), not an API
path like Views' `url` — the one place copying Views' adapter verbatim would
have been wrong. All three Service methods rewrap a bare `NotFoundError` from
the adapter with one of three distinct "Backlogs module" messages, mirroring
the existing `ProjectService` NotFoundError-rewrap precedent rather than a
new pattern), and Boards (`list_boards`, `get_board`, `create_board`,
`update_board`, `delete_board` — the eleventh migration, and the largest by
line count so far. Boards are backed by OpenProject's `queries` resource
(`_type: "Query"`, no dedicated `boards` endpoint) but are otherwise a
structural hybrid: list filtering follows Views'/Documents'/News' shape
(`ProjectRefResolver` + `project_scoped_list.py`'s
`resolve_project_filter_candidates`/`summary_matches_project_candidates`),
while the write-outcome shape (`_finalize_write`/`_WriteOutcome` for
`create`/`update`, an inline flat `delete()`) and the raw-dict
`BoardRecord.project_link` field follow Grids' full-CRUD shape.
`board_policy.py` is a thin delegation to
`scope.project_link_payload_allowed`/`ensure_project_write_link_allowed` (no
Grids-style bespoke carve-out — Boards has no `/my/page`-equivalent special
case). Two business rules have no sibling precedent and are ported
byte-for-byte from `client.py`: the groupBy/showHierarchies mutual-exclusion
(`create`/`update` auto-set `showHierarchies: false` only when `group_by` is
given and `show_hierarchies` wasn't explicitly passed), and the "global
board" rule (a board with no `project` requires BOTH
`OPENPROJECT_READ_PROJECTS` and `OPENPROJECT_WRITE_PROJECTS` fully open,
checked directly in `BoardService.create()`, not through `board_policy.py`,
since there is no link to check for an unscoped board). Write-allowlist
check ordering is preserved exactly as found in the original, inconsistent
flat code rather than unified: `update()` checks write-then-read, `delete()`
checks read-then-write. `BoardRecord.detail` is eager, built as a field-copy
off the already-computed `summary` (mirroring `view_api.py`'s/
`sprint_api.py`'s `summary_to_detail` pattern) rather than by re-running the
raw payload's normalizer a second time. `list()` has two distinct HTTP
shapes like Sprints, but the trigger condition differs — the
server-paginated `list_page` path is reachable only when no project/search
filter is given AND `read_projects` is fully open; an empty `read_projects`
tuple must still filter client-side down to zero results, not skip
filtering (a regression this domain's tests pin explicitly). The pure,
no-I/O `_resolve_query_reference_href` helper (used only for building
`group_by`/`columns`/`sort_by`/`highlighted_attributes` link hrefs) lives in
`board_service.py`, not the adapter — Services, not Adapters, own pure
write-payload-building logic elsewhere in this codebase too), and Actions &
Capabilities (`list_actions`, `list_capabilities` — the twelfth migration,
bundled as one ticket (OPM-276) since client.py placed them adjacently, but
architecturally a mixed pair in one Service. `list_actions` is the first
**genuinely project-independent** method migrated: every other domain's
Service (Projects aside, which has no domain above it to scope against)
depends on the `ProjectRefResolver` seam, but OpenProject's actions API has
no project concept at all, so `ActionCapabilityService` takes the seam only
for `list_capabilities`' benefit. `list_capabilities` IS project-scoped, but
only conditionally: `project` is one of two mutually-non-exclusive filters
(the other being `capability_id`), and `resolve_project_ref` is called only
when a `project` ref is actually given — `InvalidInputError` when neither is
supplied, ported verbatim from client.py's original guard.

`ActionRecord` carries only a `summary` field (Actions has no per-record
project link at all), but `CapabilityRecord` carries a raw `context_link`
dict alongside its `summary` — a step-6.5 Codex review found that
capability records genuinely carry a `context.href`
(`/api/v3/projects/{id}` or `/api/v3/workspaces/{id}`, per the OpenProject
API docs), not just a display title as the pre-migration client.py's own
`normalize_capability` implied. The pre-migration code only ever
allowlist-checked the caller-supplied `project` parameter (by resolving it
through `ProjectRefResolver`), never each individual RETURNED record's own
`context` link — a `capability_id`-only call skipped that check entirely,
letting a restrictive `OPENPROJECT_READ_PROJECTS` leak capability records
(and their project names/principals) for projects outside the caller's read
scope. `list_capabilities` now checks each returned record's `context_link`
via `scope.ensure_project_link_allowed`, the same "nullable link, no
dedicated policy file" shape `ViewService._allowed` uses — the server-side
`context` filter (when `project` is given) is a narrowing optimization, not
the security boundary; the per-record check runs regardless, including for
`capability_id`-only calls with no server-side filter at all. The same
review found the pre-migration `capability_id` collection filter
(`{"id": ...}`) isn't a documented OpenProject filter — the collection
endpoint accepts only `action`/`principal`/`context` — so `capability_id`
now resolves via a genuine single-item `GET /capabilities/{id}`
(`ActionCapabilityApi.get_capability`), and the `context` filter's
project-scoping value uses the current `w{id}` (workspace) syntax rather
than the deprecated `p{id}` form the pre-migration code sent.

Both methods share the same `access.ensure_read_enabled("membership", ...)`
gate, verbatim from client.py, which is why the two unrelated lookups share
one Service instead of two: splitting them would mean depending on the
identical seam twice for no behavioral difference. `_slug_from_href` has no
shared home in `app/adapters/_text.py` (only `app/policies/scope.py` has a
private copy, per that module's own "duplicated rather than imported from
client.py" rationale) so this adapter carries its own small,
verified-byte-identical copy rather than importing across the
policies/adapters boundary), and Roles (`list_roles` — the thirteenth
migration, and the second **genuinely project-independent** Service after
Actions & Capabilities: no `ProjectRefResolver` seam at all, following that
domain's template exactly. Unlike every prior migration, this one deliberately
changes `OpenProjectClient`'s public facade signature rather than preserving
it byte-for-byte: `list_roles` moves from an unpaginated `CollectionResult`
(a single `_get("roles")` call returning the entire collection) to the same
`PageResult`/`offset`/`limit` shape as `list_actions`, a behavior change
requested alongside the migration, not a mechanical consequence of it. This
broke a previously-documented shortcut: `list_roles` used to be injected into
`MembershipService` as a bare parameterless callable pointing at
`client.py`'s own unpaginated method, "without a dedicated port, since it
currently ha[d] only one consumer" (`MembershipService._resolve_role_hrefs`,
which resolves a role name to its href by scanning the complete role set).
That was safe only because the callable always returned every role in one
call; once `list_roles` paginates with `default_page_size=10`, an unchanged
callable would silently only see the first page, misreporting real roles
beyond it as "not found". Fixed by giving `MembershipService` a direct
`RoleApi` dependency instead of the callable, plus a new package-root shared
helper, `app/pagination.paginate_all`, that page-walks a server-paginated
fetcher to reassemble the complete dataset — the same shape
`VersionResolver`/`ProjectResolver` already hand-roll for the identical
"resolve a name against a paginated list" problem (see `version_resolver.py`/
`project_resolver.py`), generalized here since Roles has no project-scoped
fetch signature to entangle it with. Those two resolvers were **not**
refactored onto the new helper in this migration — their loops are tied to
project-scoped fetch signatures with per-page allowlist checks that
`paginate_all` deliberately doesn't model; unifying them is a candidate for a
future, separate cleanup, not part of this domain's own scope. `RoleRecord`
carries only a `summary` field, the same shape as `ActionRecord` (roles have
no project link, no per-record allowlist check, and no single-item GET —
OpenProject's API exposes list-only, admin-UI-managed roles). An open
question, not yet settled at migration time: this repo has no local evidence
either way (no `.op-sources` cross-check, no doc statement) for whether the
real `/api/v3/roles` endpoint actually honors `offset`/`pageSize` server-side
versus always returning the full collection regardless of paging params
(some OpenProject "static"/admin-managed collections are known to do the
latter) — `tests/integration/test_roles.py` exercises this against a live
instance, but the answer has practical significance only if a real
installation ever has more than one page of roles), and Users (`list_users`/
`get_user`/`create_user`/`update_user`/`delete_user`/`lock_user`/
`unlock_user` — the fourteenth migration, following Roles'/Actions &
Capabilities' zero-`ProjectRefResolver` template exactly: Users are purely
global/admin-scoped, with no project concept at all. Unlike Roles, `list()`
needs BOTH of `app/pagination.py`'s helpers, not just one: a no-search branch
uses `paginate_server` (exact server-side offset/pageSize slicing), while a
`search` branch over-fetches a single bounded page (`page_size=max_results`)
and filters case-insensitively across name/login/email in memory before
slicing with `paginate_client` — the identical dual-branch shape as
`client.py`'s still-flat `list_groups`, the obvious next candidate in this
bucket. `lock`/`unlock` are the first Service methods for a non-CRUD write
action anywhere in `app/`: no form, no validation-errors branch, POST/DELETE
on a `users/{id}/lock` sub-resource whose response body already carries the
full updated representation (no follow-up GET). Modeled on
`ProjectService.set_favorite`'s toggle-write shape (the closest existing
precedent) via a small `UserService`-local `_finalize_action` helper shared
only by `lock`/`unlock` — not `_write_outcome.py`'s `_finalize_write`, which
assumes a form/validation-errors branch neither action has. `commit_unlock`
needed a new `Transport.delete_json` method (`DELETE` that parses a JSON
response body): every existing `Transport` method either mutates without
reading a body (`delete`) or reads a body from a non-DELETE verb, and
OpenProject's `DELETE users/{id}/lock` uniquely returns the updated user
representation as its body. `UserRecord.to_detail` is a lazy
`Callable[[], UserDetail]` thunk, not an eager field — `normalize_user_detail`
parses several detail-only fields (`groups`, `authSource`, `identityUrl`,
`language`) beyond a cheap summary field-copy, and `UserService.list_users()`
never reads `.to_detail` on the list path (only `get_user()` does), so eager
computation would waste that parsing on every list row; a first version of
this migration wrongly reasoned eager was safe since the summary/detail
truncation limits match, an error caught and fixed by a step-6.5 Codex
review. That same review caught one more consequential finding, a genuine
pre-existing gap in the original `client.py` faithfully ported by the first
draft of this migration and then deliberately fixed rather than preserved:
`create_user`/`update_user`/`lock_user`/`unlock_user` never called the
hidden-field-write guard (`hidden_fields.ensure_field_writable`) for any
field they write, unlike every other full-CRUD Service (News/Board/Document/
Membership/Project/Version) — meaning `OPENPROJECT_HIDE_USER_FIELDS` masked
a field on reads but never blocked writing it. Fixed by adding the guard for
every written field (including the toggle-only `locked` field on
`lock`/`unlock`) — a deliberate hardening beyond byte-for-byte porting, since
every sibling domain already had this protection and there was no reason to
carry the inconsistency forward once found), and Groups (`list_groups`/
`get_group`/`create_group`/`update_group`/`delete_group` — the fifteenth and,
at the time of this migration, last individually-screened named candidate in
the purely-global/admin-scoped bucket alongside Roles/Users. Same
zero-`ProjectRefResolver` template, and `list_groups()`'s dual-branch shape
(`paginate_server` no-search / `paginate_client` search-overfetch-then-filter,
filtering only on `name`) is byte-identical to `list_users()`'s, confirming
the Users migration's own prediction. The one real structural divergence:
Groups' `create`/`update` have **no `/form` endpoint** at all (verified:
neither calls a `groups/form` path) — modeled on `NewsService`'s no-form
write shape instead of Users' form-based flow, and `GroupWriteResult.result`
is typed `GroupSummary`, not `GroupDetail` (the write response is normalized
with `normalize_group`, summary only, matching the original). `update()`
carries a genuine behavioral requirement with no Users precedent: the
`PATCH groups/{id}` endpoint requires a COMPLETE `_links.members` array, not
a delta (no add/remove operation exists), so the Service fetches current
membership via a dedicated `GroupApi.get_member_ids()` Port method (a raw
href->id extraction the Adapter exposes separately from `get_group()`, since
`GroupDetail.members` only carries display names, not ids), computes
`current | add - remove` in Python, and PATCHes the full replacement list —
verbatim port of `client.py`'s own read-modify-write step. `create()`/
`update()`/`delete()` all check `access.ensure_write_enabled("admin", ...)`
UNCONDITIONALLY, matching `client.py`'s own behavior exactly: even though
`update()` has a prior GET (for the member diff) it could gate on the way
`NewsService.update()` gates on its own prior GET, the check still runs
before both the GET and the `if not confirm` branch — a caller without
`OPENPROJECT_ENABLE_ADMIN_WRITE` is rejected immediately on `update()`, even
for a pure preview, and can never see a member-diff preview. Kept as-is to
match the verified original rather than adopting News' more-permissive-preview
pattern. `create()`/`update()` add `hidden_fields.ensure_field_writable(
"group", <field>, ...)` for `name`/`members` as a deliberate hardening: the
original `create_group`/`update_group` never called the equivalent
`_ensure_field_writable` at all, the same class of pre-existing gap the
Users migration's step-6.5 review found and fixed, found here via this
migration's own self-audit and fixed as part of the initial implementation
instead of ported faithfully):

```text
tools.py (MCP presentation)
    -> Application Services (app/services/)
        -> Policies (app/policies/, no I/O)
        -> Resolvers (app/resolvers/, I/O only via a port)
            -> Domain API ports/adapters (app/ports/, app/adapters/)
                -> Transport port -> HttpxTransport (app/transport/)
```

- **Policies** are pure functions (scope/allowlist matching, hidden-field masking,
  read/write gates) with no I/O — every `OpenProjectClient` method that used to
  implement this logic directly (`_ensure_read_enabled`, `_project_candidates`,
  `_apply_hidden_fields`, etc.) is now a one-line delegating wrapper, so **every**
  domain benefits from a single, dependency-free, directly-unit-testable source of
  truth for this security-relevant logic — not just the migrated domains.
- **Ports** are narrow, per-domain Protocols (e.g. `VersionApi`, `ProjectApi`) — no
  universal gateway. A port holds only contracts and port-owned data types (the
  Protocol itself, its Result dataclasses, and small port-level constants/conversions
  such as `FORMATTABLE_LIMIT` or `VersionRecord.to_detail()`) — never HAL->model
  mapping. **Adapters** are the concrete HTTP implementation of a port, translating HAL
  payloads into the compact dataclasses from `models.py`. For Versions, Projects, and
  News, the pure HAL-to-model `normalize_*` functions live in the adapter, not the
  port — Services never call them directly, and may depend on Ports but not Adapters.
  `NewsRecord` carries both `summary` (`NewsSummary`, truncated at the list-row cap)
  and `detail` (`NewsDetail`, truncated at the larger single-item cap) rather than
  deriving one from the other like `VersionRecord.to_detail()`: `normalize_news` and
  `normalize_news_detail` apply *different* truncation limits to the same raw
  `description`, so a copy-based derivation would silently under-truncate `get_news`.
  `DocumentRecord.to_detail` is lazy for the identical reason: `normalize_document`/
  `normalize_document_detail` apply different truncation limits to the same raw
  description, and `DocumentService.list()` never reads `.detail`, so eager
  computation would waste a second extraction pass on every list row. Each
  adapter's small helpers (`_trim_text`, `_id_from_href`, `_link_title`,
  `_delimit_user_content`, `_origin_from_url`, `_link_to_web_url`, plus
  `SUBJECT_LIMIT`) were deliberately duplicated per file through the first five
  migrations ("unify only once every domain has migrated"); once Wiki Pages
  became the sixth, they were extracted into `app/adapters/_text.py` and every
  adapter now imports them instead. Helpers that differ meaningfully between
  adapters (`_normalize_validation_errors`, `_extract_formattable_text`) stay
  local — near-identical is not the same as identical, and unifying genuinely
  different logic would change behavior, not just remove duplication. Two more
  package-root shared-kernel modules (alongside `app/errors.py`/`app/pagination.py`)
  were extracted during the Sprints migration's step-6 audit, once each pattern
  was found duplicated past the 3-copy threshold: `app/api_href.py` (a single
  `api_href(relative_path, *, api_prefix)` function, replacing byte-identical
  `_api_href` methods in `MembershipService`/`VersionService`/`ProjectService`
  and a free function in `httpx_grid_api.py`), and `app/form_result.py` (a single
  `FormResult` dataclass, aliased as `MembershipFormResult`/`GridFormResult`/
  `VersionFormResult`/`ProjectFormResult`/`ProjectCopyFormResult` in each
  domain's own port module — each domain keeps its own name so a
  `create_form`/`update_form` Protocol method still reads as a domain-owned
  type, and any one domain stays free to diverge from the shared shape later
  without a breaking rename).
- **Resolvers** turn a semantic reference (a version name, a project identifier) into
  a concrete id, using only a port — never an Application Service. `ProjectResolver`
  is also the concrete implementation the pre-existing `ProjectRefResolver` seam
  (`app/ports/project_ref.py`) is bound to, since every other domain's resolvers
  depend on Projects' resolution logic — Projects doesn't consume that seam, it
  fulfils it. `ProjectResolver` exposes a typed `resolve_record()` alongside the
  compatibility `resolve()`: the adapter's `get()` already returns a fully normalized
  `ProjectRecord` (summary + detail + raw payload), so `resolve_record()` forwards
  that record straight through instead of discarding it down to a raw payload and
  making `ProjectService` re-normalize it — this is what lets the normalizers live
  exclusively in the adapter without reintroducing a second HTTP round-trip.
  `resolve_record()` deliberately takes no `context` parameter, since
  `ProjectResolutionContext` caches raw payloads only; `resolve()` keeps its existing
  context-aware, payload-caching behavior unchanged and calls `resolve_record()` only
  when no context is given. Memberships and News have no resolver at all: a
  `membership_id`/`news_id` is always a numeric value already validated by
  `tools.py`, so there is no semantic-reference resolution for either domain to
  warrant one.
- **Application Services** (e.g. `VersionService`, `ProjectService`) orchestrate a
  single use case: Policy checks, Resolver calls, port calls, and the
  preview/confirm write state machine. They depend on a port's Protocol type, never
  a concrete adapter. The preview/confirm state machine itself
  (`_WriteOutcome`/`_finalize_write`) was duplicated byte-for-byte in Versions,
  Projects, and Memberships (the three full-CRUD domains) until a shared
  `app/services/_write_outcome.py` replaced all three copies — extracted once a
  3rd domain needed the identical shape, matching this project's standing
  unify-at-3-instances convention (already applied once before, to
  `document_policy.py`/`news_policy.py`/`version_policy.py`). Documents/News/Wiki
  Pages don't use it: a domain with fewer than 2 write actions sharing the same
  shape stays a single flat method instead. Projects additionally has
  `ProjectAdminService` (schema +
  available-parent-projects + field metadata for `get_project_admin_context`) as a
  second class in the same file, since it shares the same dependencies.
  `MembershipService` reuses the pre-existing `ProjectRefResolver` seam for project
  resolution (the same seam `VersionService` consumes) and adds one narrow seam of
  its own, `PrincipalRefResolver` (`app/ports/principal_ref.py`), bound to
  `client.py`'s still-flat `self._resolve_principal_id` — shared with the
  still-unmigrated Work-Package domain's assignee resolution, exactly mirroring how
  `ProjectRefResolver` seamed onto still-flat project resolution during the Versions
  pilot. `MembershipService._resolve_role_hrefs` depends directly on `RoleApi` (the
  Roles domain's own port, migrated as the thirteenth domain) plus the shared
  `app.pagination.paginate_all` helper, rather than an injected parameterless
  `list_roles` callable as it did before Roles was migrated — see the Roles entry
  above for why.
  `NewsService` reuses the same `ProjectRefResolver` seam and needs no domain-specific
  seam of its own. Unlike every other migrated domain, News' hidden-field masking
  (`apply_hidden_fields("news", ...)`) is applied *only* in the Service, never in the
  Adapter: `NewsSummary`/`NewsDetail` have no truncation-metadata sibling fields
  (`description_truncated`/`description_length`, as Project/Version/WorkPackage do)
  to zero out on a hide, so there is no reason for the Adapter to perform its own
  hidden-field-aware extraction — it always extracts the full text, and the Service's
  single `apply_hidden_fields` call is sufficient to drop the entire field.
  `DocumentService` follows the same shape — it reuses the `ProjectRefResolver` seam
  for `list()`'s optional project filter only, and masks hidden fields exclusively at
  the Service layer like News (the pre-migration flat code masked at both the
  extraction point and again via a whole-object stamp; both paths check the same
  `field_hidden` predicate, so dropping the Adapter-side check is behaviorally
  equivalent, not a narrowing). `update()` never calls `resolve_project_ref` at all —
  see above. `WikiPageService` reuses no `ProjectRefResolver` seam at all (unlike
  every other migrated domain) — `get_wiki_page` takes no `project` parameter to
  resolve, and there is no dedicated `wiki_page_policy.py` file either, since there
  is no list endpoint to client-side-filter (`get()` calls
  `scope_policy.ensure_project_link_allowed` directly).
- `HttpxTransport` (`app/transport/httpx_transport.py`) is the only module under
  `app/` that imports `httpx`; `client.py`'s own HTTP calls for the remaining
  still-flat domains, and `retry_transport.py`, are unaffected and keep importing it
  directly.
- `OpenProjectClient` remains a 100%-compatible facade for most migrated domains:
  its public method signatures for Versions, Projects, Memberships, News, Documents,
  Wiki Pages, Categories, Views, Grids, Sprints, Boards, and Actions & Capabilities
  are all unchanged, and `tools.py` requires no changes at all for those domains.
  Roles is the one deliberate exception: `list_roles` gained `offset`/`limit`
  parameters as part of its migration (see the Roles entry above), so `tools.py`'s
  `list_roles` tool gained the matching parameters too — the only `tools.py` change
  any migration to date has required. `get_my_project_access` and
  `get_project_work_package_context` stay as client.py-level orchestration rather
  than moving into a Service, since they combine multiple domains (Projects with
  Memberships, and Projects with the still-flat work-package-schema domain,
  respectively) and a Service must not depend on another Service —
  `get_my_project_access` keeps calling the public `list_project_memberships`
  facade method rather than reaching into `self._membership_service` directly, both
  because that facade now delegates transparently to the Service anyway and to
  preserve dynamic dispatch through the public method for subclasses/test doubles.

Remaining domains stay exactly as described in the flat model above; migrating them
further is deliberately out of scope until each migration's own lessons justify the
next one. An `ast`-based test (`tests/test_architecture_boundaries.py`) enforces the
layer directions above, confines `httpx` to `HttpxTransport`, forbids importing
`fastmcp` or reading environment variables directly anywhere under `app/`, and
checks that every `app/services/`/`app/resolvers/` class depends on a port
`Protocol`, never a concrete adapter. These checks are directory-driven, not
domain-specific, so a further domain's migration needs no test changes to stay
covered — only a small, deliberately non-generalized regression test per migrated
domain (`test_version_service_and_resolver_bind_the_api_param_to_version_api_specifically`,
`test_project_service_and_resolver_bind_the_api_param_to_project_api_specifically`,
`test_membership_service_binds_the_api_param_to_membership_api_specifically`,
`test_news_service_binds_the_api_param_to_news_api_specifically`,
`test_document_service_binds_the_api_param_to_document_api_specifically`,
`test_wiki_page_service_binds_the_api_param_to_wiki_page_api_specifically`,
`test_category_service_binds_the_api_param_to_category_api_specifically`,
`test_view_service_binds_the_api_param_to_view_api_specifically`,
`test_grid_service_binds_the_api_param_to_grid_api_specifically`,
`test_sprint_service_binds_the_api_param_to_sprint_api_specifically`,
`test_board_service_binds_the_api_param_to_board_api_specifically`,
`test_action_capability_service_binds_the_api_param_to_action_capability_api_specifically`,
`test_role_service_binds_the_api_param_to_role_api_specifically`)
pins that domain's exact port type, kept alongside the generic check rather than
folded into it. Complementary behavioral-contract tests
(`tests/unit/test_write_confirm_contracts.py`,
`tests/unit/test_write_payload_equivalence.py`) prove, for every registered
write/delete MCP tool, that writes stay preview-only until confirmed, that no
mutating call happens before confirmation or without the required write scope, and
that the previewed and actually-sent payloads match.

## Naming conventions

The code intentionally mirrors OpenProject source names at the API boundary. Do not
rename OpenProject concepts into more generic MCP names when the spelling comes
from the REST API, HAL links, query filters, or documented payload fields.

- Work package text is `subject`, not `title`.
- News and document text is `title`, because those resources use title fields.
- Time-entry dates use `spent_on`, matching the OpenProject payload.
- OpenProject timestamps keep `*_at`; calendar-only fields keep `*_date`.
- Query filters use the source-defined filter keys such as `type_id`,
  `version_id`, `assigned_to_id`, `status_id`, `priority_id`, `project_id`, and
  `subject_or_id`.
- HAL slug identifiers such as action, capability, query column, query operator,
  and sort-by ids stay strings. Database primary keys use numeric `*_id` names.
- MCP tool parameters use simple user-facing names (`project`, `version`,
  `work_package_id`). Internal helper names may use `*_ref` when the value can be
  a numeric id or a semantic/name reference, and `*_id` only when the value is
  known to be numeric.

This keeps the implementation source-conformant while still making internal
resolution steps explicit.

## Request flow

Typical read flow:

1. MCP client calls a tool in `tools.py`
2. tool input is validated and normalized
3. `client.py` checks read gating and project scope
4. OpenProject API is called
5. raw payloads are normalized into dataclasses
6. the MCP tool returns compact JSON

Typical write flow:

1. MCP client calls a mutating tool in `tools.py`
2. tool input is validated
3. `client.py` checks project scope and write enablement
4. write payload is prepared, often through OpenProject form endpoints
5. validation preview is returned unless `confirm=true`
6. confirmed write executes and the response is normalized

## Why form endpoints matter

OpenProject exposes many writable schemas and allowed values through form endpoints. The MCP relies on those endpoints to:

- validate candidate writes before executing them
- resolve allowed values for fields such as status, type, priority, activity, and custom fields
- provide safer previews instead of blindly sending writes

That is why a large part of the write path lives in `client.py` helpers instead of direct `POST` or `PATCH` calls.

## Safety model

The project aims for a defense-in-depth model rather than a single global switch.

The model has two independent layers:

**Layer 1 — MCP server gates** (env var flags, checked before any HTTP call):

- the 8 individual `OPENPROJECT_ENABLE_<GROUP>_READ` flags (which read scopes are exposed at all; `OPENPROJECT_ENABLE_EXTENDED_READ` opt-in exposes a rarely-used subset of metadata tools, `OPENPROJECT_ENABLE_ADMIN_READ` opt-in exposes the instance-wide user/group list)
- scoped write-group flags such as `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`, plus `OPENPROJECT_ENABLE_ADMIN_WRITE`
- `OPENPROJECT_READ_PROJECTS` / `OPENPROJECT_WRITE_PROJECTS` (fail-closed: empty or unset denies all project-scoped access on that side)
- `OPENPROJECT_HIDE_<ENTITY>_FIELDS` / `OPENPROJECT_HIDE_CUSTOM_FIELDS` (see [Field hiding](field-hiding.md))
- preview-by-default writes — every mutation always requires explicit `confirm=true`, with no bypass

**Layer 2 — OpenProject server permissions** (enforced by the API, not the MCP):

The MCP server acts on behalf of the user whose API token is configured. If that user lacks the required role or project permission in OpenProject, the API returns HTTP 403 regardless of what the MCP flags allow. The MCP maps this to a `PermissionDeniedError` which is surfaced as a tool error to the agent. The agent can recognize the cause from the error message and stop attempting the operation.

This means the MCP flags are a ceiling — they restrict what the agent can attempt — but OpenProject's own role system is the final authority. Setting `ENABLE_WORK_PACKAGE_WRITE=true` does not grant the configured user any permissions they do not already have in OpenProject.

Important properties of the current model:

- writes are always bounded by readable project scope
- an empty or unset `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` disables all project-scoped reads/writes respectively — fail-closed, not fail-open
- hidden fields are masked on reads and rejected on writes
- destructive operations still use the same project-scope checks as non-destructive writes
- instance-global admin operations (list/view users and groups, plus user/group management) are gated behind `OPENPROJECT_ENABLE_ADMIN_READ`/`OPENPROJECT_ENABLE_ADMIN_WRITE` — an ordinary read/write pair like every other scope, but neither is bounded by project-scoped write flags, and both default off since the data (instance-wide PII) has no project-scope safety net
- most metadata tools (statuses, types, priorities, notifications, …) are always available and not gated by any read flag; a rarely-used subset (query schema tools, `render_text`, `get_custom_option`, help texts, working days) is off by default behind `OPENPROJECT_ENABLE_EXTENDED_READ` to save context
- `list_notifications` filters by `OPENPROJECT_READ_PROJECTS`, but under a restricted (non-empty, non-`*`) scope this only filters the current server-side page — an empty filtered page does not guarantee no further allowed notifications exist on later pages, since the notifications endpoint has no server-side project filter to paginate against

## Supported scope (Community Edition)

The MCP targets OpenProject **Community Edition** only. The following feature areas are in scope:

- Projects, memberships, roles, principals, project admin context, project configuration
- Work packages, statuses, priorities, types, categories (read), relations, subtasks, attachments, watchers, activities
- Versions, boards/queries, views
- Backlogs sprints (read, plus assigning/unassigning a work package's sprint; requires the Backlogs module)
- News, documents (read/update only), wiki pages (single-page fetch only — no list endpoint in OpenProject v3)
- Time entries, Nextcloud file links (CE feature, degrades gracefully)
- Users, groups, user preferences, notifications
- Grids, help texts, working days, custom options, text rendering
- Project lifecycle phases (read only, degrades gracefully if unavailable)
- Instance configuration, query metadata, actions and capabilities

## Explicit non-goals / Enterprise exclusions

The following are intentionally **not supported** and have been removed from the codebase:

| Feature | Reason |
|---|---|
| Programs (`/api/v3/programs`) | Enterprise Edition only |
| Portfolios (`/api/v3/portfolios`) | Enterprise Edition only |
| Placeholder users (`/api/v3/placeholder_users`) | Enterprise Edition only |
| Budgets (`/api/v3/budgets`) | Enterprise Edition only |
| Custom actions (execute) | Enterprise Edition only |
| Baseline comparisons | Enterprise Edition only |
| OpenID Connect / SAML SSO management | Enterprise Edition only |

API stubs with no POST/DELETE endpoint in CE (read/update only, matching OpenProject v3 API reality):

| Feature | Available operations |
|---|---|
| Documents | GET list, GET single, PATCH update |
| Wiki pages | GET single only — the collection endpoint (`/api/v3/projects/{id}/wiki_pages`) is not implemented in OpenProject v3; `list_wiki_pages` has been removed |
| Categories | GET list, GET single |

## Design tradeoffs

Reasons this project stays flat:

- easier review of security-relevant behavior
- fewer indirection layers when mapping OpenProject endpoints
- simpler debugging during live MCP sessions
- low ceremony for adding new endpoints

The tradeoff is that `client.py` is large and policy-heavy. That is intentional for now: the sensitive logic stays centralized instead of being split across many files.

## Future split points

The Policies extraction (scope checks, hidden-field enforcement) is done, for every
domain — see "Layered architecture" above. Versions, Projects, Memberships, News,
Documents, Wiki Pages, Categories, Views, Grids, Sprints, Boards, Actions &
Capabilities, Roles, Users, and Groups are migrated; remaining candidates, once each
migration's own lessons justify the next one:

- migrating additional domains through the same `app/` layers, one at a time —
  re-evaluate which domain's resolvers most depend on already-flat logic, per the
  pilot's own "validate before extending" approach. See
  [architecture-migration-runbook.md](architecture-migration-runbook.md) for the
  step-by-step process distilled from the fifteen migrations done so far. Boards,
  Actions & Capabilities, Roles, Users, and Groups were each picked via a fresh
  screening against step 0's criteria directly — no pre-named shortlist remained
  after Grids/Sprints, and Groups was the last individually-screened named
  candidate in the purely-global/admin-scoped bucket. The next pick needs a fully
  fresh screening pass against the ~20 remaining still-flat domains — no named
  candidate remains in this bucket; Project Lifecycle Phases and Project Favorites
  already migrated as part of Projects, not separate candidates.
- separate modules for work-package writes and schema handling
- dedicated integration-test helpers around form endpoints and live smoke tests
- unifying `VersionResolver`'s/`ProjectResolver`'s hand-rolled page-walk loops onto
  the `app/pagination.paginate_all` helper extracted during the Roles migration —
  deliberately deferred at the time (their loops carry project-scoped fetch
  signatures and per-page allowlist checks `paginate_all` doesn't model), but worth
  revisiting once a third such loop appears, per this project's own
  unify-at-3-instances convention.

## See also

- [Documentation hub](README.md) — full documentation index
- [Development](development.md) — dev environment setup and running tests
- [Tool reference](tools.md) — every MCP tool this server exposes
- [Configuration](configuration.md) — the full environment variable reference
