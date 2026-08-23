from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import (
    tools_misc,  # noqa: F401 -- @register_tool side effect
    tools_query,  # noqa: F401 -- @register_tool side effect
    tools_query_schema,  # noqa: F401 -- @register_tool side effect
    tools_user_schedule,  # noqa: F401 -- @register_tool side effect
)
from .config import Settings
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
from .tools_attachments import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports all six of these from here
    create_work_package_attachment,
    delete_attachment,
    delete_file_link,
    get_attachment,
    list_work_package_attachments,
    list_work_package_file_links,
)
from .tools_boards import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports these from here
    create_board,
    delete_board,
    get_board,
    list_boards,
    update_board,
)
from .tools_categories import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports get_category/list_categories from here
    get_category,
    list_categories,
)
from .tools_costs import (  # noqa: F401 -- @register_tool side effect; re-exported for consistency with other domain modules (no existing test currently imports these four directly from tools.py)
    get_cost_entry,
    get_cost_type,
    get_work_package_costs_by_type,
    list_work_package_cost_entries,
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
from .tools_grids import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports these five from here
    create_grid,
    delete_grid,
    get_grid,
    list_grids,
    update_grid,
)
from .tools_integrations import (  # noqa: F401 -- @register_tool side effect; re-exported for consistency
    get_github_pull_request,
    list_work_package_github_pull_requests,
    list_work_package_gitlab_issues,
    list_work_package_gitlab_merge_requests,
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
from .tools_reference_data import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports all six of these and test_trimming.py imports get_status from here
    get_priority,
    get_status,
    get_type,
    list_priorities,
    list_statuses,
    list_types,
)
from .tools_relations import (  # noqa: F401 -- @register_tool side effect; re-exported, test_tool_validation.py/test_work_package_tools.py/test_trimming.py import several of these from here
    create_work_package_relation,
    delete_relation,
    get_work_package_relations,
    list_relations,
    update_relation,
)
from .tools_reminders import (  # noqa: F401 -- @register_tool side effect; re-exported, several tests import these from here
    create_work_package_reminder,
    delete_reminder,
    list_reminders,
    update_reminder,
)
from .tools_runtime import (
    register_selected_tools,
)
from .tools_sprints import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports list_sprints/get_sprint from here
    get_backlog_bucket,
    get_sprint,
    list_backlog_buckets,
    list_sprints,
)
from .tools_time_entries import (  # noqa: F401 -- @register_tool side effect; re-exported, test_project_and_domain_tools.py imports all eight tool functions and test_tool_validation.py imports both private helpers from here
    _duration_between,
    _pad_fractional_seconds,
    create_time_entry,
    create_time_entry_until,
    delete_time_entry,
    get_time_entry,
    list_time_entries,
    list_time_entry_activities,
    update_time_entry,
    update_time_entry_until,
)
from .tools_validation import (
    _validate_positive_int,  # noqa: F401 -- re-exported, test_tool_validation.py imports this from here
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
from .tools_watchers import (  # noqa: F401 -- @register_tool side effect; re-exported, test_work_package_tools.py imports both of these from here
    list_work_package_watchers,
    set_work_package_watcher,
)
from .tools_work_packages import (  # noqa: F401 -- @register_tool side effect; re-exported, test_trimming.py/test_tool_validation.py/test_work_package_tools.py import several of these from here
    add_work_package_comment,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_subtask,
    create_work_package,
    delete_work_package,
    get_work_package,
    get_work_package_activities,
    get_work_packages,
    list_my_open_work_packages,
    list_work_package_reactions,
    list_work_packages,
    search_work_packages,
    toggle_activity_emoji_reaction,
    update_work_package,
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
# — an empty root disables local uploads entirely (app/services/
# attachment_service.py's _attachment_root has no cwd fallback), so registering the tool without a root
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
