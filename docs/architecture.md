# Architecture

OpenProject MCP is intentionally small and flat. The codebase keeps transport, validation, policy checks, OpenProject API access, and MCP exposure in a few narrow layers instead of spreading them across many abstractions.

## Layout

```text
src/openproject_ce_mcp/
├── config.py    environment loading, validation, and safe defaults
├── client.py    OpenProject API client: auth, timeouts, pagination, normalization, error mapping
├── models.py    compact dataclasses returned to MCP clients
├── tools.py     validated MCP tool handlers
└── server.py    FastMCP server bootstrap and lifecycle management
```

## Layers

### `config.py`

- Parses environment variables into an immutable `Settings` object.
- Applies safe defaults such as read enabled, write disabled, explicit page limits, and opt-in confirmation skipping.
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
5. validation preview is returned unless `confirm=true` or auto-confirm is enabled
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

- scoped `OPENPROJECT_ENABLE_*_READ`
- scoped `OPENPROJECT_ENABLE_*_WRITE` / `OPENPROJECT_ENABLE_ADMIN_WRITE`
- `OPENPROJECT_ALLOWED_PROJECTS_READ` / `OPENPROJECT_ALLOWED_PROJECTS_WRITE`
- `OPENPROJECT_HIDE_<ENTITY>_FIELDS` / `OPENPROJECT_HIDE_CUSTOM_FIELDS`
- preview-by-default writes unless auto-confirm is explicitly enabled

**Layer 2 — OpenProject server permissions** (enforced by the API, not the MCP):

The MCP server acts on behalf of the user whose API token is configured. If that user lacks the required role or project permission in OpenProject, the API returns HTTP 403 regardless of what the MCP flags allow. The MCP maps this to a `PermissionDeniedError` which is surfaced as a tool error to the agent. The agent can recognize the cause from the error message and stop attempting the operation.

This means the MCP flags are a ceiling — they restrict what the agent can attempt — but OpenProject's own role system is the final authority. Setting `ENABLE_WORK_PACKAGE_WRITE=true` does not grant the configured user any permissions they do not already have in OpenProject.

Important properties of the current model:

- writes are always bounded by readable project scope
- an explicit empty `OPENPROJECT_ALLOWED_PROJECTS_WRITE` disables project-scoped writes
- hidden fields are masked on reads and rejected on writes
- destructive operations still use the same project-scope checks as non-destructive writes
- instance-global admin operations (user/group management) require explicit `OPENPROJECT_ENABLE_ADMIN_WRITE=true` — never activated by project-scoped write flags
- all other metadata tools (statuses, types, priorities, notifications, …) are always available and not gated by any read flag

## Supported scope (Community Edition)

The MCP targets OpenProject **Community Edition** only. The following feature areas are in scope:

- Projects, memberships, roles, principals, project admin context, project configuration
- Work packages, statuses, priorities, types, categories (read), relations, subtasks, attachments, watchers, activities
- Versions, boards/queries, views
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

If the project grows further, likely extraction candidates are:

- separate modules for project-scoped content like news/documents/views
- separate modules for work-package writes and schema handling
- a dedicated policy module for scope checks and hidden-field enforcement
- dedicated integration-test helpers around form endpoints and live smoke tests
