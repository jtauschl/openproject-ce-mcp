# Architecture

<p align="center">
  <img src="../img/architecture.jpg" alt="Five modular server layers connected by a guarded bidirectional request flow." width="960">
</p>

OpenProject CE MCP is organized into a small number of narrow layers with a strict, one-directional dependency order: MCP presentation, Application Services, Policies/Resolvers, domain API Ports/Adapters, and a single Transport. Each domain (projects, work packages, versions, …) follows this same shape — a narrow port, an adapter, resolver(s) where needed, policies, an Application Service, and a thin `client.py` facade delegation — so a new domain's design decisions are largely settled by the existing pattern rather than invented from scratch. `client.py` itself stays a thin, auth/transport/error-mapping facade; the domain logic and policy checks live one layer down instead of accumulating in that one file.

## Layout

```text
src/openproject_ce_mcp/
├── config.py             environment loading, validation, and safe defaults
├── client.py             OpenProject API client facade: auth, transport, error
│                         mapping, the project-identifier cache, and one-line
│                         delegations to app/ for every domain (see below) --
│                         normalization/business logic now lives entirely under
│                         app/, except two deliberate cross-service-orchestration
│                         methods (a Service must not depend on another Service)
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

- Owns all OpenProject HTTP transport (auth, timeouts, error mapping) and the shared project-identifier cache.
- Every domain's public method is a one-line delegation into `app/` (see "Layered architecture" below) — normalization, write previews/confirmation, and the runtime policy model (read gates, scoped write gates, project scoping, hidden-field masking) live in `app/policies/`, `app/services/`, and `app/adapters/` instead.
- Two deliberate exceptions stay as `client.py`-level orchestration rather than a Service (`get_project_work_package_context`, `get_my_project_access`): each combines more than one domain in a single call, and a Service must not depend on another Service.

`app/policies/` is the main policy boundary of the project.

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

## Layered architecture

`client.py` is the thin facade described above. Every domain's public methods on `OpenProjectClient`
are one-line delegations to a layered implementation under `app/`:

```text
tools.py (MCP presentation)
    -> Application Services (app/services/)
        -> Policies (app/policies/, no I/O)
        -> Resolvers (app/resolvers/, I/O only via a port)
            -> Domain API ports/adapters (app/ports/, app/adapters/)
                -> Transport port -> HttpxTransport (app/transport/)
```

- **Policies** are pure functions (scope/allowlist matching, hidden-field masking, read/write
  gates) with no I/O — every domain shares a single, dependency-free, directly-unit-testable
  source of truth for this security-relevant logic.
- **Ports** are narrow, per-domain Protocols — no universal gateway. A port holds only contracts
  and port-owned data types (the Protocol itself, its Result dataclasses, and small port-level
  constants/conversions) — never HAL→model mapping. **Adapters** are the concrete HTTP
  implementation of a port, translating HAL payloads into the compact dataclasses from `models.py`.
  The pure HAL-to-model `normalize_*` functions live in the adapter, not the port — Services never
  call them directly, and may depend on Ports but not Adapters.
  - A domain's `Record` may carry a lazily-computed `to_detail` field
    (`Callable[[], <Domain>Detail]`) instead of an eager one, when the domain's `list()` path never
    reads it and the detail normalizer does extra work beyond a cheap field-copy — this defers that
    work until `get()` actually needs it.
  - A domain whose returned record's parent link carries no reliable identifier/title of its own
    carries the raw HAL link dict, not just an extracted href string, since the allowlist check and
    project-candidate matching need more than `href` off it.
  - A Port may offer a raw-`dict`-returning method alongside its normalized Record methods when
    the original flat code read a single field off a payload without ever fully normalizing it —
    forcing full normalization there would raise a spurious exception on a payload shape the
    original never needed to parse completely (e.g. a payload missing an unrelated required field
    like `id`). Confirmed recurring, not a one-off: `EmojiReactionApi.get_activity` and
    `ReminderApi.get_remindable_link` both exist for this exact reason.
  - Small text/href-parsing helpers (`trim_text`, `id_from_href`, `link_title`,
    `delimit_user_content`, `origin_from_url`, `link_to_web_url`, `can_update_from_links`, plus
    `SUBJECT_LIMIT`) are shared via `app/adapters/_text.py`; every adapter imports what it needs
    from there rather than duplicating them. Helpers that differ meaningfully between adapters
    (`_normalize_validation_errors`, `_extract_formattable_text`) stay local per adapter —
    unifying genuinely different logic would change behavior, not just remove duplication. A small
    number of package-root shared-kernel modules exist for the same reason outside the adapter
    layer: `app/api_href.py` (a relative-API-href builder), `app/form_result.py` (a shared
    `FormResult` dataclass, aliased under each domain's own name in its port module), and
    `app/origin.py` (a same-origin-check helper usable from both Adapters and Services, since
    Services cannot import from Adapters).
  - A helper still needed by a different, still-flat sibling domain in `client.py` cannot be
    deleted from there when a domain migrates — it is duplicated (verified byte-identical) into
    the new adapter instead, rather than importing across the module boundary.
  - A caller-supplied id that can contain URL-path-unsafe characters is percent-encoded
    (`quote(<id>, safe="")`) before being interpolated into a request path.
  - A domain whose per-item read-allowlist check can fail on a malformed/unexpected raw field may
    have its `list()` Port method return raw, unnormalized elements (plus any server-reported total)
    instead of pre-built Records — the Service then filters the raw elements against the allowlist
    FIRST and normalizes only the survivors, so an out-of-scope item's malformed field can never
    raise before the allowlist ever gets a chance to drop it, and no normalization work is wasted on
    items the caller could never see. This is a deliberate divergence from the more common
    "Adapter always normalizes, Service filters the already-normalized Records" shape — pick the
    shape that matches whether filtering can safely happen on already-normalized data for that
    specific domain.
- **Resolvers** turn a semantic reference (a version name, a project identifier) into a concrete
  id, using only a port — never an Application Service. Project and reference resolution happens
  through a request-scoped resolution context: a single top-level call touching the same project
  more than once performs the read/write-allowlist check once, not once per touch, without ever
  skipping it outright. A domain whose id is always already-numeric or an opaque string (validated
  by `tools.py`) needs no dedicated Resolver at all — it depends directly on the shared
  `ProjectRefResolver` seam (`app/ports/project_ref.py`) when it needs to resolve an optional
  `project` filter, and on nothing else.
- **Application Services** orchestrate a single use case: Policy checks, Resolver calls, port
  calls, and the preview/confirm write state machine. They depend on a port's Protocol type, never
  a concrete adapter — enforced by `tests/test_architecture_boundaries.py`. The shared preview/
  confirm state machine (`app/services/_write_outcome.py`) is reused by any domain with 2+ write
  actions sharing the same result shape; a domain with fewer stays a single flat method instead of
  forcing indirection onto one or zero call sites. A domain bundling several unrelated-but-adjacent
  read-only lookups under one ticket is one Service, not one per lookup, when every method shares
  an identical read-enablement gate — this does not require every bundled method to share the exact
  same scope string: one method reusing a different, pre-existing scope than its siblings inside the
  same Service is a one-line variation, not a reason to split the domain apart. A domain with no
  project link and no allowlist concept at all (self-scoped to the token owner, not project-scoped or
  admin-scoped) uses neither a Policy module nor `app/policies/scope.py`'s helpers — the read/write
  scope gate alone is its entire enforcement surface. A domain whose parent resource is a work
  package rather than a project resolves that reference through the shared
  `WorkPackageIdResolver`/`WorkPackageProjectAllowedCheck` seams (`app/ports/work_package_ref.py`),
  the work-package-reference equivalent of `ProjectRefResolver` — a Service can depend on more than
  one domain-API Port at once when two of its methods each need a genuinely different capability
  (e.g. reference resolution for one method, a raw payload fetch for another), rather than forcing
  every dependency through a single seam that doesn't fit both shapes. `WorkPackageIdResolver(ref,
  write=True)` also directly replaces the flat-code idiom of a manual work-package fetch plus a
  write-allowlist check on its project link, when a write method's caller-supplied reference must
  itself be resolved (as opposed to a write method already holding a concrete numeric id derived
  from another resource's own link). A `list()` that fans out across several *different* work
  packages in one response (one per record, not a single anchor) uses
  `WorkPackageProjectAllowedCheck` directly, paired with a fresh, request-scoped
  `WorkPackageAllowedContext` cache (`app/ports/work_package_resolution.py`) so two records
  sharing the same work package are checked only once — this per-record filtering is Service-level
  logic, not a Policy module, since the check itself does I/O (a conditional work-package fetch)
  and `app/policies/` is documented as pure, no-I/O. A Service may touch the local filesystem
  directly (path-traversal containment, a sensitive-filename denylist, reading file bytes) when the
  domain's write path is a local file upload — this is authorization/security logic, not HAL↔model
  translation, so it stays in the Service layer rather than the Adapter, matching every other
  authorization check's home (`AttachmentService`'s `_prepare_attachment_file`/
  `_is_sensitive_attachment` is the first and, so far, only instance). A Port method may reach into
  an otherwise entirely unmigrated, different domain for exactly one field a write path needs to
  validate against (`AttachmentApi.get_max_attachment_size()` reads Instance Configuration's
  `maximumAttachmentFileSize` without migrating that domain) — a deliberate, narrow exception to
  "a Port covers its own domain," used specifically to avoid an unrelated domain's full migration
  becoming a hidden prerequisite for the one actually being migrated. Hidden-field masking
  (`hidden_fields.apply_hidden_fields`) tags its result with a dynamic `_hidden_keys` attribute, not
  a declared dataclass field — `dataclasses.replace(...)` on an already-stamped value builds a
  brand-new instance carrying only the declared fields, silently dropping that tag. Any Service
  method that both stamps a result AND transforms it afterward via `dataclasses.replace` (e.g. a
  post-processing filter step) must stamp AFTER the replace, not before, or the transformed result
  comes back fully unmasked. A domain's WRITE methods do not necessarily share the same
  read-enablement gate as its READ methods — verify each write method's flat-code original
  individually rather than assuming a domain-wide convention: Work Packages' `create`/
  `create_subtask`/`update`/`delete`/`bulk_create`/`bulk_update`/`add_comment` deliberately never
  call `access.ensure_read_enabled`, unlike that same domain's `search`/`list`/`list_my_open`/`get`,
  which all gate on it as their first action — an instance can have work-package writes enabled
  with reads entirely disabled, and every write path (including an internal, write-adjacent lookup
  like the auto-percentage/auto-remaining-time derivation's status-detail fetch, which is why that
  lookup goes through `StatusPriorityTypeApi` directly rather than `StatusPriorityTypeService`) must
  keep working in that configuration.
- `HttpxTransport` (`app/transport/httpx_transport.py`) is the only module under `app/` that
  imports `httpx`; `client.py`'s own HTTP calls (used only by the two cross-service-orchestration
  methods described above) and `retry_transport.py` are unaffected and keep importing it directly.
  The `Transport` Protocol (`app/transport/protocol.py`) is extended with a new method when a
  domain needs a request shape none of the existing methods cover — e.g. `post_raw_json` for a raw,
  non-JSON request body (`Content-Type: text/plain`), added when a domain's endpoint posts plain
  text rather than a JSON payload; `post_multipart` for a `multipart/form-data` body (a JSON
  metadata part plus a file part), added for Attachments' file upload — the metadata part is sent
  as a plain form field with no filename in its Content-Disposition, since a filename would make
  the server's multipart parser treat it as an uploaded file rather than a JSON string.
- `OpenProjectClient` remains a 100%-compatible facade: each domain's public method signatures stay
  unchanged unless a deliberate, separately-decided behavior change was bundled into a past
  migration — in which case `tools.py`'s matching tool gained the same change, the only kind of
  `tools.py` edit a domain migration itself ever requires. The two `client.py`-level orchestration
  methods that combine multiple domains (`get_project_work_package_context`, `get_my_project_access`)
  stay as `client.py`-level orchestration rather than moving into a single Service, since a Service
  must not depend on another Service.

An `ast`-based test (`tests/test_architecture_boundaries.py`) enforces the layer directions above,
confines `httpx` to `HttpxTransport`, forbids importing `fastmcp` or reading environment variables
directly anywhere under `app/`, and checks that every `app/services/`/`app/resolvers/` class
depends on a port `Protocol`, never a concrete adapter. These checks are directory-driven, not
domain-specific. Each domain also has a small, deliberately non-generalized regression test
(`test_<domain>_service_binds_the_api_param_to_<domain>_api_specifically`) that pins its exact
port type, kept alongside the generic check rather than folded into it. Complementary
behavioral-contract tests (`tests/unit/test_write_confirm_contracts.py`,
`tests/unit/test_write_payload_equivalence.py`) prove, for every registered write/delete MCP tool,
that writes stay preview-only until confirmed, that no mutating call happens before confirmation or
without the required write scope, and that the previewed and actually-sent payloads match.

Every domain has been migrated through these same `app/` layers — `client.py` is now the thin
facade described above, plus the two deliberate cross-service-orchestration exceptions. See this
project's internal engineering-docs companion repository for the step-by-step migration process
this used and its per-migration history; it is intentionally not duplicated here, since this file
describes only the current architecture.

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
3. the domain's Application Service (`app/services/`) checks read gating and project scope via `app/policies/`
4. the domain's Adapter (`app/adapters/`) calls the OpenProject API through `HttpxTransport`
5. raw payloads are normalized into dataclasses
6. the MCP tool returns compact JSON

Typical write flow:

1. MCP client calls a mutating tool in `tools.py`
2. tool input is validated
3. the domain's Application Service checks project scope and write enablement via `app/policies/`
4. write payload is prepared, often through OpenProject form endpoints
5. validation preview is returned unless `confirm=true`
6. confirmed write executes and the response is normalized

## Why form endpoints matter

OpenProject exposes many writable schemas and allowed values through form endpoints. The MCP relies on those endpoints to:

- validate candidate writes before executing them
- resolve allowed values for fields such as status, type, priority, activity, and custom fields
- provide safer previews instead of blindly sending writes

That is why a large part of the write path lives in each domain's Application Service instead of direct `POST` or `PATCH` calls.

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

Reasons for the layered structure over one large flat file:

- security-relevant checks (read/write gates, project scope, hidden-field masking) live in one
  pure, dependency-free, directly-unit-testable module (`app/policies/`) shared by every domain,
  instead of being reimplemented or copy-pasted per domain
- a narrow port `Protocol` is trivial to fake in a unit test; a monolithic client with many
  concrete responsibilities is not
- a smaller, single-purpose module (one domain's Service/Adapter/Resolver) is easier to review
  correctly than a change buried inside a much larger file
- `HttpxTransport` is the only module that imports `httpx`, enforced by a static test — every other
  layer depends on the `Transport` Protocol, never the concrete HTTP client library
- each domain follows the same shape (port, adapter, resolver(s), policies, Application Service,
  thin `client.py` delegation), so a new domain's design decisions are largely settled by the
  existing pattern

The tradeoff is more files and more indirection to trace a single request through than a flat
design would have — mitigated by every domain following the identical shape, so once one domain is
understood, the rest read the same way.

## See also

- [Documentation hub](README.md) — full documentation index
- [Development](../CONTRIBUTING.md) — dev environment setup and running tests
- [Tool reference](tools.md) — every MCP tool this server exposes
- [Configuration](configuration.md) — the full environment variable reference
