# Changelog

All notable changes to this project will be documented in this file. Versions
follow [semantic versioning](https://semver.org); 0.2.0 is the first release
published to PyPI, 0.1.0 is the first tagged release, and 0.0.1 is the
development baseline.

---

## [Unreleased 0.4.0]

Complete the layered `app/` architecture migration: decompose the client's
business logic out of a single flat file into focused Services, Ports, and
Adapters, so the codebase scales past what a monolithic client.py can
support.

### Added

- **`list_documents`, `list_views`, `list_sprints`, and
  `list_project_sprints` gain a `search` parameter.**
- **`bulk_update_work_packages` now supports `sprint`.**
- **`bulk_create_work_packages`/`bulk_update_work_packages` item fields now
  accept `parent`** as well as `parent_work_package_id`.
- **`bulk_create_work_packages`/`bulk_update_work_packages` gain a `select`
  parameter** to shrink an unconfirmed preview's echoed payload.
- **`get_project` now returns the project's ancestor chain (`ancestors`).**

### Changed

- **Breaking: `search_work_packages`'s `query` parameter is renamed to
  `search`**, matching every other search-capable tool.
- **Breaking: `list_roles` now returns a paginated result** instead of the
  complete role collection in one call.
- **Bulk work-package writes reuse resolved project/type/version/sprint
  lookups across items targeting the same project**, reducing redundant API
  calls for large batches.
- **Server startup no longer enriches the initial instructions with the
  instance's live feature flags.** This data remains available via
  `get_instance_configuration`.
- CI now runs **Semgrep** as a second SAST pass, and a complete
  shell-script gate across the repo's shell scripts. No end-user-visible
  behavior change.

### Fixed

- **`list_principals`, `get_current_user`, and `get_instance_configuration`
  are now migrated onto the layered `app/` architecture**, completing the
  set of domains with no user-facing behavior change.
- **`get_job_status` now correctly honors `OPENPROJECT_READ_PROJECTS` for a
  job status scoped only via its `sourceProject` link.**
- **`create_user`/`update_user`/`lock_user`/`unlock_user` now honor
  `OPENPROJECT_HIDE_USER_FIELDS` on writes**, not just reads.
- **`create_group`/`update_group` now honor `OPENPROJECT_HIDE_GROUP_FIELDS`
  on writes**, not just reads.
- **Breaking: `delete_grid(confirm=true)` now returns the deleted grid's
  summary in `result`**, instead of `null`, matching every sibling delete
  tool.
- **`get_news`/`list_news` description truncation now honors
  `OPENPROJECT_HIDE_NEWS_FIELDS`.**
- **`get_document`/`list_documents` description truncation now honors
  `OPENPROJECT_HIDE_DOCUMENT_FIELDS`.**
- **`get_time_entry`/`list_time_entries` comment truncation now honors
  `OPENPROJECT_HIDE_TIME_ENTRY_FIELDS`.**
- **`bulk_create_work_packages`/`bulk_update_work_packages` now report
  `assignee`/`responsible` validation errors indexed per item.**
- **`get_project` now additionally handles a project that has a parent.**
- **`configure`'s generic copy-source for MCP clients without native
  support no longer writes to `.mcp.json`** — it now writes to a dedicated
  `openproject-mcp.example.json` with a placeholder token.
- **`configure`/`--uninstall` no longer crash with an unhandled traceback
  on a filesystem error while writing or removing a client config.** A
  failure on one target no longer aborts the remaining ones, and the
  process exits non-zero with a summary of every failed target.
- **`list_work_packages` without an explicit `project` now raises a clear
  permission error instead of silently returning zero results** when it
  cannot prove the query is scoped to only the allowed projects.
- **`list_priorities`/`get_priority` now honor a new
  `OPENPROJECT_HIDE_PRIORITY_FIELDS` environment variable.**
- **New `OPENPROJECT_HIDE_NOTIFICATION_FIELDS` and
  `OPENPROJECT_HIDE_EMOJI_REACTION_FIELDS` environment variables.**
- **`OPENPROJECT_HIDE_FILE_LINK_FIELDS` now actually hides fields.**
- **Breaking: `list_grids` now returns a paginated result** instead of
  every matching grid in one unbounded call.
- **`list_capabilities`'s `capability_id` lookup no longer 404s, and
  `CapabilitySummary.id` is no longer collapsed onto the same value for
  every capability in a given project/user context.**
- **Four more unguarded walk-every-server-page loops shared the same
  hang-forever vulnerability already fixed in 0.3.4** (the layered
  Versions domain's own project-scoped resolver, `_resolve_sprint_id`,
  `list_work_package_attachments`, and the shared `paginate_all` helper);
  all now stop on a repeated page.
- **A missing project link on a work package now raises a server-error
  category, not a validation error** — matching how every other
  server-data anomaly is reported.
- **`update_reminder`/`delete_reminder`'s internal reminder lookup no
  longer risks looping forever** if the reminders collection endpoint
  ignores pagination parameters.

### Docs

- Added the missing "Notes" section to the Cursor client guide.
- Documented the monorepo/umbrella-directory case where `configure` writes
  to the wrong place relative to where an AI client actually opens its
  workspace.
- Clarified that the VS Code/Copilot guide is about VS Code's own MCP host,
  not a standalone "GitHub MCP server".

---

## 0.3.5 – 2026-08-02

### Added

- **`create_time_entry_until`/`update_time_entry_until`** let a caller specify
  `start_time`+`end_time` instead of `hours` directly.
  `create_time_entry_until` has no `ongoing` parameter (a time entry with a
  known end time is complete, not still running); `update_time_entry_until`
  always sets `ongoing=false`. `hours` now also accepts a fractional-second
  duration (e.g. `PT7H30M15.5S`) on `create_time_entry`/`update_time_entry`
  too.

### Fixed

- **`lock_user` and `mark_notification_read`/`mark_all_notifications_read`
  no longer fail with a `406` error.**
- **`create_user` with a `password` no longer silently fails to create the
  user.**
- **`create_time_entry`/`update_time_entry` no longer accept an `end_time`
  parameter** (OpenProject computes it from `start_time` + `hours` and
  rejects a caller-supplied value). `start_time` is unaffected; `end_time`
  is still returned when reading a time entry.
- **`get_work_package`/`get_work_packages` no longer return fully unmasked
  fields under a restricted `OPENPROJECT_READ_PROJECTS` scope** when the
  work package has children or ancestors to filter.
- **`get_sprint`/`list_project_sprints` name-based sprint lookup no longer
  misses sprints beyond the first page.**
- **`get_project_work_package_context` no longer duplicates the
  `status`/`priority`/`category`/`project_phase` option lists** in both
  the hoisted `available_*` fields and the raw field schema.
- **`get_project_admin_context` now returns only writable schema fields**,
  instead of every field including non-writable/internal ones.
- **`get_time_entry`/`list_time_entries` now report `comment_truncated`/
  `comment_length`** when a comment is cut, matching every other
  truncation-capable field.
- **A malformed or invisible project link on a work package, membership,
  view, job status, or board is now consistently denied instead of
  silently allowed** under a wide-open `OPENPROJECT_READ_PROJECTS`/
  `WRITE_PROJECTS="*"` scope, closing a fail-open gap that treated a
  missing/malformed link as implicitly in-scope before checking it.
  `get_job_status` and `list_notifications` had two related gaps of their
  own (a falsy-but-present project link silently replaced by a fallback
  link; a malformed link that wasn't a plain object skipping the check
  entirely) fixed the same way.
- **Attachment container authorization no longer accepts an unrelated
  resource whose path merely contains `work_packages/`** (e.g.
  `/api/v3/not_work_packages/9`) as if it were a real work-package
  container — an exact path-segment match is now required.

---

## 0.3.4 – 2026-07-29

### Fixed

- **`create_work_package_relation` no longer lets a relation target a work
  package outside `OPENPROJECT_WRITE_PROJECTS`.**
- **`create_time_entry`/`update_time_entry` now honor
  `OPENPROJECT_HIDE_TIME_ENTRY_FIELDS` for `start_time`/`end_time` on
  writes**, not just reads.
- **`create_time_entry`/`update_time_entry` previews now reflect
  OpenProject's own validation**, instead of always reporting `ready=true`.
- **`create_time_entry` with a named `activity` no longer fails with
  `permission_denied` for a user who only has OpenProject's "Log own time"
  permission.**
- **`get_work_package` no longer crashes on classic/pre-17.5 OpenProject
  instances, or on ancestor/child links without a display ID.**
- **`list_capabilities`'s `context` filter no longer rejects every request
  on OpenProject 16.x.**
- **`get_query_sort_by` no longer 404s on every OpenProject version.**
- **`get_work_package_relations`/`list_relations` no longer silently
  truncate results to the server's default page size.**
- **`list_project_memberships` no longer silently truncates results to the
  server's default page size.**
- **`list_groups`'s `member_count` no longer always reports 0.**
- **A parent-project picklist (`get_project_admin_context`) no longer
  returns full project details for every candidate, and no longer includes
  a candidate outside `OPENPROJECT_READ_PROJECTS`.**
- **`list_views`/`list_documents`/`list_versions`/`list_sprints` (including
  project-scoped and search variants) no longer silently cap results at a
  fixed maximum, hiding any item beyond it.**
- **`list_capabilities`'s `capability_id` lookup no longer 404s, and
  `CapabilitySummary.id` is no longer collapsed onto the same value for
  every capability in a given project/user context.**
- **`get_job_status`'s `job_status_id` is no longer always `null` on a real
  OpenProject instance.**
- **`get_job_status`/`copy_project` no longer silently skip their
  project/sourceProject/createdProject allowlist checks and
  identifier-cache write-through.**
- **A project/version/sprint/etc. listing that walks every server page no
  longer hangs indefinitely against an endpoint that ignores `pageSize`.**
- **`update_reminder`/`delete_reminder` no longer fail on every call.**
- **`update_my_preferences`'s `lang` parameter no longer does nothing** —
  removed together with a few other fields the real API never returns; use
  `update_user`'s `language` field to change a user's language instead.
- **`list_project_memberships` no longer returns memberships from every
  visible project instead of just the requested one.**
- **An id passed into a handful of API paths (`get_job_status`,
  `list_capabilities`'s `capability_id`, and others) could contain `.`/`..`
  path segments that bypassed the allowlist check meant to guard it** — such
  ids are now rejected before the request is made.
- **`create_grid`/`update_grid`/`delete_grid` no longer skip their
  write-allowlist check for a grid whose scope isn't a recognized project or
  personal-page URL.**
- **The "Extended Metadata" tools (help texts, working days, custom
  options) now honor their own read-enablement setting.**
- **`update_my_preferences` now honors
  `OPENPROJECT_HIDE_USER_PREFERENCES_FIELDS`.**
- **`get_category` now checks its project against the read allowlist**,
  and fetches the single category directly instead of re-listing and
  filtering in memory.
- **`list_work_package_attachments`, `list_time_entries`, and `list_grids`
  no longer silently cap results to a single page.**
- **Project/document/version descriptions, time entry comments, reminder
  notes, relation descriptions, attachment descriptions, and activity
  details are now consistently marked as untrusted user content.**
- **Grid results now honor `OPENPROJECT_HIDE_GRID_FIELDS`.**
- **A handful of smaller correctness fixes:** a `null` `_links` value in an
  API response no longer risks a crash; a user's `identity_url` now reads
  the correct property; bulk work package validation errors now name
  `assignee`/`responsible` consistently; bulk work package updates now
  accept a `sprint` field; a file-link write result no longer reports a
  fake work package id of `0`; two redundant follow-up requests were
  removed.
- **`list_notifications` no longer silently misses notifications under a
  restrictive read scope.**
- **`list_reminders` and `list_work_package_file_links` no longer silently
  truncate results to the server's default page size.**
- **`list_users`/`list_groups` (name search), `list_news`, and
  `list_versions` (project-scoped) no longer silently cap results at a
  fixed maximum, hiding any item beyond it.** An internal project-identifier
  cache used for allowlist checks now covers every visible project instead
  of only the first page.
- **Resolving a role by name no longer requires an unnecessary lookup of
  every role when the caller already passed a numeric role id.**

---

## 0.3.3 – 2026-07-28

### Fixed

- **`update_board` no longer lets a board be moved into a project outside
  `OPENPROJECT_WRITE_PROJECTS`.**
- **`get_news`/`list_news` description truncation now honors
  `OPENPROJECT_HIDE_NEWS_FIELDS`.**
- **`get_document`/`list_documents` description truncation and
  `get_time_entry`/`list_time_entries` comment truncation now honor their
  own hidden-fields settings**, instead of the wrong entity's.
- **`get_work_package_relations` no longer leaks a linked work package's id
  and subject from outside `OPENPROJECT_READ_PROJECTS`.**
- **`toggle_activity_emoji_reaction` previews (`confirm=false`) no longer
  require `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`.** The project
  write-allowlist check still runs during preview.
- **A project created or renamed through this server was invisible to
  project-scoped tools under a restrictive
  `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` until the server
  restarted.**
- **`list_work_packages` without an explicit `project` now raises a clear
  permission error instead of silently returning zero results** when it
  cannot prove the query is scoped to only the allowed projects.
- **`list_capabilities` no longer leaks capability records (including
  project names and principals) from outside `OPENPROJECT_READ_PROJECTS`.**
  `capability_id` now also resolves via the single-item lookup instead of an
  undocumented collection filter.
- **`list_capabilities`'s `context` filter no longer rejects every request
  on OpenProject 16.x.**
- **`create_user`/`update_user`/`lock_user`/`unlock_user` now honor
  `OPENPROJECT_HIDE_USER_FIELDS` on writes**, not just reads.
- **`create_grid`/`update_grid` now honor `OPENPROJECT_HIDE_GRID_FIELDS` on
  writes**, not just reads.
- **`get_job_status` no longer leaks a job status scoped only via a
  `sourceProject` link outside `OPENPROJECT_READ_PROJECTS`.**
- **`list_work_package_watchers`/`list_work_package_file_links` no longer
  leak watcher and file link data outside `OPENPROJECT_READ_PROJECTS`.**
- **`get_work_package` no longer leaks a linked work package's subject and
  identifier through `children`/`ancestors` outside
  `OPENPROJECT_READ_PROJECTS`.**
- **Attachment, reminder, and relation writes now honor their hidden-fields
  configuration**, not just reads.
- **`create_group`/`update_group` now honor `OPENPROJECT_HIDE_GROUP_FIELDS`
  on writes**, not just reads.
- **`update_reminder`'s project-write allowlist check could be bypassed by a
  malformed, truthy non-string `href`** on the reminder's linked work
  package.
- **Priorities, notifications, and emoji reactions now honor their
  `OPENPROJECT_HIDE_*_FIELDS` setting.**
- **`list_grids` now paginates** instead of fetching every grid unbounded.
- **`update_project`'s `parent` reassignment now requires write access on
  the new parent project too, not just on the project being updated.**
- **A project created via `copy_project` was invisible to every
  link-shaped allowlist check until the process restarted.**
- **`create_work_package`/`update_work_package`'s `parent_work_package_id`
  reassignment now requires write access on the new parent work package's
  project too, not just read access.**
- **`create_work_package_relation`/`update_relation`'s `type` field and
  `create_work_package_attachment`'s `file_name` field now honor their
  hidden-fields settings on writes.**
- **A `403` from OpenProject now includes OpenProject's own error message**,
  instead of a generic "denied access" text with no further detail.
- **CI workflows now pin third-party GitHub Actions to a full-length commit
  SHA**, as required by this repository's action-pinning ruleset.

---

## 0.3.2 – 2026-07-20

### Fixed

- **Milestone work packages always showed `start_date`/`due_date` as
  `null`, even when a date was genuinely set.**
- **Closing a work package with no `estimated_time` set was rejected on
  the first attempt.**

---

## 0.3.1 – 2026-07-18

### Fixed

- **`bulk_create_work_packages`/`bulk_update_work_packages` no longer
  silently drop unrecognized item fields**, and now report an indexed error
  instead.
- **`bulk_create_work_packages` no longer drops `estimated_time`/
  `remaining_time`/`duration` on every item.**
- **A broad `OPENPROJECT_READ_PROJECTS` combined with a narrower
  `OPENPROJECT_WRITE_PROJECTS` could incorrectly deny a legitimate write.**

---

## 0.3.0 – 2026-07-17

Harden the release: redesign the authorization/config model with fail-closed
scopes and mandatory write confirmation, and adopt mypy.

### Added

- **Batch work-package read**: `get_work_packages(ids=[...])` fetches
  multiple work packages in parallel (capped at 100 ids per call), with
  per-item error tracking, deduplication, and a `select` parameter.
- **Sorting and grouping** for work-package lists: `sort_by` and `group_by`
  on `list_work_packages` and `search_work_packages`.
- **Work-package filters**: assignee/status/priority equality filters, plus
  created/updated/due date filters (exact-day and range).
- **`list_versions` gains a `search` parameter.**
- **Automatic retry with exponential backoff** for transient HTTP failures,
  configurable via `OPENPROJECT_MAX_RETRIES`/`OPENPROJECT_RETRY_BASE_DELAY`/
  `OPENPROJECT_RETRY_MAX_DELAY`.
- **Work-package time tracking, metadata, and hierarchy fields**: writable
  estimated/remaining time and duration, activity details, author/category/
  timestamps, children/ancestors.
- **Work-package scheduling fields**: `scheduleManually`,
  `ignoreNonWorkingDays`, derived start/due date, percentage done,
  `readonly`.
- **Clearing nullable associations via `'none'`** now works consistently
  across assignee, responsible, category, project phase, version, and
  sprint, on both single and bulk updates.
- **Backlogs sprint support**: read tools plus a writable/clearable sprint
  link on `update_work_package`, for instances with the Backlogs module.
- **`percentage_done` is now a writable parameter** on `update_work_package`/
  `bulk_update_work_packages`.
- **`project` now falls back to a display-name match** when the numeric
  id/identifier lookup fails.
- **`doctor` command**: diagnoses setup end to end.
- Several new read-only fields, and field-hiding coverage extended to
  status, type, and sprint.

### Changed

- **Tools are now registered only when every scope their implementation
  actually needs is enabled**, not just the scope named by their obvious
  flag.
- **Every mutating tool now always requires an explicit `confirm=true`
  call** — the global auto-confirm bypass
  (`OPENPROJECT_AUTO_CONFIRM_WRITE`/`_DELETE`) is gone with no replacement.
- **Breaking + security fix: project-scope variables renamed and flipped to
  fail-closed.** `OPENPROJECT_ALLOWED_PROJECTS`/`OPENPROJECT_ALLOWED_PROJECTS_READ`
  is now `OPENPROJECT_READ_PROJECTS`, and `OPENPROJECT_ALLOWED_PROJECTS_WRITE`
  is now `OPENPROJECT_WRITE_PROJECTS` — no backward-compatible alias. An
  empty/unset scope now denies all project-scoped access instead of
  allowing it. **If your config only sets the old variable names, upgrading
  will deny all project-scoped access** — update to the new names first.
- **Breaking: personal, administrative, and extended read tools now have
  dedicated opt-in scopes** (`OPENPROJECT_ENABLE_PERSONAL_READ`,
  `OPENPROJECT_ENABLE_ADMIN_READ`, `OPENPROJECT_ENABLE_EXTENDED_READ`), all
  defaulting to `false`. Personal preferences and notifications,
  instance-wide user/group listings, and rarely-used metadata/reference
  tools are therefore no longer exposed by default. Administrative writes
  now additionally require `OPENPROJECT_ENABLE_ADMIN_READ=true`.
- **Breaking: the 5 project-scoped write flags now default `true`
  instead of `false`**, since the real gate was always
  `OPENPROJECT_WRITE_PROJECTS` (fail-closed on its own). Set one to `false`
  to carve out an exception. `OPENPROJECT_ENABLE_ADMIN_WRITE`/
  `OPENPROJECT_ENABLE_PERSONAL_WRITE` continue to default `false`.
- **Breaking: the local-attachment root no longer falls back to the current
  working directory when unset.** A configured `OPENPROJECT_ATTACHMENT_ROOT`
  must be absolute.
- **`configure` was reworked**: a live connection test and full preview now
  run behind one final confirm, the wizard writes only values that deviate
  from the default, and a new `--non-interactive` flag supports scripted
  installs.
- **Trimmed list/write responses to reduce context.**
- **Hidden fields are now omitted entirely instead of being nulled out.**
- **Long work-package text is read in full on single-item reads**, while
  list responses stay length-bounded.
- **Simplified the setup flow**: `--quick` (the default) and `--advanced`
  modes replace one runtime prompt; install docs now lead with `pipx`.
- **Improved tool descriptions and validation error messages.**

### Fixed

- **`OPENPROJECT_LOG_LEVEL` is no longer ignored**, and `DEBUG` is now
  accepted.
- **Fixed type-unsafe id validators** for bulk work-package tools.
- **Fixed `list_projects` pagination**: a multi-page walk could stop early
  or misalign results.
- **Fixed sparse result pages** in `list_versions`, `list_sprints`, and
  `list_project_sprints` under a restrictive project allowlist.
- **Fixed missing metadata fields** on work-package summaries requested via
  `select`.
- **Fixed `list_users`/`list_groups` pagination under `search`.**
- **Fixed a project-by-name type lookup** that skipped the project
  allowlist check.
- **`create_user`/`update_user` now round-trip through OpenProject's real
  form-validation endpoint** before returning a preview.
- **`doctor` now warns on the removed `OPENPROJECT_AUTO_CONFIRM_WRITE`/
  `_DELETE` env vars.**
- **`list_work_packages`/`search_work_packages` now expose
  `parent_display_id`.**
- **`add_work_package_comment` no longer leaves `user` unset**, and no
  longer leaks an unrelated prior activity's field-change details when
  OpenProject merges the comment into an existing journal entry.
- **8 update tools can now actually clear a text field via an empty
  string.**
- **Fixed an ambiguous-type-name resolution bug.**
- **Fixed a crash on non-string scalar values in bulk item fields.**

### Security

- **User-provided content is now delimited and flagged as untrusted.**
- **Fixed a project-isolation leak** where a sprint list tool could return
  results belonging to a different, disallowed project.
- **Fixed a fail-open regression** in a deprecated project-scope alias.
- **Fixed a cross-project allowlist bypass** in internal reference
  resolvers (work package parent, relation target, version, Backlogs
  sprint, grids).
- **Fixed a field-hiding gap**: watcher entries now respect
  `OPENPROJECT_HIDE_WATCHER_FIELDS`.
- **Fixed a related field-hiding gap on activity/comment reads.**
- **Fixed a match-existence leak in list totals**: `total` could reveal
  that matches existed in disallowed projects.

### Internal

- Tool registration is now table-driven instead of hand-written
  conditionals.
- Seven write finalizers now share one generic preview/commit helper.
- The API-drift checker now fails with a nonzero exit code on findings.

### Docs

- Documented the context-reduction features and new metadata fields.
- `OPENPROJECT_HIDE_<ENTITY>_FIELDS`'s entity list moved into its own
  `docs/field-hiding.md` reference page.
- Corrected `SECURITY.md`'s read-default claims and README's
  context-efficiency numbers.
- **Restructured the client setup docs into a hub** (`docs/clients.md`)
  with one guide per client, each showing that client's own recommended
  credential-handling pattern.

### Scope

- This release's CE completeness audit confirmed coverage across projects,
  work packages, versions, boards, memberships, users/groups, and the other
  core resources listed in `docs/architecture.md`. Nextcloud file links
  attached to work packages are supported today.
- Meetings and recurring meetings, Backlogs buckets, cost entries and cost
  types, forum posts, storage and project-storage administration,
  GitHub/GitLab linkage, per-user schedule overrides, and wiki page links
  are tracked for upcoming releases.

---

## 0.2.3 – 2026-07-07

### Fixed

- **`create_work_package_attachment` no longer fails with a 500 on every
  upload.**
- **`serverInfo.version` in the MCP `initialize` handshake now reports the
  package version** instead of the SDK's own version.

### Added

- **CE server instructions in the `initialize` response**, telling a
  connecting agent up front that types/statuses/workflows/modules are not
  creatable through the API and that `list_capabilities` is not the source
  of truth for what the tools allow.
- **`create_work_package` and `update_work_package` gain a `parent`
  parameter** to nest or re-parent a work package; `update_work_package`
  also accepts `'none'` to clear it.

### Docs

- Added `SECURITY.md`, documenting the supported-versions and
  vulnerability-reporting policy.

---

## 0.2.2 – 2026-07-06

### Security

- **`delete_file_link` now enforces the project write allowlist**, failing
  closed when the container cannot be resolved.
- **`toggle_activity_emoji_reaction` now enforces the project write
  allowlist.**

### Fixed

- **`get_group()` no longer crashes on real API responses** with visible
  members.
- **`create_time_entry` builds a valid entity link for semantic
  work-package references.**
- **Validation errors for `responsible` now name the correct field.**
- `openproject-ce-mcp configure` now exits cleanly on Ctrl+C.

### Changed

- **A remote plain-`http://` base URL now emits a startup warning** that
  the API token is sent unencrypted.
- Documented that self-scoped writes execute directly without a preview
  step; project-attached reactions still enforce write scope.
- CI now enforces formatting with `ruff format --check`.

---

## 0.2.1 – 2026-07-01

### Changed

- **Configure flow simplified**: two independent gates ("configure
  globally?", "configure project-scoped?") replace a mixed client prompt,
  and only the targets you pick are written. Project scope is offered for
  every supported client, whether or not it is detected.
- The early **`--local`/`--global` flags were removed** before adoption;
  the two interactive gates replace them.
- Prefill when re-running is now field-wise.
- The "Writable projects" prompt clarifies that `*` means *all readable
  projects*.

### Added

- Per-client restart hints after configuring.
- `configure --uninstall` now also removes project-local entries in the
  current directory.

---

## 0.2.0 – 2026-07-01

Publish the first PyPI release: rename the package, add an installable
configure/setup CLI, and automate PyPI distribution via GitHub Actions.
Supersedes the never-released 0.1.1.

### Added

- **PyPI distribution**, installable with `pip`/`pipx`/`uv tool install`.
- **`openproject-ce-mcp configure` setup command**, registering the server
  with detected MCP clients.
- Top-level CLI: `openproject-ce-mcp --help`/`--version`.
- `check_api.py --constants` verifies hardcoded enum/constant values
  against the OpenProject source.

### Changed

- Renamed the package to **openproject-ce-mcp**. The MCP server key stays
  `openproject`, so existing client configs do not change.
- Documentation leads with the PyPI install path.

### Fixed

- The `curl … | sh` installer no longer crashes with `EOFError` on the
  first prompt.
- Re-running `configure --global` pre-fills from an existing client
  registration.
- `configure` warns before writing a token-bearing `.mcp.json` into an
  unrelated project directory.
- The Docker integration-test harness runs on the Bash 3.2 that ships with
  macOS.

---

## 0.1.0 – 2026-07-01

Add semantic work-package identifiers and automatic MCP-client setup, and
harden the API surface (attachment containment, allowlisting, field-hiding)
ahead of the first public release.

### Compatibility

- Reviewed for compatibility with OpenProject 17.5.1/17.5.0 — no breaking
  API change affects this server.
- Verified against OpenProject 16.6 (classic), 17.4 (displayId), and 17.5
  (semantic) via the local Docker matrix, plus a source-level API audit
  across 16.0–17.5.

### Added

- Single work package tools now accept a project-prefixed identifier (e.g.
  `PROJ-123`) in addition to the numeric id; the bulk tools remain
  numeric-only.
- Relation and parent writes resolve a project-prefixed reference to the
  numeric id.
- Interactive setup can detect installed MCP clients (Claude Code, Claude
  Desktop, Codex, Cursor, VS Code/Copilot) and register the server in a
  client's user-wide config.
- `uninstall.sh`/`uninstall.ps1` and a `configure_mcp.py --uninstall` mode
  remove the `openproject` entry from client configs and clean up the local
  environment.
- `OPENPROJECT_ATTACHMENT_ROOT` confines attachment uploads to a directory;
  files outside it, and credential/config files even inside it, are
  refused.

### Security

- Attachment uploads can no longer read arbitrary local files, closing a
  credential-exfiltration path.
- `list_relations` is gated by the read scope and filtered by the project
  read allowlist on both linked work packages; `update_relation`,
  `update_reminder`, and `delete_reminder` apply the project write
  allowlist; `copy_project` validates its destination; hidden work-package
  subjects no longer leak through relation tools.
- `OPENPROJECT_AUTO_CONFIRM_DELETE` now correctly governs the preview step
  for all destructive deletes.

### Docs

- Onboarding docs reworked: install-once/register-per-client model,
  per-client config matrix, per-OS paths, verification steps, and
  gitignore reminders.

---

## 0.0.1 (development baseline)

Initial development baseline. The pre-release history is kept below as dated
milestones.

### 2026-05-18

#### Compatibility

- Verified against OpenProject 17.4. No breaking API changes in 17.4.
- Work package responses now expose a `display_id` field, informational
  ahead of 17.5's project-based identifiers; the numeric `id` remains the
  canonical identifier for all tool parameters.

#### Fixes

- Authentication header changed from `Bearer <token>` to
  `Basic base64(apikey:<token>)`, aligning with the OpenProject API
  documentation.

#### Bug fixes

- `list_work_packages`, `list_my_open_work_packages`, `list_versions`, and
  `list_projects` now report `total` and `count` consistently when the
  read allowlist filters items out of the API response.
- `list_work_packages` without an explicit `project` argument now
  correctly filters results to allowed projects when
  `OPENPROJECT_ALLOWED_PROJECTS_READ` is restricted.
- Allowlist matching now resolves project names and hyphenated display
  names to their canonical identifiers at startup.

#### Configuration

- `OPENPROJECT_ALLOWED_PROJECTS_READ` now accepts glob patterns in
  addition to exact identifiers and names.

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
