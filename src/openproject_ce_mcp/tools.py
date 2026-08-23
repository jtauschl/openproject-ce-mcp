from __future__ import annotations

import datetime
import functools
import re
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from . import (
    tools_misc,  # noqa: F401 -- @register_tool side effect
    tools_query,  # noqa: F401 -- @register_tool side effect
    tools_query_schema,  # noqa: F401 -- @register_tool side effect
    tools_user_schedule,  # noqa: F401 -- @register_tool side effect
)
from .client import (
    BATCH_READ_MAX_IDS,
    CLEAR,
    CLEAR_PARENT,
    CLEAR_VERSION,
)
from .config import Settings
from .models import (
    ActivityListResult,
    ActivitySummary,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BatchWorkPackageReadResult,
    BulkWorkPackageWriteResult,
    CategoryListResult,
    CategorySummary,
    CostEntryListResult,
    CostEntrySummary,
    CostTypeSummary,
    EmojiReactionListResult,
    EmojiReactionSummary,
    EmojiReactionWriteResult,
    FileLinkListResult,
    FileLinkSummary,
    FileLinkWriteResult,
    GithubPullRequestListResult,
    GithubPullRequestSummary,
    GitlabIssueListResult,
    GitlabMergeRequestListResult,
    GridListResult,
    GridSummary,
    GridWriteResult,
    PriorityListResult,
    PrioritySummary,
    RelationListResult,
    RelationSummary,
    RelationUpdateResult,
    RelationWriteResult,
    StatusListResult,
    StatusSummary,
    TimeEntryActivityListResult,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
    TypeListResult,
    TypeSummary,
    WatcherListResult,
    WatcherSummary,
    WatcherWriteResult,
    WorkPackageCostsByTypeResult,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)
from .tools_admin import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports create_user/update_user/delete_user/set_user_locked/create_group/update_group/delete_group from here
    create_group,
    create_storage,
    create_user,
    delete_group,
    delete_storage,
    delete_user,
    get_group,
    get_storage,
    get_user,
    list_groups,
    list_principals,
    list_storages,
    list_users,
    set_user_locked,
    update_group,
    update_storage,
    update_user,
)
from .tools_boards import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports these from here
    create_board,
    delete_board,
    get_board,
    list_boards,
    update_board,
)
from .tools_documents import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports create_news/delete_news/get_document/get_news/get_wiki_page/list_documents/list_news/update_document/update_news from here
    create_news,
    create_work_package_wiki_link,
    delete_news,
    delete_work_package_wiki_link,
    get_document,
    get_news,
    get_post,
    get_wiki_page,
    list_documents,
    list_news,
    list_work_package_wiki_links,
    update_document,
    update_news,
)
from .tools_meetings import (  # noqa: F401 -- @register_tool side effect; re-exported, test_trimming.py imports these three from here
    list_meeting_agenda_items,
    list_meeting_outcomes,
    list_work_package_meeting_agenda_items,
)
from .tools_memberships import (  # noqa: F401 -- @register_tool side effect; re-exported, existing tests import list_actions/list_capabilities/list_roles/list_project_memberships from here
    create_membership,
    delete_membership,
    get_current_user,
    get_membership,
    list_actions,
    list_capabilities,
    list_project_memberships,
    list_roles,
    update_membership,
)
from .tools_personal import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports list_notifications/mark_notifications_read from here
    get_my_preferences,
    list_notifications,
    mark_notifications_read,
    update_my_preferences,
)
from .tools_projects import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py/test_work_package_tools.py import several of these from here
    copy_project,
    create_project,
    delete_project,
    get_instance_configuration,
    get_job_status,
    get_my_project_access,
    get_project,
    get_project_admin_context,
    get_project_configuration,
    get_project_phase,
    get_project_phase_definition,
    get_project_storage,
    get_project_work_package_context,
    list_project_phase_definitions,
    list_project_storages,
    list_projects,
    set_project_favorite,
    update_project,
)
from .tools_reminders import (  # noqa: F401 -- @register_tool side effect; re-exported, several tests import these from here
    create_work_package_reminder,
    delete_reminder,
    list_reminders,
    update_reminder,
)
from .tools_runtime import (
    _client_from_context,
    _run_tool,
    register_selected_tools,
    register_tool,
)
from .tools_sprints import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports list_sprints/get_sprint from here
    get_backlog_bucket,
    get_sprint,
    list_backlog_buckets,
    list_sprints,
)
from .tools_validation import (
    _clearable,
    _clearable_duration,
    _clearable_ref,
    _require_at_least_one,
    _validate_custom_field_filters,
    _validate_group_by,
    _validate_limit,
    _validate_offset,
    _validate_optional_choice,
    _validate_optional_custom_fields,
    _validate_optional_date,
    _validate_optional_date_range,
    _validate_optional_datetime,
    _validate_optional_duration,
    _validate_optional_non_negative_int,
    _validate_optional_percentage_done,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_optional_user_or_principal_ref,
    _validate_optional_user_ref,
    _validate_optional_version,
    _validate_optional_work_package_ref,
    _validate_positive_int,
    _validate_project_ref,
    _validate_relation_type,
    _validate_required_date,
    _validate_required_datetime,
    _validate_required_duration,
    _validate_required_query,
    _validate_required_text,
    _validate_select,
    _validate_sort_by,
    _validate_work_package_ref,
)
from .tools_versions import (  # noqa: F401 -- @register_tool side effect; re-exported, several tests import these from here
    create_version,
    delete_version,
    get_version,
    list_versions,
    update_version,
)
from .tools_views import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports list_views/get_view from here
    get_view,
    list_views,
)

# ── Tool classification ──────────────────────────────────────────────────────
#
# Single source of truth for which tool belongs to which scope. Registration
# follows exactly the scopes each tool's client method actually enforces at
# runtime (verified against client.py, not guessed) — several tools that
# would otherwise be always registered regardless of any flag (e.g.
# get_current_user, list_notifications) correctly disappear when their real
# scope is disabled, instead of staying visible and failing only when called.
#
# Tool visibility is controlled by individual read/write boolean env vars
# (OPENPROJECT_ENABLE_<SCOPE>_READ / _WRITE), one pair per scope.
# Settings.from_env() validates (config.py's WRITE_GROUP_REQUIREMENTS +
# tool_exposure_violations()) that every scope's write flag being true
# requires its paired read flag to also be true — for every scope, not just
# "personal" — and refuses to start the server otherwise. That guarantee only
# holds for configs loaded through from_env(); a Settings instance built
# directly (e.g. a test fixture) can still set write=True/read=False without
# tripping it. Given a from_env()-loaded config, though, a scope's write flag
# being on already implies its read flag is too, so the generic write-scope
# loop below (WRITE_TOOLS_BY_SCOPE) only checks the write flag.
#
# "personal" is still handled separately rather than folded into
# WRITE_TOOLS_BY_SCOPE: it isn't project-scoped (see _PROJECT_SCOPED_WRITE_SCOPES
# below) and its mutation tools sit alongside a read surface
# (get_my_preferences, list_notifications) that has no write-side
# counterpart in WRITE_TOOLS_BY_SCOPE's shape. PERSONAL_MUTATION_TOOLS is
# therefore its own named constant, gated by an explicit read+write check in
# enabled_tool_names() — redundant with the startup invariant above, but kept
# for the same clarity every scope's write flag getting checked at its own
# call site provides.
PERSONAL_MUTATION_TOOLS: tuple[str, ...] = (
    "update_my_preferences",
    "mark_notifications_read",
)

READ_TOOLS_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "project": (
        "list_projects",
        "get_project",
        "get_project_admin_context",
        "get_project_configuration",
        "list_sprints",
        "get_sprint",
        "list_backlog_buckets",
        "get_backlog_bucket",
        "list_documents",
        "get_document",
        "list_project_storages",
        "get_project_storage",
        "list_news",
        "get_news",
        "get_wiki_page",
        "get_post",
        "list_views",
        "get_view",
        "list_grids",
        "get_grid",
        "list_categories",
        "get_category",
        "list_project_phase_definitions",
        "get_project_phase_definition",
        "get_project_phase",
        "get_my_project_access",
        "get_project_work_package_context",
        "get_instance_configuration",
        "get_job_status",
    ),
    "work_package": (
        "list_work_packages",
        "search_work_packages",
        "get_work_package",
        "get_work_packages",
        "list_my_open_work_packages",
        "get_work_package_activities",
        "list_work_package_reactions",
        "list_reminders",
        "get_work_package_relations",
        "list_work_package_attachments",
        "get_attachment",
        "list_work_package_file_links",
        "list_work_package_watchers",
        "list_statuses",
        "get_status",
        "list_priorities",
        "get_priority",
        "list_types",
        "get_type",
        "list_time_entry_activities",
        "list_time_entries",
        "get_time_entry",
        "get_cost_entry",
        "list_work_package_cost_entries",
        "get_work_package_costs_by_type",
        "get_cost_type",
        "get_github_pull_request",
        "list_work_package_github_pull_requests",
        "list_work_package_gitlab_issues",
        "list_work_package_gitlab_merge_requests",
        "list_relations",
        "list_work_package_wiki_links",
        "execute_query",
    ),
    "membership": (
        "list_project_memberships",
        "get_membership",
        "list_roles",
        "get_current_user",
        "list_actions",
        "list_capabilities",
    ),
    "version": ("list_versions", "get_version"),
    "board": ("list_boards", "get_board"),
    "meeting": (
        "list_meetings",
        "get_meeting",
        "list_meeting_agenda_items",
        "list_work_package_meeting_agenda_items",
        "get_meeting_agenda_item",
        "list_meeting_outcomes",
        "get_meeting_outcome",
        "list_meeting_sections",
        "get_meeting_section",
        "list_recurring_meetings",
        "get_recurring_meeting",
        "list_recurring_meeting_occurrences",
    ),
    "personal": ("get_my_preferences", "list_notifications"),
    "admin": (
        "list_principals",
        "list_users",
        "get_user",
        "list_groups",
        "get_group",
        "list_storages",
        "get_storage",
    ),
    "user_schedule": (
        "list_user_non_working_times",
        "list_user_working_hours",
        "get_user_working_hours",
    ),
    "extended": (
        "get_query_filter",
        "get_query_column",
        "get_query_operator",
        "get_query_sort_by",
        "list_query_filter_instance_schemas",
        "get_query_filter_instance_schema",
        "render_text",
        "list_help_texts",
        "get_help_text",
        "list_working_days",
        "list_non_working_days",
        "get_custom_option",
    ),
}

ADMIN_WRITE_TOOLS: tuple[str, ...] = (
    "create_user",
    "update_user",
    "delete_user",
    "set_user_locked",
    "create_group",
    "update_group",
    "delete_group",
    "create_storage",
    "update_storage",
    "delete_storage",
)

WRITE_TOOLS_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "project": (
        "create_project",
        "update_project",
        "delete_project",
        "copy_project",
        "set_project_favorite",
        "create_news",
        "update_news",
        "delete_news",
        "update_document",
        "create_grid",
        "update_grid",
        "delete_grid",
    ),
    "work_package": (
        "create_work_package",
        "create_subtask",
        "update_work_package",
        "bulk_create_work_packages",
        "bulk_update_work_packages",
        "delete_work_package",
        "add_work_package_comment",
        "toggle_activity_emoji_reaction",
        "create_work_package_reminder",
        "update_reminder",
        "delete_reminder",
        "create_work_package_relation",
        "delete_relation",
        "delete_attachment",
        "set_work_package_watcher",
        "create_time_entry",
        "update_time_entry",
        "create_time_entry_until",
        "update_time_entry_until",
        "delete_time_entry",
        "update_relation",
        "delete_file_link",
        "create_work_package_wiki_link",
        "delete_work_package_wiki_link",
    ),
    "membership": ("create_membership", "update_membership", "delete_membership"),
    "version": ("create_version", "update_version", "delete_version"),
    "board": ("create_board", "update_board", "delete_board"),
    "meeting": (
        "create_meeting",
        "update_meeting",
        "delete_meeting",
        "create_meeting_agenda_item",
        "update_meeting_agenda_item",
        "delete_meeting_agenda_item",
        "create_meeting_outcome",
        "update_meeting_outcome",
        "delete_meeting_outcome",
        "create_meeting_section",
        "update_meeting_section",
        "delete_meeting_section",
        "create_recurring_meeting",
        "update_recurring_meeting",
        "delete_recurring_meeting",
        "init_recurring_meeting_occurrence",
        "cancel_recurring_meeting_occurrence",
    ),
    "admin": ADMIN_WRITE_TOOLS,
    "user_schedule": (
        "create_user_non_working_time",
        "update_user_non_working_time",
        "delete_user_non_working_time",
        "create_user_working_hours",
        "update_user_working_hours",
        "delete_user_working_hours",
    ),
}

# Project-scoped write categories: registration additionally requires both
# OPENPROJECT_READ_PROJECTS and OPENPROJECT_WRITE_PROJECTS to be non-empty
# (see enabled_tool_names below) — the write-category flags above default to
# True, but a write tool that could never succeed against any project (no
# project is both readable and writable) shouldn't be registered at all. Not
# "admin" (instance-wide, not gated by either allowlist) and not "personal"
# (its own bespoke AND-gate below, independent of project scope).
_PROJECT_SCOPED_WRITE_SCOPES: frozenset[str] = frozenset(
    {"project", "work_package", "membership", "version", "board", "meeting"}
)

# Read-side counterpart, but at TOOL granularity rather than scope granularity:
# unlike the write side, a read scope's tools are not uniformly project-scoped —
# e.g. "project" mixes list_projects/get_project (project-scoped) with
# get_instance_configuration (instance-wide, no project dependency at all).
# Each name below was verified against its Service implementation (an
# ensure_*_read_allowed/ensure_project_link_allowed call, a required `project`
# parameter, or an early-empty-return guard on settings.read_projects) — not
# inferred from its home scope. Notable non-obvious cases: get_job_status IS
# project-scoped (a projectless job is denied under a restrictive allowlist,
# app/policies/scope.py's ensure_project_link_allowed_if_present);
# list_capabilities IS project-scoped despite sharing a service with the
# global list_actions (every record is filtered by its context link,
# app/services/action_capability_service.py); list_relations IS project-scoped
# despite an "instance-wide" sounding docstring (endpoints filtered against
# read_projects, app/services/relation_service.py). Gates registration only —
# write_projects plays no role here, and the runtime access check in the
# Service/Policy layer (fail-closed on an empty allowlist) is unaffected by
# this constant; it only prevents registering a tool that could never return
# anything useful, saving tool-definition context.
_PROJECT_SCOPED_READ_TOOLS: frozenset[str] = frozenset(
    {
        "list_projects",
        "get_project",
        "get_project_admin_context",
        "get_project_configuration",
        "list_sprints",
        "get_sprint",
        "list_backlog_buckets",
        "get_backlog_bucket",
        "list_documents",
        "get_document",
        "list_project_storages",
        "get_project_storage",
        "list_news",
        "get_news",
        "get_wiki_page",
        "get_post",
        "list_views",
        "get_view",
        "list_grids",
        "get_grid",
        "list_categories",
        "get_category",
        "get_project_phase",
        "get_my_project_access",
        "get_project_work_package_context",
        "get_job_status",
        "list_work_packages",
        "search_work_packages",
        "get_work_package",
        "get_work_packages",
        "list_my_open_work_packages",
        "get_work_package_activities",
        "list_work_package_reactions",
        "list_reminders",
        "get_work_package_relations",
        "list_work_package_attachments",
        "get_attachment",
        "list_work_package_file_links",
        "list_work_package_watchers",
        "list_time_entry_activities",
        "list_time_entries",
        "get_time_entry",
        "get_cost_entry",
        "list_work_package_cost_entries",
        "get_work_package_costs_by_type",
        "list_work_package_github_pull_requests",
        "list_work_package_gitlab_issues",
        "list_work_package_gitlab_merge_requests",
        "list_relations",
        "list_project_memberships",
        "get_membership",
        "list_capabilities",
        "list_versions",
        "get_version",
        "list_boards",
        "get_board",
        "list_work_package_wiki_links",
        "execute_query",
        "list_meetings",
        "get_meeting",
        "list_meeting_agenda_items",
        "list_work_package_meeting_agenda_items",
        "get_meeting_agenda_item",
        "list_meeting_outcomes",
        "get_meeting_outcome",
        "list_meeting_sections",
        "get_meeting_section",
        "list_recurring_meetings",
        "get_recurring_meeting",
        "list_recurring_meeting_occurrences",
    }
)

# create_work_package_attachment is NOT in WRITE_TOOLS_BY_SCOPE["work_package"]
# above: it needs work_package write AND a configured OPENPROJECT_ATTACHMENT_ROOT
# — an empty root disables local uploads entirely (client.py's
# _attachment_root has no cwd fallback), so registering the tool without a root
# would only expose a schema whose every call fails, wasting context. Its own
# named constant, handled by a bespoke AND-gate branch in enabled_tool_names()
# below (mirroring the "personal" bespoke branch), rather than a generic
# mechanism — this is currently the only scope-flag-AND-config-value gate in
# the codebase.
ATTACHMENT_UPLOAD_TOOLS: tuple[str, ...] = ("create_work_package_attachment",)

# Additional read scopes required by tools whose home group above is not
# sufficient on its own (verified against each client method, not guessed).
# Only ADDITIONAL requirements are listed here — never the tool's own home
# scope. role/principal are aliases of the same enable_membership_read flag
# as membership (see config.py), so they are not listed as separate entries.
# The 7 "extended"-home tools below point at their additional scopes
# ("board"/"work_package"), not at "extended" itself.
ADDITIONAL_READ_SCOPES_BY_TOOL: dict[str, frozenset[str]] = {
    "get_my_project_access": frozenset({"membership"}),
    "get_project_work_package_context": frozenset({"work_package", "version"}),
    "delete_file_link": frozenset({"work_package"}),  # home: work_package WRITE; also work_package READ
    "create_membership": frozenset({"membership"}),  # home: membership WRITE; also membership READ (role lookup)
    "update_membership": frozenset({"membership"}),
    "get_query_filter": frozenset({"board"}),
    "get_query_column": frozenset({"board"}),
    "get_query_operator": frozenset({"board"}),
    "get_query_sort_by": frozenset({"board"}),
    "list_query_filter_instance_schemas": frozenset({"board"}),
    "get_query_filter_instance_schema": frozenset({"board"}),
    "render_text": frozenset({"work_package"}),
}


def enabled_tool_names(settings: Settings) -> tuple[str, ...]:
    """Ordered, duplicate-free tool names to register for this configuration.

    The single source of truth for register_tools() (production). Tests must
    NOT use this function as their expected value — they compute expectations
    independently from the classification constants above, so a bug in the
    selection logic here cannot silently pass by comparing itself to itself.

    Read-side registration additionally requires a non-empty read_projects
    allowlist for tools in _PROJECT_SCOPED_READ_TOOLS (write_projects is
    irrelevant to reads); the write side has its own, independent
    project_scope_usable gate further below.
    """
    enabled: list[str] = []
    seen: set[str] = set()

    def include(names: tuple[str, ...]) -> None:
        for name in names:
            if name not in seen:
                enabled.append(name)
                seen.add(name)

    def additional_scopes_ok(name: str) -> bool:
        return all(settings.read_enabled(scope) for scope in ADDITIONAL_READ_SCOPES_BY_TOOL.get(name, ()))

    # A project-scoped read tool (_PROJECT_SCOPED_READ_TOOLS) is only worth
    # registering when read_projects is non-empty — with an empty allowlist it
    # can only ever return an empty result or a PermissionDeniedError. This is
    # deliberately gated on read_projects alone, never write_projects: reading
    # is independent of write authorization in both directions (an empty write
    # allowlist must not hide readable projects; a non-empty write allowlist
    # must not substitute for missing read authorization).
    read_project_scope_usable = bool(settings.read_projects)
    for scope, names in READ_TOOLS_BY_SCOPE.items():
        if settings.read_enabled(scope):
            include(
                tuple(
                    name
                    for name in names
                    if additional_scopes_ok(name)
                    and (name not in _PROJECT_SCOPED_READ_TOOLS or read_project_scope_usable)
                )
            )

    project_scope_usable = bool(settings.read_projects) and bool(settings.write_projects)
    for scope, names in WRITE_TOOLS_BY_SCOPE.items():
        if not settings.write_enabled(scope):
            continue
        if scope in _PROJECT_SCOPED_WRITE_SCOPES and not project_scope_usable:
            continue
        include(tuple(name for name in names if additional_scopes_ok(name)))

    # Handled separately from the generic write-scope loop above (not folded
    # into WRITE_TOOLS_BY_SCOPE) — see the constant's docstring-comment above.
    if settings.read_enabled("personal") and settings.write_enabled("personal"):
        include(PERSONAL_MUTATION_TOOLS)

    # Bespoke AND-gate: local upload needs work_package write, a configured
    # OPENPROJECT_ATTACHMENT_ROOT, AND usable project scope (it is
    # project-/work-package-scoped like the rest of WRITE_TOOLS_BY_SCOPE's
    # project-scoped entries) — see ATTACHMENT_UPLOAD_TOOLS above.
    if settings.write_enabled("work_package") and settings.attachment_root and project_scope_usable:
        include(ATTACHMENT_UPLOAD_TOOLS)

    return tuple(enabled)


def register_tools(mcp: MCPServer, settings: Settings) -> None:
    """Register every tool enabled by `settings`.

    Policy (which names are enabled) is this module's job; the mechanics of
    resolving a name to its function and wrapping it for error-categorization
    and trimming live in tools_runtime.register_selected_tools.
    """
    register_selected_tools(mcp, names=enabled_tool_names(settings), hide_active=bool(settings.hidden_fields))


@register_tool
async def list_categories(
    ctx: Context,
    project: str,
    select: list[str] | None = None,
) -> CategoryListResult:
    """List work-package categories configured for a project.

    select fields: id, name (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    _validate_select(select, row_type=CategorySummary)
    return await _run_tool(client.list_categories(safe_project))


@register_tool
async def get_category(
    ctx: Context,
    category_id: int,
    project: str | None = None,
) -> CategorySummary:
    """Get a single category by id.

    project is optional: when given, it's cross-checked against the
    category's real project and a mismatch raises a not-found error, rather
    than being the sole source of authorization.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_id = _validate_positive_int(category_id, field_name="category_id")
    return await _run_tool(client.get_category(category_id=safe_id, project_ref=safe_project))


@register_tool
async def search_work_packages(
    ctx: Context,
    search: str,
    project: str | None = None,
    status: str | None = None,
    open_only: bool = False,
    assignee_me: bool = False,
    assignee: str | None = None,
    priority: str | None = None,
    created_on: str | None = None,
    created_between: list[str] | None = None,
    updated_on: str | None = None,
    updated_between: list[str] | None = None,
    due_on: str | None = None,
    due_between: list[str] | None = None,
    overdue_only: bool = False,
    due_within_days: int | None = None,
    sort_by: list[str] | None = None,
    group_by: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_sums: bool = False,
    custom_field_filters: dict[str, dict[str, Any]] | None = None,
) -> WorkPackageListResult:
    """Search work packages by free text, optionally scoped to a project.

    search matches only the work package subject and numeric ID (OpenProject's
    native subject_or_id full-text filter) — it does NOT match version,
    category, description, or other linked-resource fields. To filter by
    version, use list_work_packages(version=..., project=...) instead.

    Without project, the search runs globally across every project readable
    under OPENPROJECT_READ_PROJECTS, not just one project — pass project
    explicitly to scope results to it.

    Set status to restrict results to an exact OpenProject status name or
    numeric ID — not a meta-value like 'open'/'closed'.
    Set open_only=true to return only open (not-closed) work packages.
    Set assignee_me=true to return only work packages assigned to the current user.

    assignee filters by any user (username, id, or "me"). assignee_me takes precedence.

    priority filters by priority name or numeric ID (case-insensitive).

    Date filters, overdue_only/due_within_days, sort_by/group_by, select,
    pagination (offset/limit/total), include_sums, and each result's
    custom_fields/custom_comments (raw-key custom-field values/comments,
    capped and hide-matched exactly as documented) all work exactly as
    documented on list_work_packages — see that tool's docstring for the
    full field lists and semantics. One difference: total is the real
    matching count only when scope is unrestricted or an explicit project
    was given (list_work_packages's server-side allowed-project filter for
    the no-project+restricted-scope case does not apply here); otherwise
    total/groups/total_sums fall back to this page's data, same safety
    guarantee either way.

    custom_field_filters filters by custom field value(s); see
    list_work_packages's docstring for the full parameter documentation
    (identical shape and semantics on both tools).
    """
    client = _client_from_context(ctx)
    safe_search = _validate_required_query(search, field_name="search", max_length=120)
    safe_project = _validate_optional_project_ref(project)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_assignee = _validate_optional_user_or_principal_ref(assignee)
    safe_priority = _validate_optional_query(priority, field_name="priority", max_length=100)
    safe_created_on = _validate_optional_date(created_on, "created_on")
    safe_created_between = _validate_optional_date_range(created_between, "created_between")
    safe_updated_on = _validate_optional_date(updated_on, "updated_on")
    safe_updated_between = _validate_optional_date_range(updated_between, "updated_between")
    safe_due_on = _validate_optional_date(due_on, "due_on")
    safe_due_between = _validate_optional_date_range(due_between, "due_between")
    safe_due_within_days = _validate_optional_non_negative_int(due_within_days, field_name="due_within_days")
    safe_sort_by = _validate_sort_by(sort_by)
    safe_group_by = _validate_group_by(group_by)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=WorkPackageSummary)
    safe_custom_field_filters = _validate_custom_field_filters(custom_field_filters)
    return await _run_tool(
        client.search_work_packages(
            search=safe_search,
            project=safe_project,
            status=safe_status,
            open_only=open_only,
            assignee_me=assignee_me,
            assignee=safe_assignee,
            priority=safe_priority,
            created_on=safe_created_on,
            created_between=safe_created_between,
            updated_on=safe_updated_on,
            updated_between=safe_updated_between,
            due_on=safe_due_on,
            due_between=safe_due_between,
            overdue_only=overdue_only,
            due_within_days=safe_due_within_days,
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
            include_sums=include_sums,
            custom_field_filters=safe_custom_field_filters,
        )
    )


@register_tool
async def list_work_packages(
    ctx: Context,
    project: str | None = None,
    type: str | None = None,
    version: str | None = None,
    version_status: str | None = None,
    open_only: bool = False,
    assignee_me: bool = False,
    assignee: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    created_on: str | None = None,
    created_between: list[str] | None = None,
    updated_on: str | None = None,
    updated_between: list[str] | None = None,
    due_on: str | None = None,
    due_between: list[str] | None = None,
    overdue_only: bool = False,
    due_within_days: int | None = None,
    sort_by: list[str] | None = None,
    group_by: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_sums: bool = False,
    custom_field_filters: dict[str, dict[str, Any]] | None = None,
) -> WorkPackageListResult:
    """List work packages with structured filters and no free-text query requirement.

    project accepts a numeric ID, exact identifier/slug, or project name; the
    parameter is named project, not project_id. There is no generic
    filters=[...] parameter — each filter is its own named argument (version,
    status, assignee, the date filters, etc.), listed below.

    version_status filters by the status of a work package's assigned version:
    one of 'open', 'closed', or 'locked'.

    assignee filters by any user (username, id, or "me"). assignee_me takes precedence.

    status/priority filter by exact OpenProject status/priority name or numeric
    ID (case-insensitive) — not meta-values like 'open'/'closed'; set
    open_only=true to restrict results to not-closed work packages instead.

    Date filters accept YYYY-MM-DD format:
    - created_on/updated_on/due_on: exact date match
    - created_between/updated_between/due_between: inclusive date range [start, end]
    Cannot specify both _on and _between for the same field.

    overdue_only=true restricts results to work packages with due_date before
    today that are not closed (OpenProject's own overdue? predicate — there
    is no dedicated overdue API filter, this composes a relative date filter
    with the open-status meta-filter). due_within_days=N restricts to
    due_date in [today, today+N days]. Neither can be combined with each
    other or with due_on/due_between (all four constrain the same field).

    sort_by accepts a list of sort criteria in format "field:direction"
    (e.g., ["status:desc", "priority:asc"]). Direction defaults to "asc" if omitted.
    Each field is checked against OpenProject's real sortable work-package
    columns (id, project, subject, type, status, priority, author, assigned_to,
    responsible, updated_at, category, version, start_date, due_date,
    estimated_time, remaining_time, done_ratio, created_at, duration,
    project_phase, story_points, or a custom field's cf_<id> identifier) —
    an unknown field raises a ValueError listing the valid set instead of
    only failing once OpenProject itself rejects the request.

    group_by accepts one field name to group results by (e.g., "status",
    "assigned_to"), checked the same way against OpenProject's actual
    groupable columns (a subset of the sortable ones above — notably
    start_date/due_date/estimated_time/remaining_time/duration/created_at/
    updated_at sort fine but cannot be grouped by).

    select restricts each result row to the given fields (e.g. ["id", "subject",
    "status"]); an invalid name returns the allowed set. Common fields: id,
    display_id, subject, type, status, priority, assignee, project, version,
    parent_id, parent_display_id, start_date, due_date, estimated_time,
    spent_time, created_at, updated_at, author, category, description,
    schedule_manually, derived_start_date, derived_due_date, percentage_done,
    derived_percentage_done, readonly, ignore_non_working_days, custom_fields,
    custom_fields_truncated, custom_comments, custom_comments_truncated.
    custom_fields/custom_comments are selectable/hideable only as a whole
    field, not by individual custom-field key (per-key filtering is
    OPENPROJECT_HIDE_CUSTOM_FIELDS' concern, not select's).
    parent_display_id is only populated on OpenProject 17.5+ (semantic mode);
    it stays null on older/classic instances even when parent_id is set.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is the real
    matching count only when the query is provably restricted to
    OPENPROJECT_READ_PROJECTS server-side — scope is unrestricted, an explicit
    project was given, or (no project, restricted scope) a server-side filter for
    the resolved allowed project IDs was sent. Otherwise total falls back to this
    page's item count, and next_offset/truncated are based on whether this page
    came back full rather than the server's own total, so nothing here ever
    reveals how many matches exist in projects you can't see. Because of this,
    total can read 0 while next_offset is still non-null (a restrictive scope
    filtered out every match on this page, but the raw server page was full) —
    that is not an inconsistency, keep paging via next_offset rather than
    stopping on a low/zero total. Page until next_offset is null either way.

    include_sums=true adds server-computed aggregates instead of requiring
    client-side pagination and summation: groups (one entry per group_by
    value, with count and a sums dict of OpenProject's fixed summable
    fields — estimated_time, story_points, percentage_done, remaining_time,
    overall_costs, labor_costs, material_costs, plus any custom fields — as
    raw server-formatted values, e.g. ISO 8601 durations and currency
    strings) and total_sums (the same shape, across all matches). groups is
    only populated when group_by is also set; total_sums is populated
    either way (a sum over the whole filtered result set even without
    grouping). Same scope-safety rule as total above: groups/total_sums
    come back null whenever the query cannot be proven restricted to
    OPENPROJECT_READ_PROJECTS server-side.

    Version rollup recipe: group_by="status", version="<version id or
    name>", include_sums=true returns per-status progress/time sums for one
    version's work packages, replacing manual pagination + client-side
    summation.

    custom_fields is a dict keyed by the RAW OpenProject key (e.g.
    "customField12") -- never a friendly name -- with values normalized by
    shape: plain scalars pass through; link-typed values (list/user/version
    format) become title-only strings (or a list of titles for a multi-value
    field), matching every other link field in this response; multi-
    paragraph "text"-format values are capped like description (this call's
    effective text_limit); a scalar string/link/date-format value is
    independently capped at ~255 characters. custom_fields_truncated is true
    when the dict was capped at 50 entries and/or any individual entry's
    value was itself capped. custom_comments (keyed the same way, holding a
    field's freeform comment text) and custom_comments_truncated follow the
    identical shape and caps, independently -- in practice custom_comments
    is always empty/null for work packages on OpenProject's stock CE
    behavior: only Projects opt into per-custom-field comments, work
    packages do not, so this field is present for forward compatibility
    only. Combined worst case is roughly 250 KB for custom_fields per work
    package, always finite regardless of how many custom fields exist or
    how large their values are. get_work_packages (batch) and
    list_my_open_work_packages return the same custom_fields/custom_comments
    shape and caps, since they reuse this same normalization.
    OPENPROJECT_HIDE_CUSTOM_FIELDS hides individual custom_fields entries by
    matching ONLY the raw key/wildcard (e.g. "customField12", "customField*")
    -- unlike the write path, which also accepts the custom field's friendly
    name, a read-side hide pattern written as a friendly name has no effect.

    custom_field_filters filters results by custom field value(s) -- a dict
    keyed by "cf_<N>" or "customField<N>" (both forms accepted transparently
    and always normalized to "cf_<N>" on the wire; "cf_<N>" is
    CustomField#column_name, the actual OpenProject filter key, distinct from
    "customField<N>" which is the JSON/PATCH key used by custom_fields
    above -- do not confuse the two). Each entry's value is
    {"operator": "<symbol>", "values": [...]}, e.g.
    {"cf_12": {"operator": "=", "values": ["42"]}}. Learn a field's cf_<N> id
    from any prior get_work_package call's custom_fields dict keys (strip the
    "customField" prefix). Only raw cf_<N>/customField<N> keys are accepted --
    friendly-name resolution is not supported (a list/search call has no
    single project+type context to resolve a name against safely; a friendly
    name is only meaningful for the write path's per-call project+type
    schema probe). At most 20 custom-field filters per call, at most 100
    values per filter, each value at most 1000 characters.

    Legal operators depend on the field's format on this instance -- see
    docs/filters.md's "Custom-Field Filters" section for the full
    format-to-operator matrix, verified against OpenProject CE source. This
    tool validates the key shape and the operator symbol locally (a
    recognized custom-field operator, not necessarily legal for this
    specific field's format) and rejects hidden fields
    (OPENPROJECT_HIDE_CUSTOM_FIELDS) before any network call; an
    operator/value that is syntactically valid but illegal for the field's
    actual format is rejected by OpenProject itself with a clear error
    (surfaced as a ValueError here, not a raw HTTP passthrough) rather than
    validated client-side against a live schema -- this keeps list/search
    calls at their existing single-request cost (no per-call schema probe).
    user/version-format custom-field filters additionally require project to
    be set (OpenProject only considers project-scoped custom fields of these
    two formats filterable at all; this is not checked locally -- a global,
    no-project user/version CF filter fails server-side with an unhelpful
    "filter not available" error, see docs/filters.md's "Global (no-project)
    filtering constraint" section).
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_type = _validate_optional_query(type, field_name="type", max_length=100)
    safe_version = _validate_optional_query(version, field_name="version", max_length=100)
    safe_version_status = _validate_optional_choice(
        version_status, field_name="version_status", allowed_values={"open", "closed", "locked"}
    )
    safe_assignee = _validate_optional_user_or_principal_ref(assignee)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_priority = _validate_optional_query(priority, field_name="priority", max_length=100)
    safe_created_on = _validate_optional_date(created_on, "created_on")
    safe_created_between = _validate_optional_date_range(created_between, "created_between")
    safe_updated_on = _validate_optional_date(updated_on, "updated_on")
    safe_updated_between = _validate_optional_date_range(updated_between, "updated_between")
    safe_due_on = _validate_optional_date(due_on, "due_on")
    safe_due_between = _validate_optional_date_range(due_between, "due_between")
    safe_due_within_days = _validate_optional_non_negative_int(due_within_days, field_name="due_within_days")
    safe_sort_by = _validate_sort_by(sort_by)
    safe_group_by = _validate_group_by(group_by)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=WorkPackageSummary)
    safe_custom_field_filters = _validate_custom_field_filters(custom_field_filters)
    return await _run_tool(
        client.list_work_packages(
            project=safe_project,
            type=safe_type,
            version=safe_version,
            version_status=safe_version_status,
            open_only=open_only,
            assignee_me=assignee_me,
            assignee=safe_assignee,
            status=safe_status,
            priority=safe_priority,
            created_on=safe_created_on,
            created_between=safe_created_between,
            updated_on=safe_updated_on,
            updated_between=safe_updated_between,
            due_on=safe_due_on,
            due_between=safe_due_between,
            overdue_only=overdue_only,
            due_within_days=safe_due_within_days,
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
            include_sums=include_sums,
            custom_field_filters=safe_custom_field_filters,
        )
    )


@register_tool
async def get_work_package(
    ctx: Context,
    work_package_id: int | str,
    text_limit: int | None = None,
    select: list[str] | None = None,
) -> WorkPackageDetail:
    """Get a work package by id, including its full description.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"),
    not UI display number (e.g., 51) — the same value list_work_packages/
    search_work_packages return as each row's `id` field.

    The description is returned in full by default (single work packages are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``description_truncated`` is true and ``description_length``
    reports the real length. This same ``text_limit`` also caps any
    "text"-format custom field value in ``custom_fields`` (see
    list_work_packages's docstring for the full custom_fields/custom_comments
    shape and hide-matching rules) -- but a scalar string/link/date-format
    custom field value is capped independently at ~255 characters regardless
    of ``text_limit``, including when ``text_limit=None`` (the default here):
    "single work packages are not truncated" applies to description and CF
    text-format values, not to that separate, always-on scalar cap.

    select restricts the response to the given fields (e.g. ["id", "subject",
    "status"]); an invalid name returns the allowed set.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    _validate_select(select, row_type=WorkPackageDetail)
    return await _run_tool(client.get_work_package(safe_id, text_limit=safe_text_limit))


@register_tool
async def get_work_packages(
    ctx: Context,
    ids: list[int | str],
    text_limit: int | None = None,
    select: list[str] | None = None,
) -> BatchWorkPackageReadResult:
    """Get multiple work packages by ID in a single batch call.

    Fetches work packages in parallel and returns per-item results.
    Failed fetches are reported individually without stopping the batch.
    Maximum 100 IDs per batch.

    ids: internal ids (e.g., 952) or display_ids (e.g., "PROJ-51"),
    not UI display numbers. Duplicate IDs are automatically deduplicated.

    select restricts each result's work_package to the given fields (e.g.
    ["id", "subject", "status"]); an invalid name returns the allowed set.
    The id/success/error fields on each result are always included regardless
    of select, so you can still tell which items succeeded.

    For batches with many full-detail items, set text_limit and/or select
    proactively — an unbounded batch of large work packages can exceed the
    tool-result size limit and get redirected to a file.

    Each item's work_package carries the same custom_fields/custom_comments
    shape and caps as get_work_package — see list_work_packages's docstring
    for the full details (raw-key values, per-field caps, and the
    OPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching asymmetry). With
    many items, an unbounded custom_fields/custom_comments per item adds to
    the same size-limit risk text_limit/select address above.
    """
    client = _client_from_context(ctx)

    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    if not ids:
        raise ValueError("ids list cannot be empty")

    seen = set()
    unique_ids: list[int | str] = []
    for raw_id in ids:
        safe_id = _validate_work_package_ref(raw_id)
        normalized = str(safe_id)
        if normalized not in seen:
            seen.add(normalized)
            unique_ids.append(safe_id)

    if len(unique_ids) > BATCH_READ_MAX_IDS:
        raise ValueError(f"Maximum {BATCH_READ_MAX_IDS} unique work packages per batch (got {len(unique_ids)})")

    safe_text_limit = _validate_optional_text_limit(text_limit)
    _validate_select(select, row_type=WorkPackageDetail)

    return await _run_tool(client.get_work_packages(ids=unique_ids, text_limit=safe_text_limit))


def _validate_work_package_create_fields(
    *,
    description: str | None,
    version: str | None,
    project_phase: str | None,
    assignee: str | None,
    responsible: str | None,
    priority: str | None,
    category: str | None,
    custom_fields: dict[str, Any] | None,
    start_date: str | None,
    due_date: str | None,
    estimated_time: str | None = None,
    remaining_time: str | None = None,
    duration: str | None = None,
    field_prefix: str = "",
) -> dict[str, Any]:
    """Shared optional-field validation for create_work_package/create_subtask/
    bulk_create_work_packages' per-item block. No clearing semantics here --
    create has nothing to clear, every field is a plain optional value.
    """
    return {
        "description": _validate_optional_text(description, field_name=f"{field_prefix}description", max_length=10_000),
        "version": _validate_optional_query(version, field_name=f"{field_prefix}version", max_length=100),
        "project_phase": _validate_optional_query(
            project_phase, field_name=f"{field_prefix}project_phase", max_length=100
        ),
        "assignee": _validate_optional_user_ref(assignee, field_name=f"{field_prefix}assignee"),
        "responsible": _validate_optional_user_ref(responsible, field_name=f"{field_prefix}responsible"),
        "priority": _validate_optional_query(priority, field_name=f"{field_prefix}priority", max_length=100),
        "category": _validate_optional_query(category, field_name=f"{field_prefix}category", max_length=100),
        "custom_fields": _validate_optional_custom_fields(custom_fields),
        "start_date": _validate_optional_date(start_date, field_name=f"{field_prefix}start_date"),
        "due_date": _validate_optional_date(due_date, field_name=f"{field_prefix}due_date"),
        "estimated_time": _validate_optional_duration(estimated_time, field_name=f"{field_prefix}estimated_time"),
        "remaining_time": _validate_optional_duration(remaining_time, field_name=f"{field_prefix}remaining_time"),
        "duration": _validate_optional_duration(duration, field_name=f"{field_prefix}duration"),
    }


@register_tool
async def create_work_package(
    ctx: Context,
    project: str,
    type: str,
    subject: str,
    description: str | None = None,
    version: str | None = None,
    project_phase: str | None = None,
    assignee: str | None = None,
    responsible: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    parent: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    estimated_time: str | None = None,
    remaining_time: str | None = None,
    duration: str | None = None,
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or create a work package.

    The tool validates the payload first. Set confirm=true to write.
    assignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number to nest the new work package under a parent.
    estimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day, 'P2W' for 2 weeks).
    due_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the
    next working day by OpenProject — compare the request and the returned `result.due_date` if
    the exact calendar date matters. This server does not expose a way to opt out of that shift
    (OpenProject's own `ignoreNonWorkingDays` flag is not a write parameter here).
    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    If you issue multiple create_work_package/create_subtask calls concurrently, OpenProject assigns IDs in
    server completion order, not call order — use bulk_create_work_packages instead when relative
    ID/creation order across a batch matters.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_type = _validate_required_query(type, field_name="type", max_length=100)
    safe_subject = _validate_required_query(subject, field_name="subject", max_length=255)
    common = _validate_work_package_create_fields(
        description=description,
        version=version,
        project_phase=project_phase,
        assignee=assignee,
        responsible=responsible,
        priority=priority,
        category=category,
        custom_fields=custom_fields,
        start_date=start_date,
        due_date=due_date,
        estimated_time=estimated_time,
        remaining_time=remaining_time,
        duration=duration,
    )
    safe_parent = _validate_optional_work_package_ref(parent, field_name="parent")
    return await _run_tool(
        client.create_work_package(
            project=safe_project,
            type=safe_type,
            subject=safe_subject,
            description=common["description"],
            version=common["version"],
            project_phase=common["project_phase"],
            assignee=common["assignee"],
            responsible=common["responsible"],
            priority=common["priority"],
            category=common["category"],
            custom_fields=common["custom_fields"],
            parent_work_package_id=safe_parent,
            start_date=common["start_date"],
            due_date=common["due_date"],
            estimated_time=common["estimated_time"],
            remaining_time=common["remaining_time"],
            duration=common["duration"],
            confirm=confirm,
        )
    )


def _validate_work_package_update_fields(
    *,
    subject: str | None,
    description: str | None,
    type: str | None,
    version: str | None,
    sprint: str | None,
    project_phase: str | None,
    status: str | None,
    assignee: str | None,
    responsible: str | None,
    priority: str | None,
    category: str | None,
    custom_fields: dict[str, Any] | None,
    parent: str | None,
    start_date: str | None,
    due_date: str | None,
    estimated_time: str | None,
    remaining_time: str | None,
    duration: str | None,
    percentage_done: int | None,
    field_prefix: str = "",
    parent_field_name: str = "parent",
) -> dict[str, Any]:
    """Shared field validation for update_work_package/bulk_update_work_packages'
    per-item block. Most fields are wrapped in _clearable/_clearable_ref/
    _clearable_duration -- 'none' (any case) clears the field, matching the
    single-call update_work_package tool's documented convention.
    """
    return {
        "subject": _validate_optional_query(subject, field_name=f"{field_prefix}subject", max_length=255),
        "description": _validate_optional_update_text(
            description, field_name=f"{field_prefix}description", max_length=10_000
        ),
        "type": _validate_optional_query(type, field_name=f"{field_prefix}type", max_length=100),
        "version": _validate_optional_version(version, field_name=f"{field_prefix}version", sentinel=CLEAR_VERSION),
        "sprint": _clearable(
            sprint,
            lambda v: _validate_optional_query(v, field_name=f"{field_prefix}sprint", max_length=100),
            sentinel=CLEAR,
        ),
        "project_phase": _clearable(
            project_phase,
            lambda v: _validate_optional_query(v, field_name=f"{field_prefix}project_phase", max_length=100),
            sentinel=CLEAR,
        ),
        "status": _validate_optional_query(status, field_name=f"{field_prefix}status", max_length=100),
        "assignee": _clearable(
            assignee,
            lambda v: _validate_optional_user_ref(v, field_name=f"{field_prefix}assignee"),
            sentinel=CLEAR,
        ),
        "responsible": _clearable(
            responsible,
            lambda v: _validate_optional_user_ref(v, field_name=f"{field_prefix}responsible"),
            sentinel=CLEAR,
        ),
        "priority": _validate_optional_query(priority, field_name=f"{field_prefix}priority", max_length=100),
        "category": _clearable(
            category,
            lambda v: _validate_optional_query(v, field_name=f"{field_prefix}category", max_length=100),
            sentinel=CLEAR,
        ),
        "custom_fields": _validate_optional_custom_fields(custom_fields),
        "parent": _clearable_ref(
            parent, functools.partial(_validate_work_package_ref, field_name=parent_field_name), sentinel=CLEAR_PARENT
        ),
        "start_date": _validate_optional_date(start_date, field_name=f"{field_prefix}start_date"),
        "due_date": _validate_optional_date(due_date, field_name=f"{field_prefix}due_date"),
        "estimated_time": _clearable_duration(
            estimated_time, field_name=f"{field_prefix}estimated_time", sentinel=CLEAR
        ),
        "remaining_time": _clearable_duration(
            remaining_time, field_name=f"{field_prefix}remaining_time", sentinel=CLEAR
        ),
        "duration": _clearable_duration(duration, field_name=f"{field_prefix}duration", sentinel=CLEAR),
        "percentage_done": _validate_optional_percentage_done(
            percentage_done, field_name=f"{field_prefix}percentage_done"
        ),
    }


@register_tool
async def update_work_package(
    ctx: Context,
    work_package_id: int | str,
    subject: str | None = None,
    description: str | None = None,
    type: str | None = None,
    version: str | None = None,
    sprint: str | None = None,
    project_phase: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    responsible: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    parent: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    estimated_time: str | None = None,
    remaining_time: str | None = None,
    duration: str | None = None,
    percentage_done: int | None = None,
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or update a work package.

    The tool validates the patch first. Set confirm=true to write.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    assignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent re-parents the work package (numeric id or a PROJ-123 reference); pass 'none' to remove the parent and make it top-level. version accepts a version name/id, or 'none' to unassign the version. sprint accepts a Backlogs sprint name/id (requires the Backlogs module and OpenProject 17.3+), or 'none' to unassign it. Pass 'none' to assignee, responsible, category or project_phase to unassign that field. Omitted fields stay unchanged.
    estimated_time, remaining_time, duration accept ISO8601 duration strings (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'P1D' for 1 day); omit to leave unchanged, or pass 'none' to clear the field. percentage_done is an integer 0-100.
    Setting status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H when you
    don't supply them explicitly and OpenProject's schema reports those fields as writable (on instances
    using status-based progress calculation, OpenProject already derives them itself and this is skipped).
    On such an instance, explicitly passing percentage_done together with a closing status is rejected
    with a hard validation error (percentageDone is not writable there) rather than silently ignored —
    omit percentage_done and let OpenProject derive it instead.
    due_date's non-working-day shift and the confirm/preview contract work exactly as documented
    on create_work_package.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    common = _validate_work_package_update_fields(
        subject=subject,
        description=description,
        type=type,
        version=version,
        sprint=sprint,
        project_phase=project_phase,
        status=status,
        assignee=assignee,
        responsible=responsible,
        priority=priority,
        category=category,
        custom_fields=custom_fields,
        parent=parent,
        start_date=start_date,
        due_date=due_date,
        estimated_time=estimated_time,
        remaining_time=remaining_time,
        duration=duration,
        percentage_done=percentage_done,
    )
    _require_at_least_one(
        *common.values(),
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_work_package(
            work_package_id=safe_id,
            subject=common["subject"],
            description=common["description"],
            type=common["type"],
            version=common["version"],
            sprint=common["sprint"],
            project_phase=common["project_phase"],
            status=common["status"],
            assignee=common["assignee"],
            responsible=common["responsible"],
            priority=common["priority"],
            category=common["category"],
            custom_fields=common["custom_fields"],
            parent_work_package_id=common["parent"],
            start_date=common["start_date"],
            due_date=common["due_date"],
            estimated_time=common["estimated_time"],
            remaining_time=common["remaining_time"],
            duration=common["duration"],
            percentage_done=common["percentage_done"],
            confirm=confirm,
        )
    )


def _resolve_bulk_parent_field(item: dict[str, Any], index: int) -> tuple[Any, str]:
    """Resolve a bulk item's parent value, accepting `parent` as an alias for `parent_work_package_id`."""
    has_parent = "parent" in item
    has_parent_wp_id = "parent_work_package_id" in item
    if has_parent and has_parent_wp_id:
        raise ValueError(f"items[{index}] must not specify both parent and parent_work_package_id.")
    if has_parent:
        return item["parent"], f"items[{index}].parent"
    return item.get("parent_work_package_id"), f"items[{index}].parent_work_package_id"


_BULK_CREATE_WORK_PACKAGE_ITEM_FIELDS = frozenset(
    {
        "project",
        "type",
        "subject",
        "description",
        "version",
        "project_phase",
        "assignee",
        "responsible",
        "priority",
        "category",
        "custom_fields",
        "parent",
        "parent_work_package_id",
        "start_date",
        "due_date",
        "estimated_time",
        "remaining_time",
        "duration",
    }
)


@register_tool
async def bulk_create_work_packages(
    ctx: Context,
    items: list[dict[str, Any]],
    select: list[str] | None = None,
    confirm: bool = False,
) -> BulkWorkPackageWriteResult:
    """Create multiple work packages in one call.

    New items have no identifier field to set (unlike `bulk_update_work_packages`'s
    `work_package_id`) — each result item is matched back to its input purely by `index`.

    Each item in `items` must contain `project`, `type`, and `subject`. Optional fields per item:
    `description`, `version`, `project_phase`, `assignee`, `responsible`, `priority`, `category`,
    `custom_fields`, `parent_work_package_id` (or `parent`, an alias for the same field, matching
    `create_work_package`'s naming — do not specify both on the same item), `start_date`
    (YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`, `remaining_time`, `duration`
    (ISO8601 duration strings, e.g. 'PT8H' or 'P1D'). An item containing any other key is
    rejected with an indexed validation error rather than silently dropping the unrecognized field.
    due_date falling on a non-working day (e.g. a weekend) can be silently moved forward to the
    next working day by OpenProject — compare the request and the returned item's
    `result.result.due_date` if the exact calendar date matters. This server does not expose a
    way to opt out of that shift (OpenProject's own `ignoreNonWorkingDays` flag is not a write
    parameter here).

    With confirm=false (default) all items are validated and a preview is returned.
    With confirm=true all items are created. Failed items are reported in the result — the operation
    continues for remaining items regardless of individual failures. A rejected
    item's validation is not a tool error; inspect each item's `success`,
    `error`, and nested `result` rather than the MCP error envelope.

    select restricts each item's nested result to the given fields (e.g.
    ["ready", "work_package_id"]); an invalid name returns the allowed set. The
    index/success/error fields on each item are always included regardless of
    select, so you can still tell which items succeeded. For batches with many
    items or long descriptions, set select proactively — an unconfirmed preview
    echoes each item's full proposed payload, and an unbounded batch can exceed
    the tool-result size limit and get redirected to a file.

    A per-item timeout is reported as that item's failure and does not stop
    the loop. If this call is cancelled outright (e.g. the host cancels the
    request), items already created beforehand remain on the server; items not
    yet attempted are not created. No result summary is returned in that case
    (the call ends via cancellation, not a normal return) — use
    list_work_packages/get_work_package afterward to determine what was
    actually written. This operation is not atomic; OpenProject CE has no
    batch/transaction endpoint.

    Items are processed strictly sequentially in list order, and each result's index reflects that order —
    use this tool instead of parallel create_work_package/create_subtask calls whenever the relative order
    of a batch matters.
    """
    client = _client_from_context(ctx)
    if not items:
        raise ValueError("items must not be empty.")
    _validate_select(select, row_type=WorkPackageWriteResult)
    safe_items: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object.")
        unknown_keys = set(item) - _BULK_CREATE_WORK_PACKAGE_ITEM_FIELDS
        if unknown_keys:
            raise ValueError(f"items[{i}] has unsupported field(s): {', '.join(sorted(unknown_keys))}.")
        project = item.get("project")
        type_ = item.get("type")
        subject = item.get("subject")
        parent_value, parent_field_name = _resolve_bulk_parent_field(item, i)
        safe_parent_work_package_id = _validate_optional_work_package_ref(parent_value, field_name=parent_field_name)
        if not project:
            raise ValueError(f"items[{i}].project is required.")
        if not type_:
            raise ValueError(f"items[{i}].type is required.")
        if not subject:
            raise ValueError(f"items[{i}].subject is required.")
        common = _validate_work_package_create_fields(
            description=item.get("description"),
            version=item.get("version"),
            project_phase=item.get("project_phase"),
            assignee=item.get("assignee"),
            responsible=item.get("responsible"),
            priority=item.get("priority"),
            category=item.get("category"),
            custom_fields=item.get("custom_fields"),
            start_date=item.get("start_date"),
            due_date=item.get("due_date"),
            estimated_time=item.get("estimated_time"),
            remaining_time=item.get("remaining_time"),
            duration=item.get("duration"),
            field_prefix=f"items[{i}].",
        )
        safe_items.append(
            {
                "project": _validate_project_ref(str(project)),
                "type": _validate_required_query(str(type_), field_name=f"items[{i}].type", max_length=100),
                "subject": _validate_required_query(str(subject), field_name=f"items[{i}].subject", max_length=255),
                "description": common["description"],
                "version": common["version"],
                "project_phase": common["project_phase"],
                "assignee": common["assignee"],
                "responsible": common["responsible"],
                "priority": common["priority"],
                "category": common["category"],
                "custom_fields": common["custom_fields"],
                "parent_work_package_id": safe_parent_work_package_id,
                "start_date": common["start_date"],
                "due_date": common["due_date"],
                "estimated_time": common["estimated_time"],
                "remaining_time": common["remaining_time"],
                "duration": common["duration"],
            }
        )
    return await _run_tool(client.bulk_create_work_packages(items=safe_items, confirm=confirm))


_BULK_UPDATE_WORK_PACKAGE_ITEM_FIELDS = frozenset(
    {
        "work_package_id",
        "subject",
        "description",
        "type",
        "version",
        "sprint",
        "project_phase",
        "status",
        "assignee",
        "responsible",
        "priority",
        "category",
        "custom_fields",
        "parent",
        "parent_work_package_id",
        "start_date",
        "due_date",
        "estimated_time",
        "remaining_time",
        "duration",
        "percentage_done",
    }
)


@register_tool
async def bulk_update_work_packages(
    ctx: Context,
    items: list[dict[str, Any]],
    select: list[str] | None = None,
    confirm: bool = False,
) -> BulkWorkPackageWriteResult:
    """Update multiple work packages in one call.

    Each item's identifier field is `work_package_id`, not `id` — e.g.
    {"work_package_id": 952, "status": "Closed"}.

    Each item in `items` must contain `work_package_id`. At least one other field must be present per item.
    Optional fields per item: `subject`, `description`, `type`, `version`, `sprint` (Backlogs sprint
    name/id, requires the Backlogs module and OpenProject 17.3+), `project_phase`, `status`,
    `assignee`, `responsible`, `priority`, `category`, `custom_fields`, `parent_work_package_id` (or
    `parent`, an alias for the same field, matching `update_work_package`'s naming — do not specify
    both on the same item), `start_date` (YYYY-MM-DD), `due_date` (YYYY-MM-DD), `estimated_time`,
    `remaining_time`, `duration` (ISO8601 duration strings, e.g. 'PT8H' or 'P1D'; pass 'none' to clear
    one of these), `percentage_done` (integer 0-100). Pass 'none' to `version`, `sprint`,
    `project_phase`, `assignee`, `responsible`, `category`, `parent_work_package_id`, or `parent` to
    clear that field on the item, same as `update_work_package`. An item containing any other key is
    rejected with an indexed validation error rather than silently dropping the unrecognized field.
    Setting an item's status to a closed status auto-fills percentage_done=100 and remaining_time=PT0H
    when that item doesn't supply them explicitly and OpenProject's schema reports those fields as
    writable. On an instance using status-based progress calculation, explicitly passing
    percentage_done together with a closing status on the same item is rejected with a hard,
    indexed validation error (percentageDone is not writable there) rather than silently ignored —
    omit percentage_done on that item and let OpenProject derive it instead.

    due_date's non-working-day shift, the confirm/preview contract, select's item-trimming
    behavior, and cancellation/atomicity semantics all work exactly as documented on
    bulk_create_work_packages — only the affected result field differs
    (`result.result.due_date` here too).
    """
    client = _client_from_context(ctx)
    if not items:
        raise ValueError("items must not be empty.")
    _validate_select(select, row_type=WorkPackageWriteResult)
    safe_items: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object.")
        unknown_keys = set(item) - _BULK_UPDATE_WORK_PACKAGE_ITEM_FIELDS
        if unknown_keys:
            raise ValueError(f"items[{i}] has unsupported field(s): {', '.join(sorted(unknown_keys))}.")
        work_package_id = item.get("work_package_id")
        if work_package_id is None:
            raise ValueError(f"items[{i}].work_package_id is required.")
        safe_id = _validate_work_package_ref(work_package_id, field_name=f"items[{i}].work_package_id")
        parent_value, parent_field_name = _resolve_bulk_parent_field(item, i)
        common = _validate_work_package_update_fields(
            subject=item.get("subject"),
            description=item.get("description"),
            type=item.get("type"),
            version=item.get("version"),
            sprint=item.get("sprint"),
            project_phase=item.get("project_phase"),
            status=item.get("status"),
            assignee=item.get("assignee"),
            responsible=item.get("responsible"),
            priority=item.get("priority"),
            category=item.get("category"),
            custom_fields=item.get("custom_fields"),
            parent=parent_value,
            start_date=item.get("start_date"),
            due_date=item.get("due_date"),
            estimated_time=item.get("estimated_time"),
            remaining_time=item.get("remaining_time"),
            duration=item.get("duration"),
            percentage_done=item.get("percentage_done"),
            field_prefix=f"items[{i}].",
            parent_field_name=parent_field_name,
        )
        _require_at_least_one(
            *common.values(),
            message=f"items[{i}]: at least one field to update is required.",
        )
        safe_items.append(
            {
                "work_package_id": safe_id,
                "subject": common["subject"],
                "description": common["description"],
                "type": common["type"],
                "version": common["version"],
                "sprint": common["sprint"],
                "project_phase": common["project_phase"],
                "status": common["status"],
                "assignee": common["assignee"],
                "responsible": common["responsible"],
                "priority": common["priority"],
                "category": common["category"],
                "custom_fields": common["custom_fields"],
                "parent_work_package_id": common["parent"],
                "start_date": common["start_date"],
                "due_date": common["due_date"],
                "estimated_time": common["estimated_time"],
                "remaining_time": common["remaining_time"],
                "duration": common["duration"],
                "percentage_done": common["percentage_done"],
            }
        )
    return await _run_tool(client.bulk_update_work_packages(items=safe_items, confirm=confirm))


@register_tool
async def delete_work_package(
    ctx: Context,
    work_package_id: int | str,
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or delete a work package.

    The tool previews the target first. Set confirm=true to delete.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.delete_work_package(work_package_id=safe_id, confirm=confirm))


@register_tool
async def create_subtask(
    ctx: Context,
    parent_work_package_id: int | str,
    type: str,
    subject: str,
    description: str | None = None,
    version: str | None = None,
    project_phase: str | None = None,
    assignee: str | None = None,
    responsible: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or create a subtask under an existing work package.

    The tool validates the payload first. Set confirm=true to write.
    parent_work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"),
    not UI display number (e.g., 51) — the same value list_work_packages/
    get_work_package return as each row's `id` field (and as `parent_id`/
    `parent_display_id` on a child work package).
    Concurrent calls to this tool (or create_work_package) do not preserve call order in the resulting IDs;
    use bulk_create_work_packages when order across several new items matters.
    """
    client = _client_from_context(ctx)
    safe_parent_id = _validate_work_package_ref(parent_work_package_id, field_name="parent_work_package_id")
    safe_type = _validate_required_query(type, field_name="type", max_length=100)
    safe_subject = _validate_required_query(subject, field_name="subject", max_length=255)
    common = _validate_work_package_create_fields(
        description=description,
        version=version,
        project_phase=project_phase,
        assignee=assignee,
        responsible=responsible,
        priority=priority,
        category=category,
        custom_fields=custom_fields,
        start_date=start_date,
        due_date=due_date,
    )
    return await _run_tool(
        client.create_subtask(
            parent_work_package_id=safe_parent_id,
            type=safe_type,
            subject=safe_subject,
            description=common["description"],
            version=common["version"],
            project_phase=common["project_phase"],
            assignee=common["assignee"],
            responsible=common["responsible"],
            priority=common["priority"],
            category=common["category"],
            custom_fields=common["custom_fields"],
            start_date=common["start_date"],
            due_date=common["due_date"],
            confirm=confirm,
        )
    )


@register_tool
async def add_work_package_comment(
    ctx: Context,
    work_package_id: int | str,
    comment: str,
    internal: bool = False,
    notify: bool = False,
    confirm: bool = False,
) -> ActivityWriteResult:
    """Prepare or add a comment to a work package.

    The tool only writes when confirm=true. notify=false avoids change emails by default.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    The result never includes `details`/`created_at`, even on an ordinary,
    non-aggregated comment: OpenProject can aggregate a new comment into an
    existing, more recent journal entry (e.g. a prior status change) instead
    of always creating a fresh one, which would otherwise surface that
    unrelated change's details and timestamp here — and there is no reliable
    way to tell an aggregated response from a fresh one, so both fields are
    omitted unconditionally rather than only when aggregation is suspected.
    `user` is normally populated, but on rare cases where OpenProject's own
    write response omits it, a best-effort follow-up lookup fills it in; if
    that also comes back empty, `user` stays null even though the comment was
    saved successfully.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_comment = _validate_required_text(comment, field_name="comment", max_length=10_000)
    return await _run_tool(
        client.add_work_package_comment(
            work_package_id=safe_id,
            comment=safe_comment,
            internal=internal,
            notify=notify,
            confirm=confirm,
        )
    )


@register_tool
async def create_work_package_relation(
    ctx: Context,
    work_package_id: int | str,
    related_to_work_package_id: int | str,
    relation_type: str,
    description: str | None = None,
    lag: int | None = None,
    confirm: bool = False,
) -> RelationWriteResult:
    """Prepare or create a relation between work packages.

    Both work_package_id and related_to_work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    relation_type: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required.
    work_package_id becomes from_id and related_to_work_package_id becomes to_id — but OpenProject stores
    only one canonical type per pair and silently rewrites the other: creating with relation_type='precedes'
    (or 'blocked', 'duplicated', 'partof', 'required') is stored as the paired canonical type ('follows',
    'blocks', 'duplicates', 'includes', 'requires' respectively) with from_id/to_id SWAPPED relative to
    work_package_id/related_to_work_package_id. The canonical types themselves ('follows', 'blocks',
    'duplicates', 'includes', 'requires', and non-directional 'relates') are stored exactly as given, with
    from_id/to_id unswapped. This happens once at creation and does not depend on which work package's
    relations you later query — always read the actual type/from_id/to_id from the response rather than
    assuming they match what you requested.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_related_id = _validate_work_package_ref(related_to_work_package_id, field_name="related_to_work_package_id")
    safe_relation_type = _validate_relation_type(relation_type)
    safe_description = _validate_optional_text(description, field_name="description", max_length=255)
    safe_lag = _validate_optional_non_negative_int(lag, field_name="lag")
    return await _run_tool(
        client.create_work_package_relation(
            work_package_id=safe_id,
            related_to_work_package_id=safe_related_id,
            relation_type=safe_relation_type,
            description=safe_description,
            lag=safe_lag,
            confirm=confirm,
        )
    )


@register_tool
async def delete_relation(
    ctx: Context,
    relation_id: int,
    confirm: bool = False,
) -> RelationWriteResult:
    """Prepare or delete a relation between work packages."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    return await _run_tool(client.delete_relation(relation_id=safe_id, confirm=confirm))


@register_tool
async def list_my_open_work_packages(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> WorkPackageListResult:
    """List the current user's open assigned work packages.

    select fields: id, subject, due_date (see server instructions for
    select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. This query has no
    project scope of its own, so total is the real matching count only when
    OPENPROJECT_READ_PROJECTS is unrestricted ("*"); under a restricted scope,
    total always falls back to this page's item count, and next_offset/truncated
    are based on whether this page came back full rather than the server's own
    total, so nothing here ever reveals how many matches exist in projects you
    can't see. Page until next_offset is null either way.

    Each result row also carries custom_fields/custom_comments (not listed
    under "select fields" above since they are selectable/hideable only as a
    whole field, like every other field) with the same shape, caps, and
    OPENPROJECT_HIDE_CUSTOM_FIELDS key-only hide-matching as
    list_work_packages -- see that tool's docstring for the full details.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=WorkPackageSummary)
    return await _run_tool(client.list_my_open_work_packages(offset=safe_offset, limit=safe_limit))


@register_tool
async def list_work_package_attachments(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_total_size: bool = False,
) -> AttachmentListResult:
    """List attachments on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, title, file_name, description (see server instructions
    for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.

    include_total_size=true sums file_size_bytes across every attachment
    (independent of limit/offset) — OpenProject's attachments endpoint
    always returns the full list in one response, so this costs no extra
    request in the common case. Null if file_size_bytes is hidden by
    server configuration, rather than leaking it indirectly through a sum.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=AttachmentSummary)
    return await _run_tool(
        client.list_work_package_attachments(
            safe_id, offset=safe_offset, limit=safe_limit, include_total_size=include_total_size
        )
    )


@register_tool
async def get_attachment(
    ctx: Context,
    attachment_id: int,
) -> AttachmentSummary:
    """Get a single attachment by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.get_attachment(safe_id))


@register_tool
async def create_work_package_attachment(
    ctx: Context,
    work_package_id: int | str,
    file_path: str,
    description: str | None = None,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or upload an attachment to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_work_package_id = _validate_work_package_ref(work_package_id)
    safe_file_path = _validate_required_text(file_path, field_name="file_path", max_length=4096)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    return await _run_tool(
        client.create_work_package_attachment(
            work_package_id=safe_work_package_id,
            file_path=safe_file_path,
            description=safe_description,
            confirm=confirm,
        )
    )


@register_tool
async def delete_attachment(
    ctx: Context,
    attachment_id: int,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or delete an attachment."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.delete_attachment(attachment_id=safe_id, confirm=confirm))


@register_tool
async def list_time_entry_activities(ctx: Context) -> TimeEntryActivityListResult:
    """List available time entry activities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_time_entry_activities())


@register_tool
async def list_time_entries(
    ctx: Context,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    spent_on_from: str | None = None,
    spent_on_to: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_total_hours: bool = False,
) -> TimeEntryListResult:
    """List time entries with optional project, work package, user, and date filters.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, hours, spent_on, comment, activity, user, work_package_id
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed time entries returned on THIS page, not a full
    count of all matches — the search stops as soon as it has enough, so an
    exact total would need an extra full walk. Page until next_offset is
    null.

    include_total_hours=true sums `hours` (as an ISO 8601 duration) across
    every matching entry, independent of limit/offset — this runs its own
    full walk of the filtered collection (bounded; see
    total_hours_truncated), since OpenProject has no server-side sum for
    time entries (unlike list_work_packages's include_sums). Leave false
    unless the total is actually needed: it costs extra requests on top of
    the page this call already returns.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_spent_on_from = _validate_optional_date(spent_on_from, field_name="spent_on_from")
    safe_spent_on_to = _validate_optional_date(spent_on_to, field_name="spent_on_to")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=TimeEntrySummary)
    return await _run_tool(
        client.list_time_entries(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            spent_on_from=safe_spent_on_from,
            spent_on_to=safe_spent_on_to,
            offset=safe_offset,
            limit=safe_limit,
            include_total_hours=include_total_hours,
        )
    )


@register_tool
async def get_time_entry(
    ctx: Context,
    time_entry_id: int,
    text_limit: int | None = None,
) -> TimeEntrySummary:
    """Get a single time entry by id, including its full comment.

    The comment is returned in full by default (single time entries are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``comment_truncated`` is true and ``comment_length`` reports
    the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_time_entry(safe_id, text_limit=safe_text_limit))


@register_tool
async def create_time_entry(
    ctx: Context,
    activity: str,
    hours: str,
    spent_on: str,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    start_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or create a time entry.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    hours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).
    start_time is an ISO 8601 date-time and requires the instance setting "allow
    tracking of start and end times"; ignored otherwise. No end_time parameter --
    OpenProject derives it read-only from start_time + hours. Use
    create_time_entry_until to specify an end time instead of hours directly.
    """
    client = _client_from_context(ctx)
    safe_activity = _validate_required_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_required_duration(hours, field_name="hours")
    safe_spent_on = _validate_required_date(spent_on, field_name="spent_on")
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_comment = _validate_optional_text(comment, field_name="comment", max_length=10_000)
    if safe_project is None and safe_work_package_id is None:
        raise ValueError("Either project or work_package_id is required.")
    return await _run_tool(
        client.create_time_entry(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


@register_tool
async def update_time_entry(
    ctx: Context,
    time_entry_id: int,
    user: str | None = None,
    activity: str | None = None,
    hours: str | None = None,
    spent_on: str | None = None,
    start_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or update a time entry.

    hours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).
    start_time is an ISO 8601 date-time. No end_time parameter -- OpenProject
    derives it read-only from start_time + hours. Use update_time_entry_until
    to specify an end time instead of hours directly.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_activity = _validate_optional_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_optional_duration(hours, field_name="hours")
    safe_spent_on = _validate_optional_date(spent_on, field_name="spent_on")
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_comment = _validate_optional_update_text(comment, field_name="comment", max_length=10_000)
    _require_at_least_one(
        safe_user,
        safe_activity,
        safe_hours,
        safe_spent_on,
        safe_start_time,
        safe_comment,
        ongoing,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_time_entry(
            time_entry_id=safe_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


@register_tool
async def create_time_entry_until(
    ctx: Context,
    activity: str,
    start_time: str,
    end_time: str,
    spent_on: str,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    comment: str | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or create a time entry by start/end time instead of a duration.

    Computes hours = end_time - start_time locally; only hours and start_time
    are sent to OpenProject (end_time itself is never accepted by the server,
    see create_time_entry's docstring). end_time must be strictly after
    start_time. There is no ongoing parameter here -- a time entry with a
    known end time is complete, not still running; use create_time_entry for
    an ongoing entry.
    """
    client = _client_from_context(ctx)
    safe_activity = _validate_required_query(activity, field_name="activity", max_length=100)
    safe_start_time = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_required_datetime(end_time, field_name="end_time")
    safe_hours = _validate_required_duration(_duration_between(safe_start_time, safe_end_time), field_name="hours")
    safe_spent_on = _validate_required_date(spent_on, field_name="spent_on")
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_comment = _validate_optional_text(comment, field_name="comment", max_length=10_000)
    if safe_project is None and safe_work_package_id is None:
        raise ValueError("Either project or work_package_id is required.")
    return await _run_tool(
        client.create_time_entry(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            confirm=confirm,
        )
    )


@register_tool
async def update_time_entry_until(
    ctx: Context,
    time_entry_id: int,
    start_time: str,
    end_time: str,
    user: str | None = None,
    activity: str | None = None,
    spent_on: str | None = None,
    comment: str | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or update a time entry by start/end time instead of a duration.

    Computes hours = end_time - start_time locally; only hours and start_time
    are sent to OpenProject (end_time itself is never accepted by the server,
    see update_time_entry's docstring). end_time must be strictly after
    start_time. Always sets ongoing=False, since a completed time span with a
    known end time cannot still be running.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_start_time = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_required_datetime(end_time, field_name="end_time")
    safe_hours = _validate_required_duration(_duration_between(safe_start_time, safe_end_time), field_name="hours")
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_activity = _validate_optional_query(activity, field_name="activity", max_length=100)
    safe_spent_on = _validate_optional_date(spent_on, field_name="spent_on")
    safe_comment = _validate_optional_update_text(comment, field_name="comment", max_length=10_000)
    return await _run_tool(
        client.update_time_entry(
            time_entry_id=safe_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=False,
            confirm=confirm,
        )
    )


@register_tool
async def delete_time_entry(
    ctx: Context,
    time_entry_id: int,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or delete a time entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    return await _run_tool(client.delete_time_entry(time_entry_id=safe_id, confirm=confirm))


@register_tool
async def get_cost_entry(
    ctx: Context,
    cost_entry_id: int,
) -> CostEntrySummary:
    """Get a single cost entry by id.

    Cost entries are entirely read-only in OpenProject's API (Community
    Edition) -- there is no create/update/delete endpoint for this resource.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(cost_entry_id, field_name="cost_entry_id")
    return await _run_tool(client.get_cost_entry(safe_id))


@register_tool
async def list_work_package_cost_entries(
    ctx: Context,
    work_package_id: int | str,
) -> CostEntryListResult:
    """List all cost entries recorded against a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every cost entry for the work package in one call -- this endpoint
    is unpaginated on OpenProject's side (no offset/limit parameters exist).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_cost_entries(safe_id))


@register_tool
async def get_work_package_costs_by_type(
    ctx: Context,
    work_package_id: int | str,
) -> WorkPackageCostsByTypeResult:
    """Get a work package's costs aggregated by cost type.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    count is the number of distinct cost types with recorded spend on this
    work package, not a monetary total. Each result's spent_units is a
    quantity in that cost type's own unit (see get_cost_type for the unit
    name) -- there is no currency conversion or grand total computed here or
    by OpenProject's own API.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.get_work_package_costs_by_type(safe_id))


@register_tool
async def get_cost_type(
    ctx: Context,
    cost_type_id: int,
) -> CostTypeSummary:
    """Get a cost type by id.

    Cost types are entirely read-only in OpenProject's API (Community
    Edition) -- there is no create/update/delete endpoint, and no collection
    GET either (no list_cost_types tool exists because the endpoint does not
    exist upstream).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(cost_type_id, field_name="cost_type_id")
    return await _run_tool(client.get_cost_type(safe_id))


@register_tool
async def get_github_pull_request(
    ctx: Context,
    github_pull_request_id: int,
) -> GithubPullRequestSummary:
    """Get a single GitHub pull request by its own id.

    GitHub pull requests are read-only mirror rows synced by OpenProject's own
    GitHub App integration -- never creatable via this API. An empty or 404
    result can mean either the pull request doesn't exist, or the GitHub App
    integration isn't configured on this instance; OpenProject's API does not
    distinguish these cases.

    Unlike work-package-scoped lookups in this domain, this global lookup
    relies on OpenProject's own visibility check (whether the linked work
    package is visible to the API token), not on this MCP's
    OPENPROJECT_READ_PROJECTS allowlist -- the pull request payload carries no
    project link for this MCP to check against.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(github_pull_request_id, field_name="github_pull_request_id")
    return await _run_tool(client.get_github_pull_request(safe_id))


@register_tool
async def list_work_package_github_pull_requests(
    ctx: Context,
    work_package_id: int | str,
) -> GithubPullRequestListResult:
    """List all GitHub pull requests linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked pull request in one call -- this endpoint is
    unpaginated on OpenProject's side (no offset/limit parameters exist). An
    empty result can mean either no pull requests are linked, or the GitHub
    App integration isn't configured on this instance; OpenProject's API does
    not distinguish these cases.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_github_pull_requests(safe_id))


@register_tool
async def list_work_package_gitlab_issues(
    ctx: Context,
    work_package_id: int | str,
) -> GitlabIssueListResult:
    """List all GitLab issues linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked issue in one call -- this endpoint is unpaginated on
    OpenProject's side (no offset/limit parameters exist). An empty result can
    mean either no issues are linked, or the GitLab integration isn't
    configured on this instance; OpenProject's API does not distinguish these
    cases. No single-item get_gitlab_issue tool exists because no such
    endpoint exists upstream -- only this work-package-scoped list.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_gitlab_issues(safe_id))


@register_tool
async def list_work_package_gitlab_merge_requests(
    ctx: Context,
    work_package_id: int | str,
) -> GitlabMergeRequestListResult:
    """List all GitLab merge requests linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked merge request in one call -- this endpoint is
    unpaginated on OpenProject's side (no offset/limit parameters exist). An
    empty result can mean either no merge requests are linked, or the GitLab
    integration isn't configured on this instance; OpenProject's API does not
    distinguish these cases. No single-item get_gitlab_merge_request tool
    exists because no such endpoint exists upstream -- only this
    work-package-scoped list.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_gitlab_merge_requests(safe_id))


@register_tool
async def get_work_package_relations(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> RelationListResult:
    """Get all relations for a work package (blocks, relates to, duplicates, etc.).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    type/from_id/to_id reflect how OpenProject actually stored the relation, which does not depend on
    which work package's relations you query — but can differ from how it was originally requested, since
    OpenProject canonicalizes some relation types at creation time (e.g. a relation requested as 'precedes'
    is stored as 'follows' with from_id/to_id swapped; see create_work_package_relation). Use from_id/to_id
    together with type, not the request you expect to have made, to determine the actual direction.

    Each result additionally carries queried_perspective, a caller-relative reading of the same relation
    from work_package_id's own side — never a replacement for type/from_id/to_id, which stay unchanged.
    queried_perspective.direction is "from" or "to" (which raw id equals work_package_id);
    queried_perspective.effective_type is the type as read FROM work_package_id's side (e.g. a stored
    "blocks" relation reads as effective_type="blocked" when work_package_id is the to_id side, "blocks"
    when it's the from_id side). queried_perspective.predecessor_id/successor_id are populated only for
    the precedes/follows type pair (OpenProject's own scheduling-relevant relation types); both stay null
    for every other type, since no other type has an equivalent first/second concept.

    select fields: id, type, to_id (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed relations returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=RelationSummary)
    return await _run_tool(client.get_work_package_relations(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_work_package_activities(
    ctx: Context,
    work_package_id: int | str,
    limit: int | None = None,
    text_limit: int | None = None,
    select: list[str] | None = None,
) -> ActivityListResult:
    """Get the activity log for a work package, most recent first.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Comments are returned in full by default (this is one work package's own
    history, not an open-ended multi-row list — same rationale as
    get_work_package). Pass ``text_limit`` to cap each comment at that many
    characters; when a comment is cut, ``comment_truncated`` is true and
    ``comment_length`` reports its real length.

    select fields: id, type, created_at (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_limit = _validate_limit(limit)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    _validate_select(select, row_type=ActivitySummary)
    return await _run_tool(client.get_work_package_activities(safe_id, limit=safe_limit, text_limit=safe_text_limit))


@register_tool
async def list_work_package_reactions(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> EmojiReactionListResult:
    """List emoji reactions across a work package's comment activities.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: reaction, count (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=EmojiReactionSummary)
    return await _run_tool(client.list_work_package_reactions(safe_id))


@register_tool
async def toggle_activity_emoji_reaction(
    ctx: Context,
    activity_id: int,
    reaction: str,
    confirm: bool = False,
) -> EmojiReactionWriteResult:
    """Toggle an emoji reaction on a work package comment activity.

    Adds the reaction if absent, removes it if already present. `reaction` is
    one of: thumbs_up, thumbs_down, grinning_face_with_smiling_eyes,
    confused_face, heart, party_popper, rocket, eyes. Set confirm=true to apply
    it; call without confirm=true first to get a preview.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(activity_id, field_name="activity_id")
    safe_reaction = _validate_required_query(reaction, field_name="reaction", max_length=50)
    return await _run_tool(client.toggle_activity_emoji_reaction(safe_id, safe_reaction, confirm=confirm))


@register_tool
async def list_statuses(ctx: Context) -> StatusListResult:
    """List all available work package statuses.

    Read-only: statuses cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.list_statuses())


@register_tool
async def get_status(ctx: Context, status_id: int) -> StatusSummary:
    """Get a single work package status by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(status_id, field_name="status_id")
    return await _run_tool(client.get_status(safe_id))


@register_tool
async def list_priorities(ctx: Context) -> PriorityListResult:
    """List all available work package priorities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_priorities())


@register_tool
async def get_priority(ctx: Context, priority_id: int) -> PrioritySummary:
    """Get a single work package priority by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(priority_id, field_name="priority_id")
    return await _run_tool(client.get_priority(safe_id))


@register_tool
async def list_types(
    ctx: Context,
    project: str | None = None,
) -> TypeListResult:
    """List all available work package types, optionally filtered by project.

    Read-only: types cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    return await _run_tool(client.list_types(project=safe_project))


@register_tool
async def get_type(ctx: Context, type_id: int) -> TypeSummary:
    """Get a single work package type by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(type_id, field_name="type_id")
    return await _run_tool(client.get_type(safe_id))


@register_tool
async def list_work_package_watchers(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> WatcherListResult:
    """List watchers of a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, name (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=WatcherSummary)
    return await _run_tool(client.list_work_package_watchers(safe_id))


@register_tool
async def set_work_package_watcher(
    ctx: Context,
    work_package_id: int | str,
    user_id: int,
    watching: bool,
    confirm: bool = False,
) -> WatcherWriteResult:
    """Prepare or add/remove a watcher on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    watching=true adds the watcher; watching=false removes it. The two
    previews are NOT symmetric: watching=true's preview looks up and returns
    the real watcher's summary (result is populated); watching=false's
    preview makes no extra lookup and always returns result=null.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_user_id = _validate_positive_int(user_id, field_name="user_id")
    if watching:
        return await _run_tool(client.add_work_package_watcher(safe_wp_id, safe_user_id, confirm=confirm))
    return await _run_tool(client.remove_work_package_watcher(safe_wp_id, safe_user_id, confirm=confirm))


@register_tool
async def list_work_package_file_links(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> FileLinkListResult:
    """List Nextcloud file links attached to a work package (Community Edition).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, title (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=FileLinkSummary)
    return await _run_tool(client.list_work_package_file_links(safe_id))


@register_tool
async def delete_file_link(
    ctx: Context,
    file_link_id: int,
    confirm: bool = False,
) -> FileLinkWriteResult:
    """Prepare or delete a Nextcloud file link."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(file_link_id, field_name="file_link_id")
    return await _run_tool(client.delete_file_link(safe_id, confirm=confirm))


@register_tool
async def list_grids(
    ctx: Context,
    scope: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> GridListResult:
    """List dashboard grids, optionally filtered by scope (page path).

    select fields: id, scope (see server instructions for select's general
    semantics). limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned next_offset as
    the next call's offset to page past the cap. total is only the count of
    allowed grids returned on THIS page, not a full count of all matches —
    the search stops as soon as it has enough, so an exact total would need
    an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_scope = _validate_optional_query(scope, field_name="scope", max_length=500)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=GridSummary)
    return await _run_tool(client.list_grids(scope=safe_scope, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_grid(ctx: Context, grid_id: int) -> GridSummary:
    """Get a single dashboard grid by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.get_grid(safe_id))


@register_tool
async def create_grid(
    ctx: Context,
    name: str,
    scope: str,
    row_count: int | None = None,
    column_count: int | None = None,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or create a dashboard grid for a scope such as `/my/page` or `/projects/<identifier>`."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_scope = _validate_required_query(scope, field_name="scope", max_length=500)
    if not safe_scope.startswith("/"):
        raise ValueError("scope must start with '/'.")
    safe_row_count = _validate_positive_int(row_count, field_name="row_count") if row_count is not None else None
    safe_column_count = (
        _validate_positive_int(column_count, field_name="column_count") if column_count is not None else None
    )
    return await _run_tool(
        client.create_grid(
            name=safe_name,
            scope=safe_scope,
            row_count=safe_row_count,
            column_count=safe_column_count,
            confirm=confirm,
        )
    )


@register_tool
async def update_grid(
    ctx: Context,
    grid_id: int,
    name: str | None = None,
    row_count: int | None = None,
    column_count: int | None = None,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or update a dashboard grid.

    Omitted fields stay unchanged. Set confirm=true to write.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_row_count = _validate_positive_int(row_count, field_name="row_count") if row_count is not None else None
    safe_column_count = (
        _validate_positive_int(column_count, field_name="column_count") if column_count is not None else None
    )
    _require_at_least_one(
        safe_name, safe_row_count, safe_column_count, message="At least one field to update is required."
    )
    return await _run_tool(
        client.update_grid(
            grid_id=safe_id,
            name=safe_name,
            row_count=safe_row_count,
            column_count=safe_column_count,
            confirm=confirm,
        )
    )


@register_tool
async def delete_grid(
    ctx: Context,
    grid_id: int,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or delete a dashboard grid. Only deletes when called again with confirm=true."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.delete_grid(grid_id=safe_id, confirm=confirm))


@register_tool
async def list_relations(
    ctx: Context,
    relation_type: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> RelationListResult:
    """List all relations across the instance, optionally filtered by type (e.g. 'blocks', 'follows').

    type/from_id/to_id reflect how OpenProject actually stored the relation (it does not change depending
    on which work package's relations you're viewing), which can differ from how it was originally
    requested — OpenProject canonicalizes some relation types at creation time (e.g. a relation requested
    as 'precedes' is stored as 'follows' with from_id/to_id swapped; see create_work_package_relation).
    Filtering by relation_type matches the stored (canonical) type, not necessarily the type a caller
    originally requested when creating it.

    Each result's queried_perspective field is always null here — a caller-relative reading needs one
    anchor work package to read the relation FROM, and this instance-wide listing has none. Use
    get_work_package_relations instead when you need queried_perspective populated.

    select fields: id, type, to_id (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed relations returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=RelationSummary)
    return await _run_tool(client.list_relations(relation_type=safe_type, offset=safe_offset, limit=safe_limit))


@register_tool
async def update_relation(
    ctx: Context,
    relation_id: int,
    relation_type: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> RelationUpdateResult:
    """Prepare or update the type or description of a relation. Set confirm=true to write.

    relation_type is subject to the same write-time canonicalization as create_work_package_relation:
    setting it to a "reverse" pair member (precedes, blocked, duplicated, partof, required) rewrites the
    stored relation to the paired canonical type (follows, blocks, duplicates, includes, requires) with
    from_id/to_id swapped relative to the relation's existing from/to. Read the actual type/from_id/to_id
    back afterward rather than assuming they match what was requested.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    safe_desc = _validate_optional_update_text(description, field_name="description", max_length=500)
    return await _run_tool(
        client.update_relation(
            relation_id=safe_id,
            relation_type=safe_type,
            description=safe_desc,
            confirm=confirm,
        )
    )


def _pad_fractional_seconds(value: str) -> str:
    """Pad a `.d{1,6}` fractional-seconds fragment to exactly 6 digits.

    Python's `datetime.fromisoformat` only accepts 0, 3, or 6 fractional
    digits before 3.11 (this project supports 3.10+); the date-time validator
    in tools_validation.py accepts any count from 1 to 6 (matching what
    OpenProject itself accepts), so a value like "09:00:07.5Z" must be
    normalized to "09:00:07.500000Z" before parsing, not just have "Z"
    swapped for "+00:00".
    """
    return re.sub(r"\.(\d{1,6})(?=Z|[+-]\d{2}:\d{2}$)", lambda m: f".{m.group(1):0<6}", value)


def _duration_between(start_time: str, end_time: str) -> str:
    """Compute an ISO 8601 duration string for end_time - start_time.

    Used by create_time_entry_until/update_time_entry_until to derive `hours`
    locally, since OpenProject's API accepts an ISO 8601 duration in `hours`,
    not `end_time`, as a write field (see the create_time_entry docstring).
    Uses timedelta's own exact integer fields (days/seconds/microseconds),
    never total_seconds() -- a float -- for the whole-unit breakdown, so the
    hours/minutes/seconds split is exact by construction.
    """
    start = datetime.datetime.fromisoformat(_pad_fractional_seconds(start_time).replace("Z", "+00:00"))
    end = datetime.datetime.fromisoformat(_pad_fractional_seconds(end_time).replace("Z", "+00:00"))
    delta = end - start
    if delta <= datetime.timedelta(0):
        raise ValueError("end_time must be after start_time.")
    total_seconds = delta.days * 86400 + delta.seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    microseconds = delta.microseconds
    # Durations generated here use a fractional value only on the seconds
    # component; the ISO 8601 duration validator in tools_validation.py
    # accepts that shape. `microseconds` is an exact integer (0-999999) added
    # to the already-whole `seconds`, then formatted with a fixed decimal
    # count (never `%g`/`str(float)`), avoiding both scientific notation on
    # tiny fractions and any rounding-induced carry.
    if microseconds:
        seconds_str = f"{seconds + microseconds / 1_000_000:.6f}".rstrip("0").rstrip(".")
    else:
        seconds_str = str(seconds)
    parts = [
        f"{hours}H" if hours else "",
        f"{minutes}M" if minutes else "",
        f"{seconds_str}S" if seconds or microseconds else "",
    ]
    body = "".join(p for p in parts if p)
    return f"PT{body}"
