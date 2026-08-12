# Tool reference

<p align="center">
  <img src="../img/tools-reference.jpg" alt="A structured set of project tools connected through a central router to a work board." width="960">
</p>

All tools exposed by the OpenProject CE MCP server.

All mutating tools follow the same guarded write pattern by default:

- Call the tool without `confirm=true` to get a preview or validation result.
- Call it again with `confirm=true` to execute the write or delete.

Every mutation requires explicit `confirm=true` — there is no way to skip the preview step.

Clearing a field: on `update_work_package` and `update_project`, pass the string `"none"` to unassign a nullable association instead of changing it — work-package `assignee`, `responsible`, `version`, `sprint`, `parent`, `category`, `project_phase`, and project `parent`. Omitting a field leaves it unchanged; `"none"` clears it. Required fields (type, status, subject, project) cannot be cleared.

All list tools are bounded and paginated. They return compact summaries — not raw OpenProject HAL payloads.

Responses are trimmed for context economy: list results omit the derivable `count`/`truncated` fields, and a confirmed write omits the echoed request `payload` (its normalized `result` carries the same data). `list_work_packages`, `search_work_packages`, `list_projects`, `list_users` and the batch-read `get_work_packages` accept an optional `select` (a list of field names) to return only the fields you need per row (for `get_work_packages`, per fetched work package); an invalid name returns the allowed set for that row type.

Beyond the obvious fields, work packages also carry scheduling/derived state (`schedule_manually`, `ignore_non_working_days`, `derived_start_date`, `derived_due_date`, `percentage_done`, `derived_percentage_done`, `readonly`); versions and memberships carry `created_at`/`updated_at`; users carry `firstname`/`lastname`; categories carry `default_assignee`/`default_assignee_id`; projects carry `favorited`; Backlogs sprints carry `status`, `finish_date`, `defining_workspace`/`defining_workspace_id`, and `created_at`/`updated_at`; Backlogs backlog buckets carry `defining_workspace`/`defining_workspace_id` and `created_at`/`updated_at`. Any of these can be hidden per entity via the matching `OPENPROJECT_HIDE_<ENTITY>_FIELDS` environment variable — see [Configuration](configuration.md).

A subset of rarely-used metadata tools — the `get_query_*` schema tools, `render_text`, `get_custom_option`, `list_help_texts`/`get_help_text`, `list_working_days`/`list_non_working_days` — is **opt-in**: they are registered only when `OPENPROJECT_ENABLE_EXTENDED_READ=true`, to keep them out of the default tool set and save context.

---

## Projects

| Tool | Description |
|---|---|
| `list_projects` | List visible projects with an optional name/identifier filter |
| `get_project` | Fetch a compact project summary by id or identifier |
| `get_project_admin_context` | Return project admin metadata such as lifecycle statuses, parent project options, and writable fields |
| `get_project_configuration` | Return project-scoped configuration such as internal comment support |
| `list_sprints` | List Backlogs sprints (requires Backlogs/OpenProject 17.3+), with an optional project filter and name search filter — omit `project` to list every sprint visible to the current token, or pass it to list only that project's sprints |
| `get_sprint` | Fetch a Backlogs sprint by id |
| `list_backlog_buckets` | List Backlogs backlog buckets (requires Backlogs/OpenProject 17.6+), with an optional project filter and name search filter — omit `project` to list every backlog bucket visible to the current token, or pass it to list only that project's backlog buckets |
| `get_backlog_bucket` | Fetch a Backlogs backlog bucket by id (requires OpenProject 17.6+) |
| `create_project` | Validate and then create a project; only writes when called again with `confirm=true` |
| `copy_project` | Validate and then copy an existing project into a new project; only starts the copy job when called again with `confirm=true` |
| `get_job_status` | Fetch the current status of a background job such as project copy |
| `update_project` | Validate and then update a project; only writes when called again with `confirm=true` |
| `delete_project` | Validate and then delete a project; only deletes when called again with `confirm=true` |
| `set_project_favorite` | Validate and then mark or unmark a project as a favorite (OpenProject 17.0+), based on `favorite`; only writes when called again with `confirm=true` |
| `get_instance_configuration` | Return instance-level OpenProject configuration and active feature flags |

## Memberships

`get_current_user` and `get_my_project_access` (below) report only the
caller's own identity/access and are on by default
(`OPENPROJECT_ENABLE_MEMBERSHIP_READ`). `list_principals` is the odd one out
in this table: it returns the instance-wide user/group list (the same PII as
`list_users`/`list_groups`), so it lives behind
`OPENPROJECT_ENABLE_ADMIN_READ` like the [Users](#users) and
[Groups](#groups) read tools below, not `OPENPROJECT_ENABLE_MEMBERSHIP_READ`.

| Tool | Description |
|---|---|
| `list_roles` | List OpenProject roles visible to the current user |
| `list_principals` | List users and groups that can be used for memberships (`OPENPROJECT_ENABLE_ADMIN_READ`) |
| `list_project_memberships` | List memberships for a project, including principals and role names |
| `get_membership` | Fetch a compact membership summary by id |
| `create_membership` | Validate and then create a project membership; only writes when called again with `confirm=true` |
| `update_membership` | Validate and then update a project membership; only writes when called again with `confirm=true` |
| `delete_membership` | Validate and then delete a project membership; only deletes when called again with `confirm=true` |
| `get_my_project_access` | Return the current user's project membership and inferred access hints based on roles and HATEOAS links |

## Users

`get_current_user` is the exception in this table — it returns only the
caller's own identity and is on by default. Every other tool here lists or
looks up other users and requires `OPENPROJECT_ENABLE_ADMIN_READ=true`
(reads) / `OPENPROJECT_ENABLE_ADMIN_WRITE=true` (writes), off by default
since this is instance-wide PII with no project-scope boundary.

| Tool | Description |
|---|---|
| `get_current_user` | Return the currently authenticated user's profile |
| `list_users` | List visible OpenProject users with an optional search filter (`OPENPROJECT_ENABLE_ADMIN_READ`) |
| `get_user` | Fetch a compact user profile by id (`OPENPROJECT_ENABLE_ADMIN_READ`) |
| `create_user` | Validate and then create a user account; only writes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `update_user` | Validate and then update a user account; only writes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `delete_user` | Validate and then delete a user account; only deletes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `set_user_locked` | Lock or unlock a user account, based on `locked` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |

## Groups

Same gating as [Users](#users) above: reads need
`OPENPROJECT_ENABLE_ADMIN_READ=true`, writes need
`OPENPROJECT_ENABLE_ADMIN_WRITE=true`.

| Tool | Description |
|---|---|
| `list_groups` | List visible OpenProject groups with an optional search filter |
| `get_group` | Fetch a compact group profile by id |
| `create_group` | Validate and then create a group; only writes when called again with `confirm=true` |
| `update_group` | Validate and then update a group; only writes when called again with `confirm=true` |
| `delete_group` | Validate and then delete a group; only deletes when called again with `confirm=true` |

## User schedule overrides

Per-user schedule overrides (vacation date ranges and recurring weekly
working-hours schedules) — requires OpenProject 17.3+ (feature-flag-gated
through 17.6, generally available from 17.7; earlier versions return a
`[server_error]`, since the underlying route does not exist at all before
17.3). Gated by its own dedicated flag pair,
`OPENPROJECT_ENABLE_USER_SCHEDULE_READ`/`_WRITE` (both default `false`) —
neither [Users](#users)' `OPENPROJECT_ENABLE_ADMIN_READ`/`_WRITE` nor a
`personal`-style current-user-only scope fits: OpenProject itself always
lets a caller view/edit their own schedule (`user_ref="me"`) regardless of
role, so an admin-only gate would incorrectly block ordinary self-service,
while every tool here also accepts a `user_ref` for another user, which a
strictly-current-user scope can't express. OpenProject enforces the actual
authorization at the API level regardless of this flag: viewing/editing
another user's schedule requires the `manage_working_times` global
permission, else OpenProject returns 404 (not 403) to avoid confirming that
user exists.

| Tool | Description |
|---|---|
| `list_user_non_working_times` | List a user's non-working-time (vacation) date ranges, with an optional `year` filter |
| `create_user_non_working_time` | Validate and then create a non-working-time date range for a user; only writes when called again with `confirm=true` |
| `update_user_non_working_time` | Validate and then update a user's non-working-time date range; only writes when called again with `confirm=true` |
| `delete_user_non_working_time` | Validate and then delete a user's non-working-time date range; only deletes when called again with `confirm=true` |
| `list_user_working_hours` | List a user's recurring weekly working-hours schedules, most recent `valid_from` first |
| `get_user_working_hours` | Fetch a single working-hours schedule entry for a user |
| `create_user_working_hours` | Validate and then create a new weekly working-hours schedule version for a user; only writes when called again with `confirm=true` |
| `update_user_working_hours` | Validate and then update a user's working-hours schedule entry; only writes when called again with `confirm=true` |
| `delete_user_working_hours` | Validate and then delete a user's working-hours schedule entry; only deletes when called again with `confirm=true` |

## Notifications

| Tool | Description |
|---|---|
| `list_notifications` | List the current user's unread notifications |
| `mark_notifications_read` | Mark a single notification as read (pass `notification_id`), or every unread notification as read (omit it) |

## Actions & capabilities

| Tool | Description |
|---|---|
| `list_actions` | List API actions exposed by the current OpenProject instance |
| `list_capabilities` | List capabilities for a specific project/workspace context or capability id |

## Query metadata

| Tool | Description |
|---|---|
| `get_query_filter` | Fetch a single query filter definition by id such as `assignee` |
| `get_query_column` | Fetch a single query column definition by id such as `subject` |
| `get_query_operator` | Fetch a single query operator definition by id such as `=` |
| `get_query_sort_by` | Fetch a single query sort-by definition by id such as `id-asc` |
| `list_query_filter_instance_schemas` | List query filter-instance schemas globally or for a specific project |
| `get_query_filter_instance_schema` | Fetch a single query filter-instance schema by id |

## Project lifecycle

| Tool | Description |
|---|---|
| `list_project_phase_definitions` | List available project lifecycle phase definitions |
| `get_project_phase_definition` | Fetch a single project lifecycle phase definition by id |
| `get_project_phase` | Fetch a single project lifecycle phase by id |

## Views

| Tool | Description |
|---|---|
| `list_views` | List saved OpenProject views, optionally filtered by project, view subtype, or name search |
| `get_view` | Fetch a single OpenProject view by id |
| `execute_query` | Execute a saved OpenProject query by id and return its resolved work packages, filtered against `OPENPROJECT_READ_PROJECTS` |

## Documents

| Tool | Description |
|---|---|
| `list_documents` | List documents globally or filtered to a specific project, with an optional title search filter |
| `get_document` | Fetch a single document by id |
| `update_document` | Validate and then update a document title or description; only writes when called again with `confirm=true` |

## News

| Tool | Description |
|---|---|
| `list_news` | List news entries globally or filtered to a specific project |
| `get_news` | Fetch a single news entry by id |
| `create_news` | Validate and then create a news entry; only writes when called again with `confirm=true` |
| `update_news` | Validate and then update a news entry; only writes when called again with `confirm=true` |
| `delete_news` | Validate and then delete a news entry; only deletes when called again with `confirm=true` |

## Wiki

| Tool | Description |
|---|---|
| `get_wiki_page` | Fetch a single wiki page by id |
| `list_work_package_wiki_links` | List wiki pages linked to a work package (requires OpenProject 17.6+) |
| `create_work_package_wiki_link` | Validate and then create a link from a work package to a wiki page; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `delete_work_package_wiki_link` | Validate and then delete a work package's wiki page link; only deletes when called again with `confirm=true` (requires OpenProject 17.6+) |

> **Note:** OpenProject API v3 does not provide a collection endpoint for wiki pages
> (`GET /api/v3/projects/{id}/wiki_pages` is not implemented). `list_wiki_pages` has
> therefore been removed. Individual pages can be fetched by id via `get_wiki_page`.
>
> **Note:** the `wiki_page_links` endpoint (`list_work_package_wiki_links`/
> `create_work_package_wiki_link`/`delete_work_package_wiki_link`) requires
> OpenProject 17.6 or later — earlier versions return a `[server_error]`.
>
> **Note:** `list_work_package_wiki_links` returns a `[server_error]` whenever
> the work package actually has one or more wiki page links — a confirmed
> OpenProject server bug (16.6/17.6/17.7.1, tracked as OPM-399). Only the
> empty-list case reliably works. `delete_work_package_wiki_link` is affected
> too: it verifies `link_id` actually belongs to `work_package_id` before
> deleting (a real authorization check, not skippable) by listing the work
> package's links internally first, so it hits the same bug whenever the
> link being deleted actually exists. `create_work_package_wiki_link` is
> unaffected.

## Forums

| Tool | Description |
|---|---|
| `get_post` | Fetch a single forum post by id |

> **Note:** OpenProject API v3 provides exactly one route for forum posts —
> `GET /api/v3/posts/{id}`. There is no collection endpoint for posts and no
> separate "forums" resource in the API at all, so `list_posts` cannot be
> implemented. A post's id must come from elsewhere (e.g. a work package's
> activity/journal referencing a forum post, or a link from the OpenProject
> web UI).

## Work packages

> Single work-package tools accept either a numeric id or a project-prefixed
> `displayId` reference such as `PROJ-123` (OpenProject 17.5+). The bulk tools
> (`bulk_create_work_packages`, `bulk_update_work_packages`) are numeric-only.

| Tool | Description |
|---|---|
| `list_statuses` | List available work-package statuses |
| `get_status` | Fetch a single work-package status by id |
| `list_priorities` | List available work-package priorities |
| `get_priority` | Fetch a single work-package priority by id |
| `list_types` | List available work-package types globally or for a project |
| `get_type` | Fetch a single work-package type by id |
| `list_categories` | List work-package categories configured for a project |
| `get_category` | Fetch a single category from a project's category list |
| `get_project_work_package_context` | Return project metadata plus the writable work-package schema for an optional type, including custom fields, project phases, and allowed values |
| `list_work_packages` | List work packages with structured filters such as `project`, `type`, `version`, `version_status` (open/closed/locked), `assignee`, `status`, and `priority` |
| `search_work_packages` | Search work packages by free-text query matching only subject/ID (not version); optional `project`, `status`, `open_only`, and `assignee_me` filters — for version-based filtering use `list_work_packages(version=...)` instead |
| `get_work_package` | Fetch a detailed work package summary by id or `displayId` reference |
| `get_work_packages` | Fetch multiple work packages by ID in parallel (max 100 IDs per batch) |
| `create_work_package` | Validate and then create a work package; only writes when called again with `confirm=true` |
| `create_subtask` | Validate and then create a child work package below an existing parent; only writes when called again with `confirm=true` |
| `update_work_package` | Validate and then update a work package; only writes when called again with `confirm=true` |
| `bulk_create_work_packages` | Validate and then create multiple work packages in one call; returns per-item results including errors; only writes when called again with `confirm=true` |
| `bulk_update_work_packages` | Validate and then update multiple work packages in one call; returns per-item results including errors; only writes when called again with `confirm=true` |
| `delete_work_package` | Validate and then delete a work package; only deletes when called again with `confirm=true` |
| `add_work_package_comment` | Validate and then add a comment to a work package; `notify=false` by default to avoid change emails; only writes when called again with `confirm=true` |
| `create_work_package_relation` | Validate and then create a relation between work packages; only writes when called again with `confirm=true` |
| `delete_relation` | Validate and then delete a work package relation; only deletes when called again with `confirm=true` |
| `get_work_package_relations` | Fetch all relations for a work package (blocks, relates to, duplicates, …) |
| `get_work_package_activities` | Fetch the activity log for a work package, most recent first |
| `list_work_package_reactions` | List emoji reactions across a work package's comment activities |
| `toggle_activity_emoji_reaction` | Toggle an emoji reaction on a work package comment activity (add if absent, remove if present) |
| `list_reminders` | List the current user's active reminders across all work packages |
| `create_work_package_reminder` | Validate and then create a reminder on a work package (one active reminder per work package) |
| `update_reminder` | Validate and then update a reminder's time or note |
| `delete_reminder` | Validate and then delete a reminder; only deletes when called again with `confirm=true` |
| `list_my_open_work_packages` | List the current user's open assigned work packages |
| `list_work_package_watchers` | List watchers on a work package |
| `set_work_package_watcher` | Add or remove a user as a watcher on a work package, based on `watching` |
| `list_work_package_file_links` | List Nextcloud file links attached to a work package (Community Edition) |
| `delete_file_link` | Validate and then delete a Nextcloud file link; only deletes when called again with `confirm=true` |

## Attachments

| Tool | Description |
|---|---|
| `list_work_package_attachments` | List attachments on a work package |
| `get_attachment` | Fetch a single work-package attachment by id |
| `create_work_package_attachment` | Validate and then upload an attachment to a work package; only writes when called again with `confirm=true` |
| `delete_attachment` | Validate and then delete an attachment; only deletes when called again with `confirm=true` |

`OPENPROJECT_ATTACHMENT_ROOT` must be set to an absolute directory for local uploads to work at all — `create_work_package_attachment` isn't even registered otherwise, no working-directory fallback. Once set, files outside it — and credential/config files such as `.mcp.json`, `.env`, or private keys even inside it — are refused, so a tool call cannot exfiltrate local secrets.

## Versions

| Tool | Description |
|---|---|
| `list_versions` | List versions globally or scoped to a specific project, with an optional name filter |
| `get_version` | Fetch a compact version summary by id |
| `create_version` | Validate and then create a version; only writes when called again with `confirm=true` |
| `update_version` | Validate and then update a version; only writes when called again with `confirm=true` |
| `delete_version` | Validate and then delete a version; only deletes when called again with `confirm=true` |

## Boards

| Tool | Description |
|---|---|
| `list_boards` | List saved OpenProject boards/queries globally or scoped to a project |
| `get_board` | Fetch a saved OpenProject board/query by id |
| `create_board` | Validate and then create a saved OpenProject board/query; only writes when called again with `confirm=true` |
| `update_board` | Validate and then update a saved OpenProject board/query; only writes when called again with `confirm=true` |
| `delete_board` | Validate and then delete a saved OpenProject board/query; only deletes when called again with `confirm=true` |

## Meetings

Meetings has its own dedicated `OPENPROJECT_ENABLE_MEETING_READ`/`_WRITE` scope (default: both `true`, same as Boards), shared by all five sub-resources below. Requires OpenProject 17.4+ for Meetings/Agenda Items/Sections/Recurring Meetings; Meeting Outcomes additionally require 17.6+.

| Tool | Description |
|---|---|
| `list_meetings` | List meetings globally or scoped to a project (requires OpenProject 17.4+) |
| `get_meeting` | Fetch a single meeting by id (requires OpenProject 17.4+) |
| `create_meeting` | Validate and then create a meeting in a project; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `update_meeting` | Validate and then update a meeting; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `delete_meeting` | Validate and then delete a meeting; only deletes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `list_meeting_agenda_items` | List a meeting's agenda items (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.4+) |
| `list_work_package_meeting_agenda_items` | List meeting agenda items linked to a work package (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.4+) |
| `get_meeting_agenda_item` | Fetch a single meeting agenda item by id (requires OpenProject 17.4+) |
| `create_meeting_agenda_item` | Validate and then create a meeting agenda item, optionally linked to a work package or a section; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `update_meeting_agenda_item` | Validate and then update a meeting agenda item; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `delete_meeting_agenda_item` | Validate and then delete a meeting agenda item; only deletes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `list_meeting_outcomes` | List an agenda item's outcomes (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.6+) |
| `get_meeting_outcome` | Fetch a single meeting outcome by id (requires OpenProject 17.6+) |
| `create_meeting_outcome` | Validate and then create a meeting outcome on an agenda item; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `update_meeting_outcome` | Validate and then update a meeting outcome; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `delete_meeting_outcome` | Validate and then delete a meeting outcome; only deletes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `list_meeting_sections` | List a meeting's sections (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.4+) |
| `get_meeting_section` | Fetch a single meeting section by id (requires OpenProject 17.4+) |
| `create_meeting_section` | Validate and then create a meeting section; `backlog` may only be set here, not via `update_meeting_section`; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `update_meeting_section` | Validate and then update a meeting section's title/position; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `delete_meeting_section` | Validate and then delete a meeting section; only deletes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `list_recurring_meetings` | List recurring meeting series globally or scoped to a project (requires OpenProject 17.4+) |
| `get_recurring_meeting` | Fetch a single recurring meeting series by id (requires OpenProject 17.4+) |
| `create_recurring_meeting` | Validate and then create a recurring meeting series in a project; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `update_recurring_meeting` | Validate and then update a recurring meeting series; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `delete_recurring_meeting` | Validate and then delete a recurring meeting series; only deletes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `list_recurring_meeting_occurrences` | List a recurring meeting's virtual occurrences by `filter` (`upcoming`/`past`/`cancelled`/`open`); no offset/pagination envelope (requires OpenProject 17.4+) |
| `init_recurring_meeting_occurrence` | Validate and then materialize a virtual occurrence into a real, standalone meeting (addressed by `start_time`, not an id); only writes when called again with `confirm=true`; result is a full meeting (requires OpenProject 17.4+) |
| `cancel_recurring_meeting_occurrence` | Validate and then cancel a not-yet-materialized occurrence (addressed by `start_time`); only writes when called again with `confirm=true` (requires OpenProject 17.4+) |

> **Note:** `cancel_recurring_meeting_occurrence` on an occurrence that has NOT
> yet been materialized creates a new, **permanently cancelled** meeting
> server-side to record the cancellation — this is a real, permanent
> data-creation side effect behind what reads like a pure "cancel" call. The
> response does not report that new meeting's id (OpenProject returns 204
> with no body); use `list_meetings` or `list_recurring_meeting_occurrences`
> with `filter="cancelled"` to find it afterward if needed. If the occurrence
> is already materialized and not itself cancelled, the call fails instead —
> use `delete_meeting` on the materialized meeting directly.
>
> **Note:** Meeting Agenda Items, Meeting Sections, and Meeting Outcomes are
> addressed by their own bare id (not nested under their parent's id) —
> OpenProject's global routes for these resources already resolve their
> parent project server-side via an authoritative join, so this MCP's own
> project-allowlist check runs against that resolved project on every
> `get`/`update`/`delete` call.

## Time entries

| Tool | Description |
|---|---|
| `list_time_entry_activities` | List available time entry activities |
| `list_time_entries` | List time entries with optional project, work package, user, and date filters |
| `get_time_entry` | Fetch a single time entry by id |
| `create_time_entry` | Validate and then create a time entry (optional `start_time` when the instance allows start/end time tracking; `end_time` is read-only on OpenProject's side and not a parameter); only writes when called again with `confirm=true` |
| `update_time_entry` | Validate and then update a time entry; only writes when called again with `confirm=true` |
| `create_time_entry_until` | Like `create_time_entry`, but takes `start_time`+`end_time` instead of `hours` -- `hours` is computed locally as the exact duration between them (never sent as `end_time`, since OpenProject rejects that); only writes when called again with `confirm=true` |
| `update_time_entry_until` | Like `update_time_entry`, but takes `start_time`+`end_time` instead of `hours`, and always completes the entry (`ongoing=false`); only writes when called again with `confirm=true` |
| `delete_time_entry` | Validate and then delete a time entry; only deletes when called again with `confirm=true` |

## Costs

| Tool | Description |
|---|---|
| `get_cost_entry` | Fetch a single cost entry by id |
| `list_work_package_cost_entries` | List all cost entries recorded against a work package |
| `get_work_package_costs_by_type` | Get a work package's costs aggregated by cost type |
| `get_cost_type` | Fetch a cost type by id |

> **Note:** the Costs module is entirely read-only in OpenProject's API —
> there is no create/update/delete endpoint for cost entries or cost types,
> and no collection `GET` for cost types (only single-item lookup by id).

## Grids

| Tool | Description |
|---|---|
| `list_grids` | List dashboard grids globally or scoped to a project or user |
| `get_grid` | Fetch a single grid by id |
| `create_grid` | Validate and then create a dashboard grid for a scope such as `/my/page` or `/projects/<identifier>`; only writes when called again with `confirm=true` |
| `update_grid` | Validate and then update a dashboard grid (name, row/column count); only writes when called again with `confirm=true` |
| `delete_grid` | Validate and then delete a dashboard grid; only deletes when called again with `confirm=true` |

## User preferences

| Tool | Description |
|---|---|
| `get_my_preferences` | Return the current user's preferences (language, timezone, comment sorting, …) |
| `update_my_preferences` | Prepare or update the current user's preferences; only writes when called again with `confirm=true` |

## Text rendering

| Tool | Description |
|---|---|
| `render_text` | Render markdown or plain text to HTML using the OpenProject API |

## Help texts

| Tool | Description |
|---|---|
| `list_help_texts` | List all help texts configured for work-package and project attributes |
| `get_help_text` | Fetch a single help text by id |

## Working days

| Tool | Description |
|---|---|
| `list_working_days` | List the working-day configuration (Mon–Sun) for a given year or the current year |
| `list_non_working_days` | List non-working days (public holidays / closures) for a given year or the current year |

## Custom options

| Tool | Description |
|---|---|
| `get_custom_option` | Fetch the label/value of a single custom field option by id |

## Relations (global)

| Tool | Description |
|---|---|
| `list_relations` | List all relations across the instance, optionally filtered by type |
| `update_relation` | Prepare or update the type or description of a relation; only writes when called again with `confirm=true` |

## Errors

Every tool failure carries a stable, machine-readable category as a leading
`[category]` prefix on the error message, so an agent can branch on the failure
type instead of parsing free text. The categories are:

| Category | Meaning |
|---|---|
| `[validation_error]` | An input was rejected before the request (fix the arguments and retry) |
| `[auth_error]` | Authentication failed (check the API token) |
| `[permission_denied]` | The token lacks permission, or a write scope is disabled |
| `[not_found]` | The resource does not exist (or the feature needs a newer OpenProject) |
| `[transport_error]` | OpenProject could not be reached (transient — safe to retry) |
| `[server_error]` | OpenProject returned an unexpected failure |
| `[openproject_error]` | Any other OpenProject-side failure |

Successful write previews are not errors — they return a structured result with
`ready`, `state` (`"rejected"` | `"invalid"` | `"preview"` | `"confirmed"`),
`validation_errors`, and a human-readable `message`.

## See also

- [Documentation hub](README.md) — full documentation index
- [Work package filters](filters.md) — filter keys and operators for `list_work_packages` / `search_work_packages`
- [Field hiding](field-hiding.md) — full list of entities supported by `OPENPROJECT_HIDE_<ENTITY>_FIELDS`
- [Configuration](configuration.md) — the full environment variable reference
- [Troubleshooting](troubleshooting.md) — common tool/setup issues
