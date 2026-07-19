# Architecture

<p align="center">
  <img src="../img/architecture.jpg" alt="Five modular server layers connected by a guarded bidirectional request flow." width="960">
</p>

OpenProject CE MCP is intentionally small and flat. The codebase keeps transport, validation, policy checks, OpenProject API access, and MCP exposure in a few narrow layers instead of spreading them across many abstractions.

## Layout

```text
src/openproject_ce_mcp/
├── config.py            environment loading, validation, and safe defaults
├── client.py             OpenProject API client facade: auth, timeouts, most domains'
│                         pagination/normalization/error mapping, plus one-line
│                         delegations to app/ for the Versions domain (see below)
├── retry_transport.py    HTTP retry with backoff for transient failures
├── models.py             compact dataclasses returned to MCP clients
├── tools.py              validated MCP tool handlers
├── server.py             FastMCP server bootstrap and lifecycle management
├── setup_cli.py          the interactive `configure` command
├── doctor.py             the `doctor` diagnostics command
└── app/                  layered architecture pilot -- see "Layered architecture" below
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

## Layered architecture (pilot: Versions)

`client.py` stays the small, flat facade described above for most domains, but the
Versions domain (`list_versions`, `get_version`, `create_version`, `update_version`,
`delete_version`) has been migrated into `app/` as a pilot for a stricter layered
structure, validating the pattern before any other domain follows:

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
  truth for this security-relevant logic — not just Versions.
- **Ports** are narrow, per-domain Protocols (e.g. `VersionApi`) — no universal
  gateway. **Adapters** are the concrete HTTP implementation of a port, translating
  HAL payloads into the compact dataclasses from `models.py`.
- **Resolvers** turn a semantic reference (a version name, a numeric id) into a
  concrete id, using only a port — never an Application Service.
- **Application Services** (e.g. `VersionService`) orchestrate a single use case:
  Policy checks, Resolver calls, port calls, and the preview/confirm write state
  machine. They depend on a port's Protocol type, never a concrete adapter.
- `HttpxTransport` (`app/transport/httpx_transport.py`) is the only module under
  `app/` that imports `httpx`; `client.py`'s own HTTP calls for the ~50 still-flat
  domains, and `retry_transport.py`, are unaffected and keep importing it directly.
- `OpenProjectClient` remains a 100%-compatible facade throughout: its public method
  signatures for Versions are unchanged, and `tools.py` requires no changes at all.

Remaining domains stay exactly as described in the flat model above; migrating them
is deliberately out of scope until the pilot's lessons inform a second migration.
An `ast`-based test (`tests/test_architecture_boundaries.py`) enforces the layer
directions above, confines `httpx` to `HttpxTransport`, forbids importing `fastmcp`
or reading environment variables directly anywhere under `app/`, and checks that
every `app/services/`/`app/resolvers/` class depends on a port `Protocol`, never a
concrete adapter. These checks are directory-driven, not Versions-specific, so a
second domain's migration needs no test changes to stay covered. Complementary
behavioral-contract tests (`tests/unit/test_write_confirm_contracts.py`,
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
domain — see "Layered architecture" above. Remaining candidates, once the Versions
pilot's lessons justify a second migration:

- migrating additional domains through the same `app/` layers, one at a time,
  starting with the ones the pilot's own dependencies already touch (Projects, since
  every domain's resolvers call into its still-flat resolution logic)
- separate modules for project-scoped content like news/documents/views
- separate modules for work-package writes and schema handling
- dedicated integration-test helpers around form endpoints and live smoke tests

## See also

- [Documentation hub](README.md) — full documentation index
- [Development](development.md) — dev environment setup and running tests
- [Tool reference](tools.md) — every MCP tool this server exposes
- [Configuration](configuration.md) — the full environment variable reference
