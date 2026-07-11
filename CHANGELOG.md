# Changelog

All notable changes to this project will be documented in this file. Versions
follow [semantic versioning](https://semver.org); 0.2.0 is the first release
published to PyPI, 0.1.0 is the first tagged release, and 0.0.1 is the
development baseline.

---

## 0.3.0 – Unreleased

### Changed

- **Tools are now registered only when all read and write scopes required by
  their client implementation are enabled** (OPM-123, Phase 1 of the
  authorization/config redesign, OPM-122). Previously, several tools were
  always registered regardless of any `OPENPROJECT_ENABLE_*_READ` flag, even
  though their underlying client method enforced a real scope check at call
  time — the tool was visible to the agent but failed on every call once
  that scope was disabled. Affected tools now correctly disappear together
  with their real scope: `get_current_user`, `list_actions`,
  `list_capabilities` (membership read), `list_notifications` (work-package
  read), `get_instance_configuration`, `get_job_status` (project read).
  This can also hide some **write** tools when their supporting read scope
  is disabled, e.g. `create_membership`/`update_membership` (need membership
  read for a role lookup) or `delete_file_link` (needs work-package read) —
  not just read tools. No environment variable was renamed, added, or
  removed; only the effective tool exposure of the existing
  `OPENPROJECT_ENABLE_*_READ`/`_WRITE` flags is now more precise.
- `Settings.read_enabled()`/`write_enabled()` now raise `ConfigError` for an
  unrecognized scope string instead of silently defaulting to allow-all
  (read) or deny-all (write). Scope strings are internal literals, never
  user input, so this can only surface a programming error, not a user
  misconfiguration.

### Internal

- Tool registration in `tools.py` is now table-driven from a small set of
  classification constants (`READ_TOOLS_BY_SCOPE`, `WRITE_TOOLS_BY_SCOPE`,
  `PERSONAL_READ_TOOLS`, `PERSONAL_MUTATION_TOOLS`, `ADMIN_WRITE_TOOLS`,
  `METADATA_TOOLS`, `ADDITIONAL_READ_SCOPES_BY_TOOL`) instead of ~190 lines
  of hand-written conditional blocks — closes OPM-47.

---

## 0.2.3 – 2026-07-07

### Fixed

- **`create_work_package_attachment` no longer fails with a 500 on every upload.**
  The `metadata` multipart part was sent with a filename (`name="metadata";
  filename="metadata"`), so OpenProject's parser treated it as an uploaded file
  instead of a JSON field and returned `no implicit conversion of
  ActiveSupport::HashWithIndifferentAccess into String`. The part is now sent
  without a filename, as the API expects.
- **`serverInfo.version` in the MCP `initialize` handshake now reports the package
  version** instead of the SDK's own version. FastMCP has no `version` constructor
  argument, so it is set on the low-level server.

### Added

- **CE server instructions in the `initialize` response.** The server now tells a
  connecting agent up front that types/statuses/workflows/modules are not
  creatable through the API and that `list_capabilities` is not the source of
  truth for what the tools allow, enriched at startup with the instance's live
  active feature flags (best-effort; never blocks server start).

---

## 0.2.2 – 2026-07-06

### Security

- **`delete_file_link` now enforces the project write allowlist.** It previously
  checked only the global `work_package` write flag, so with
  `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE=true` a file link in a project outside
  `OPENPROJECT_ALLOWED_PROJECTS_WRITE` could be deleted. It now loads the
  container work package and enforces the allowlist before deleting, and fails
  closed when the container cannot be resolved.
- **`toggle_activity_emoji_reaction` now enforces the project write allowlist.**
  It patched reactions with no per-project check; it now resolves the activity's
  work package and enforces the allowlist before the write, failing closed if the
  activity has no resolvable work-package link.

### Fixed

- **`get_group()` no longer crashes on real API responses.** Group detail embeds
  members as a flat array; the client assumed a `{count, elements}` collection and
  raised `AttributeError` for any group with visible members.
- **`create_time_entry` builds a valid entity link for semantic work-package
  references.** A reference like `PROJ-123` was placed in the HAL entity link
  verbatim; HAL links resolve only by numeric id, so the numeric id is now used.
- **Validation errors for `responsible` name the correct field.** An invalid
  `responsible` value previously reported an `assignee` error.
- `openproject-ce-mcp configure` now exits cleanly on Ctrl+C — it prints
  "Cancelled" and exits with code 130 instead of dumping a `KeyboardInterrupt`
  traceback.

### Changed

- **A remote plain-`http://` base URL now emits a startup warning** that the API
  token is sent unencrypted. `localhost`/`127.0.0.1`/`::1` are exempt from the
  warning.
- Documented that self-scoped writes — marking notifications read, updating your
  own preferences, and toggling your own emoji reactions — execute directly
  without a preview step; project-attached reactions still enforce write scope.
- CI now enforces formatting with `ruff format --check`, and the codebase was run
  through `ruff format` once.
- Removed two unused internal helpers (`_validate_optional_positive_int`,
  `_load_existing`).

---

## 0.2.1 – 2026-07-01

### Changed

- **Configure flow simplified.** `openproject-ce-mcp configure` now asks two
  independent questions — "Configure globally (user-wide)?" and "Configure
  project-scoped (this directory)?" — and writes only the targets you pick,
  instead of mixing a client prompt with an implicit project `.mcp.json`. Project
  scope is offered for every supported client (Claude Code, Codex, Cursor, VS
  Code), whether or not it is detected, so a fresh IDE setup works. The wording is
  "configure", not "install" (the package is already installed).
- The **early 0.2.0 `--local` / `--global` flags were removed** before adoption;
  the two interactive gates replace them.
- Prefill when re-running is now field-wise: a partial project config contributes
  the fields it has without discarding a complete global entry's token.
- The "Writable projects" prompt clarifies that `*` means *all readable projects*
  (write scope is always intersected with read scope).

### Added

- Per-client restart hints after configuring (config written ≠ server running).
- `configure --uninstall` now also removes project-local entries in the current
  directory (`.mcp.json`, `.codex/config.toml`, `.vscode/mcp.json`,
  `.cursor/mcp.json`), grouped by scope, keeping other MCP servers intact.

---

## 0.2.0 – 2026-07-01

First release published to PyPI. Supersedes the never-released 0.1.1 (its
package-rename and installer fixes are folded in here).

### Added

- **PyPI distribution.** The package is installable with `pip` / `pipx` /
  `uv tool install openproject-ce-mcp`. A GitHub Actions workflow publishes to
  PyPI on a version tag via trusted publishing (OIDC, no stored token).
- **`openproject-ce-mcp configure` setup command** (plus the
  `openproject-ce-mcp-setup` alias), shipped in the installed package. It
  registers the server with detected MCP clients and writes `.mcp.json`. Scope is
  auto-detected — a project directory gets a local `.mcp.json`, elsewhere the
  server is registered user-wide — and can be forced with `--local` / `--global`.
- Top-level CLI: `openproject-ce-mcp --help` / `--version`; running with no
  arguments still starts the stdio server, unchanged for MCP clients.
- `check_api.py --constants` verifies hardcoded enum/constant values (emoji
  reactions, version statuses and their operators) against the OpenProject source
  across versions, catching a value rename the presence check would miss.

### Changed

- Renamed the package to **openproject-ce-mcp** (distribution name, import
  package `openproject_ce_mcp`, and the `openproject-ce-mcp` command). The PyPI
  name `openproject-mcp` is taken by an unrelated project; the new name is free
  and states the Community-Edition focus. The MCP server key stays `openproject`,
  so existing client configs do not change.
- Documentation leads with the PyPI install path; the `curl … | sh` source
  installer is kept as an alternative. Uninstall is documented per install type.
- The `User-Agent` header now derives from the package version instead of a
  hardcoded string.

### Fixed

- The `curl … | sh` installer no longer crashes with `EOFError` on the first
  prompt: `get.sh` attaches the controlling terminal, and the prompt helpers fall
  back to defaults when stdin is not interactive.
- Re-running `configure --global` pre-fills from an existing client registration
  instead of demanding the base URL and token again.
- `configure` warns before writing a token-bearing `.mcp.json` into an unrelated
  project directory, and when the server command cannot be resolved to an absolute
  path (which would fail for GUI clients that do not inherit the shell `PATH`).
- The Docker integration-test harness (`docker/test/up.sh`) runs on the Bash 3.2
  that ships with macOS (no `declare -A`).

---

## 0.1.0 – 2026-07-01

### Compatibility

- Reviewed for compatibility with OpenProject 17.5.1 / 17.5.0. No breaking API change
  affects this server. The 17.5 change that replaces the `X-Requested-With` header check with
  `Sec-Fetch-Site` applies to session authentication only; this server authenticates
  with an API token (HTTP Basic auth) and is unaffected. The 17.4.1 security fixes
  touch meeting, journal, and baseline endpoints that this server does not use.
- Verified against OpenProject 16.6 (classic), 17.4 (displayId), and 17.5 (semantic)
  via the local Docker matrix, plus a source-level API audit across 16.0–17.5.

### Added

- Single work package tools now accept a project-prefixed identifier (e.g. `PROJ-123`)
  in addition to the numeric id (sent as either a number or a string); the bulk tools
  remain numeric-only. OpenProject 17.5 lets administrators switch the displayed
  identifier to a project-based format exposed via `displayId`, and its
  `work_packages/{id}` endpoints resolve that form server-side. References are passed
  through to the endpoint verbatim, so the behaviour degrades cleanly: on instances
  without semantic identifiers a project-prefixed reference simply yields a 404
  (surfaced as not-found), while numeric ids keep working on every supported version.
- Relation and parent writes resolve a project-prefixed reference to the numeric id
  before building the HAL link, since link hrefs are not resolved by `displayId`.
- Interactive setup can detect installed MCP clients (Claude Code, Claude Desktop,
  Codex, Cursor, VS Code/Copilot) and register the server in a client's user-wide
  config. Registration merges rather than overwrites, backing up the existing file.
- `uninstall.sh` / `uninstall.ps1` and a `configure_mcp.py --uninstall` mode remove
  the `openproject` entry from client configs (keeping other servers, with backups)
  and clean up the local environment.
- `OPENPROJECT_ATTACHMENT_ROOT` confines attachment uploads to a directory (default:
  the working directory); files outside it, and credential/config files such as
  `.mcp.json` / `.env` / private keys even inside it, are refused.

### Security

- Attachment uploads can no longer read arbitrary local files, closing a
  credential-exfiltration path.
- `list_relations` is gated by the read scope and filtered by the project read
  allowlist on both linked work packages; `update_relation`, `update_reminder`, and
  `delete_reminder` apply the project write allowlist; `copy_project` validates its
  destination; hidden work-package subjects no longer leak through relation tools.
- `OPENPROJECT_AUTO_CONFIRM_DELETE` now correctly governs the preview step for all
  destructive deletes.

### Docs

- Onboarding docs reworked: install-once/register-per-client model, per-client
  config matrix, per-OS paths, verification steps, and gitignore reminders. Added a
  Cursor guide and a generic "any other MCP client" note.

---

## 0.0.1 (development baseline)

Initial development baseline. The pre-release history is kept below as dated
milestones.

### 2026-05-18

#### Compatibility

- Verified against OpenProject 17.4. No breaking API changes in 17.4.
- Work package responses now expose a `display_id` field (`displayId` in the API),
  introduced in 17.4 as preparation for project-based identifiers in 17.5.
  The numeric `id` remains the canonical identifier for all tool parameters; `display_id`
  is informational and may show a project-prefixed form (e.g. `ABC-42`) once 17.5 is deployed.

#### Fixes

- Authentication header changed from `Bearer <token>` to `Basic base64(apikey:<token>)`,
  aligning with the OpenProject API documentation. Both formats are accepted by OpenProject;
  this change makes the implementation spec-compliant.

#### Bug fixes

- `list_work_packages`, `list_my_open_work_packages`, `list_versions`, and `list_projects`
  now report `total` and `count` consistently when the read allowlist filters items out
  of the API response. Previously `total` reflected the unfiltered server count while
  `count`/`results` reflected the filtered set, producing responses like
  `{"total": 8, "count": 0, "results": []}`. `next_offset` and `truncated` continue to
  follow server-side pagination so callers still walk every page that may contain
  allowed items.
- `list_work_packages` without an explicit `project` argument now correctly filters
  results to allowed projects when `OPENPROJECT_ALLOWED_PROJECTS_READ` is restricted.
  Previously the API returned all visible work packages and client-side filtering was
  applied per-page, causing `total` to be unreliable. The server is now given a
  project-id filter so only allowed work packages are returned from the start.
- Allowlist matching now resolves project names and hyphenated display names to their
  canonical identifiers at startup, so HAL links that carry only the project id are
  correctly matched against name-based allowlist entries.

#### Configuration

- `OPENPROJECT_ALLOWED_PROJECTS_READ` now accepts glob patterns in addition to exact
  identifiers and names (e.g. `team-*` matches `team-alpha`, `team-beta`).

---

### 2026-04-08

#### Tools

- **Projects** — list, get, create, copy (with background job tracking), update, delete;
  read admin context, project configuration, and lifecycle phase definitions/instances
- **Work packages** — list with structured filters (`project`, `type`, `version`,
  `has_description`); free-text search with optional `project`, `status`, `open_only`,
  `assignee_me` filters; get, create, subtask, update, delete; add comments; create/delete
  relations; get relations and activity log; bulk create and bulk update; list own open
  work packages
- **Watchers** — list, add, remove
- **Attachments** — list, get, upload, delete
- **File links** — list, delete (Nextcloud CE integration)
- **Time entries** — list, get, create, update, delete; list available activities
- **Versions** — list (global or project-scoped), get, create, update, delete
- **Boards** — list, get, create (basic and grouped), update, delete; list saved views,
  get view
- **Memberships** — list, get, create, update, delete; list roles and principals; get
  current user's project access
- **Users** — get current user; list, get, create, update, delete, lock, unlock
- **Groups** — list, get, create, update (full member-list replacement with add/remove
  helpers), delete
- **Documents** — list, get, update (no create/delete endpoint in CE API)
- **News** — list, get, create, update, delete
- **Wiki pages** — get single page by id; no list tool (CE API v3 has no collection
  endpoint — `GET /api/v3/projects/{id}/wiki_pages` is not implemented)
- **Categories** — list, get (no write API in CE)
- **Notifications** — list, mark single read, mark all read
- **Grids** — list, get, create, update, delete
- **User preferences** — get, update (always available — no write gate required)
- **Instance configuration** — get
- **Query metadata** — get filter, column, operator, sort-by; list/get filter-instance
  schemas
- **Help texts** — list, get
- **Working days** — list working-day configuration; list non-working days
- **Custom options** — get
- **Relations (global)** — list, update
- **Actions & capabilities** — list
- **Text rendering** — render markdown or plain text to HTML via OpenProject API

#### Permission model

- Scoped read flags per chain: `OPENPROJECT_ENABLE_PROJECT_READ`,
  `OPENPROJECT_ENABLE_WORK_PACKAGE_READ`, `OPENPROJECT_ENABLE_MEMBERSHIP_READ`,
  `OPENPROJECT_ENABLE_VERSION_READ`, `OPENPROJECT_ENABLE_BOARD_READ` (all default `true`)
- Scoped write flags per chain: `OPENPROJECT_ENABLE_PROJECT_WRITE`,
  `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`, `OPENPROJECT_ENABLE_MEMBERSHIP_WRITE`,
  `OPENPROJECT_ENABLE_VERSION_WRITE`, `OPENPROJECT_ENABLE_BOARD_WRITE` (all default `false`)
- `OPENPROJECT_ENABLE_ADMIN_WRITE` — dedicated opt-in for instance-wide user and group
  management; never activated by project-scoped write flags (default `false`)
- No global shortcut flags — each scope must be enabled explicitly
- Two-layer safety model: MCP env-var gates (ceiling) + OpenProject server-side role
  permissions (final authority); a `403` from OpenProject surfaces as a tool error

#### Architecture

- Five-module layout: `server.py`, `config.py`, `client.py`, `models.py`, `tools.py`
- All policy logic (read gates, write gates, project scoping, field hiding) concentrated
  in `client.py` for easier security review
- Preview/confirm two-step pattern for all writes and deletes; bypassable globally via
  `OPENPROJECT_AUTO_CONFIRM_WRITE` or per class via `OPENPROJECT_AUTO_CONFIRM_DELETE`
- Project allowlists matched case-insensitively against identifier, name, and numeric ID;
  hyphenated name variant tested for HAL-embedded links
- Field hiding per entity type via `OPENPROJECT_HIDE_<ENTITY>_FIELDS`; hidden fields are
  rejected on writes too
- HAL responses normalized into compact dataclasses; raw payloads never forwarded to MCP
  clients
- Pagination bounded by `OPENPROJECT_DEFAULT_PAGE_SIZE`, `OPENPROJECT_MAX_PAGE_SIZE`,
  `OPENPROJECT_MAX_RESULTS`
- Form validation against OpenProject schema endpoints before create/update writes

#### Test coverage

- 152 unit tests (httpx mock transport, no network)
- Integration test suite (`tests/integration/`) against a live OpenProject instance;
  excluded from the default run, opt in with `-m integration`

#### Scope

- Community Edition only — Enterprise features (Placeholder Users, Budgets, Portfolios,
  Programs, Custom Actions, Baseline Comparisons) are not implemented
- Nextcloud file links included (CE feature; returns empty list gracefully if Nextcloud
  not connected)
- Project lifecycle phases included (read-only; degrades gracefully if unavailable)

#### Known API notes

- `GET /api/v3/projects/{id}/wiki_pages` is not implemented in OpenProject v3;
  `list_wiki_pages` is therefore not provided. Individual pages are accessible via
  `get_wiki_page`.
- Project-scoped endpoints for work packages and versions are deprecated in OpenProject
  17.2 in favour of workspace-scoped alternatives; the deprecated paths remain in use as
  the workspace-scoped alternatives are not yet stable in CE.
- Relations use the canonical `/api/v3/relations` endpoint with a filter instead of the
  redirecting project-scoped path.
- Groups PATCH requires a complete `_links.members` array (full replacement); the client
  fetches the current list and applies adds/removes before sending.
