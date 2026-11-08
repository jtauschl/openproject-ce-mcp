# Tool reference

<p align="center">
  <img src="../img/tools-reference.jpg" alt="A structured set of project tools connected through a central router to a work board." width="960">  <!-- markdownlint-disable-line MD013 -->
</p>

All tools exposed by the OpenProject CE MCP server.

All mutating tools follow the same guarded write pattern by default:

- Call the tool without `confirm=true` to get a preview or validation result.
- Call it again with `confirm=true` to execute the write or delete.
- A write that takes a work package reference names the work package it
  resolved to in `target` (id, display id, project, subject, status), in the
  preview and in the result. A bare number is the internal id and `PROJ-123`
  the display id, so check `target` before confirming. For `create_work_package`, `create_subtask` and `bulk_create_work_packages`
  `target` is the referenced parent, for relations `related_target` names
  the other end, and `update_work_package` and `bulk_update_work_packages` name
  the work package a given `parent` resolved to in `parent_target`.
  A project reference works the same way: `create_project`, `update_project`
  and `copy_project` name the project a given `parent` resolved to in
  `parent_target` (id, identifier, name). An identifier wins over a project name,
  so check `parent_target` before confirming.
- On an instance with semantic display ids, `update_work_package`,
  `delete_work_package`, `add_work_package_comment`,
  `create_work_package_attachment`, `set_work_package_watcher` and each item of
  `bulk_update_work_packages` refuse a write that names the work package by a
  bare number, in preview and in confirm, unless `expect_display_id` names the
  ticket you mean (for example `"PROJ-51"`, project identifier case-sensitive).
  The refusal names the ticket the number resolved to; either repeat the call
  with `expect_display_id` or pass the display id as the reference. A given
  `expect_display_id` that does not name the resolved work package is refused,
  and so is one on a work package without a semantic display id. A bulk item
  that is refused is reported in its `error`; the other items continue. The
  guard cannot tell whether the caller read the preview: it stops the wrong
  ticket, not a copied `target.display_id`. A record that has no project
  identifier (semantic mode before an identifier is allocated) shows its
  numeric id as display id and is written by that id without a guard.
- The same rule covers a parent: `create_work_package`, `create_subtask`,
  `update_work_package` and each item of `bulk_create_work_packages` and
  `bulk_update_work_packages` refuse a parent named by a bare number unless
  `expect_parent_display_id` names the ticket. The refusal names the parameter
  to repeat the call with. `update_work_package` checks its own
  `work_package_id` and its parent independently. An expectation with no parent
  to check (none given, or `parent` set to `none`) is refused.
- The remaining writes that take a work package apply the same rule through
  `expect_display_id`: `create_work_package_relation`,
  `create_work_package_reminder`, `create_work_package_wiki_link`,
  `delete_work_package_wiki_link`, `create_time_entry`,
  `create_time_entry_until`, `create_meeting_agenda_item`,
  `update_meeting_agenda_item`, `create_meeting_outcome` and
  `update_meeting_outcome`. `create_work_package_relation` guards its source
  with `expect_display_id` and its related work package with
  `expect_related_display_id`, each independently. A tool whose work package is
  optional (time entries, agenda items, outcomes) refuses an expectation given
  without a work package.

Every mutation requires explicit `confirm=true` — there is no way to skip the
preview step.

Each tool declares MCP annotations (read-only, destructive, idempotent,
open-world); they are hints for clients, not a permission gate.

Parameters that take a reference to a resource (a project, work package, version
or user by name, key or id) accept a numeric id as either a JSON number or a
decimal string. Every other argument keeps its own JSON type: a plain id, offset
or limit is sent as a number (not `"5"`, not `5.0` for a whole number), `confirm`
and other flags as `true` or `false` (not `"yes"`, `"true"` or `1`), and a
mistyped argument is rejected with a validation error before anything is sent
to OpenProject.

Argument names mostly follow one scheme: `<entity>_id` is the one resource a tool acts on
(`work_package_id`, `version_id`), `<entity>_ids` several of them
(`work_package_ids`), and the bare entity name is a reference or a filter
(`project`, `user`, `version`). A project is always `project`. Exceptions: a user
is `user_id` on the tools that write one (`update_user`, `delete_user`) but `user`
on `get_user`, and a user reference is `user_ref` on some tools and `user` on
others; a parent is `parent` on `create_work_package` and `update_work_package`
but `parent_work_package_id` on `create_subtask`. A rejected unknown argument
names the closest allowed one, for example `id (did you mean work_package_id?)`,
and the call is still not sent. No hint is given where several arguments could
be meant.

Clearing a field: on `update_work_package` and `update_project`, pass the string
`"none"` to unassign a nullable association instead of changing it —
work-package `assignee`, `responsible`, `version`, `sprint`, `parent`,
`category`, `project_phase`, and project `parent`. Omitting a field leaves it
unchanged; `"none"` clears it. Required fields (type, status, subject, project)
cannot be cleared. `target_versions` is the one exception to the `"none"`
convention: it's a list, so it already disambiguates unchanged (omit it) from
cleared (pass `[]`) without needing a sentinel string.

Editing a long text: these tools take `<field>_append` (a new paragraph after the
stored text) and `<field>_replace` (`{"old": ..., "new": ...}`, where `old` names
exactly one passage of the stored text and whitespace runs may differ):

- `update_work_package` and each item of `bulk_update_work_packages`: `description`.
- `update_work_package_comment`: `comment`.
- `update_project`: `description` and `status_explanation`.
- `update_version`, `update_document` and `update_news`: `description`.

Both are computed against the stored text, not against a read of it, so
everything outside the edit stays byte-identical. A read cuts long text and
flattens the line breaks of a version, document or news text, so a full text
built from a read rewrites the stored one. The three inputs of one field cannot
be combined, and the fields of one call do not interfere. A full text that holds
a cut copy of the stored text (a read ending in `…`) is refused. The preview and
the result name the length before and after. These resources have no lock
version: the edit is computed again on the confirming call, so a change made
between preview and confirm changes what an append lands on or makes a replace
fail. `update_work_package_comment` needs exactly one of `comment`,
`comment_append` and `comment_replace`, and refuses an edit that would leave the
comment blank.

`version`/`target_versions`: `target_versions` is the canonical field — a list
of version names/ids, supporting OpenProject's multi-version assignment
feature. `version` is a derived, backward-compatible single-value convenience:
it mirrors the one assigned version when exactly one is assigned, and is `None`
both when no version is assigned and when more than one is — this second case
is a lossy collapse, not a distinguishable "no version" state, so check
`target_versions` directly if that distinction matters. On write,
`create_work_package`/`create_subtask`/`update_work_package` (and both bulk
tools' per-item fields) accept `version` or `target_versions` but never both in
the same call — they write the same underlying data. Writing more than one
target version is only accepted by OpenProject when its
`Setting::WorkPackageMultipleVersions` instance setting is active (an
admin-controlled toggle; the request is rejected server-side otherwise,
surfaced as a normal validation error). A fresh OpenProject 17.8 installation
ships with this setting active by default — check the instance's own admin
settings rather than assuming either state.
`update_work_package`'s legacy `version` parameter (including clearing it via
`"none"`) is rejected client-side against a work package that already has more
than one target version — use `target_versions` explicitly instead, so a
multi-version assignment is never silently collapsed to one or wiped by a call
that only meant to touch the single-value field.

`observed_in_versions` (OpenProject 17.9+): a list of version names/ids
recording where a bug was observed, independent of `target_versions`. Read on
every work package (empty on older servers), written through the same create,
update and bulk tools (`[]` clears it), and filterable with
`list_work_packages(observed_in_version=...)`. OpenProject offers the
attribute per work package type; a write for a type or server without it is
rejected instead of being silently dropped.

All list tools are bounded and paginated. They return compact summaries — not
raw OpenProject HAL payloads.

Responses are trimmed for context economy: list results omit the derivable
`count`/`truncated` fields, and a confirmed write omits the echoed request
`payload`, even when selected (its normalized `result` carries the same data).
`list_work_packages`, `search_work_packages`, `list_projects`, `list_users`,
the batch-read `get_work_packages` and the bulk writes
`bulk_create_work_packages`/`bulk_update_work_packages` accept an optional
`select` (a list of field names) to return only the fields you need per row
(for `get_work_packages`, per fetched work package; for `search_work_packages`,
also its `exact_match` when present; for the bulk writes, per item's write
result, with fields of the written work package selected as `result.<field>`,
e.g. `["work_package_id", "result.status"]`); an invalid name returns the
allowed set for that row type. Without `select`, a bulk item that succeeded in a
confirmed call is lean (`work_package_id`, `state`, `result.display_id`,
`result.status`, and `target` and `parent_target` when present); a failed or
rejected item and a preview keep their full write result, and
`["work_package_id", "state", "result"]` returns the whole written work package.

Beyond the obvious fields, work packages also carry scheduling/derived state
(`schedule_manually`, `ignore_non_working_days`, `derived_start_date`,
`derived_due_date`, `percentage_done`, `derived_percentage_done`, `readonly`,
`has_project_attributes` — the last requires OpenProject 17.7+, absent/`None` on
older instances); versions and memberships carry `created_at`/`updated_at`;
users carry `firstname`/`lastname`; categories carry
`default_assignee`/`default_assignee_id`; projects carry `favorited`, and
`get_project`'s detail shape additionally carries `ancestors` (its
parent-project chain, absent from `list_projects`' compact summary shape);
Backlogs sprints carry `status`, `finish_date`,
`defining_workspace`/`defining_workspace_id`, and `created_at`/`updated_at`;
Backlogs backlog buckets carry `defining_workspace`/`defining_workspace_id` and
`created_at`/`updated_at`. Any of these can be hidden per entity via the
matching `OPENPROJECT_HIDE_<ENTITY>_FIELDS` environment variable — see
[Configuration](configuration.md).

A subset of rarely-used metadata tools — the `get_query_*` schema tools,
`render_text`, `get_custom_option`, `list_help_texts`/`get_help_text`,
`list_working_days`/`list_non_working_days`, `list_project_budgets`, `list_version_projects`, `list_work_package_available_watchers`, `list_work_package_available_projects`, `list_work_package_revisions` — is **opt-in**: they are registered
only when `OPENPROJECT_ENABLE_EXTENDED_READ=true`, to keep them out of the
default tool set and save context.

---

## Projects

| Tool | Description |
| --- | --- |
| `list_projects` | List visible projects with an optional name/identifier filter, `custom_field_filters` and `sort_by` on project attributes (`cf_<N>`, see [filters.md](filters.md#project-attributes)); each row carries the project attributes the token may see as `custom_fields`, and `select` keeps them when it names `custom_fields` |
| `get_project` | Fetch a compact project summary by id, identifier or name, including the project attributes (`custom_fields`, and from OpenProject 17.2 `custom_comments`) the token may see |
| `get_project_admin_context` | Return project admin metadata such as lifecycle statuses, parent project options, and writable fields |
| `get_project_configuration` | Return project-scoped configuration such as internal comment support |
| `list_sprints` | List Backlogs sprints (requires Backlogs/OpenProject 17.3+), with an optional project filter and name search filter — omit `project` to list every sprint visible to the current token, or pass it to list only that project's sprints |
| `get_sprint` | Fetch a Backlogs sprint by id (requires OpenProject 17.3+) |
| `list_backlog_buckets` | List Backlogs backlog buckets (requires Backlogs/OpenProject 17.6+), with an optional project filter and name search filter — omit `project` to list every backlog bucket visible to the current token, or pass it to list only that project's backlog buckets |
| `get_backlog_bucket` | Fetch a Backlogs backlog bucket by id (requires OpenProject 17.6+) |
| `create_project` | Validate and then create a project, with `custom_fields` for project attributes; only writes when called again with `confirm=true` |
| `copy_project` | Validate and then copy an existing project into a new project, with `custom_fields` for project attributes (not their comments: OpenProject fails a copy that names one); only starts the copy job when called again with `confirm=true` |
| `get_job_status` | Fetch the current status of a background job such as project copy |
| `update_project` | Validate and then update a project, with `custom_fields` for project attributes; only writes when called again with `confirm=true` |
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
| --- | --- |
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
| --- | --- |
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
| --- | --- |
| `list_groups` | List visible OpenProject groups with an optional search filter |
| `get_group` | Fetch a compact group profile by id |
| `create_group` | Validate and then create a group; only writes when called again with `confirm=true` |
| `update_group` | Validate and then update a group; only writes when called again with `confirm=true` |
| `delete_group` | Validate and then delete a group; only deletes when called again with `confirm=true` |

## Storages

External file storage connections (Nextcloud/OneDrive/Sharepoint) and each
project's link to a configured storage (Community Edition). Same gating as
[Users](#users) above: `list_storages`/`get_storage`/`create_storage`/
`update_storage`/`delete_storage` need `OPENPROJECT_ENABLE_ADMIN_READ=true`
(reads) / `OPENPROJECT_ENABLE_ADMIN_WRITE=true` (writes) — genuine admin-only
operations in OpenProject's own API. `list_project_storages`/
`get_project_storage` are project-scoped instead (`OPENPROJECT_ENABLE_PROJECT_READ`
plus `OPENPROJECT_READ_PROJECTS`), matching [Documents](#documents): OpenProject's
own API gates this resource per-project (`view_file_links`), not admin-only.
`create_storage` targeting OneDrive/Sharepoint on a Community Edition instance
is rejected by OpenProject itself at `confirm=true` with a clear validation
error (Enterprise-only providers); Nextcloud is unrestricted. Project storages
are read-only in OpenProject's API — no create/update/delete endpoint exists
for that resource.

| Tool | Description |
| --- | --- |
| `list_storages` | List configured external file storage connections (`OPENPROJECT_ENABLE_ADMIN_READ`) |
| `get_storage` | Fetch a single storage connection by id (`OPENPROJECT_ENABLE_ADMIN_READ`) |
| `create_storage` | Validate and then create a storage connection; only writes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `update_storage` | Validate and then update a storage connection; only writes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `delete_storage` | Validate and then delete a storage connection; only deletes when called again with `confirm=true` (`OPENPROJECT_ENABLE_ADMIN_WRITE`) |
| `list_project_storages` | List a project's links to configured external storages, optionally filtered to one project |
| `get_project_storage` | Fetch a single project-storage link by id |

## User schedule overrides

Per-user schedule overrides (vacation date ranges and recurring weekly
working-hours schedules) — requires OpenProject 17.3+ (feature-flag-gated
through 17.6, generally available from 17.7; on an older server, or on 17.3 to 17.6
with the feature flag off, the route answers 404 and the tool returns a
`[RESOURCE_NOT_FOUND]` naming the 17.3 floor). Gated by its own dedicated flag pair,
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
| --- | --- |
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
| --- | --- |
| `list_notifications` | List the current user's in-app notifications; pass `unread_only=true` to list only unread ones |
| `get_notification` | Get one in-app notification with its details (the dates of a date alert, the note of a reminder) and the activity it points at; under a restricted `OPENPROJECT_READ_PROJECTS`, only one about a project it covers |
| `mark_notifications_read` | Mark a single notification as read (pass `notification_id`), or every unread notification as read (omit it); under a restricted `OPENPROJECT_READ_PROJECTS`, only notifications about projects it covers |
| `mark_notifications_unread` | Mark a single notification as unread (pass `notification_id`), or every read notification as unread (omit it); same scope rules as `mark_notifications_read` |

## Actions & capabilities

| Tool | Description |
| --- | --- |
| `list_actions` | List API actions exposed by the current OpenProject instance |
| `list_capabilities` | List capabilities for a specific project/workspace context or capability id |

## Query metadata

| Tool | Description |
| --- | --- |
| `get_query_filter` | Fetch a single query filter definition by id such as `assignee` |
| `get_query_column` | Fetch a single query column definition by id such as `subject` |
| `get_query_operator` | Fetch a single query operator definition by id such as `=` |
| `get_query_sort_by` | Fetch a single query sort-by definition by id such as `id:asc` or `id-asc` |
| `list_query_filter_instance_schemas` | List query filter-instance schemas globally or for a specific project |
| `get_query_filter_instance_schema` | Fetch a single query filter-instance schema by id |

## Project lifecycle

| Tool | Description |
| --- | --- |
| `list_project_phase_definitions` | List available project lifecycle phase definitions |
| `get_project_phase_definition` | Fetch a single project lifecycle phase definition by id |
| `get_project_phase` | Fetch a single project lifecycle phase by id, with its definition and `active` flag (`start_date` and `finish_date` are always null: the API does not provide them) |

## Views

| Tool | Description |
| --- | --- |
| `list_views` | List saved OpenProject views, optionally filtered by project, view subtype, or name search |
| `get_view` | Fetch a single OpenProject view by id |
| `execute_query` | Execute a saved OpenProject query by id and return its resolved work packages, filtered against `OPENPROJECT_READ_PROJECTS` |
| `set_query_starred` | Star or unstar a saved query; the star belongs to the query, so a public query changes for everyone: a query of a project needs that project in `OPENPROJECT_WRITE_PROJECTS`, a public query without a project needs the write scope `*`; a private query only for its owner; only when OpenProject allows the caller to use that route; only writes when called again with `confirm=true` |

## Documents

| Tool | Description |
| --- | --- |
| `list_documents` | List documents globally or filtered to a specific project, with an optional title search filter |
| `get_document` | Fetch a single document by id |
| `update_document` | Validate and then update a document title or description; only writes when called again with `confirm=true`. On OpenProject 16.6, the server rejects every update with a generic permission error unless the instance's "Block note editor" experimental feature flag is enabled (`/admin/settings/experimental`) — this flag is on by default from 17.x onward, so this only affects older instances. |

## News

| Tool | Description |
| --- | --- |
| `list_news` | List news entries globally or filtered to a specific project |
| `get_news` | Fetch a single news entry by id |
| `create_news` | Validate and then create a news entry; only writes when called again with `confirm=true` |
| `update_news` | Validate and then update a news entry; only writes when called again with `confirm=true` |
| `delete_news` | Validate and then delete a news entry; only deletes when called again with `confirm=true` |

## Wiki

| Tool | Description |
| --- | --- |
| `get_wiki_page` | Fetch a single wiki page by id |
| `list_work_package_wiki_links` | List wiki pages linked to a work package (requires OpenProject 17.5+; see the server bug note below) |
| `create_work_package_wiki_link` | Validate and then create a link from a work package to a wiki page; only writes when called again with `confirm=true` (requires OpenProject 17.7+: `POST work_packages/{id}/wiki_page_links` does not exist on 17.6 or earlier) |
| `delete_work_package_wiki_link` | Validate and then delete a work package's wiki page link; only deletes when called again with `confirm=true` (requires OpenProject 17.6+: `DELETE wiki_page_links/{id}` does not exist on 17.5 or earlier) |

> **Note:** OpenProject API v3 does not provide a collection endpoint for wiki pages
> (`GET /api/v3/projects/{id}/wiki_pages` is not implemented). `list_wiki_pages`
has
> therefore been removed. Individual pages can be fetched by id via `get_wiki_page`.
>
> **Note:** on a server older than the version a wiki page link tool
> requires (list 17.5, delete 17.6, create 17.7), the tool returns a
> `[RESOURCE_NOT_FOUND]` that names the required version. On 17.5,
> `delete_work_package_wiki_link` usually fails earlier with an
> `[OPENPROJECT_UNAVAILABLE]`, because its link check runs into the server
> bug below.
>
> **Note:** an OpenProject server bug (17.5 to at least 17.9.1) makes
> `list_work_package_wiki_links` return an `[OPENPROJECT_UNAVAILABLE]` when
> none of the work package's links resolves to a wiki page the user can see;
> on 17.5 and 17.6 this also happens when the work package has no links. A
> link to the internal wiki resolves when its `identifier` is the page's
> numeric id (the `wiki_page_id` of `get_wiki_page`); OpenProject accepts any
> other string when the link is created. `delete_work_package_wiki_link` is
> affected too: it verifies `link_id` actually belongs to `work_package_id`
> before deleting (a real authorization check, not skippable) by listing the
> work package's links internally first. `create_work_package_wiki_link` is
> unaffected.
>
> `list_work_package_wiki_links` checks only the work package against
> `OPENPROJECT_READ_PROJECTS`: a link carries no project, so a link to a page in
> another project is listed. It shows the identifier, provider and author,
> never the page's title or text.
>
> **Note:** `delete_work_package_wiki_link` deletes relation links only
> (`link_type` `relation`). An inline link comes from a wiki link in the work
> package's description or from a wiki page that mentions the work package;
> OpenProject offers no API to delete it, so the tool rejects it with a
> `[VALIDATION_FAILED]` without sending the delete request, and the link goes
> away only when that text changes. Deleting needs the "Manage wiki page
> links" permission in the work package's project; without it OpenProject
> answers 404, which the tool reports as `[RESOURCE_NOT_FOUND]` naming 17.6, not as
> `[OPENPROJECT_PERMISSION_DENIED]`.

## Forums

| Tool | Description |
| --- | --- |
| `get_post` | Fetch a single forum post by id |

> **Note:** OpenProject API v3 provides exactly one route for forum posts —
> `GET /api/v3/posts/{id}`. There is no collection endpoint for posts and no
> separate "forums" resource in the API at all, so `list_posts` cannot be
> implemented. A post's id must come from elsewhere (e.g. a work package's
> activity/journal referencing a forum post, or a link from the OpenProject
> web UI).

## Work packages

> Single work-package tools accept either a numeric id or a project-prefixed
> `displayId` reference such as `PROJ-123` (OpenProject 17.5+, or 17.4 with
> its semantic identifier feature flag): a current or former project
> identifier, semantic (`PROJ`) or classic (`my-proj`), a hyphen, then the
> number. Any other value is rejected as invalid input before a request is
> made. The bulk tools (`bulk_create_work_packages`,
> `bulk_update_work_packages`) accept the same references per item
> (`work_package_id`, `parent`/`parent_work_package_id`).

| Tool | Description |
| --- | --- |
| `list_statuses` | List available work-package statuses |
| `get_status` | Fetch a single work-package status by id |
| `list_priorities` | List available work-package priorities |
| `get_priority` | Fetch a single work-package priority by id |
| `list_types` | List available work-package types globally or for a project |
| `get_type` | Fetch a single work-package type by id |
| `list_categories` | List work-package categories configured for a project |
| `get_category` | Fetch a single category from a project's category list |
| `get_project_work_package_context` | Return project metadata plus the writable work-package schema for an optional type, including custom fields, project phases, and allowed values |
| `list_work_packages` | List work packages with structured filters such as `project`, `type`, `version`, `version_status` (open/closed/locked, requires OpenProject 16.4+), `assignee`, `status`, `priority`, and `custom_field_filters` (filter by custom field value, keyed by `cf_<N>`/`customField<N>` — see [filters.md](filters.md#custom-field-filters)) |
| `search_work_packages` | Search work packages by free-text query matching only subject/ID (not version); optional `project`, `status`, `open_only`, `assignee_me`, and `custom_field_filters` filters — for version-based filtering use `list_work_packages(version=...)` instead. Also resolves the query directly, in parallel, when it is a numeric id or display id (e.g. `PROJ-42`) and not shaped like a date; a match satisfying every other active filter is returned separately as `exact_match`, never merged into `results`/`total`/pagination |
| `get_work_package` | Fetch a detailed work package summary by id or `displayId` reference |
| `get_work_packages` | Fetch multiple work packages by ID in parallel (max 100 IDs per batch) |
| `create_work_package` | Validate and then create a work package; only writes when called again with `confirm=true` |
| `create_subtask` | Validate and then create a child work package below an existing parent; only writes when called again with `confirm=true` |
| `update_work_package` | Validate and then update a work package; only writes when called again with `confirm=true` |
| `bulk_create_work_packages` | Validate and then create multiple work packages in one call; returns per-item results including errors; only writes when called again with `confirm=true` |
| `bulk_update_work_packages` | Validate and then update multiple work packages in one call; returns per-item results including errors; only writes when called again with `confirm=true` |
| `delete_work_package` | Validate and then delete a work package; only deletes when called again with `confirm=true` |
| `add_work_package_comment` | Validate and then add a comment to a work package; `notify=false` by default to avoid change emails; the result never carries change details (`details_omitted` is true); only writes when called again with `confirm=true` |
| `update_work_package_comment` | Validate and then replace the text of an existing comment (by activity id); reports up front when OpenProject would not let the configured user edit it; the result never carries change details (`details_omitted` is true); only writes when called again with `confirm=true` |
| `create_work_package_relation` | Validate and then create a relation between work packages; only writes when called again with `confirm=true` |
| `delete_relation` | Validate and then delete a work package relation; only deletes when called again with `confirm=true` |
| `get_work_package_relations` | Fetch all relations for a work package (blocks, relates to, duplicates, …); each result also carries `queried_perspective`, a caller-relative reading of the relation from `work_package_id`'s own side (`direction`, `effective_type`, and — only for the precedes/follows pair — `predecessor_id`/`successor_id`), alongside the unchanged raw `type`/`from_id`/`to_id` |
| `get_work_package_activities` | Fetch the activity log for a work package, most recent first; the change details of an entry are returned only when `OPENPROJECT_READ_PROJECTS` is `*` and no work package or custom field is hidden, otherwise `details_omitted` is true |
| `list_work_package_reactions` | List emoji reactions across a work package's comment activities |
| `toggle_activity_emoji_reaction` | Toggle an emoji reaction on a work package comment activity (add if absent, remove if present) |
| `list_reminders` | List the current user's active reminders across all work packages |
| `create_work_package_reminder` | Validate and then create a reminder on a work package (one active reminder per work package) |
| `update_reminder` | Validate and then update a reminder's time or note |
| `delete_reminder` | Validate and then delete a reminder; only deletes when called again with `confirm=true` |
| `list_my_open_work_packages` | List the current user's open assigned work packages |
| `list_available_assignees` | List the users and groups OpenProject accepts as assignee, for a work package or (before it exists) for a project |
| `list_work_package_available_relation_candidates` | List work packages that can be the other end of a new relation, optionally by text and relation type |
| `list_work_package_available_watchers` | List the users that can be added as watchers of a work package, paged; needs `OPENPROJECT_ENABLE_EXTENDED_READ` and the right to add watchers |
| `list_work_package_available_projects` | List the projects a work package can be moved to, limited to the read scope, paged; needs `OPENPROJECT_ENABLE_EXTENDED_READ` and the right to edit the work package |
| `list_work_package_watchers` | List watchers on a work package |
| `set_work_package_watcher` | Add or remove a user as a watcher on a work package, based on `watching` |
| `list_work_package_file_links` | List Nextcloud file links attached to a work package (Community Edition) |
| `list_work_package_revisions` | List the repository revisions linked to a work package, limited to projects the read scope covers; empty also when the repository module is off; needs `OPENPROJECT_ENABLE_EXTENDED_READ` |
| `delete_file_link` | Validate and then delete a Nextcloud file link; only deletes when called again with `confirm=true` |

### Bulk writes vs. parallel single calls

`bulk_create_work_packages`/`bulk_update_work_packages` process items strictly
sequentially, one at a time — this is deliberate, not a missing optimization:
each item's outcome is independent (one item's rejection never blocks the
rest of the batch), and items are processed in the order given. Neither
guarantee holds if you instead issue N parallel `create_work_package`/
`update_work_package` calls yourself. Note this is *processing* order, not a
monotonic-ID guarantee, and items cannot reference each other's IDs within
the same batch — every item's payload is built before any item is sent.

**Use `bulk_*` when per-item failure isolation or a single consolidated
result matters** — you get one report covering every item's success/failure
instead of reconciling N independent call results yourself.

**Otherwise, weigh the real per-item request count** (all figures are for
one `confirm=true` call; `confirm=false` previews cost one less), which
differs sharply between create and update and depends on how many optional
fields resolve by name rather than numeric ID:

| Scenario | First item | Later items, same project |
| --- | --- | --- |
| Create, only required fields (`project`/`type`/`subject`) | 3 requests | 2 requests |
| Create, type + version by name, `assignee="me"`, one custom field | `7 + L` requests | `3 + L` requests (often just 3) |
| Update, no optional fields (only the target work package's id) | 3 requests | 3 requests (no batch saving) |
| Update, type + version + sprint by name, one custom field, closing status without explicit remaining time | `12 + L` requests | `6 + L` requests |

`L` is the number of distinct, not-yet-cached `allowedValues` schema hrefs
the batch touches (e.g. a User-typed custom field's candidate list) —
data-dependent, no fixed upper bound. A simpler mix of optional fields costs
less than the table's worked examples — e.g. update with just a type and
version by name, no custom fields or status change, runs closer to `8 + L`
first item / `4 + L` later items. Spreading a batch across multiple projects
loses most of the "later items" saving, since the per-project/per-type/
per-href caches this counts on are scoped to what's already been seen in the
batch.

The two scenarios land so differently because **create batches well, update
doesn't**: same-project/type/version lookups and dereferenced `allowedValues`
schema fields are cached across the whole batch, so item 2+ in a uniform
create batch is cheap. `update` additionally requires one uncached
`GET` of the current record per item (needed for its `lockVersion`), and its
`allowedValues` hrefs are frequently work-package-specific rather than
project-specific, so they rarely hit the batch cache. Request count isn't the
same as wall-clock time — sequential processing can be slower in practice
than N genuinely parallel single calls, even at a lower total request count.
In practice, prefer `bulk_update_work_packages` for its consolidated result
and failure-isolation guarantee, not as a request-count optimization — the
saving over N individual `update_work_package` calls is real but modest.

## Attachments

| Tool | Description |
| --- | --- |
| `list_work_package_attachments` | List attachments on a work package |
| `get_attachment` | Fetch a single work-package attachment by id |
| `get_attachment_content` | Read an attachment's content: images come back as images the model can see, text-like files as text, anything else as metadata explaining why it wasn't inlined |
| `create_work_package_attachment` | Validate and then upload an attachment to a work package; only writes when called again with `confirm=true` |
| `delete_attachment` | Validate and then delete an attachment; only deletes when called again with `confirm=true` |
| `list_container_attachments` | List attachments on a wiki page, forum post, meeting or comment (`container_type` + `container_id`) |
| `create_container_attachment` | Validate and then upload an attachment to a wiki page, forum post, meeting or comment; only writes when called again with `confirm=true` |

`OPENPROJECT_ATTACHMENT_ROOT` must be set to an absolute directory for local
uploads to work at all — `create_work_package_attachment` and
`create_container_attachment` aren't even registered otherwise, no
working-directory fallback. Once set, files outside it — and
credential/config files such as `.mcp.json`, `.env`, or private keys even inside
it — are refused, so a tool call cannot exfiltrate local secrets.

`create_container_attachment` is registered when the root is configured and
any of project, meeting or work-package writes is enabled, with usable project
scope. `create_work_package_attachment` still requires work-package writes.

`list_container_attachments` belongs to the work-package read group, so
`OPENPROJECT_ENABLE_WORK_PACKAGE_READ` must be enabled even to list wiki,
post or meeting attachments.

`list_container_attachments`/`create_container_attachment` check the
container's own scope flag (project for wiki pages and posts, meeting for
meetings, work package for comments) and its project against the allowlists.
`get_attachment`, `get_attachment_content` and `delete_attachment` still accept
work package attachments only.

### Reading attachment content

`get_attachment_content` (and `list_work_package_attachments` with
`include_images=true`) return a JSON metadata block describing the outcome,
followed by a native MCP content block only when content was actually inlined.
`outcome` is one of:

| Outcome | Meaning | Content block |
| --- | --- | --- |
| outcome `image` | PNG, JPEG, GIF or WebP within the byte limit | `ImageContent` |
| outcome `text` | `text/*`, JSON or XML; `truncated=true` when cut at the limit | `TextContent`, wrapped in `<user-content>` |
| outcome `too_large` | An image over the byte limit — never returned partially | none |
| outcome `not_inline_supported` | A type no MCP client can display; the bytes are not returned at all | none |

The byte limit is `OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES` (5 MB by default,
25 MB ceiling), enforced while streaming so an oversized file is never fully
downloaded. `get_attachment_content`'s `max_bytes` argument may only lower it.
With `include_images=true` the same value is the aggregate budget for the whole
call, spent in listing order — every attachment that was not inlined is listed
in `images` with its reason, never silently dropped. The type decision uses the
served response's `Content-Type`; for text-like types only, it falls back to the
stored metadata's type when the server answers with a generic
`application/octet-stream` (which OpenProject does for JSON). Images are decided
on the served header alone. The `content_type` **reported** for
`not_inline_supported` is the stored type instead, which names the file where
the served header only repeats that it was not inlineable; `size_bytes` (the
size of the returned block, not the stored size) is null when
`file_size_bytes` is hidden by `OPENPROJECT_HIDE_ATTACHMENT_FIELDS`. Nothing is
written to disk, and the content is read from OpenProject's own
`/attachments/{id}/content` endpoint rather than from `download_url`, which
needs credentials the MCP client does not carry.

## Versions

| Tool | Description |
| --- | --- |
| `list_versions` | List versions globally or scoped to a specific project, with an optional name filter |
| `get_version` | Fetch a compact version summary by id |
| `list_version_projects` | List the projects a version is shared with, limited to the read scope; needs `OPENPROJECT_ENABLE_EXTENDED_READ` |
| `create_version` | Validate and then create a version; only writes when called again with `confirm=true` |
| `update_version` | Validate and then update a version; only writes when called again with `confirm=true` |
| `delete_version` | Validate and then delete a version; only deletes when called again with `confirm=true` |

## Boards

| Tool | Description |
| --- | --- |
| `list_boards` | List saved OpenProject boards/queries globally or scoped to a project |
| `get_board` | Fetch a saved OpenProject board/query by id |
| `create_board` | Validate and then create a saved OpenProject board/query; only writes when called again with `confirm=true` |
| `update_board` | Validate and then update a saved OpenProject board/query; only writes when called again with `confirm=true` |
| `delete_board` | Validate and then delete a saved OpenProject board/query; only deletes when called again with `confirm=true` |

On `create_board` and `update_board`, `sort_by` takes criteria as `field:direction` or `field-direction`, the same
form as `list_work_packages`; the direction defaults to `asc`. OpenProject reports an unknown field as a validation
error in the preview.

## Meetings

Meetings has its own dedicated `OPENPROJECT_ENABLE_MEETING_READ`/`_WRITE` scope
(default: both `true`, same as Boards), shared by all five sub-resources below.
Requires OpenProject 17.4+ for Meetings and Recurring Meetings. Agenda Items and
Sections are both split the same way: the meeting-nested list routes (`GET
meetings/{id}/agenda_items`, `GET meetings/{id}/sections`) work from 17.4+, but
every other operation (get/create/update/delete, all addressed via a top-level
`meeting_agenda_items`/`meeting_sections` route) does not exist server-side
before 17.6. `list_work_package_meeting_agenda_items` needs its own, later floor
of 17.7+ (a third route, `GET work_packages/{id}/meeting_agenda_items`, added
later still). Meeting Outcomes require 17.6+ throughout.

| Tool | Description |
| --- | --- |
| `list_meetings` | List meetings globally or scoped to a project (requires OpenProject 17.4+); optional `title` substring filter (17.9+) |
| `get_meeting` | Fetch a single meeting by id (requires OpenProject 17.4+) |
| `create_meeting` | Validate and then create a meeting in a project; only writes when called again with `confirm=true`; `state` and `notify` cannot be set on create (set them with `update_meeting`); `participant_user_refs` becomes the exact participant list, so name yourself to take part (requires OpenProject 17.4+) |
| `update_meeting` | Validate and then update a meeting; only writes when called again with `confirm=true`; `participant_user_refs` is rejected, change participants in OpenProject (requires OpenProject 17.4+) |
| `delete_meeting` | Validate and then delete a meeting; only deletes when called again with `confirm=true`; rejects the template meeting of a recurring series (stop it with `end_recurring_meeting`, 17.8+, or delete it with `delete_recurring_meeting`) (requires OpenProject 17.4+) |
| `list_meeting_agenda_items` | List a meeting's agenda items (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.4+ — uses the meeting-nested `GET meetings/{id}/agenda_items` route) |
| `list_work_package_meeting_agenda_items` | List meeting agenda items linked to a work package; under a restricted `OPENPROJECT_READ_PROJECTS`, only items of meetings in projects it covers (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.7+ — the `GET work_packages/{id}/meeting_agenda_items` route does not exist server-side before 17.7) |
| `get_meeting_agenda_item` | Fetch a single meeting agenda item by id (requires OpenProject 17.6+ — uses the top-level `meeting_agenda_items/{id}` route, which does not exist before 17.6) |
| `create_meeting_agenda_item` | Validate and then create a meeting agenda item, optionally linked to a work package or a section; only writes when called again with `confirm=true` (requires OpenProject 17.6+, for the same reason as `get_meeting_agenda_item` above) |
| `update_meeting_agenda_item` | Validate and then update a meeting agenda item; only writes when called again with `confirm=true` (requires OpenProject 17.6+, for the same reason as `get_meeting_agenda_item` above) |
| `delete_meeting_agenda_item` | Validate and then delete a meeting agenda item; only deletes when called again with `confirm=true` (requires OpenProject 17.6+, for the same reason as `get_meeting_agenda_item` above) |
| `list_meeting_outcomes` | List an agenda item's outcomes (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.6+) |
| `get_meeting_outcome` | Fetch a single meeting outcome by id (requires OpenProject 17.6+) |
| `create_meeting_outcome` | Validate and then create a meeting outcome on an agenda item; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `update_meeting_outcome` | Validate and then update a meeting outcome; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `delete_meeting_outcome` | Validate and then delete a meeting outcome; only deletes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `list_meeting_sections` | List a meeting's sections (unpaginated server-side; `offset`/`limit` applied client-side) (requires OpenProject 17.4+) |
| `get_meeting_section` | Fetch a single meeting section by id (requires OpenProject 17.6+) |
| `create_meeting_section` | Validate and then create a meeting section; `backlog` may only be set here, not via `update_meeting_section`; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `update_meeting_section` | Validate and then update a meeting section's title/position; only writes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `delete_meeting_section` | Validate and then delete a meeting section; only deletes when called again with `confirm=true` (requires OpenProject 17.6+) |
| `list_recurring_meetings` | List recurring meeting series globally or scoped to a project (requires OpenProject 17.4+) |
| `get_recurring_meeting` | Fetch a single recurring meeting series by id (requires OpenProject 17.4+) |
| `create_recurring_meeting` | Validate and then create a recurring meeting series in a project; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `update_recurring_meeting` | Validate and then update a recurring meeting series; only writes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `delete_recurring_meeting` | Validate and then delete a recurring meeting series; only deletes when called again with `confirm=true` (requires OpenProject 17.4+) |
| `end_recurring_meeting` | Validate and then end a recurring meeting series, keeping it and its past occurrences; only writes when called again with `confirm=true` (requires OpenProject 17.8+) |
| `list_recurring_meeting_occurrences` | List a recurring meeting's virtual occurrences by `filter` (`upcoming`/`past`/`cancelled`/`open`); no offset/pagination envelope (requires OpenProject 17.4+) |
| `init_recurring_meeting_occurrence` | Validate and then materialize a virtual occurrence into a real, standalone meeting (addressed by `start_time`, not an id); only writes when called again with `confirm=true`; result is a full meeting (requires OpenProject 17.4+) |
| `cancel_recurring_meeting_occurrence` | Validate and then cancel a not-yet-materialized occurrence (addressed by `start_time`); only writes when called again with `confirm=true` (requires OpenProject 17.4+) |

> **Note:** `cancel_recurring_meeting_occurrence` on an occurrence that has NOT
> yet been materialized creates a cancelled meeting server-side to record the
> cancellation. This is a data-creation side effect behind what reads like a
> pure "cancel" call. `init_recurring_meeting_occurrence` restores it, and a later
> schedule change of the series other than the time of day can delete it. The
> response does not report that new meeting's id (OpenProject returns 204
> with no body); use `list_meetings` or `list_recurring_meeting_occurrences`
> with `filter="cancelled"` to find it afterward if needed. If the occurrence
> is already materialized and not itself cancelled, the call fails instead —
> use `delete_meeting` on the materialized meeting directly.
>
> **Note:** On OpenProject 17.4 and 17.5, `init_recurring_meeting_occurrence`
> on an occurrence that already exists fails with a server error instead of
> returning it, and writes nothing; 17.6 and later return the existing
> occurrence.
>
> **Note:** Meeting Agenda Items, Meeting Sections, and Meeting Outcomes are
> addressed by their own bare id (not nested under their parent's id) —
> OpenProject's global routes for these resources already resolve their
> parent project server-side via an authoritative join, so this MCP's own
> project-allowlist check runs against that resolved project on every
> `get`/`update`/`delete` call.

## Time entries

| Tool | Description |
| --- | --- |
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
| --- | --- |
| `get_cost_entry` | Fetch a single cost entry by id |
| `list_work_package_cost_entries` | List all cost entries recorded against a work package |
| `get_work_package_costs_by_type` | Get a work package's costs aggregated by cost type |
| `get_cost_type` | Fetch a cost type by id |

> **Note:** the Costs module is entirely read-only in OpenProject's API —
> there is no create/update/delete endpoint for cost entries or cost types,
> and no collection `GET` for cost types (only single-item lookup by id).

## GitHub / GitLab work-package linkage

| Tool | Description |
| --- | --- |
| `get_github_pull_request` | Fetch a single GitHub pull request by its own id |
| `list_work_package_github_pull_requests` | List all GitHub pull requests linked to a work package |
| `list_work_package_gitlab_issues` | List all GitLab issues linked to a work package |
| `list_work_package_gitlab_merge_requests` | List all GitLab merge requests linked to a work package |

> **Note:** all three resources are read-only mirror rows synced by
> OpenProject's own GitHub App / GitLab webhook integration — never creatable
> via this API. An empty result can mean either "nothing linked" or "the
> integration isn't configured on this instance"; OpenProject's own API
> doesn't distinguish these cases. No `get_gitlab_issue`/
> `get_gitlab_merge_request` single-item tools exist because no such endpoint
> exists upstream for either resource — only `github_pull_requests` has a
> global single-item route.

## Grids

| Tool | Description |
| --- | --- |
| `list_grids` | List dashboard grids globally or scoped to a project or user |
| `get_grid` | Fetch a single grid by id |
| `create_grid` | Validate and then create a dashboard grid for the scope `/my/page`, `/projects/<identifier>` or `/projects/<identifier>/boards` (after the instance's root path on a subpath install); any other scope is rejected before a request. Only writes when called again with `confirm=true` |
| `update_grid` | Validate and then update a dashboard grid (name, row/column count); only writes when called again with `confirm=true` |
| `delete_grid` | Validate and then delete a dashboard grid; only deletes when called again with `confirm=true` |

## User preferences

| Tool | Description |
| --- | --- |
| `get_my_preferences` | Return the current user's preferences (timezone, comment sorting, popups, …); language is a user attribute, see `update_user` |
| `update_my_preferences` | Prepare or update the current user's preferences; only writes when called again with `confirm=true` |

## Text rendering

| Tool | Description |
| --- | --- |
| `render_text` | Render markdown or plain text to HTML using the OpenProject API; refused unless `OPENPROJECT_READ_PROJECTS` is `*` and no field of work packages, projects, versions, documents, meetings, posts, users, groups, principals or views is hidden, because OpenProject expands macros such as `#123` or `version#4` into the name or display id of any record |

## Help texts

| Tool | Description |
| --- | --- |
| `list_help_texts` | List all help texts configured for work-package and project attributes |
| `get_help_text` | Fetch a single help text by id |

## Working days

| Tool | Description |
| --- | --- |
| `list_working_days` | List the working-day configuration (Mon–Sun) for a given year or the current year |
| `list_non_working_days` | List non-working days (public holidays / closures) for a given year or the current year |

## Budgets

| Tool | Description |
| --- | --- |
| `list_project_budgets` | List the cost budgets of a project; needs the Budgets module and `view_budgets` on the instance (otherwise permission denied) |

## Custom options

| Tool | Description |
| --- | --- |
| `get_custom_option` | Fetch the label/value of a single custom field option by id |

## Relations (global)

| Tool | Description |
| --- | --- |
| `list_relations` | List all relations across the instance, optionally filtered by type |
| `update_relation` | Prepare or update the type or description of a relation; only writes when called again with `confirm=true` |

## Errors

Every tool failure carries a stable, machine-readable category as a leading
`[category]` prefix on the error message, so an agent can branch on the failure
type instead of parsing free text. The categories are:

| Category | Meaning |
| --- | --- |
| `[VALIDATION_FAILED]` | An input was rejected before the request (fix the arguments and retry) |
| `[AUTHENTICATION_FAILED]` | Authentication failed (check the API token) |
| `[PROJECT_SCOPE_DENIED]` | The target project is outside `OPENPROJECT_READ_PROJECTS`/`OPENPROJECT_WRITE_PROJECTS` |
| `[CAPABILITY_DISABLED]` | This category of operation is turned off for this deployment (an `OPENPROJECT_ENABLE_*` flag, or a required setting like `OPENPROJECT_ATTACHMENT_ROOT`, is not set) |
| `[OPENPROJECT_PERMISSION_DENIED]` | OpenProject itself rejected the request with 403 (a permissions problem on the OpenProject side, not this server's configuration) |
| `[RESOURCE_NOT_FOUND]` | The resource does not exist (or the feature needs a newer OpenProject) |
| `[CONFLICT]` | The request conflicts with the resource's current state (e.g. an optimistic-locking version mismatch) |
| `[RATE_LIMITED]` | OpenProject is rate-limiting this client (safe to retry after a delay) |
| `[NETWORK_ERROR]` | OpenProject could not be reached (transient — safe to retry) |
| `[OPENPROJECT_UNAVAILABLE]` | OpenProject returned an unexpected failure |
| `[CONFIGURATION_ERROR]` | OpenProject links its projects under a different path than `OPENPROJECT_BASE_URL` implies (set it to the path OpenProject itself uses) |
| `[INTERNAL_ERROR]` | An unexpected error in this server itself (not OpenProject) — the underlying detail is logged locally, never returned to the caller |

Successful write previews are not errors — they return a structured result with
`ready`, `state` (`"rejected"` | `"invalid"` | `"preview"` | `"confirmed"`),
`validation_errors`, and a human-readable `message`.

### Validation errors

Each entry of `validation_errors` is keyed by the attribute OpenProject rejected and holds a `message` and
`error_codes`. The message is written in the language of the account the token belongs to; `Accept-Language` does not
change it. `error_codes` are OpenProject's error classes and do not depend on the language:

| Code | Meaning |
| --- | --- |
| `PropertyConstraintViolation` | A value breaks a constraint: blank, too long, taken, out of range. The reason is only in the message |
| `PropertyIsReadOnly` | The attribute cannot be written |
| `PropertyFormatError` | The value has the wrong format |

A field with several violated constraints lists each distinct code once, in order, and its messages are joined with
`; `. An entry without a code has an empty list. The code is coarse: use the attribute and the class to branch, the
message to explain.

A request OpenProject rejects with 422 (a malformed value, a refused commit) starts its error text with the same
information as a header: `PropertyFormatError (dueDate): <message>`; several errors give
`PropertyConstraintViolation (identifier), PropertyIsReadOnly (id): <message>; <message>`. Read only that header.
Without an error class in the response the text is OpenProject's message, with any nested messages in parentheses.

## See also

- [Documentation hub](README.md) — full documentation index
- [Work package filters](filters.md) — filter keys and operators for
`list_work_packages` / `search_work_packages`
- [Field hiding](field-hiding.md) — full list of entities supported by `OPENPROJECT_HIDE_<ENTITY>_FIELDS`
- [Configuration](configuration.md) — the full environment variable reference
- [Troubleshooting](troubleshooting.md) — common tool/setup issues
