# Tool reference

All tools exposed by the OpenProject MCP server.

All mutating tools follow the same guarded write pattern by default:

- Call the tool without `confirm=true` to get a preview or validation result.
- Call it again with `confirm=true` to execute the write or delete.

If `OPENPROJECT_AUTO_CONFIRM_WRITE` is explicitly enabled, the preview step is skipped for all writes, including deletes.

All list tools are bounded and paginated. They return compact summaries — not raw OpenProject HAL payloads.

---

## Projects

| Tool | Description |
|---|---|
| `list_projects` | List visible projects with an optional name/identifier filter |
| `get_project` | Fetch a compact project summary by id or identifier |
| `get_project_admin_context` | Return project admin metadata such as lifecycle statuses, parent project options, and writable fields |
| `get_project_configuration` | Return project-scoped configuration such as internal comment support |
| `create_project` | Validate and then create a project; only writes when called again with `confirm=true` |
| `copy_project` | Validate and then copy an existing project into a new project; only starts the copy job when called again with `confirm=true` |
| `get_job_status` | Fetch the current status of a background job such as project copy |
| `update_project` | Validate and then update a project; only writes when called again with `confirm=true` |
| `delete_project` | Validate and then delete a project; only deletes when called again with `confirm=true` |
| `get_instance_configuration` | Return instance-level OpenProject configuration and active feature flags |

## Memberships

| Tool | Description |
|---|---|
| `list_roles` | List OpenProject roles visible to the current user |
| `list_principals` | List users and groups that can be used for memberships |
| `list_project_memberships` | List memberships for a project, including principals and role names |
| `get_membership` | Fetch a compact membership summary by id |
| `create_membership` | Validate and then create a project membership; only writes when called again with `confirm=true` |
| `update_membership` | Validate and then update a project membership; only writes when called again with `confirm=true` |
| `delete_membership` | Validate and then delete a project membership; only deletes when called again with `confirm=true` |
| `get_my_project_access` | Return the current user's project membership and inferred access hints based on roles and HATEOAS links |

## Users

| Tool | Description |
|---|---|
| `get_current_user` | Return the currently authenticated user's profile |
| `list_users` | List visible OpenProject users with an optional search filter |
| `get_user` | Fetch a compact user profile by id |
| `create_user` | Validate and then create a user account; only writes when called again with `confirm=true` |
| `update_user` | Validate and then update a user account; only writes when called again with `confirm=true` |
| `delete_user` | Validate and then delete a user account; only deletes when called again with `confirm=true` |
| `lock_user` | Lock a user account to prevent login |
| `unlock_user` | Unlock a previously locked user account |

## Groups

| Tool | Description |
|---|---|
| `list_groups` | List visible OpenProject groups with an optional search filter |
| `get_group` | Fetch a compact group profile by id |
| `create_group` | Validate and then create a group; only writes when called again with `confirm=true` |
| `update_group` | Validate and then update a group; only writes when called again with `confirm=true` |
| `delete_group` | Validate and then delete a group; only deletes when called again with `confirm=true` |

## Notifications

| Tool | Description |
|---|---|
| `list_notifications` | List the current user's unread notifications |
| `mark_notification_read` | Mark a single notification as read |
| `mark_all_notifications_read` | Mark all notifications as read |

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
| `list_views` | List saved OpenProject views, optionally filtered by project or view subtype |
| `get_view` | Fetch a single OpenProject view by id |

## Documents

| Tool | Description |
|---|---|
| `list_documents` | List documents globally or filtered to a specific project |
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

> **Note:** OpenProject API v3 does not provide a collection endpoint for wiki pages
> (`GET /api/v3/projects/{id}/wiki_pages` is not implemented). `list_wiki_pages` has
> therefore been removed. Individual pages can be fetched by id via `get_wiki_page`.

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
| `list_work_packages` | List work packages with structured filters such as `project`, `type`, `version`, and `has_description` |
| `search_work_packages` | Search work packages by free-text query; optional `project`, `status`, `open_only`, and `assignee_me` filters |
| `get_work_package` | Fetch a detailed work package summary by id or `displayId` reference |
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
| `list_my_open_work_packages` | List the current user's open assigned work packages |
| `list_work_package_watchers` | List watchers on a work package |
| `add_work_package_watcher` | Add a user as a watcher on a work package |
| `remove_work_package_watcher` | Remove a user from the watchers of a work package |
| `list_work_package_file_links` | List Nextcloud file links attached to a work package (Community Edition) |
| `delete_file_link` | Validate and then delete a Nextcloud file link; only deletes when called again with `confirm=true` |

## Attachments

| Tool | Description |
|---|---|
| `list_work_package_attachments` | List attachments on a work package |
| `get_attachment` | Fetch a single work-package attachment by id |
| `create_work_package_attachment` | Validate and then upload an attachment to a work package; only writes when called again with `confirm=true` |
| `delete_attachment` | Validate and then delete an attachment; only deletes when called again with `confirm=true` |

## Versions

| Tool | Description |
|---|---|
| `list_versions` | List versions globally or scoped to a specific project |
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

## Time entries

| Tool | Description |
|---|---|
| `list_time_entry_activities` | List available time entry activities |
| `list_time_entries` | List time entries with optional project, work package, user, and date filters |
| `get_time_entry` | Fetch a single time entry by id |
| `create_time_entry` | Validate and then create a time entry; only writes when called again with `confirm=true` |
| `update_time_entry` | Validate and then update a time entry; only writes when called again with `confirm=true` |
| `delete_time_entry` | Validate and then delete a time entry; only deletes when called again with `confirm=true` |

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
