# Features by version

The capabilities of `openproject-ce-mcp` and the release that introduced
each one. It lists features only; fixes, security changes and behaviour changes
are in the [changelog](../CHANGELOG.md), the tools themselves in the
[tool reference](tools.md). A feature that a later release widened is listed
once, under the release that introduced it, and the later widening has its own
row.

## Setup and clients

| Since | Feature |
| --- | --- |
| 0.1.0 | Interactive setup that detects Claude Code, Claude Desktop, Codex, Cursor and VS Code/Copilot and registers or removes the server in their configurations ([clients](clients.md)). |
| 0.2.0 | PyPI distribution, installable with `pip`, `pipx` or `uv tool install` ([installation](installation.md)). |
| 0.2.0 | `openproject-ce-mcp configure` registers the server with detected clients ([configuration](configuration.md)); top-level CLI with `--help` and `--version`. |
| 0.2.1 | Setup asks independently about [global and project-scoped](clients.md#global-vs-project-scoped) registration, keeps existing values field by field, and gives client-specific restart instructions. |
| 0.2.1 | `configure --uninstall` also removes project-local registrations in the current directory. |
| 0.3.0 | Setup has quick, advanced and non-interactive [modes](configuration.md#wizard-modes), a live connection test and a final configuration preview. |
| 0.3.0 | [`doctor`](troubleshooting.md#quick-diagnosis-doctor) diagnoses configuration and connectivity end to end. |
| 0.4.3 | Installable with [Homebrew](installation.md#homebrew-macos) (`brew tap jtauschl/tap`). |
| 0.4.3 | Listed in the official MCP Registry as `io.github.jtauschl/openproject-ce-mcp`. |

## Safety and access control

| Since | Feature |
| --- | --- |
| 0.1.0 | Read, write and administrative capabilities have independent [feature gates](configuration.md#tool-groups). |
| 0.1.0 | Project allowlists match identifiers, names, numeric ids and glob patterns case-insensitively ([project scope](configuration.md#project-scope)). |
| 0.1.0 | Writes and deletes use a preview-and-confirm flow ([tool reference](tools.md)); OpenProject role permissions stay the final authority. |
| 0.1.0 | Attachment uploads are confined to `OPENPROJECT_ATTACHMENT_ROOT` ([attachments](tools.md#attachments)). |
| 0.1.0 | Field-hiding settings apply to reads and writes ([field hiding](field-hiding.md)). |
| 0.2.3 | The server instructions explain the Community Edition limits to the connected agent. |
| 0.3.0 | Transient HTTP failures are retried with configurable exponential backoff ([network and runtime](configuration.md#network--runtime)). |
| 0.4.3 | Every tool declares MCP annotations (read-only, destructive, idempotent, open-world; [tool reference](tools.md)). |

## Work packages

| Since | Feature |
| --- | --- |
| 0.1.0 | Structured and free-text search, subtasks, comments, relations, activity history, bulk writes, watchers, attachments and Nextcloud file links ([work packages](tools.md#work-packages)). |
| 0.1.0 | Project-prefixed identifiers such as `PROJ-123` are accepted by single-item, relation and parent operations. |
| 0.2.3 | `parent` nests, re-parents or detaches a work package. |
| 0.3.0 | `get_work_packages` reads up to 100 work packages in parallel with per-item errors and field selection. |
| 0.3.0 | Lists sort, group and filter by assignee, status, priority and created, updated or due dates ([filters](filters.md)). |
| 0.3.0 | Richer scheduling, time-tracking, metadata, hierarchy and progress fields on reads and writes. |
| 0.3.0 | `none` clears the nullable assignee, responsible, category, project phase, version and sprint links on single and bulk updates. |
| 0.3.0 | Sprint reads and writable sprint links on Backlogs-enabled instances. |
| 0.3.8 | `search_work_packages` resolves numeric and display ids directly and returns them as `exact_match`. |
| 0.4.0 | `include_sums`, `overdue_only`, `due_within_days` and `custom_field_filters` on the list tools ([custom-field filters](filters.md#custom-field-filters)); custom field values on every work package read. |
| 0.4.0 | `bulk_update_work_packages` supports `sprint`; the bulk tools accept `parent` and `select` ([bulk writes](tools.md#bulk-writes-vs-parallel-single-calls)). |
| 0.4.0 | `target_versions` (OpenProject 17.7+) on creates and updates; `has_project_attributes` on results. |
| 0.4.0 | `list_work_package_relations` reports `queried_perspective`, the relation read from the caller's side. |
| 0.4.5 | `parent_target` names the work package a given `parent` resolved to, before and after `confirm`. |
| 0.4.6 | `none` clears `start_date` and `due_date` on `update_work_package` and `bulk_update_work_packages`. |

## Projects and versions

| Since | Feature |
| --- | --- |
| 0.1.0 | Read and write tools for [projects](tools.md#projects), [versions](tools.md#versions), [memberships](tools.md#memberships), [users](tools.md#users) and [groups](tools.md#groups). |
| 0.3.0 | `list_versions` supports text search; project references fall back to an exact display-name match. |
| 0.4.0 | `get_project` returns the ancestor chain. |
| 0.4.5 | `list_projects` takes `sort_by`; project custom fields are read, written, filtered and sorted. |
| 0.4.5 | `parent_target` on `create_project`, `update_project` and `copy_project`; `get_project_phase` returns the `active` flag. |

## Time tracking

| Since | Feature |
| --- | --- |
| 0.1.0 | [Time entry](tools.md#time-entries) tools. |
| 0.3.5 | `create_time_entry_until` and `update_time_entry_until` take a start and an end time and calculate the duration. |
| 0.4.0 | Time entry lists can include total hours. |

## Attachments

| Since | Feature |
| --- | --- |
| 0.1.0 | Attachment upload and listing ([attachments](tools.md#attachments)). |
| 0.4.0 | `get_attachment_content` returns bounded image or text content with a skip reason for unsupported or oversized files. |
| 0.4.0 | `list_work_package_attachments` inlines images under one byte budget (`include_images`), paginates, and can include the total file size. |

## Queries, boards and views

| Since | Feature |
| --- | --- |
| 0.1.0 | [Boards](tools.md#boards), grids and [query metadata](tools.md#query-metadata). |
| 0.4.0 | `execute_query` runs saved OpenProject queries ([query metadata](tools.md#query-metadata)). |
| 0.4.0 | `search` on `list_documents`, `list_views` and `list_sprints`. |

## Further domains

| Since | Feature |
| --- | --- |
| 0.1.0 | News, notifications, preferences, documents, wiki pages, categories, instance configuration, help texts, working days, custom options, actions, capabilities and text rendering. |
| 0.4.0 | Wiki-link tools for work packages (listing from OpenProject 17.5, deleting from 17.6, creating from 17.7; [wiki](tools.md#wiki)). |
| 0.4.0 | [Storage tools](tools.md#storages) for external storages and project-storage connections. |
| 0.4.0 | [Meetings](tools.md#meetings): meetings, agenda items, sections, outcomes and recurring meetings. |
| 0.4.0 | Costs: cost entries, cost types and work package costs by type. |
| 0.4.0 | Read tools for GitHub and GitLab integration links, [forum](tools.md#forums) posts and Backlogs buckets. |
| 0.4.0 | Per-user [schedule tools](tools.md#user-schedule-overrides) for non-working times and working hours. |

## Result shaping

| Since | Feature |
| --- | --- |
| 0.4.0 | Per-call text limits on documents, news, wiki pages and meeting notes ([context efficiency](context-efficiency.md#response-size)). |
| 0.4.0 | Response-field selection (`select`; [context efficiency](context-efficiency.md#response-size)) on `get_work_package`, `list_actions`, `list_capabilities`, `list_time_entries`, notification, meeting and attachment lists. |
