# Changelog

All notable changes to this project will be documented in this file. Versions
follow [semantic versioning](https://semver.org); 0.2.0 is the first release
published to PyPI, 0.1.0 is the first tagged release, and 0.0.1 is the
development baseline.

---

## [0.4.0] - Unreleased

Complete the layered `app/` architecture migration so the codebase can scale
beyond a monolithic client while expanding and hardening the Community Edition
tool surface. This release adds new domains, richer work-package and attachment
capabilities, simpler installation, clearer permission and error behavior, and
broader OpenProject version compatibility.

### Security

- Updated `cryptography` to 50.0.0 to fix the high-severity
  GHSA-g6cj-pr64-35w5 padding-oracle vulnerability.
- Hidden project fields no longer leak through the available-parent-projects
  list.
- Unexpected bulk work-package errors no longer expose internal details.

### Added

#### Attachments

- `get_attachment_content` returns bounded image or text content for supported
  attachments and a clear skip reason for unsupported or oversized files.
- `list_work_package_attachments` gains `include_images`, inlining the listed
  images under one aggregate byte budget and reporting per-attachment skip
  reasons in `images`.

#### Work packages

- `list_work_packages`/`search_work_packages` gain `include_sums` (server-
  computed group aggregates), `overdue_only`/`due_within_days` (due-date
  filtering), and `custom_field_filters` (filter by custom field value).
- `bulk_update_work_packages` now supports `sprint`.
- `bulk_create_work_packages`/`bulk_update_work_packages` item fields now
  accept `parent` as well as `parent_work_package_id`, and both gain a
  `select` parameter to shrink an unconfirmed preview's echoed payload.
- `get_project` now returns the project's ancestor chain (`ancestors`).
- `get_work_package_relations` results now carry `queried_perspective`, a
  caller-relative reading of the relation (direction, effective type).
- `list_work_packages`/`search_work_packages`/`get_work_package`/
  `get_work_packages`/`list_my_open_work_packages` now expose custom field
  values.
- Work-package results now expose `has_project_attributes` on OpenProject
  17.7 and later.
- `create_work_package`/`create_subtask`/`update_work_package` (and both
  bulk tools' per-item fields) gain `target_versions`, OpenProject 17.7+'s
  multi-value successor to `version` — cannot be combined with `version`
  in the same call. Every work package result now also carries
  `target_versions`; `version` stays as a derived single-value field,
  `None` when more than one target version is assigned.

#### Search and result shaping

- `list_documents`, `list_views`, and `list_sprints` gain a `search`
  parameter.
- `get_document`, `get_news`, `get_wiki_page`, and meeting agenda-item and
  outcome lists gain per-call text limits; documents and news return their
  full descriptions by default.
- `get_work_package`, `list_actions`, `list_capabilities`, `list_time_entries`,
  `list_notifications`, meeting lists, and attachment lists gain response-field
  selection; attachment lists also gain pagination.
- Attachment lists can include total file size, and time-entry lists can
  include total hours.

#### New domains

- Wiki-link CRUD is available on OpenProject 17.6 and later.
- `execute_query` runs saved OpenProject queries.
- Storage tools manage external storages and project-storage connections.
- The Meetings domain covers meetings, agenda items, sections, outcomes, and
  recurring meetings.
- Costs read tools include `get_cost_entry`,
  `list_work_package_cost_entries`, `get_work_package_costs_by_type`,
  and `get_cost_type`.
- GitHub/GitLab integration links, forum posts, and Backlogs buckets have
  dedicated read tools.
- Per-user schedule tools manage non-working times and working hours.

### Changed

#### Tool interface

- Tool descriptions are substantially shorter across the whole catalog,
  reducing the fixed per-session token cost of the tool catalog itself.
- A project-scoped read tool is no longer registered when
  `OPENPROJECT_READ_PROJECTS` is empty, matching how write tools already
  behaved.
- **Breaking:** project-favorite operations are consolidated into
  `set_project_favorite(favorite: bool)`.
- **Breaking:** user locking operations are consolidated into
  `set_user_locked(locked: bool)`.
- **Breaking:** work-package watcher operations are consolidated into
  `set_work_package_watcher(watching: bool)`.
- **Breaking:** notification-read operations are consolidated into
  `mark_notifications_read(notification_id=None)`.
- **Breaking:** `list_project_sprints` is replaced by
  `list_sprints(project=None, ...)`.
- **Breaking:** `maximum_attachment_file_size`/`file_size` output fields
  renamed to `maximum_attachment_file_size_bytes`/`file_size_bytes`.

### Removed

- **Breaking:** `get.ps1`/`get.sh` and `uninstall.ps1`/`uninstall.sh` are
  removed. Use `pipx`, or `git clone` with `uv sync --dev` for a source install.
- **Breaking:** removed client-constructed `url` fields (and a few sub-
  collection hrefs) from MCP output models across most domains — these
  never resolved to a real page.
- **Breaking:** every non-bulk write/delete result's `confirmed`/
  `requires_confirmation` boolean pair is replaced by a single `state`
  field. Bulk work-package writes are unaffected.
- **Breaking:** `search_work_packages`'s `query` parameter is renamed to
  `search`, matching every other search-capable tool.
- **Breaking:** `list_roles` now returns a paginated result instead of the
  complete role collection in one call.
- **Breaking:** the legacy env-var names deprecated in 0.3.0 are removed. Use
  `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS`, the individual
  `OPENPROJECT_ENABLE_<GROUP>_READ` flags, `OPENPROJECT_ENABLE_EXTENDED_READ`,
  and `OPENPROJECT_ENABLE_PERSONAL_WRITE`; the old auto-confirm flags have no
  replacement. `OPENPROJECT_ALLOWED_PROJECTS`/`_READ`/`_WRITE` still emit a
  one-time startup/`doctor` warning naming their replacement and are prefilled
  by `configure`, unlike every other legacy name in this list — see
  [Configuration](docs/configuration.md#legacy-configuration-migration).

### Fixed

- Some write rejections showed a generic message instead of the actual
  reason (e.g. a rejected storage connection on Community Edition). The
  specific reason is now surfaced.
- A permission-denied response could be misreported as an authentication
  failure if OpenProject's rejection bundled an unrelated detail message
  mentioning "token" or "authenticate".
- Time and cost entries now retain their work-package association on
  OpenProject versions earlier than 16.6.
- `list_projects` and `list_work_packages`/`search_work_packages` no
  longer report a false `truncated: true` when exactly the requested
  `limit` of allowed results exists and nothing else does.
- User-typed fields (`responsible`, and user/version reference custom fields)
  can now be set on work-package writes.
- Time-entry activities can now be resolved when OpenProject returns their
  allowed values as a link.
- `update_document`'s `description` field no longer corrupts the stored
  value into an unusable string.

## [0.3.8] - 2026-08-25

### Added

- `search_work_packages` resolves numeric and display IDs such as `PROJ-42`
  directly and returns the result separately as `exact_match`.

### Changed

- The setup wizard's quick-mode write-scope question now asks per category
  instead of offering only `none`/`work-packages`/`all`.

### Fixed

- Work-package writes can set `version` without a false conflict with target
  versions.
- The source installers install their dependencies before starting setup.
- The Windows installer keeps the calling PowerShell window open on failure
  and reports an unsupported Python installation clearly.
- Source installation works reliably with PowerShell 5.1 TLS defaults.
- The Windows setup wizard accepts pasted API tokens without corrupting them.

### Known Issues

- Source installation on Windows ARM64 (`win_arm64`) requires the Visual
  Studio Build Tools C++ workload because `cryptography` has no prebuilt wheel
  for this platform. Alternatively, use `win_amd64` or WSL. The missing wheel
  is tracked upstream in
  [modelcontextprotocol/python-sdk#3373](https://github.com/modelcontextprotocol/python-sdk/issues/3373).

## [0.3.7] - 2026-08-17

### Security

- Updated `cryptography` to 50.0.0 to fix the high-severity
  GHSA-79v4-65xg-pq6g padding-oracle vulnerability.

### Fixed

- `list_my_open_work_packages` now returns complete allowed results under a
  restricted project read scope, including matches beyond the first server
  page.

## [0.3.6] - 2026-08-10

### Changed

- **Breaking:** Client-constructed `url` fields and related collection links
  are removed from most output models. Server-provided `download_url`,
  `avatar_url`, `identity_url`, and resolvable `url` fields remain available.
- **Breaking:** `list_work_package_attachments`, `list_reminders`, and
  `list_work_package_file_links` now use `offset`/`limit` and return paginated
  results with `total`, `next_offset`, and `truncated`. Treat `total` as a
  lower bound and continue paging until `next_offset` is `null`.
- Batch work-package reads limit concurrent requests to ten.
- Project allowlist checks for relations, notifications, reminders, and work-
  package hierarchies run concurrently for faster restricted-scope reads.

### Fixed

- Tools reject unknown or misspelled arguments instead of silently using
  defaults.
- Generic setup instructions use a token-free example file instead of writing
  a real token to `.mcp.json`.
- Setup and uninstall operations report filesystem failures cleanly and
  continue processing other selected clients.
- Collection tools now honor requested page sizes, return reliable pagination
  state, and avoid hiding boards beyond the server's default result cap.

---

## [0.3.5] - 2026-08-02

### Added

- `create_time_entry_until` and `update_time_entry_until` accept start and end
  times and calculate the duration. Time-entry durations also accept
  fractional seconds.

### Changed

- **Breaking:** `create_time_entry` and `update_time_entry` no longer accept
  the unsupported `end_time` parameter. Use the new `*_until` tools when both
  start and end times are known.

### Fixed

- User locking, notification-read operations, and password-based user creation
  now succeed against the OpenProject API.
- Work-package field hiding remains effective when returning hierarchies under
  a restricted read scope.
- Name-based sprint lookup includes matches beyond the first page.
- Work-package and project context results no longer duplicate or expose
  non-writable schema fields.
- Truncated time-entry comments report their original length and truncation
  state.
- Malformed, invisible, or unrelated project and attachment links are denied
  consistently instead of passing scope checks.

---

## [0.3.4] - 2026-07-29

### Changed

- **Breaking:** The ineffective `lang` preference field is removed. Use
  `update_user`'s `language` field instead.

### Security

- Relation targets, job statuses, copied projects, categories, grids, and
  project memberships now consistently enforce project allowlists.
- API path IDs containing `.` or `..` segments are rejected before requests
  are sent.
- Hidden-field rules now cover time-entry `start_time`/`end_time` writes, user
  preference updates, and grid results.
- Project, document, version, attachment, reminder, relation, and activity
  descriptions, plus time-entry comments, are now consistently marked as
  untrusted user content.

### Fixed

#### Time entries and reminders

- Time-entry previews now reflect OpenProject validation, and named activities
  work for users with only the "Log own time" permission.
- Reminder updates and deletions no longer fail on every call.

#### Lists and lookups

- Relation, membership, attachment, time-entry, grid, notification, reminder,
  file-link, view, document, version, sprint, news, user, and group listings no
  longer hide results because of single-page or fixed-cap fetching.
- Pagination terminates safely when an endpoint ignores its requested page
  size.
- Capability, sort-by, and job-status lookups now return valid IDs and work on
  the supported OpenProject versions.
- Group results report the correct member count.

#### Work packages and projects

- Work-package reads work on classic OpenProject versions and tolerate hierarchy
  links without display IDs.
- Parent-project choices contain only allowed projects and no longer expose full
  project details.
- Bulk work-package updates accept `sprint`, and their validation errors name
  `assignee` and `responsible` consistently.
- File-link writes no longer report a fabricated work-package ID.

#### Preferences and metadata

- Extended metadata tools honor their read-enablement setting.
- Null link collections and user identity URLs are handled correctly.

---

## [0.3.3] - 2026-07-28

### Security

- Board moves, parent-project changes, work-package parent and relation changes,
  job statuses, capabilities, watchers, file links, hierarchies, attachments,
  reminders, groups, users, and grids now consistently enforce project scope and
  hidden-field rules.
- Project-scoped results no longer leak subjects, identifiers, names, or
  principals from disallowed projects.

### Fixed

- News, document, and time-entry truncation honor their own hidden-field
  settings.
- Emoji-reaction previews no longer require the work-package write feature to
  be enabled, while still enforcing the project write allowlist.
- Projects created, copied, or renamed become immediately available to scoped
  tools without a server restart.
- Unscoped work-package lists return a clear permission error when they cannot
  prove that all results are allowed.
- Capability filtering works on OpenProject 16.x.
- Grid lists are paginated.
- Permission-denied responses include OpenProject's specific error message.

---

## [0.3.2] - 2026-07-20

### Fixed

- Milestone work packages now return their actual start and due dates.
- Closing a work package without an estimated time now succeeds on the first
  attempt.

---

## [0.3.1] - 2026-07-18

### Fixed

- Bulk work-package writes report indexed errors for unknown item fields
  instead of silently dropping them.
- Bulk work-package creation preserves `estimated_time`, `remaining_time`, and
  `duration`.
- A write scope narrower than the read scope no longer rejects otherwise
  allowed writes.

---

## [0.3.0] - 2026-07-17

Harden project isolation with fail-closed scopes and mandatory confirmation for
every write. Expand work-package querying, scheduling, hierarchy, and Backlogs
support while making setup and responses easier to use.

### Added

#### Work packages

- `get_work_packages` reads up to 100 work packages in parallel with per-item
  errors, deduplication, and field selection.
- Work-package lists support sorting, grouping, and filters for assignee,
  status, priority, and created, updated, or due dates.
- Work-package reads and writes expose richer scheduling, time-tracking,
  metadata, hierarchy, and progress fields.
- Nullable assignee, responsible, category, project phase, version, and sprint
  links can be cleared with `none` in single and bulk updates.
- Backlogs-enabled instances gain sprint reads and writable work-package sprint
  links.

#### Reliability and setup

- Transient HTTP failures are retried with configurable exponential backoff.
- `list_versions` supports text search, and project references fall back to an
  exact display-name match.
- The new `doctor` command diagnoses configuration and connectivity end to end.

### Changed

- **Breaking:** Every write and delete now requires `confirm=true`;
  `OPENPROJECT_AUTO_CONFIRM_WRITE` and `OPENPROJECT_AUTO_CONFIRM_DELETE` no
  longer bypass confirmation.
- **Breaking:** Project scopes are renamed to `OPENPROJECT_READ_PROJECTS` and
  `OPENPROJECT_WRITE_PROJECTS` and now deny access when empty or unset. Update
  configurations that still use the former `OPENPROJECT_ALLOWED_PROJECTS*`
  names before upgrading.
- **Breaking:** Personal, administrative, and extended read tools now require
  their dedicated opt-in scopes, which default to disabled.
- **Breaking:** Project-scoped write feature flags now default to enabled, with
  the fail-closed `OPENPROJECT_WRITE_PROJECTS` scope remaining the effective
  gate. Administrative and personal write flags remain disabled by default.
- **Breaking:** Attachment uploads no longer use the current directory as a
  fallback. `OPENPROJECT_ATTACHMENT_ROOT` must be configured as an absolute
  path.
- Tool registration now requires every scope used by a tool to be enabled.
- Setup gains quick, advanced, and non-interactive modes, a live connection
  test, and a final configuration preview.
- Hidden fields are omitted instead of returned as null, responses are more
  compact, and single work-package reads return long text in full.

### Fixed

- `OPENPROJECT_LOG_LEVEL` is honored and accepts `DEBUG`.
- Project, version, sprint, user, and group listings paginate correctly under
  search and restricted project scopes.
- Work-package field selection includes requested metadata, and list results
  expose `parent_display_id`.
- User write previews now use OpenProject's form validation.
- Work-package comments report the correct author without leaking unrelated
  activity details.
- Text fields can be cleared with an empty string across supported update
  tools.
- Bulk item IDs, scalar values, and ambiguous type names are validated without
  crashes or unsafe coercion.

### Security

- User-provided content is delimited and identified as untrusted.
- Sprint lists, reference resolution, and deprecated scope handling no longer
  allow cross-project data exposure or writes.
- Watcher and activity fields honor their hidden-field settings.
- List totals no longer reveal matches in disallowed projects.

---

## [0.2.3] - 2026-07-07

### Fixed

- Work-package attachment uploads no longer fail with a server error.
- The MCP initialization handshake reports this package's version.

### Added

- The MCP initialization response explains Community Edition API limits to
  connected agents.
- Work packages can be nested, re-parented, or detached with the new `parent`
  parameter.

---

## [0.2.2] - 2026-07-06

### Security

- File-link deletion and activity emoji reactions now enforce the project write
  allowlist.

### Fixed

- Group reads no longer crash when members are visible.
- Time-entry creation accepts semantic work-package references.
- Validation errors for `responsible` name the correct field.
- `openproject-ce-mcp configure` now exits cleanly on Ctrl+C.

### Changed

- A remote plain-HTTP base URL now warns that the API token will be transmitted
  without encryption.

---

## [0.2.1] - 2026-07-01

### Changed

- Setup now asks independently about global and project-scoped registration and
  writes only the selected targets.
- Re-running setup preserves existing values field by field.
- The writable-project prompt clarifies that `*` means all readable projects.

### Added

- Setup gives client-specific restart instructions.
- `configure --uninstall` also removes project-local registrations in the
  current directory.

---

## [0.2.0] - 2026-07-01

Publish the first PyPI release under the `openproject-ce-mcp` name. Add a
guided setup command and a top-level command-line interface for installation
and client registration.

### Added

- PyPI distribution, installable with `pip`, `pipx`, or `uv tool install`.
- `openproject-ce-mcp configure` registers the server with detected MCP
  clients.
- Top-level CLI: `openproject-ce-mcp --help`/`--version`.

### Changed

- The package is renamed to `openproject-ce-mcp`; the MCP server key remains
  `openproject`, so existing client registrations keep working.

### Fixed

- The shell installer no longer crashes on its first interactive prompt.
- Re-running `configure --global` pre-fills from an existing client
  registration.
- `configure` warns before writing a token-bearing `.mcp.json` into an
  unrelated project directory.

---

## [0.1.0] - 2026-07-01

Deliver the first Community Edition MCP server with broad OpenProject API v3
coverage. Provide guarded read and write access, compact MCP responses, and an
interactive setup flow for supported clients.

### Added

#### Core OpenProject domains

- Read and write tools cover projects, work packages, versions, boards,
  memberships, users, groups, news, notifications, grids, preferences, and
  time entries.
- Read or API-supported update tools cover documents, wiki pages, categories,
  instance configuration, query metadata, help texts, working days, custom
  options, actions, capabilities, and text rendering.
- Work-package tools include structured and free-text search, subtasks,
  comments, relations, activity history, bulk writes, watchers, attachments,
  and Nextcloud file links.
- Project-prefixed work-package identifiers such as `PROJ-123` are accepted by
  single-item, relation, and parent operations; numeric IDs remain canonical.

#### Setup and safety

- Interactive setup detects Claude Code, Claude Desktop, Codex, Cursor, and VS
  Code/Copilot and can register or remove the server in their configurations.
- Read, write, and administrative capabilities have independent feature gates,
  with write access disabled by default.
- Project allowlists match identifiers, names, numeric IDs, and glob patterns
  case-insensitively.
- Writes and deletes use a preview-and-confirm flow, while OpenProject role
  permissions remain the final authority.
- Attachment uploads are confined to `OPENPROJECT_ATTACHMENT_ROOT` and reject
  paths outside it as well as credential and configuration files.
- Field-hiding settings apply to reads and writes, and list results remain
  bounded and compact.

### Security

- Project allowlists protect relations, reminders, copied projects, and other
  linked resources from cross-project access.
- Hidden work-package subjects are not exposed through relation tools.
