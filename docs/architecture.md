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

## Layered architecture (Versions, Projects, Memberships, News, Documents, Wiki Pages)

`client.py` stays the small, flat facade described above for most domains, but six
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
own `project_link`):

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
  different logic would change behavior, not just remove duplication.
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
  pilot. `list_roles` stays flat in `client.py` too (a plain read-only lookup, not a
  CRUD object of its own) and is injected into `MembershipService` as a bare
  callable, without a dedicated port, since it currently has only one consumer.
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
- `OpenProjectClient` remains a 100%-compatible facade throughout: its public method
  signatures for Versions, Projects, Memberships, News, Documents, and Wiki Pages are
  unchanged, and `tools.py` requires no changes at all. `get_my_project_access` and
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
`test_wiki_page_service_binds_the_api_param_to_wiki_page_api_specifically`)
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
Documents, and Wiki Pages are migrated; remaining candidates, once each migration's
own lessons justify the next one:

- migrating additional domains through the same `app/` layers, one at a time —
  re-evaluate which domain's resolvers most depend on already-flat logic, per the
  pilot's own "validate before extending" approach. See
  [architecture-migration-runbook.md](architecture-migration-runbook.md) for the
  step-by-step process distilled from the five migrations done so far.
- separate modules for project-scoped content like views
- separate modules for work-package writes and schema handling
- dedicated integration-test helpers around form endpoints and live smoke tests

## See also

- [Documentation hub](README.md) — full documentation index
- [Development](development.md) — dev environment setup and running tests
- [Tool reference](tools.md) — every MCP tool this server exposes
- [Configuration](configuration.md) — the full environment variable reference
