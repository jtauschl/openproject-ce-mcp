# Changelog

All notable changes to this project will be documented in this file. Versions
follow [semantic versioning](https://semver.org); 0.2.0 is the first release
published to PyPI, 0.1.0 is the first tagged release, and 0.0.1 is the
development baseline.

---

## [0.3.7] - Unreleased

### Security

- **Bumped `cryptography` to 50.0.0** (from 48.0.1), fixing GHSA-79v4-65xg-pq6g
  (high severity): a Bleichenbacher-style padding oracle in PKCS#7
  `EnvelopedData` decryption via distinguishable errors/timing. Pulled in
  transitively through `pyjwt`; not directly exercised by this project's own
  code, but the vulnerable range (`>=44.0.0,<50.0.0`) covered the previously
  locked version.

### Fixed

- **A rejected write's error message now includes the actual per-field
  reason instead of a generic summary.** OpenProject wraps multiple
  simultaneous validation failures in a `MultipleErrors` HAL response whose
  top-level message alone ("Multiple field constraints have been
  violated.") gave no way to tell which fields, or whether an Enterprise-
  only feature was involved — the real detail lives in `_embedded.errors[]`
  and is now surfaced alongside it.
- **A permission-denied response could be misreported as an authentication
  failure** if OpenProject's rejection bundled an unrelated detail message
  mentioning "token" or "authenticate" (e.g. an Enterprise-gate rejection
  alongside a genuine permission denial) — a side effect of the surfaced-
  detail fix directly above. The actual error type is now classified
  correctly again.
- **`list_my_open_work_packages` could silently return zero or incomplete
  results even when matching, allowed work packages genuinely existed.**
  This query has no server-side project filter at all, so under a
  restricted `OPENPROJECT_READ_PROJECTS` scope a single bounded fetch could
  land entirely on server pages whose matches belonged to disallowed
  projects, missing every allowed match beyond that window — reproduced
  live against a real OpenProject instance: 33 total server matches, only
  1 in an allowed project, that one match landing past a single page's
  worth of results. Now scans as many server pages as needed (skipping
  already-seen allowed matches, stopping once enough are found or the
  server is exhausted) instead of inspecting only one bounded page —
  reusing the existing `_scan_and_paginate` helper the same way
  `list_relations`/`list_views`/etc. already do.
- **`create_subtask`'s docstring now states that `parent_work_package_id`
  is the same value `list_work_packages`/`get_work_package` return as each
  row's `id` field (and as `parent_id`/`parent_display_id` on a child work
  package)** — same class of clarification as `get_work_package`'s
  existing docstring note.
- **`list_work_packages`/`search_work_packages`'s docstrings now explain
  that `total` can read 0 while `next_offset` is still non-null** under a
  restrictive `OPENPROJECT_READ_PROJECTS` scope (a full raw server page
  with every match filtered out by the allowlist) — not an inconsistency,
  keep paging.
- **User-typed fields can now be set on writes.** `responsible`, and every
  user/version reference custom field (e.g. a required "Business Owner" or
  "Tech Owner" on an Epic), previously failed with
  `OpenProject value 'X' is not allowed for field 'Y'` for *every* input —
  display name, numeric id, or href alike — making those work packages
  impossible to create through the server whenever such a field is required.
  Option resolution only ever read `schema[field]._embedded.allowedValues`,
  but fields whose candidate set is unbounded (any `User` field) never embed
  that list; OpenProject links a pre-filtered collection under
  `schema[field]._links.allowedValues.href` instead. That link is now
  dereferenced when no embedded list is present. Embedded option sets
  (status, priority, type) keep resolving locally with no extra request.
  Because a linked collection can legitimately hold two principals sharing a
  display name, an ambiguous name is now rejected rather than silently
  resolved to whichever matched first. (Thanks to @mehow-vng for the fix.)

## 0.3.6 – 2026-08-10

### Changed

- **Breaking: removed client-constructed `url` fields (and a few
  sub-collection hrefs like `activities_url`/`relations_url`) from MCP
  output models across most domains, including work packages, projects,
  and users.** These were built from `base_url` + id, with no matching link
  from the server, and some never resolved to a real page. `download_url`,
  `avatar_url`, and `identity_url` are unaffected, as are the handful of
  `url` fields that resolve a link OpenProject actually sends.

### Fixed

- **Every tool now rejects an unknown or misnamed argument with a clear
  error instead of silently dropping it and running with defaults.**
  FastMCP's auto-generated per-tool argument model ignores extra keys by
  default; a caller passing e.g. `filters=[...]` to `list_work_packages`
  (whose real filter parameters are `version`/`status`/`open_only`/etc.) or
  `page=` to `list_versions` (whose real parameter is `offset`) previously
  got back an unfiltered/first-page result with no error at all. A startup
  self-test now also verifies this enforcement is actually wired into live
  request dispatch, so a future `mcp` SDK upgrade that changes how tool
  calls are routed fails loudly instead of silently going dark.
- **`search_work_packages`'s docstring now states what its free-text
  `query` actually matches** — only the work package subject and numeric
  ID (OpenProject's native `subject_or_id` filter), never version,
  category, description, or other linked fields — and that omitting
  `project` searches globally across every readable project. Use
  `list_work_packages(version=..., project=...)` for version-based
  filtering instead.
- **`configure`'s generic copy-source for MCP clients without native
  support no longer writes to `.mcp.json`** — it now writes to a dedicated
  `openproject-mcp.example.json` with a placeholder token, so a real API
  token can no longer end up in a file meant only as a copy-source
  reference.
- **`configure`/`--uninstall` no longer crash with an unhandled traceback
  on a filesystem error while writing or removing a client config.** A
  failure on one target no longer aborts the remaining ones, and the
  process exits non-zero with a summary of every failed target.
- **`create_work_package`/`update_work_package`/`bulk_create_work_packages`/
  `bulk_update_work_packages` now document two previously-undocumented
  OpenProject behaviors**: a `due_date` on a non-working day can be
  silently moved forward by OpenProject (with no way to opt out via this
  server), and explicitly setting `percentage_done` together with a
  closing `status` is hard-rejected on instances using status-based
  progress calculation instead of being silently ignored.
- **`list_projects`/`list_sprints`/`list_project_sprints`/`list_grids`/
  `list_versions` (without `project`)/`list_documents`/`list_views`/
  `list_news`/`list_time_entries`/`list_users` and `list_groups` (both with
  `search`) now actually reduce server load and response size when paging**
  — `offset`/`limit` previously had no effect on how much data these tools
  fetched from OpenProject: each call loaded the entire matching collection
  into memory before slicing out the requested page, regardless of `limit`.
  A related bug in the fix's first draft (`list_relations`/
  `list_notifications`, already fixed) could also report `truncated: true`
  on the last page when the number of matches landed exactly on `limit` —
  the same fix applies here. `total` on these tools is now a lower bound
  (the count returned on this page) rather than an exact count of the full
  matching collection; page with `next_offset` until it is `null`.
- **`list_boards` (when filtering by `project`, `search`, or a restricted
  `OPENPROJECT_READ_PROJECTS`) could silently hide a board beyond the
  server's default result cap.** The client-side-filtered path now scans
  server pages the same way `list_documents`/`list_news` already do,
  instead of fetching a single bounded page.
- **`get_work_packages` (batch read) now bounds how many requests it sends
  to OpenProject at once (max 10 concurrent) instead of firing all of them
  simultaneously** — with the full 100-item batch limit, this could
  previously mean up to 100 concurrent HTTP requests from a single call.
- **Breaking: `list_work_package_attachments`, `list_reminders`, and
  `list_work_package_file_links` now accept `offset`/`limit` and return a
  paginated result (`total`/`next_offset`/`truncated`) instead of an
  unbounded, uncapped collection.** All three used to fetch the entire
  matching collection on every call with no way to request a smaller page —
  `total` on these tools is now a lower bound (the count returned on this
  page), the same convention every other paginated list tool already uses;
  page with `next_offset` until it is `null`.
- **`list_relations`, `get_work_package_relations`, `list_notifications`,
  `list_reminders`, and `get_work_package`'s children/ancestors filtering now
  resolve their per-item project-allowlist checks concurrently** (bounded,
  max 10 at once) instead of one at a time — faster under a restricted
  `OPENPROJECT_READ_PROJECTS` on a page or hierarchy with many entries.

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
  `list_capabilities`'s `capability_id`, and others) is now rejected before
  the request is made if it contains `.`/`..` path segments**, closing a gap
  that previously let such ids bypass the allowlist check meant to guard
  them.
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
