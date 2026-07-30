# Changelog

All notable changes to this project will be documented in this file. Versions
follow [semantic versioning](https://semver.org); 0.2.0 is the first release
published to PyPI, 0.1.0 is the first tagged release, and 0.0.1 is the
development baseline.

---

## [Unreleased 0.4.0]

These are fixes and features genuinely exclusive to the `release/0.4.0`
architecture-migration branch — either only possible because of the layered
`app/` migration itself, or not yet ported to/from `release/0.3.5`. See
[Unreleased 0.3.5](#unreleased-035) below for changes shared with (or
originating on) that branch; once 0.4.0 actually releases, its final
changelog entry will be assembled from the latest released 0.3.x entry plus
only this chapter.

### Added

- **`list_documents`, `list_views`, `list_sprints`, and `list_project_sprints`
  gain a `search` parameter**, matching the same name-substring pattern as
  `list_versions`/`list_boards`/`list_news`.
- **`bulk_update_work_packages` now supports `sprint`** (name/id, or `'none'`
  to clear), matching the field support `update_work_package` already had for
  single items.
- **`bulk_create_work_packages`/`bulk_update_work_packages` item fields now
  accept `parent`** as well as `parent_work_package_id` for the identical
  "attach to parent" concept, matching `create_work_package`/
  `update_work_package`'s naming.
- **`bulk_create_work_packages`/`bulk_update_work_packages` gain a `select`
  parameter** to shrink an unconfirmed preview's echoed payload, matching the
  `select` support already available on list/read tools.
- **`get_project` now returns the project's ancestor chain (`ancestors`)**,
  same shape as the existing `WorkPackageDetail.ancestors`. `list_projects`
  rows stay on the leaner existing shape, unchanged.

### Changed

- **Breaking: `search_work_packages`'s `query` parameter is renamed to
  `search`** (both the MCP tool parameter and the underlying Python client
  method's keyword argument), matching the naming used by `list_projects`,
  `list_versions`, `list_boards`, and other search-capable tools.
- **Breaking: `list_roles` now returns a paginated result** (`offset`/`limit`,
  same shape as `list_actions`) instead of the complete role collection in
  one call.
- **Bulk work-package writes reuse resolved project/type/version/sprint
  lookups across items targeting the same project**, reducing redundant API
  calls for large batches.
- **Server startup no longer enriches the initial instructions with the
  instance's live feature flags.** This data remains available via the
  `get_instance_configuration` tool; the change removes a network call from
  server startup.
- CI now runs **Semgrep** as a second SAST pass alongside the existing
  bandit scan, and a complete shell-script gate (shellcheck, `shfmt`,
  `bash -n`) across `dev`, `get.sh`, `uninstall.sh`,
  `docker/test/up.sh`/`down.sh`, and `tools/api-check/fetch-sources.sh`. No
  end-user-visible behavior change.

### Fixed

- **`get_job_status` now correctly honors `OPENPROJECT_READ_PROJECTS` for a
  job status scoped only via its `sourceProject` link** (e.g. the response
  returned by copying a project), instead of only checking the `project`
  link. A job status scoped exclusively via `sourceProject` previously
  bypassed the read allowlist entirely.
- **`create_user`/`update_user`/`lock_user`/`unlock_user` now honor
  `OPENPROJECT_HIDE_USER_FIELDS` on writes**, not just reads. Every hidden
  field previously could still be written even though it was masked on
  read, unlike every other write-capable domain (news, boards, documents,
  memberships, projects, versions), all of which already reject a write to
  a hidden field.
- **`create_group`/`update_group` now honor `OPENPROJECT_HIDE_GROUP_FIELDS`
  on writes**, not just reads. Same gap as the `OPENPROJECT_HIDE_USER_FIELDS`
  fix above: a hidden `name` or group-membership write was previously never
  rejected even though it was masked on read.
- **Breaking: `delete_grid(confirm=true)` now returns the deleted grid's
  summary in `result`**, instead of `null`. Every sibling delete tool
  (`delete_version`, `delete_membership`, `delete_project`) has always
  returned the deleted entity on confirmed delete; `delete_grid` alone
  returned `null` there since its introduction, with no documented reason
  for the inconsistency.
- **`get_news`/`list_news` description truncation now honors
  `OPENPROJECT_HIDE_NEWS_FIELDS`**, instead of incorrectly checking
  `OPENPROJECT_HIDE_PROJECT_FIELDS`.
- **`get_document`/`list_documents` description truncation now honors
  `OPENPROJECT_HIDE_DOCUMENT_FIELDS`**, instead of incorrectly checking
  `OPENPROJECT_HIDE_PROJECT_FIELDS`.
- **`get_time_entry`/`list_time_entries` comment truncation now honors
  `OPENPROJECT_HIDE_TIME_ENTRY_FIELDS`**, instead of incorrectly checking
  `OPENPROJECT_HIDE_ACTIVITY_FIELDS`.
- **`bulk_create_work_packages`/`bulk_update_work_packages` now report
  `assignee`/`responsible` validation errors indexed per item** (e.g.
  `items[0].assignee`), like every sibling field, instead of the unprefixed
  field name.
- **`get_project` now additionally handles a project that has a parent**
  (project ancestor links never carry a `displayId`, that field is a
  work-package-only concept) — building on the `get_work_package`
  ancestor/child `displayId` fix already released in 0.3.4.
- **`configure`'s generic copy-source for MCP clients without native support
  (Zed, Continue, ...) no longer writes to `.mcp.json`** — that path is
  Claude Code's own active project config, so a non-Claude project-scoped
  selection could leave a file there that Claude Code would later load as if
  it were a real registration. It now writes to a dedicated
  `openproject-mcp.example.json`, and its `OPENPROJECT_API_TOKEN` is always a
  placeholder rather than the real value, since the file is a manual
  copy/adapt reference, not something any client loads automatically.
- **`configure`/`--uninstall` no longer crash with an unhandled traceback on
  a filesystem error (permissions, disk full) while writing or removing one
  of several selected client configs.** Each target's config file is now
  written atomically (temp file + `os.replace()`, existing content backed up
  via copy rather than move first) so a failed write can never leave a
  half-written or missing file; a failure on one target no longer aborts the
  remaining ones, and the process now exits non-zero with a summary of every
  target that failed instead of silently reporting success.
- **`list_work_packages` without an explicit `project` now raises a clear
  permission error instead of silently returning zero results** when it
  cannot prove the query is scoped to only the allowed projects — previously
  indistinguishable from "this project genuinely has no work packages yet."
- **`list_priorities`/`get_priority` now honor `OPENPROJECT_HIDE_PRIORITY_FIELDS`**,
  a new environment variable. Priority was previously the only reference-data
  entity with no hidden-field support at all, unlike its close siblings
  statuses and types.
- **New `OPENPROJECT_HIDE_NOTIFICATION_FIELDS` and
  `OPENPROJECT_HIDE_EMOJI_REACTION_FIELDS` environment variables**, closing
  the same gap as the priority fix above for these two entities.
- **`OPENPROJECT_HIDE_FILE_LINK_FIELDS` now actually hides fields.** The
  variable was already documented and accepted, but had no effect on any
  response — a configuration gap, not a code path that ever ran.
- **Breaking: `list_grids` now returns a paginated result** (`offset`/`limit`/
  `total`/`next_offset`/`truncated`, same shape as `list_boards`/`list_sprints`)
  instead of every matching grid in one unbounded call, and gains `offset`/
  `limit` parameters to match.
- **`list_capabilities`'s `capability_id` lookup no longer 404s, and
  `CapabilitySummary.id` is no longer collapsed onto the same value for
  every capability in a given project/user context.** A capability's real
  id is multi-segment (e.g. `activities/read/w3-4`); the id was previously
  extracted from only the last path segment, and the lookup itself
  percent-encoded the id's slashes into a path OpenProject rejects.
- **Four more unguarded walk-every-server-page loops shared the same
  hang-forever vulnerability already fixed in 0.3.4 for `list_versions`'s
  project-scoped branch and `list_project_memberships`** (an endpoint that
  ignores `pageSize` and returns every element regardless — verified live
  against a project's `versions` endpoint — never triggers such a loop's
  repeated-page termination check). A systematic sweep of this migration's
  own code found four more affected loops, some of them a regression
  introduced by the migration itself: the layered Versions domain's own
  project-scoped resolver, `_resolve_sprint_id` (previously a single
  non-looping call, unlike its 0.3.x flat equivalent),
  `list_work_package_attachments` (previously an unbounded single fetch, not
  a loop), and the shared `paginate_all` helper (used by
  Documents/Views/Reminders/global Sprints). All now track seen ids/keys
  across iterations and stop on a repeated page.

### Docs

- Added the missing "Notes" section to the Cursor client guide
  (`OPENPROJECT_READ_PROJECTS`/`WRITE_PROJECTS` semantics), matching every
  other client guide.
- Documented the monorepo/umbrella-directory case where `configure` writes
  to the wrong place relative to where an AI client actually opens its
  workspace, with a troubleshooting entry for it.
- Clarified that the VS Code/Copilot guide is about VS Code's own MCP host,
  not a standalone "GitHub MCP server".

---

## [Unreleased 0.3.5]

Carried over verbatim from `release/0.3.5`'s own `CHANGELOG.md` — these
changes originate on (or are shared with) that branch, which is expected to
release first. Do not add new entries here directly; port them from
`release/0.3.5` instead, keeping this chapter in sync with that branch's own
Unreleased section.

### Added

- **`create_time_entry_until`/`update_time_entry_until`** let a caller specify
  `start_time`+`end_time` instead of `hours` directly; the exact duration
  between them is computed locally and sent as `hours` (`end_time` itself is
  never sent to OpenProject, which rejects it — see the `end_time` removal
  below). `create_time_entry_until` has no `ongoing` parameter (a time entry
  with a known end time is complete, not still running); `update_time_entry_until`
  always sets `ongoing=false`. `hours`'s ISO 8601 duration validation
  (`ISO8601_DURATION_RE`) now also accepts an optional fractional-second
  component (e.g. `PT7H30M15.5S`), matching what OpenProject's own
  server-side duration parser (the `iso8601` gem) actually accepts — this
  also widens what `hours` accepts on the existing `create_time_entry`/
  `update_time_entry`.

### Fixed

- **`lock_user` and `mark_notification_read`/`mark_all_notifications_read`
  no longer fail with a `406` error** ("Missing content-type header").
  These are bodyless POST requests; without an explicit (empty) JSON body,
  the underlying HTTP client sent no `Content-Type` header at all, which
  OpenProject's API rejects even though the request carries no real data.
- **`create_user` with a `password` no longer silently fails to create the
  user.** OpenProject's own create-form response never echoes `password`
  back (a security precaution), and the write was committing that form
  response verbatim — dropping the password even though the original
  request had passed validation, so the actual write failed server-side
  with "Password can't be blank." despite the preview reporting the request
  as valid.
- **`create_time_entry`/`update_time_entry` no longer accept an `end_time`
  parameter.** OpenProject's own API schema marks `end_time` as read-only
  (computed from `start_time` + `hours`), and its server-side representer has
  no setter for it at all — sending it crashed the server with an internal
  error even though preview validation reported the request as valid.
  `start_time` remains supported and unaffected; `end_time` is still returned
  when reading a time entry.

## 0.3.4 – 2026-07-29

### Fixed

- **`create_work_package_relation` no longer lets a relation be created to a
  work package outside `OPENPROJECT_WRITE_PROJECTS`.** Only the source work
  package's project was authorized against the write allowlist; the relation
  target was resolved read-only, letting a caller with write access to one
  project link it to a work package in a project they could only read.
- **`create_time_entry`/`update_time_entry` now honor
  `OPENPROJECT_HIDE_TIME_ENTRY_FIELDS` for `start_time`/`end_time` on
  writes**, not just reads — the only two time entry fields that previously
  bypassed the hidden-field write check every other field already had.
- **`create_time_entry`/`update_time_entry` previews now reflect OpenProject's
  own validation**, instead of always reporting `ready=true`. A locally-built
  payload could pass this server's own field checks yet still be rejected by
  OpenProject itself (e.g. an hours/date/activity combination its schema
  disallows), which the previous hardcoded preview could never surface.
- **`create_time_entry` with a named `activity` no longer fails with
  `permission_denied` for a user who only has OpenProject's "Log own time"
  permission** (not "Log time for other users"), even with the correct role
  and project module configured. The activity-lookup request only carried a
  project reference, never the target work package — which OpenProject's own
  authorization needs to recognize a "log my own time" caller as such. It now
  carries the work package reference whenever it's already known, matching
  what the real time entry write already sends.
- **`get_work_package` no longer crashes on classic/pre-17.5 OpenProject
  instances (or on ancestor/child links OpenProject didn't tag with a display
  ID) with a schema validation error.** Hierarchy links were rejected as
  invalid whenever OpenProject omitted a display ID for them, which it always
  does for pre-17.5 instances.
- **`list_capabilities`'s `context` filter rejected every request on
  OpenProject 16.x with "Filters Context malformed value"**, the same
  regression already fixed once and since reintroduced. Reverted again to the
  project-prefixed form, the only one that works across the full supported
  version range (16.0-17.6).
- **`get_query_sort_by` returned a 404 on every OpenProject version.** The
  request path used the raw sort-by id verbatim; OpenProject's actual route
  requires a hyphen-joined id-direction pair instead.
- **`get_work_package_relations`/`list_relations` no longer silently
  truncate results to OpenProject's server-side default page size.** Neither
  request specified a page size, so any relation beyond that default was
  permanently unreachable regardless of the requested offset/limit.
- **`list_project_memberships` no longer silently truncates results to
  OpenProject's server-side default page size**, the same gap as the
  relations fix above.
- **`list_groups`'s `member_count` no longer always reports 0.** OpenProject
  exposes a group's membership differently depending on the endpoint: a
  single-item lookup embeds a flat member list, while the group listing
  only ever carries a bare array of member links — only the single-item
  shape was recognized at first, and a follow-up fix added recognition of
  the listing's own shape too, so `member_count` is now correct from both
  endpoints.
- **A parent-project picklist (`get_project_admin_context`) no longer
  returns full project details (including description) for every candidate,
  and no longer includes a candidate outside `OPENPROJECT_READ_PROJECTS`.**
  Candidates are now a lightweight reference, filtered by the same read
  allowlist every other project-returning path already applies.
- **`list_views`/`list_documents`/`list_versions`/`list_sprints` (including
  project-scoped and search variants) no longer silently cap results at a
  fixed maximum, hiding any item beyond it.** All four now walk every server
  page instead of fetching a single bounded page.
- **`list_capabilities`'s `capability_id` lookup no longer 404s, and
  `CapabilitySummary.id` is no longer collapsed onto the same value for
  every capability in a given project/user context.** A capability's real
  id is multi-segment (e.g. `activities/read/w3-4`); the id was previously
  extracted from only the last path segment, and the lookup itself
  percent-encoded the id's slashes into a path OpenProject rejects.
- **`get_job_status`'s `job_status_id` is no longer always `null` on a real
  OpenProject instance.** Job status ids are UUID strings, never a plain
  integer, on every supported version; the field is now typed and returned
  as a string.
- **`get_job_status`/`copy_project` no longer silently skip their
  project/sourceProject/createdProject allowlist checks and identifier-cache
  write-through.** Those links live inside the job-specific `payload`
  object's own `_links`, one level below the top-level `_links` (which only
  ever carries `self`) the code previously read from — the checks were
  therefore never exercised against real data.
- **A project/version/sprint/etc. listing that walks every server page no
  longer hangs indefinitely against an endpoint that ignores `pageSize`.**
  A sub-collection endpoint that returns every element regardless of the
  requested page size (verified live: a project's `versions` endpoint) used
  to make the walk-every-page loop's termination condition never trigger,
  looping forever; a repeated-page check now stops it. Found in a systematic
  sweep for the same pattern: `list_versions`'s project-scoped branch (and
  its `_resolve_version_id` caller) and `list_project_memberships` had the
  identical unguarded loop shape, reached via a separate code path from the
  already-fixed `_fetch_all_pages`/`_fetch_bounded_and_paginate` helpers.
- **`update_reminder`/`delete_reminder` no longer fail on every call.** The
  authorization check that runs before either write fetched a reminder by
  requesting a single-item GET that does not exist on OpenProject's API;
  it now finds the reminder through the reminders listing endpoint
  instead, and correctly walks every page of it rather than only the
  first, so a reminder past the first page is no longer misreported as
  not found.
- **`update_my_preferences`'s `lang` parameter no longer does nothing.**
  Language is a property of a user account, not of that account's
  preferences, so the previous request silently succeeded without ever
  changing anything. The parameter has been removed together with a few
  other fields the real API never returns; use `update_user`'s `language`
  field to change a user's language instead.
- **Two security gaps found during pre-release review have been closed.**
  `list_project_memberships` could return memberships from every visible
  project instead of just the requested one, because its own project
  filter was silently discarded by the way the request's query parameters
  were combined. Separately, an id passed into a handful of API paths
  (`get_job_status`, `list_capabilities`'s `capability_id`) could contain
  `.`/`..` path segments that survived encoding and let the request reach
  an unintended endpoint, bypassing the allowlist check meant to guard it;
  such ids are now rejected before the request is made. The same
  path-traversal guard has since been extended to every other method that
  builds a URL from a caller-supplied id (`get_user`, `get_query_filter`,
  `get_query_column`, `get_query_operator`, `get_query_sort_by`,
  `get_query_filter_instance_schema`, work package lookups by id, and
  project lookups by id/identifier).
- **`create_grid`/`update_grid`/`delete_grid` no longer skip their
  write-allowlist check for a grid whose scope isn't a recognized project
  or personal-page URL.** Only a `/projects/...` scope was ever checked
  against `OPENPROJECT_WRITE_PROJECTS`; any other, unrecognized scope
  value silently bypassed the check entirely instead of being denied.
- **Several read-side gaps found during a wider pre-release review have
  been closed:** the "Extended Metadata" tools (help texts, working days,
  custom options) previously ignored their own read-enablement setting
  entirely; `update_my_preferences` previously ignored
  `OPENPROJECT_HIDE_USER_PREFERENCES_FIELDS`; `get_category` re-listed and
  filtered categories in memory instead of fetching the single category
  directly, and never checked its project against the read allowlist;
  and `list_work_package_attachments`, `list_time_entries`, and
  `list_grids` each fetched only a single bounded page, silently hiding
  any result beyond it. Project/document/version descriptions, time entry
  comments, and activity details were never marked as untrusted user
  content, unlike every other user-supplied text field; that marking is
  now applied consistently through a shared helper, which also newly
  covers reminder notes, relation descriptions, and attachment
  descriptions. Grid results never applied `OPENPROJECT_HIDE_GRID_FIELDS`
  at all, unlike every other resource type.
- **A number of smaller correctness fixes from the same review:** a
  `_links` value of `null` in an API response is now normalized before
  any field is read from it, instead of risking a crash; a user's
  `identity_url` now reads the correct property instead of duplicating
  their profile URL; bulk work package create/update validation errors
  now name `assignee`/`responsible` consistently with every other field;
  bulk work package updates now accept a `sprint` field, matching single
  updates; a file-link write result no longer reports a fake work
  package id of `0` when the real one can't be resolved; and a couple of
  redundant follow-up requests (in `unlock_user` and
  `get_work_package_relations`) have been removed.
- **`list_notifications` no longer silently misses notifications under a
  restrictive read scope.** With `OPENPROJECT_READ_PROJECTS` set to
  anything other than "all projects", results are filtered after
  fetching, so a page that happened to contain no allowed notifications
  was previously treated as proof no more existed — it now keeps scanning
  server pages until enough allowed notifications are found or the
  collection is genuinely exhausted, and reports pagination metadata
  (`truncated`/`next_offset`) accurately for both scoped and unscoped
  requests.
- **`list_reminders` and `list_work_package_file_links` no longer
  silently truncate results to the server's default page size**, the
  same gap already fixed for other listings.
- **`list_users`/`list_groups` (name search), `list_news`, and
  `list_versions` (project-scoped) no longer silently cap results at a
  fixed maximum, hiding any item beyond it** — the same gap already fixed
  for other listings, closed here for the remaining affected methods. The
  project-scoped version listing was also switched to reading
  OpenProject's actual (unpaginated) response shape instead of trusting
  page parameters the server was silently ignoring. A related internal
  cache (used to recognize a project by its identifier when checking
  `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS`) is now built
  from every visible project instead of only the first page, so an
  instance with more than 500 projects no longer misses some of them.
- **Resolving a role by name no longer requires an unnecessary lookup of
  every role when the caller already passed a numeric role id.**

---

## 0.3.3 – 2026-07-28

### Fixed

- **`update_board` no longer lets a board be moved into a project outside
  `OPENPROJECT_WRITE_PROJECTS`.** Only the board's current project was
  authorized against the write allowlist; a `project=` reparent target was
  resolved for the outgoing request but never checked for write access.
- **`get_news`/`list_news` description truncation now honors
  `OPENPROJECT_HIDE_NEWS_FIELDS`**, instead of incorrectly checking
  `OPENPROJECT_HIDE_PROJECT_FIELDS`.
- **`get_document`/`list_documents` description truncation and
  `get_time_entry`/`list_time_entries` comment truncation now honor
  `OPENPROJECT_HIDE_DOCUMENT_FIELDS`/`OPENPROJECT_HIDE_TIME_ENTRY_FIELDS`
  respectively**, instead of incorrectly checking
  `OPENPROJECT_HIDE_PROJECT_FIELDS`/`OPENPROJECT_HIDE_ACTIVITY_FIELDS`.
- **`get_work_package_relations` no longer leaks a linked work package's id
  and subject from outside `OPENPROJECT_READ_PROJECTS`.** Only the anchor
  work package's project was checked; the other side of each relation was
  not, the same gap `list_relations` had already closed for the identical
  concern.
- **`toggle_activity_emoji_reaction` previews (`confirm=false`) no longer
  require `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`.** The write-enablement
  check ran unconditionally, even during a preview; it now runs only on the
  confirmed mutation. The project write-allowlist check (an authorization
  gate on the specific target) is unaffected and still runs during preview.
- **A project created or renamed through this server was invisible to
  `get_work_package`/`update_work_package`/`create_work_package` (when
  linking a `parent`) and every other project-scoped tool under a
  restrictive `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS`,
  until the server process restarted**, even though `get_project` and
  `list_projects` already saw it correctly. The identifier lookup these
  tools rely on was only ever populated once, at startup; a confirmed
  `create_project`/`update_project` now keeps it up to date immediately.
- **`list_work_packages` without an explicit `project` now raises a clear
  permission error instead of silently returning zero results** when it
  cannot prove the query is scoped to only the allowed projects — previously
  indistinguishable from "this project genuinely has no work packages yet."
- **`list_capabilities` no longer leaks capability records (including project
  names and principals) from outside `OPENPROJECT_READ_PROJECTS`.** Only the
  caller-supplied `project` parameter was ever checked against the allowlist;
  each returned capability's own project link was not, so a `capability_id`
  lookup with no `project` given skipped the check entirely. `capability_id`
  now also resolves via the single-item lookup rather than an undocumented
  collection filter.
- **`list_capabilities`'s `context` filter rejected every request on
  OpenProject 16.x with "Filters Context malformed value".** An earlier fix
  switched the filter's project-scoping value from the project-prefixed
  form to the workspace-prefixed one, on the mistaken assumption the latter
  was the current/recommended syntax across all supported versions — the
  workspace prefix is only accepted from OpenProject 17.0 onward, and the
  project-prefixed form is the only one that works across the full
  supported version range (16.0-17.6). Reverted to the project-prefixed
  form.
- **`create_user`/`update_user`/`lock_user`/`unlock_user` now honor
  `OPENPROJECT_HIDE_USER_FIELDS` on writes**, not just reads. Every hidden
  field previously could still be written even though it was masked on
  read, unlike every other write-capable domain (news, boards, documents,
  memberships, projects, versions), all of which already reject a write to
  a hidden field.
- **`create_grid`/`update_grid` now honor `OPENPROJECT_HIDE_GRID_FIELDS`
  on writes**, not just reads. Same gap as the `OPENPROJECT_HIDE_USER_FIELDS`
  fix above — Grids additionally had no such setting at all until now, since
  `"grid"` was missing entirely from the hidden-fields configuration.
- **`get_job_status` no longer leaks a job status scoped only via a
  `sourceProject` link (e.g. a `copy_project` response referencing the
  copy's source project) outside `OPENPROJECT_READ_PROJECTS`.** The
  allowlist check only ever read the `project` link; the response's own
  `project`/`project_id` fields were already populated from `project` with
  a `sourceProject` fallback, so a payload scoped only via `sourceProject`
  bypassed the check entirely despite exposing that project's data.
- **`list_work_package_watchers`/`list_work_package_file_links` no longer
  leak watcher and file link data outside `OPENPROJECT_READ_PROJECTS`.**
  Neither method checked the allowlist at all, not even against the anchor
  work package's own project — unlike their write-path siblings
  (`add_work_package_watcher`/`remove_work_package_watcher`,
  `delete_file_link`), which already resolved the containing work package
  and checked it first.
- **`get_work_package` no longer leaks a linked work package's subject and
  identifier through `children`/`ancestors` outside
  `OPENPROJECT_READ_PROJECTS`.** OpenProject's parent/child hierarchy is not
  project-constrained, so a linked work package could belong to a different,
  unreadable project; only the anchor work package's own project was
  checked, the same gap `get_work_package_relations` already closed for the
  identical concern.
- **Attachment, reminder, and relation writes now honor their hidden-fields
  configuration**, not just reads. `create_work_package_attachment`'s
  `description`, `create_work_package_reminder`/`update_reminder`'s
  `note`/`remind_at`, and `update_relation`'s `description` could all still
  be written even when configured as hidden — the same class of gap already
  fixed for Users/Grids above. `update_relation` was additionally
  asymmetric with its own sibling `create_work_package_relation`, which
  already rejected a hidden `description`.
- **`create_group`/`update_group` now honor `OPENPROJECT_HIDE_GROUP_FIELDS`
  on writes**, not just reads. Same gap as the `OPENPROJECT_HIDE_USER_FIELDS`
  fix above.
- **`update_reminder`'s project-write allowlist check could be bypassed by a
  malformed, truthy non-string `href`** (e.g. `{"href": 42}`) on the
  reminder's linked work package — it fell through to a raw path lookup
  instead of failing closed with the intended permission error.
- **Priorities, notifications, and emoji reactions were never masked by
  their `OPENPROJECT_HIDE_*_FIELDS` setting**, the same class of gap already
  fixed for other domains above — file links had a call site for this but no
  matching config entry, making it a permanent no-op.
- **`list_grids` never paginated at all** (an unbounded fetch-all, unlike
  every other `list_*` method); it now clamps and paginates client-side,
  matching `list_boards`.
- **`update_project`'s `parent` reassignment now requires write access on
  the NEW parent project too, not just on the project being updated.**
  Previously the new parent was only read-checked, so a caller with write
  access to one project could attach it under a project they could only
  read — the same gap `update_board`'s reparent-target fix already closed
  for boards.
- **A project created via `copy_project` was invisible to every
  link-shaped allowlist check until the process restarted**, the same gap
  an earlier fix already closed for `create_project`/`update_project`.
  `copy_project` itself never observes the new project's numeric id, since
  it only starts an async copy job and returns immediately; `get_job_status`
  now resolves and remembers the copied project's real identifier once the
  job's `createdProject` link reports it. An earlier version of this fix
  triggered on a `type` field OpenProject's real `createdProject` payload
  never actually sends (only `href`/`title`), so it silently never fired —
  found via a Codex review and corrected to key off the link's presence
  instead.
- **`create_work_package`/`update_work_package`'s `parent_work_package_id`
  reassignment now requires write access on the NEW parent work package's
  project too, not just read access.** Previously the new parent was only
  read-checked, so a caller with write access to one project could attach
  a work package under a parent in a project they could only read — the
  same gap `update_project`'s/`update_board`'s reparent-target fixes
  already closed. Found via a Codex review of the `update_project` fix
  above.
- **`create_work_package_relation`/`update_relation`'s `type` field and
  `create_work_package_attachment`'s `file_name` field now honor
  `OPENPROJECT_HIDE_RELATION_FIELDS`/`OPENPROJECT_HIDE_ATTACHMENT_FIELDS`
  on writes.** Both are mandatory fields written unconditionally, unlike
  the optional `description` field the existing guards already covered —
  found via a Codex review of the attachment/reminder/relation
  hidden-fields fix above.
- **A `403` from OpenProject now includes OpenProject's own error message**,
  instead of always showing the same generic "denied access to this
  resource" text with no further detail — e.g. a project's required module
  not being enabled for a non-admin user was previously indistinguishable
  from any other permission denial.
- **`Publish to PyPI` and `Tests` GitHub Actions workflows now pin
  `actions/checkout` and `astral-sh/setup-uv` to a full-length commit SHA**,
  as required by this repository's action-pinning ruleset. The previous
  `@v7` tag references caused every workflow run to be rejected outright.

---

## 0.3.2 – 2026-07-20

### Fixed

- **Milestone work packages always showed `start_date`/`due_date` as `null`,
  even when a date was genuinely set.** OpenProject reports a milestone's
  date under a different field than it does for every other work-package
  type, which this server did not previously read.
- **Closing a work package with no `estimated_time` set was rejected on the
  first attempt.** `update_work_package`/`bulk_update_work_packages` always
  auto-filled `remaining_time` to `PT0H` on a transition to a closed status,
  but OpenProject requires the opposite value (`null`, not `PT0H`) when the
  work package has no estimate — the common case for simple tasks.

---

## 0.3.1 – 2026-07-18

### Fixed

- **`bulk_create_work_packages`/`bulk_update_work_packages` no longer silently
  drop unrecognized item fields.** Each tool now validates every item's keys
  and rejects any item containing an unsupported or misspelled field with an
  indexed error, instead of quietly ignoring it.
- **`bulk_create_work_packages` no longer drops `estimated_time`/
  `remaining_time`/`duration` on every item.** These three fields are now
  forwarded to the underlying work-package create, matching the single-item
  `create_work_package` tool's existing support for them.
- **A broad `OPENPROJECT_READ_PROJECTS` combined with a narrower
  `OPENPROJECT_WRITE_PROJECTS` could incorrectly deny a legitimate write.**
  Startup project-identifier resolution used to skip itself whenever read
  access was unrestricted, without accounting for a separately restricted
  write scope — so a write validated only against an embedded project
  reference (as most work-package writes are) could fail to recognize a
  project identifier that was, in fact, correctly allowed. Startup resolution
  now runs whenever either scope is restricted.

---

## 0.3.0 – 2026-07-17

### Added

- **Batch work-package read**: `get_work_packages(ids=[...])` fetches multiple
  work packages in parallel, with per-item error tracking and deduplication
  (capped at 100 ids per call), and accepts a `select` parameter to trim each
  fetched work package to just the requested fields.
- **Sorting and grouping** for work-package lists: `sort_by` and `group_by`
  parameters on `list_work_packages` and `search_work_packages`.
- **Work-package filters**: assignee/status/priority equality filters, plus
  created/updated/due date filters (exact-day and range), using the official
  OpenProject filter keys.
- **`list_versions` gains a `search` parameter**, matching the same
  name-substring pattern as `list_projects`.
- **Automatic retry with exponential backoff** for transient HTTP failures
  (429/502/503/504, connection/timeout errors), honoring `Retry-After` and
  configurable via `OPENPROJECT_MAX_RETRIES`/`OPENPROJECT_RETRY_BASE_DELAY`/
  `OPENPROJECT_RETRY_MAX_DELAY`. Only idempotent methods are retried.
- **Work-package time tracking, metadata, and hierarchy fields**: writable
  estimated/remaining time and duration (ISO 8601, e.g. `PT8H`, now
  supported on bulk updates too), activity details, author/category/
  timestamps, children/ancestors.
- **Work-package scheduling fields**: `scheduleManually`,
  `ignoreNonWorkingDays`, derived start/due date, percentage done, `readonly`.
- **Clearing nullable associations via `'none'`** now works consistently
  across assignee, responsible, category, project phase, version, and sprint,
  and `bulk_update_work_packages` gained the same sentinel for version/
  project phase/assignee/responsible/category/parent that `update_work_package`
  already had. `estimated_time`/`remaining_time`/`duration` also accept
  `'none'` now, and their format check was widened from `PT`-only to the full
  ISO 8601 duration grammar (`P1D`, `P2W`, `P1Y2M3D`, …), live-verified
  against real OpenProject.
- **Backlogs sprint support**: read tools plus a writable/clearable sprint
  link on `update_work_package`, for instances with the Backlogs module.
- **`percentage_done` is now a writable parameter** on `update_work_package`/
  `bulk_update_work_packages` (0-100), auto-filling to 100/`remaining_time=PT0H`
  on a transition to a closed status when left unset and OpenProject reports
  the fields as writable.
- **`project` now falls back to a display-name match** when the numeric id/
  identifier lookup fails, using the same non-ambiguous matching algorithm
  `list_projects` already used — wired through all 18 call sites that accept
  a project reference.
- **`doctor` command**: diagnoses setup end to end — binary resolution,
  client config discovery, environment merging, live connectivity, tool
  registration.
- Several new read-only fields, and field-hiding coverage extended to
  status, type, and sprint (previously unsupported).

### Changed

- **Tools are now registered only when every scope their implementation
  actually needs is enabled**, not just the scope named by their obvious
  flag — some read and write tools that previously stayed visible after
  their supporting scope was disabled now correctly disappear with it. This
  particular change needs no configuration update on its own; see the
  breaking changes below for this release's actual environment-variable
  renames.
- **Every mutating tool now always requires an explicit `confirm=true`
  call.** The global auto-confirm bypass has been removed —
  `OPENPROJECT_AUTO_CONFIRM_WRITE` and `OPENPROJECT_AUTO_CONFIRM_DELETE` are
  gone with no replacement — closing a gap where three tools (marking
  notifications read, toggling an emoji reaction) previously skipped the
  preview step unconditionally.
- **Breaking + security fix: project-scope variables renamed and flipped to
  fail-closed.** `OPENPROJECT_ALLOWED_PROJECTS`/`OPENPROJECT_ALLOWED_PROJECTS_READ`
  is now `OPENPROJECT_READ_PROJECTS`, and `OPENPROJECT_ALLOWED_PROJECTS_WRITE`
  is now `OPENPROJECT_WRITE_PROJECTS` — no backward-compatible alias. An
  empty/unset scope now denies all project-scoped access instead of allowing
  it — `*` must be set explicitly to keep the old "allow everything"
  behavior. **If your config only sets the old variable names, upgrading
  will deny all project-scoped access**, with a startup/`doctor` warning
  naming the exact replacement variable — update to the new names first.
  This also fixes two data-leak bugs where an empty scope skipped
  filtering entirely instead of denying, and adds project-scope filtering to
  two list tools that previously had none.
- **Breaking: personal, administrative, and extended read tools now have
  dedicated opt-in scopes.** The existing project, work-package,
  membership, version, and board read flags remain available with their
  previous defaults.

  The new `OPENPROJECT_ENABLE_PERSONAL_READ`,
  `OPENPROJECT_ENABLE_ADMIN_READ`, and `OPENPROJECT_ENABLE_EXTENDED_READ`
  settings default to `false`. Personal preferences and notifications,
  instance-wide user/group listings, and rarely-used metadata/reference
  tools are therefore no longer exposed by default.

  Administrative writes now require both `OPENPROJECT_ENABLE_ADMIN_READ=true`
  and `OPENPROJECT_ENABLE_ADMIN_WRITE=true`. Existing `0.2.3` configurations
  with administrative writes enabled must add the new admin-read setting.
  Personal-data mutations use the new `OPENPROJECT_ENABLE_PERSONAL_WRITE`
  setting together with `OPENPROJECT_ENABLE_PERSONAL_READ`.
- **Breaking: the 5 project-scoped write flags
  (`OPENPROJECT_ENABLE_PROJECT_WRITE`, `_WORK_PACKAGE_WRITE`,
  `_MEMBERSHIP_WRITE`, `_VERSION_WRITE`, `_BOARD_WRITE`) now default `true`
  instead of `false`.** The real gate for them was always
  `OPENPROJECT_WRITE_PROJECTS` — a category flag alone can't write anything
  without a project also listed there, and that allowlist stays fail-closed
  (empty/unset denies all project-scoped writes) — so this makes a granted
  project scope immediately usable across all 5 categories without also
  toggling 5 separate flags; set one to `false` to carve out an exception.
  `OPENPROJECT_ENABLE_ADMIN_WRITE` continues to default to `false`. The new
  `OPENPROJECT_ENABLE_PERSONAL_WRITE` setting also defaults to `false`.
  Neither has a project-scope safety net. Project-scoped write tools are now
  also only *registered* when both `OPENPROJECT_READ_PROJECTS` and
  `OPENPROJECT_WRITE_PROJECTS` are non-empty, so an unconfigured install's
  tool catalog stays small and read-only despite the new write defaults.
- **Breaking: the local-attachment root no longer falls back to the current
  working directory when unset.** An empty/unset `OPENPROJECT_ATTACHMENT_ROOT`
  now disables local uploads entirely instead of defaulting to an
  unpredictable path; a configured root must be absolute.
- **`configure` was reworked**: a live connection test and full preview now
  run behind one final confirm (fixing an ordering bug where config
  removals could run before credentials were collected), the wizard writes
  only values that deviate from the default, legacy-variable warnings now
  also show at server startup, and a new `--non-interactive` flag supports
  scripted installs.
- **Trimmed list/write responses to reduce context.** Confirmed writes no
  longer repeat the raw request payload, list results drop derivable
  fields, and a new `select` parameter returns only the requested row
  fields on the main list/search tools.
- **Hidden fields are now omitted entirely instead of being nulled out.**
- **Long work-package text is read in full on single-item reads**, while
  list responses stay length-bounded.
- **Simplified the setup flow**: the `configure` wizard now has explicit
  `--quick` (the default — client target(s), base URL, token, readable
  projects, and a single project-scoped write-scope choice) and `--advanced`
  (the full questionnaire, including personal-data and admin writes) modes
  instead of one runtime "advanced options?" prompt; install docs now lead
  with `pipx`.
- **Improved tool descriptions and validation error messages** to reduce
  agent retry loops.

### Fixed

- **`OPENPROJECT_LOG_LEVEL` is no longer ignored**, and `DEBUG` is now
  accepted as a valid level (was wrongly rejected).
- **Fixed type-unsafe id validators** that raised an unhelpful error for a
  JSON string, `None`, or boolean id; bulk work-package tools now accept
  the same semantic id references as single-item tools.
- **Fixed `list_projects` pagination**: a multi-page walk could stop early
  or skip/misalign results on a later page.
- **Fixed sparse result pages** in `list_versions`, `list_sprints`, and
  `list_project_sprints` under a restrictive project allowlist.
- **Fixed missing metadata fields** on work-package summaries that were
  documented but raised validation errors when requested via `select`.
- **Fixed `list_users`/`list_groups` pagination under `search`**: `total`,
  `next_offset`, and `truncated` were computed from the unfiltered server
  page instead of the actually-matching results, so a search could report
  the wrong count or stop paging too early.
- **Fixed a project-by-name type lookup** that skipped the project allowlist
  check its sibling lookups already applied, letting a type resolve against
  a project outside `OPENPROJECT_READ_PROJECTS`.
- **`create_user`/`update_user` now round-trip through OpenProject's real
  form-validation endpoint** before returning a preview, like every other
  create/update tool — a `confirm=false` call previously always reported the
  request as valid even when it would actually be rejected (e.g. a duplicate
  login or email).
- **`doctor` now warns on the removed `OPENPROJECT_AUTO_CONFIRM_WRITE`/
  `_DELETE` env vars**, matching the warning coverage every renamed legacy
  variable already had — a stale value left over from a pre-0.2.2 config no
  longer sits silently unflagged.
- **`list_work_packages`/`search_work_packages` now expose `parent_display_id`**
  on results, mirroring `get_work_package`'s single-item detail (the data was
  already fetched, only unread).
- **`add_work_package_comment` no longer leaves `user` unset** when
  OpenProject's write response omits it (a best-effort follow-up lookup fills
  it in), and no longer leaks an unrelated prior activity's field-change
  details/timestamp when OpenProject merges the new comment into an existing,
  more recent journal entry instead of creating a fresh one.
- **8 update tools (`update_project`, `update_work_package` and
  `bulk_update_work_packages`, `update_document`, `update_news`,
  `update_version`, `update_time_entry`, `update_reminder`,
  `update_relation`) can now actually clear a text field via an empty
  string** — it previously collapsed silently to "not provided" and left the
  field unchanged.
- **Fixed an ambiguous-type-name resolution bug**: `_resolve_type_id` now
  rejects two types sharing a name (case-insensitively) in the same project
  instead of silently picking whichever the API returned first, matching the
  existing ambiguity guard on principal/sprint resolution.
- **Fixed a crash on non-string scalar values in bulk item fields**
  (e.g. `bulk_update_work_packages(items=[{"assignee": 42}])` raised an
  unhandled `AttributeError` instead of a clean validation error).

### Security

- **User-provided content is now delimited and flagged as untrusted.**
  Work-package descriptions, comments, news, wiki pages, and custom text
  fields are wrapped in markers, and server instructions warn connecting
  agents to treat this content as data, not instructions.
- **Fixed a project-isolation leak** where a sprint list tool could return
  results belonging to a different, disallowed project.
- **Fixed a fail-open regression** in a deprecated project-scope alias that
  had been silently dropped, removing a deployment's read restriction
  instead of keeping it.
- **Fixed a cross-project allowlist bypass** in internal reference
  resolvers: linking a work package's parent, a relation target, a version,
  or a Backlogs sprint could reach an entity in a project outside
  `OPENPROJECT_READ_PROJECTS` without being checked first. Reading grids had
  the same gap and is fixed the same way.
- **Fixed a field-hiding gap**: watcher entries never respected
  `OPENPROJECT_HIDE_WATCHER_FIELDS`, unlike every other user-identifying
  field.
- **Fixed a related field-hiding gap on activity/comment reads**: replacing a
  field on a normalized activity via `dataclasses.replace()` silently dropped
  the internal stamp that marks `OPENPROJECT_HIDE_ACTIVITY_FIELDS` entries,
  un-hiding a field (e.g. a hidden user) that had already been redacted.
- **Fixed a match-existence leak in list totals**: `list_work_packages`/
  `search_work_packages`/`list_my_open_work_packages`'s `total` field could
  reflect the server's real match count even when the query wasn't provably
  restricted to `OPENPROJECT_READ_PROJECTS`, revealing that matches existed
  in disallowed projects. It's now only trusted when the query is verifiably
  scoped, and `next_offset`/`truncated` stay consistent with what `total`
  actually discloses.

### Internal

- Tool registration is now table-driven from a small set of classification
  constants instead of ~190 lines of hand-written conditionals.
- The seven write finalizers (work package, version, board, grid, project,
  membership, user) now share one generic preview/commit helper instead of
  near-duplicate implementations.
- Wizard tests now match prompts by their text instead of positional
  order, so reordering a prompt can't silently misalign answers.
- The API-drift checker (`tools/api-check/check_api.py --all`) now fails
  with a nonzero exit code when a client-used resource or filter is missing
  from the latest pinned OpenProject version, instead of always exiting 0
  regardless of findings; its source inventory (`check_coverage.py`) now
  also walks every module's API subtree (e.g. Meetings), not just the
  top-level one.

### Docs

- Documented the context-reduction features, the `'none'` field-clearing
  pattern, and all new metadata fields in server instructions, README, and
  `docs/tools.md`.
- `OPENPROJECT_HIDE_<ENTITY>_FIELDS`'s full entity list moved from README
  into its own `docs/field-hiding.md` reference page.
- Corrected `SECURITY.md`'s read-default claims; re-measured and corrected
  README's context-efficiency numbers, with a repeatable script to
  regenerate them.
- Added a "why use this MCP" summary to README, and reordered it ahead of
  the scope/limitations section.
- **Restructured the client setup docs into a hub** (`docs/clients.md`) with
  one guide per client, each verified against that client's own official
  documentation and updated with its actual recommended credential-handling
  pattern instead of a one-size-fits-all example: Claude Code's native
  private Local scope, VS Code's `${input:...}` prompt-and-store variables,
  Codex's `env_vars` environment-forwarding, and Cursor's `${env:...}`
  references for a local STDIO server — each shown alongside what this
  package's `configure` wizard actually writes today.
- Clarified that a source install's `uninstall.sh`/`uninstall.ps1` only clean
  up project-local client configs for the install directory itself, not
  whatever project you actually work in; updated the OpenProject
  compatibility line to distinguish source-audited (17.6) from
  runtime-smoke-tested (17.5) versions; listed Cursor and Claude Desktop
  alongside the other client config files in the credential-hygiene intro;
  refreshed `docs/filters.md`'s stale 17.5 source citations to 17.6.

### Scope

- This release's CE completeness audit confirmed coverage across projects,
  work packages, versions, boards, memberships, users/groups, and the other
  core resources listed in `docs/architecture.md`. Nextcloud file links
  attached to work packages are supported today.
- Meetings and recurring meetings, Backlogs buckets, cost entries and cost
  types, forum posts, storage and project-storage administration,
  GitHub/GitLab linkage, per-user schedule overrides, and wiki page links are
  tracked for upcoming releases.

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
- **`create_work_package` and `update_work_package` gain a `parent` parameter**
  (numeric id or a `PROJ-123` reference) to nest or re-parent a work package.
  `update_work_package` also accepts the literal `'none'` to clear the parent
  and make the work package top-level again.

### Docs

- Added `SECURITY.md`, documenting the supported-versions and vulnerability-
  reporting policy.

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
