from __future__ import annotations

import functools
import re
from collections.abc import Callable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, cast

from mcp.server.fastmcp import Context, FastMCP

from .client import (
    BATCH_READ_MAX_IDS,
    CLEAR,
    CLEAR_PARENT,
    CLEAR_VERSION,
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,
    TransportError,
)
from .config import TEXT_LIMIT_MAX, Settings
from .models import (
    ActionListResult,
    ActivityListResult,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BatchWorkPackageReadResult,
    BoardDetail,
    BoardListResult,
    BoardWriteResult,
    BulkWorkPackageWriteResult,
    CapabilityListResult,
    CategoryListResult,
    CategorySummary,
    CurrentUser,
    CustomOptionSummary,
    DocumentDetail,
    DocumentListResult,
    DocumentWriteResult,
    EmojiReactionListResult,
    EmojiReactionWriteResult,
    FavoriteWriteResult,
    FileLinkListResult,
    FileLinkWriteResult,
    GridListResult,
    GridSummary,
    GridWriteResult,
    GroupDetail,
    GroupListResult,
    GroupWriteResult,
    HelpTextListResult,
    HelpTextSummary,
    InstanceConfiguration,
    JobStatusDetail,
    MembershipListResult,
    MembershipSummary,
    MembershipWriteResult,
    NewsDetail,
    NewsListResult,
    NewsWriteResult,
    NonWorkingDayListResult,
    NotificationListResult,
    NotificationMarkResult,
    PrincipalListResult,
    PriorityListResult,
    PrioritySummary,
    ProjectAccessSummary,
    ProjectAdminContext,
    ProjectConfiguration,
    ProjectCopyResult,
    ProjectListResult,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectPhaseDefinitionListResult,
    ProjectSummary,
    ProjectWorkPackageContext,
    ProjectWriteResult,
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
    RelationListResult,
    RelationUpdateResult,
    RelationWriteResult,
    ReminderListResult,
    ReminderWriteResult,
    RenderedText,
    RoleListResult,
    SortCriterion,
    SprintDetail,
    SprintListResult,
    StatusListResult,
    StatusSummary,
    TimeEntryActivityListResult,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
    TypeListResult,
    TypeSummary,
    UserDetail,
    UserListResult,
    UserPreferences,
    UserPreferencesWriteResult,
    UserSummary,
    UserWriteResult,
    VersionDetail,
    VersionListResult,
    VersionWriteResult,
    ViewDetail,
    ViewListResult,
    WatcherListResult,
    WatcherWriteResult,
    WikiPageDetail,
    WorkingDayListResult,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ISO 8601 date-time, e.g. 2026-12-01T09:00:00Z or with a +HH:MM offset.
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
ISO8601_DURATION_RE = re.compile(r"^P(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)$")
PROJECT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A project-based work package reference: a project identifier followed by "-<number>"
# (e.g. PROJ-123). The numeric form is handled separately before this pattern applies.
WORK_PACKAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}-\d+$")
RELATION_TYPE_RE = re.compile(
    r"^(relates|duplicates|duplicated|blocks|blocked|precedes|follows|includes|partof|requires|required)$"
)


# ── Tool classification (OPM-123) ───────────────────────────────────────────
#
# Single source of truth for which tool belongs to which scope, replacing the
# previously hand-written if/tool(...) blocks. Registration now follows
# exactly the scopes each tool's client method actually enforces at runtime
# (verified against client.py, not guessed) — this is a real behavior change
# for existing OPENPROJECT_ENABLE_*_READ flags: several tools that were
# always registered regardless of any flag (e.g. get_current_user,
# list_notifications) now correctly disappear when their real scope is
# disabled, instead of staying visible and failing only when called.
#
# This is Phase 1 of a larger authorization redesign (OPM-122); Phase 4
# (OPM-126) replaced the 5 per-scope read booleans and the metadata-tools flag
# with a single OPENPROJECT_TOOLS group list ("personal" and "extended" joined
# the 5 original scopes as first-class groups) and introduced the independent
# OPENPROJECT_PERSONAL_WRITE flag.
#
# "personal" is NOT a normal write scope: the other 5 scopes treat read and
# write as independent axes (a write tool appears once its write flag is on,
# regardless of the paired read flag). For "personal", the repo owner decided
# that "personal" in OPENPROJECT_TOOLS controls visibility of the WHOLE
# personal surface (read AND write), with OPENPROJECT_PERSONAL_WRITE acting as
# an additional gate only within that already-visible surface — an AND, not
# an independent toggle. PERSONAL_MUTATION_TOOLS is therefore its own named
# constant, handled by a bespoke branch in enabled_tool_names() (mirroring
# the existing ADMIN_WRITE_TOOLS bespoke branch) rather than being folded into
# WRITE_TOOLS_BY_SCOPE, which would run it through the generic independent
# read/write iteration and lose the AND semantics.
PERSONAL_MUTATION_TOOLS: tuple[str, ...] = (
    "update_my_preferences",
    "mark_notification_read",
    "mark_all_notifications_read",
)

READ_TOOLS_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "project": (
        "list_projects",
        "get_project",
        "get_project_admin_context",
        "get_project_configuration",
        "list_sprints",
        "list_project_sprints",
        "get_sprint",
        "list_documents",
        "get_document",
        "list_news",
        "get_news",
        "get_wiki_page",
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
        "list_relations",
    ),
    "membership": (
        "list_project_memberships",
        "get_membership",
        "list_roles",
        "list_principals",
        "list_users",
        "get_user",
        "list_groups",
        "get_group",
        "get_current_user",
        "list_actions",
        "list_capabilities",
    ),
    "version": ("list_versions", "get_version"),
    "board": ("list_boards", "get_board"),
    "personal": ("get_my_preferences", "list_notifications"),
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

WRITE_TOOLS_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "project": (
        "create_project",
        "update_project",
        "delete_project",
        "copy_project",
        "add_project_favorite",
        "remove_project_favorite",
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
        "create_work_package_attachment",
        "delete_attachment",
        "add_work_package_watcher",
        "remove_work_package_watcher",
        "create_time_entry",
        "update_time_entry",
        "delete_time_entry",
        "update_relation",
        "delete_file_link",
    ),
    "membership": ("create_membership", "update_membership", "delete_membership"),
    "version": ("create_version", "update_version", "delete_version"),
    "board": ("create_board", "update_board", "delete_board"),
}

ADMIN_WRITE_TOOLS: tuple[str, ...] = (
    "create_user",
    "update_user",
    "delete_user",
    "lock_user",
    "unlock_user",
    "create_group",
    "update_group",
    "delete_group",
)
# Gated by settings.enable_admin_write directly (checked in enabled_tool_names
# below), not via write_enabled("admin") — "admin" is deliberately not a key
# of Settings.write_enabled's scope table (see config.py).

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

    for scope, names in READ_TOOLS_BY_SCOPE.items():
        if settings.read_enabled(scope):
            include(tuple(name for name in names if additional_scopes_ok(name)))

    for scope, names in WRITE_TOOLS_BY_SCOPE.items():
        if settings.write_enabled(scope):
            include(tuple(name for name in names if additional_scopes_ok(name)))

    if settings.enable_admin_write:
        include(ADMIN_WRITE_TOOLS)

    # Bespoke AND-gate (not the generic independent read/write iteration above):
    # personal mutations need BOTH "personal" visible AND OPENPROJECT_PERSONAL_WRITE
    # on, see the constant's docstring-comment above.
    if settings.read_enabled("personal") and settings.write_enabled("personal"):
        include(PERSONAL_MUTATION_TOOLS)

    return tuple(enabled)


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    # Register a tool with error-categorization applied, so every failure reaches
    # the agent with a stable [category] prefix.
    #
    # Tools that return a list/write/bulk result are routed through _to_payload for
    # context reduction (OPM-65/66/71): payload is dropped on confirmed writes,
    # count/truncated on lists, and `select` trims rows. Those tools are registered
    # with structured_output=False so FastMCP does not build a fixed dataclass
    # output schema — it serializes the trimmed dict we return verbatim, letting us
    # omit keys. Detection is by the result model's fields, so no per-tool tagging
    # is needed and it cannot drift. Tool bodies are unchanged; they still return
    # their dataclass, which the wrapper trims.
    #
    # When any hide-field config is active, every dataclass-returning tool is
    # trimmed too, so single-entity reads (get_*) can drop hidden keys entirely
    # rather than emit them as null (OPM-72). This only widens schema loss when the
    # operator opted into hiding.
    hide_active = bool(settings.hidden_fields)

    def tool(fn):
        if not (_returns_trimmable(fn) or (hide_active and _returns_dataclass(fn))):
            return mcp.tool()(_categorize_tool_errors(fn))

        wrapped = _categorize_tool_errors(fn)

        @functools.wraps(wrapped)
        async def trimming(*args, **kwargs):
            select = _normalize_select(kwargs.get("select"))
            return _to_payload(await wrapped(*args, **kwargs), select=select)

        return mcp.tool(structured_output=False)(trimming)

    for name in enabled_tool_names(settings):
        tool(_TOOL_FUNCTIONS[name])


async def list_projects(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ProjectListResult:
    """List visible projects with optional name or identifier search.

    select restricts each result row to the given fields (e.g. ["id", "name",
    "identifier"]); an invalid name returns the allowed set. Common fields: id,
    name, identifier, active, public, status, parent_name, created_at, updated_at.
    """
    client = _client_from_context(ctx)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=ProjectSummary)
    return await _run_tool(client.list_projects(search=safe_search, offset=safe_offset, limit=safe_limit))


async def get_project(
    ctx: Context,
    project: str,
) -> ProjectSummary:
    """Get a compact project summary by id or identifier.

    project: numeric id (e.g., 7) or identifier (e.g., "opm-openproject-ce-mcp"), not display name.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.get_project(safe_project))


async def list_sprints(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
) -> SprintListResult:
    """List Backlogs sprints visible to the current token.

    Requires the OpenProject Backlogs module; unavailable instances return a clear not-found message.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_sprints(offset=safe_offset, limit=safe_limit))


async def list_project_sprints(
    ctx: Context,
    project: str,
    offset: int = 1,
    limit: int | None = None,
) -> SprintListResult:
    """List Backlogs sprints for a project by id or identifier."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_project_sprints(safe_project, offset=safe_offset, limit=safe_limit))


async def get_sprint(
    ctx: Context,
    sprint_id: int,
) -> SprintDetail:
    """Get a Backlogs sprint by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(sprint_id, field_name="sprint_id")
    return await _run_tool(client.get_sprint(safe_id))


async def get_project_admin_context(
    ctx: Context,
    project: str,
) -> ProjectAdminContext:
    """Return project admin metadata such as lifecycle statuses, parent options, and writable fields."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.get_project_admin_context(safe_project))


async def get_project_configuration(
    ctx: Context,
    project: str,
) -> ProjectConfiguration:
    """Return project-scoped configuration such as internal comment support."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.get_project_configuration(safe_project))


async def create_project(
    ctx: Context,
    name: str,
    identifier: str,
    description: str | None = None,
    public: bool | None = None,
    active: bool | None = None,
    status: str | None = None,
    status_explanation: str | None = None,
    parent: str | None = None,
    confirm: bool = False,
) -> ProjectWriteResult:
    """Prepare or create a project."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_project_identifier(identifier)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_status_explanation = _validate_optional_text(
        status_explanation, field_name="status_explanation", max_length=10_000
    )
    safe_parent = _validate_optional_project_ref(parent)
    return await _run_tool(
        client.create_project(
            name=safe_name,
            identifier=safe_identifier,
            description=safe_description,
            public=public,
            active=active,
            status=safe_status,
            status_explanation=safe_status_explanation,
            parent=safe_parent,
            confirm=confirm,
        )
    )


async def copy_project(
    ctx: Context,
    source_project: str,
    name: str,
    identifier: str,
    description: str | None = None,
    public: bool | None = None,
    active: bool | None = None,
    status: str | None = None,
    status_explanation: str | None = None,
    parent: str | None = None,
    confirm: bool = False,
) -> ProjectCopyResult:
    """Prepare or copy an existing project into a new project."""
    client = _client_from_context(ctx)
    safe_source_project = _validate_project_ref(source_project)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_project_identifier(identifier)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_status_explanation = _validate_optional_text(
        status_explanation, field_name="status_explanation", max_length=10_000
    )
    safe_parent = _validate_optional_project_ref(parent)
    return await _run_tool(
        client.copy_project(
            source_project=safe_source_project,
            name=safe_name,
            identifier=safe_identifier,
            description=safe_description,
            public=public,
            active=active,
            status=safe_status,
            status_explanation=safe_status_explanation,
            parent=safe_parent,
            confirm=confirm,
        )
    )


async def get_job_status(
    ctx: Context,
    job_status_id: int,
) -> JobStatusDetail:
    """Get the current status of a background job such as project copy."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(job_status_id, field_name="job_status_id")
    return await _run_tool(client.get_job_status(safe_id))


async def update_project(
    ctx: Context,
    project: str,
    name: str | None = None,
    identifier: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    active: bool | None = None,
    status: str | None = None,
    status_explanation: str | None = None,
    parent: str | None = None,
    confirm: bool = False,
) -> ProjectWriteResult:
    """Prepare or update a project.

    Pass 'none' to parent to make the project top-level (remove its parent).
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_optional_project_identifier(identifier)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_status_explanation = _validate_optional_text(
        status_explanation, field_name="status_explanation", max_length=10_000
    )
    # parent: 'none' (any case) makes the project top-level; otherwise a project ref.
    safe_parent = _clearable(parent, lambda v: _validate_optional_project_ref(v))
    if not any(
        value is not None
        for value in (
            safe_name,
            safe_identifier,
            safe_description,
            public,
            active,
            safe_status,
            safe_status_explanation,
            safe_parent,
        )
    ):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_project(
            project_ref=safe_project,
            name=safe_name,
            identifier=safe_identifier,
            description=safe_description,
            public=public,
            active=active,
            status=safe_status,
            status_explanation=safe_status_explanation,
            parent=safe_parent,
            confirm=confirm,
        )
    )


async def delete_project(
    ctx: Context,
    project: str,
    confirm: bool = False,
) -> ProjectWriteResult:
    """Prepare or delete a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.delete_project(project_ref=safe_project, confirm=confirm))


async def list_roles(ctx: Context) -> RoleListResult:
    """List OpenProject roles visible to the current user."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_roles())


async def list_principals(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> PrincipalListResult:
    """List users and groups that can be used for project memberships."""
    client = _client_from_context(ctx)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_principals(search=safe_search, offset=safe_offset, limit=safe_limit))


async def list_users(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> UserListResult:
    """List users visible to the current token.

    select restricts each result row to the given fields (e.g. ["id", "name",
    "login"]); an invalid name returns the allowed set. Common fields: id, name,
    login, email, status, admin, created_at, updated_at.
    """
    client = _client_from_context(ctx)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=UserSummary)
    return await _run_tool(client.list_users(search=safe_search, offset=safe_offset, limit=safe_limit))


async def get_user(
    ctx: Context,
    user: str,
) -> UserDetail:
    """Get a user by id, login, or `me` when supported by OpenProject."""
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user, field_name="user", max_length=100)
    return await _run_tool(client.get_user(safe_user))


async def list_groups(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> GroupListResult:
    """List groups visible to the current token."""
    client = _client_from_context(ctx)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_groups(search=safe_search, offset=safe_offset, limit=safe_limit))


async def get_group(
    ctx: Context,
    group_id: int,
) -> GroupDetail:
    """Get a single group by id."""
    client = _client_from_context(ctx)
    safe_group_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.get_group(safe_group_id))


async def list_actions(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
) -> ActionListResult:
    """List API actions exposed by OpenProject."""
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_actions(offset=safe_offset, limit=safe_limit))


async def list_capabilities(
    ctx: Context,
    project: str | None = None,
    capability_id: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> CapabilityListResult:
    """List API capabilities exposed by OpenProject."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_capability_id = _validate_optional_query(capability_id, field_name="capability_id", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_capabilities(
            project=safe_project,
            capability_id=safe_capability_id,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


async def get_query_filter(
    ctx: Context,
    filter_id: str,
) -> QueryFilterSummary:
    """Get a single query filter by id."""
    client = _client_from_context(ctx)
    safe_filter_id = _validate_required_query(filter_id, field_name="filter_id", max_length=100)
    return await _run_tool(client.get_query_filter(safe_filter_id))


async def get_query_column(
    ctx: Context,
    column_id: str,
) -> QueryColumnSummary:
    """Get a single query column by id."""
    client = _client_from_context(ctx)
    safe_column_id = _validate_required_query(column_id, field_name="column_id", max_length=100)
    return await _run_tool(client.get_query_column(safe_column_id))


async def get_query_operator(
    ctx: Context,
    operator_id: str,
) -> QueryOperatorSummary:
    """Get a single query operator by id."""
    client = _client_from_context(ctx)
    safe_operator_id = _validate_required_query(operator_id, field_name="operator_id", max_length=100)
    return await _run_tool(client.get_query_operator(safe_operator_id))


async def get_query_sort_by(
    ctx: Context,
    sort_by_id: str,
) -> QuerySortBySummary:
    """Get a single query sort-by definition by id."""
    client = _client_from_context(ctx)
    safe_sort_by_id = _validate_required_query(sort_by_id, field_name="sort_by_id", max_length=100)
    return await _run_tool(client.get_query_sort_by(safe_sort_by_id))


async def list_query_filter_instance_schemas(
    ctx: Context,
    project: str | None = None,
) -> QueryFilterInstanceSchemaListResult:
    """List query filter instance schemas globally or for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    return await _run_tool(client.list_query_filter_instance_schemas(project=safe_project))


async def get_query_filter_instance_schema(
    ctx: Context,
    schema_id: str,
) -> QueryFilterInstanceSchemaSummary:
    """Get a single query filter instance schema by id."""
    client = _client_from_context(ctx)
    safe_schema_id = _validate_required_query(schema_id, field_name="schema_id", max_length=100)
    return await _run_tool(client.get_query_filter_instance_schema(safe_schema_id))


async def list_project_memberships(
    ctx: Context,
    project: str,
) -> MembershipListResult:
    """List memberships for a project, including principal and role names."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.list_project_memberships(safe_project))


async def get_membership(
    ctx: Context,
    membership_id: int,
) -> MembershipSummary:
    """Get a compact membership summary by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.get_membership(safe_id))


async def create_membership(
    ctx: Context,
    project: str,
    principal: str,
    roles: list[str],
    notification_message: str | None = None,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or create a project membership."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_principal = _validate_required_query(principal, field_name="principal", max_length=255)
    safe_roles = _validate_required_string_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=10_000
    )
    return await _run_tool(
        client.create_membership(
            project=safe_project,
            principal=safe_principal,
            roles=safe_roles,
            notification_message=safe_notification_message,
            confirm=confirm,
        )
    )


async def update_membership(
    ctx: Context,
    membership_id: int,
    roles: list[str],
    notification_message: str | None = None,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or update a project membership."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    safe_roles = _validate_required_string_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=10_000
    )
    return await _run_tool(
        client.update_membership(
            membership_id=safe_id,
            roles=safe_roles,
            notification_message=safe_notification_message,
            confirm=confirm,
        )
    )


async def delete_membership(
    ctx: Context,
    membership_id: int,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or delete a project membership."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.delete_membership(membership_id=safe_id, confirm=confirm))


async def get_my_project_access(
    ctx: Context,
    project: str,
) -> ProjectAccessSummary:
    """Return the current user's membership and inferred access hints for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.get_my_project_access(safe_project))


async def get_instance_configuration(ctx: Context) -> InstanceConfiguration:
    """Return instance-level OpenProject configuration and active feature flags."""
    client = _client_from_context(ctx)
    return await _run_tool(client.get_instance_configuration())


async def list_project_phase_definitions(ctx: Context) -> ProjectPhaseDefinitionListResult:
    """List available project lifecycle phase definitions exposed by OpenProject."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_project_phase_definitions())


async def get_project_phase_definition(
    ctx: Context,
    phase_definition_id: int,
) -> ProjectPhaseDefinition:
    """Get a single project lifecycle phase definition by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(phase_definition_id, field_name="phase_definition_id")
    return await _run_tool(client.get_project_phase_definition(safe_id))


async def get_project_phase(
    ctx: Context,
    phase_id: int,
) -> ProjectPhase:
    """Get a single project lifecycle phase by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(phase_id, field_name="phase_id")
    return await _run_tool(client.get_project_phase(safe_id))


async def list_views(
    ctx: Context,
    project: str | None = None,
    type: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> ViewListResult:
    """List saved OpenProject views, optionally filtered by project or view subtype."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_type = _validate_optional_query(type, field_name="type", max_length=120)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_views(
            project=safe_project,
            view_type=safe_type,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


async def get_view(
    ctx: Context,
    view_id: int,
) -> ViewDetail:
    """Get a single OpenProject view by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(view_id, field_name="view_id")
    return await _run_tool(client.get_view(safe_id))


async def list_documents(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> DocumentListResult:
    """List documents, optionally filtered to a single project."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_documents(project=safe_project, offset=safe_offset, limit=safe_limit))


async def get_document(
    ctx: Context,
    document_id: int,
) -> DocumentDetail:
    """Get a single document by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(document_id, field_name="document_id")
    return await _run_tool(client.get_document(safe_id))


async def update_document(
    ctx: Context,
    document_id: int,
    title: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> DocumentWriteResult:
    """Prepare or update a document."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(document_id, field_name="document_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    if not any(value is not None for value in (safe_title, safe_description)):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_document(
            document_id=safe_id,
            title=safe_title,
            description=safe_description,
            confirm=confirm,
        )
    )


async def list_news(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> NewsListResult:
    """List news entries, optionally filtered by project or title/summary search."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_news(
            project=safe_project,
            search=safe_search,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


async def get_news(
    ctx: Context,
    news_id: int,
) -> NewsDetail:
    """Get a single news entry by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    return await _run_tool(client.get_news(safe_id))


async def create_news(
    ctx: Context,
    project: str,
    title: str,
    summary: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> NewsWriteResult:
    """Prepare or create a news entry inside a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_query(title, field_name="title", max_length=255)
    safe_summary = _validate_optional_text(summary, field_name="summary", max_length=500)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    return await _run_tool(
        client.create_news(
            project=safe_project,
            title=safe_title,
            summary=safe_summary,
            description=safe_description,
            confirm=confirm,
        )
    )


async def update_news(
    ctx: Context,
    news_id: int,
    title: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> NewsWriteResult:
    """Prepare or update a news entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_summary = _validate_optional_text(summary, field_name="summary", max_length=500)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    if not any(value is not None for value in (safe_title, safe_summary, safe_description)):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_news(
            news_id=safe_id,
            title=safe_title,
            summary=safe_summary,
            description=safe_description,
            confirm=confirm,
        )
    )


async def delete_news(
    ctx: Context,
    news_id: int,
    confirm: bool = False,
) -> NewsWriteResult:
    """Prepare or delete a news entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    return await _run_tool(client.delete_news(news_id=safe_id, confirm=confirm))


async def get_wiki_page(
    ctx: Context,
    wiki_page_id: int,
) -> WikiPageDetail:
    """Get a single wiki page by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(wiki_page_id, field_name="wiki_page_id")
    return await _run_tool(client.get_wiki_page(safe_id))


async def list_categories(
    ctx: Context,
    project: str,
) -> CategoryListResult:
    """List work-package categories configured for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.list_categories(safe_project))


async def get_category(
    ctx: Context,
    project: str,
    category_id: int,
) -> CategorySummary:
    """Get a single category from a project's category list."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_id = _validate_positive_int(category_id, field_name="category_id")
    return await _run_tool(client.get_category(project_ref=safe_project, category_id=safe_id))


async def get_project_work_package_context(
    ctx: Context,
    project: str,
    type: str | None = None,
) -> ProjectWorkPackageContext:
    """Return project metadata and, optionally, the writable work-package schema for a given type."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_type = _validate_optional_query(type, field_name="type", max_length=100)
    return await _run_tool(client.get_project_work_package_context(project=safe_project, type=safe_type))


async def search_work_packages(
    ctx: Context,
    query: str,
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
    sort_by: list[str] | None = None,
    group_by: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> WorkPackageListResult:
    """Search work packages by free text, optionally scoped to a project.

    Set status to restrict results to a specific OpenProject status.
    Set open_only=true to return only open work packages.
    Set assignee_me=true to return only work packages assigned to the current user.

    assignee filters by any user (username, id, or "me"). assignee_me takes precedence.

    priority filters by priority name or numeric ID (case-insensitive).

    Date filters accept YYYY-MM-DD format:
    - created_on/updated_on/due_on: exact date match
    - created_between/updated_between/due_between: inclusive date range [start, end]
    Cannot specify both _on and _between for the same field.

    sort_by accepts a list of sort criteria in format "field:direction"
    (e.g., ["status:desc", "priority:asc"]). Direction defaults to "asc" if omitted.
    Common sortable fields: id, subject, status, priority, type, assignee, author,
    created_at, updated_at, start_date, due_date.

    group_by accepts a field name to group results by (e.g., "status", "assignee").
    Common groupable fields: status, priority, type, assignee, author, version, category.

    select restricts each result row to the given fields (e.g. ["id", "subject",
    "status"]); an invalid name returns the allowed set. Common fields: id,
    display_id, subject, type, status, priority, assignee, project, version,
    parent_id, start_date, due_date, estimated_time, spent_time, created_at,
    updated_at, author, category, description, schedule_manually,
    derived_start_date, derived_due_date, percentage_done, derived_percentage_done,
    readonly, ignore_non_working_days.
    """
    client = _client_from_context(ctx)
    safe_query = _validate_required_query(query, field_name="query", max_length=120)
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
    safe_sort_by = _validate_sort_by(sort_by)
    safe_group_by = _validate_optional_query(group_by, field_name="group_by", max_length=120)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=WorkPackageSummary)
    return await _run_tool(
        client.search_work_packages(
            query=safe_query,
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
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


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
    sort_by: list[str] | None = None,
    group_by: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> WorkPackageListResult:
    """List work packages with structured filters and no free-text query requirement.

    version_status filters by the status of a work package's assigned version:
    one of 'open', 'closed', or 'locked'.

    assignee filters by any user (username, id, or "me"). assignee_me takes precedence.

    status/priority filter by name or numeric ID (case-insensitive).

    Date filters accept YYYY-MM-DD format:
    - created_on/updated_on/due_on: exact date match
    - created_between/updated_between/due_between: inclusive date range [start, end]
    Cannot specify both _on and _between for the same field.

    sort_by accepts a list of sort criteria in format "field:direction"
    (e.g., ["status:desc", "priority:asc"]). Direction defaults to "asc" if omitted.
    Common sortable fields: id, subject, status, priority, type, assignee, author,
    created_at, updated_at, start_date, due_date.

    group_by accepts a field name to group results by (e.g., "status", "assignee").
    Common groupable fields: status, priority, type, assignee, author, version, category.

    select restricts each result row to the given fields (e.g. ["id", "subject",
    "status"]); an invalid name returns the allowed set. Common fields: id,
    display_id, subject, type, status, priority, assignee, project, version,
    parent_id, start_date, due_date, estimated_time, spent_time, created_at,
    updated_at, author, category, description, schedule_manually,
    derived_start_date, derived_due_date, percentage_done, derived_percentage_done,
    readonly, ignore_non_working_days.
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
    safe_sort_by = _validate_sort_by(sort_by)
    safe_group_by = _validate_optional_query(group_by, field_name="group_by", max_length=120)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=WorkPackageSummary)
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
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


async def get_work_package(
    ctx: Context,
    work_package_id: int | str,
    text_limit: int | None = None,
) -> WorkPackageDetail:
    """Get a work package by id, including its full description.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"),
    not UI display number (e.g., 51).

    The description is returned in full by default (single work packages are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``description_truncated`` is true and ``description_length``
    reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_work_package(safe_id, text_limit=safe_text_limit))


async def get_work_packages(
    ctx: Context,
    ids: list[int | str],
    text_limit: int | None = None,
) -> BatchWorkPackageReadResult:
    """Get multiple work packages by ID in a single batch call.

    Fetches work packages in parallel and returns per-item results.
    Failed fetches are reported individually without stopping the batch.
    Maximum 100 IDs per batch.

    ids: internal ids (e.g., 952) or display_ids (e.g., "OPM-51"),
    not UI display numbers. Duplicate IDs are automatically deduplicated.
    """
    client = _client_from_context(ctx)

    # Validate input
    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    if not ids:
        raise ValueError("ids list cannot be empty")

    # Validate and deduplicate while preserving order
    seen = set()
    unique_ids = []
    for raw_id in ids:
        safe_id = _validate_work_package_ref(raw_id)
        normalized = str(safe_id)
        if normalized not in seen:
            seen.add(normalized)
            unique_ids.append(safe_id)

    if len(unique_ids) > BATCH_READ_MAX_IDS:
        raise ValueError(f"Maximum {BATCH_READ_MAX_IDS} unique work packages per batch (got {len(unique_ids)})")

    safe_text_limit = _validate_optional_text_limit(text_limit)

    return await _run_tool(client.get_work_packages(ids=unique_ids, text_limit=safe_text_limit))


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
    assignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number to nest the new work package under a parent.
    estimated_time, remaining_time, duration accept ISO8601 duration strings in PT format (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours, 'PT30M' for 30 minutes). Day-based formats like 'P1D' are not supported by OpenProject.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_type = _validate_required_query(type, field_name="type", max_length=100)
    safe_subject = _validate_required_query(subject, field_name="subject", max_length=255)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_version = _validate_optional_query(version, field_name="version", max_length=100)
    safe_project_phase = _validate_optional_query(project_phase, field_name="project_phase", max_length=100)
    safe_assignee = _validate_optional_user_ref(assignee)
    safe_responsible = _validate_optional_user_ref(responsible, field_name="responsible")
    safe_priority = _validate_optional_query(priority, field_name="priority", max_length=100)
    safe_category = _validate_optional_query(category, field_name="category", max_length=100)
    safe_custom_fields = _validate_optional_custom_fields(custom_fields)
    safe_parent = _validate_optional_work_package_ref(parent, field_name="parent")
    safe_start_date = _validate_optional_date(start_date, field_name="start_date")
    safe_due_date = _validate_optional_date(due_date, field_name="due_date")
    safe_estimated_time = _validate_optional_duration(estimated_time, field_name="estimated_time")
    safe_remaining_time = _validate_optional_duration(remaining_time, field_name="remaining_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    return await _run_tool(
        client.create_work_package(
            project=safe_project,
            type=safe_type,
            subject=safe_subject,
            description=safe_description,
            version=safe_version,
            project_phase=safe_project_phase,
            assignee=safe_assignee,
            responsible=safe_responsible,
            priority=safe_priority,
            category=safe_category,
            custom_fields=safe_custom_fields,
            parent_work_package_id=safe_parent,
            start_date=safe_start_date,
            due_date=safe_due_date,
            estimated_time=safe_estimated_time,
            remaining_time=safe_remaining_time,
            duration=safe_duration,
            confirm=confirm,
        )
    )


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
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or update a work package.

    The tool validates the patch first. Set confirm=true to write.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    assignee: 'me' or numeric user id (e.g., 42). Call list_users to find ids. parent re-parents the work package (numeric id or a PROJ-123 reference); pass 'none' to remove the parent and make it top-level. version accepts a version name/id, or 'none' to unassign the version. sprint accepts a Backlogs sprint name/id (requires the Backlogs module and OpenProject 17.3+), or 'none' to unassign it. Pass 'none' to assignee, responsible, category or project_phase to unassign that field. Omitted fields stay unchanged.
    estimated_time, remaining_time, duration accept ISO8601 duration strings in PT format (e.g., 'PT8H' for 8 hours, 'PT1H30M' for 1.5 hours) or None to leave unchanged. Day-based formats like 'P1D' are not supported by OpenProject.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_subject = _validate_optional_query(subject, field_name="subject", max_length=255)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_type = _validate_optional_query(type, field_name="type", max_length=100)
    # version: 'none' (any case) clears the assigned version; otherwise a version name/id.
    safe_version = _validate_optional_version(version)
    # sprint: 'none' (any case) clears the assigned sprint; otherwise a sprint name/id.
    safe_sprint = _clearable(sprint, lambda v: _validate_optional_query(v, field_name="sprint", max_length=100))
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    # assignee/responsible/category/project_phase: 'none' (any case) unassigns the
    # field; otherwise the normal validation applies.
    safe_assignee = _clearable(assignee, lambda v: _validate_optional_user_ref(v))
    safe_responsible = _clearable(responsible, lambda v: _validate_optional_user_ref(v, field_name="responsible"))
    safe_category = _clearable(category, lambda v: _validate_optional_query(v, field_name="category", max_length=100))
    safe_project_phase = _clearable(
        project_phase, lambda v: _validate_optional_query(v, field_name="project_phase", max_length=100)
    )
    safe_priority = _validate_optional_query(priority, field_name="priority", max_length=100)
    safe_custom_fields = _validate_optional_custom_fields(custom_fields)
    # parent: 'none' (any case) clears the parent (top-level); otherwise a work package ref.
    if parent is None:
        safe_parent: int | str | object | None = None
    elif parent.strip().lower() == "none":
        safe_parent = CLEAR_PARENT
    else:
        safe_parent = _validate_work_package_ref(parent, field_name="parent")
    safe_start_date = _validate_optional_date(start_date, field_name="start_date")
    safe_due_date = _validate_optional_date(due_date, field_name="due_date")
    safe_estimated_time = _validate_optional_duration(estimated_time, field_name="estimated_time")
    safe_remaining_time = _validate_optional_duration(remaining_time, field_name="remaining_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    if not any(
        value is not None
        for value in (
            safe_subject,
            safe_description,
            safe_type,
            safe_version,
            safe_sprint,
            safe_project_phase,
            safe_status,
            safe_assignee,
            safe_responsible,
            safe_priority,
            safe_category,
            safe_custom_fields,
            safe_parent,
            safe_start_date,
            safe_due_date,
            safe_estimated_time,
            safe_remaining_time,
            safe_duration,
        )
    ):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_work_package(
            work_package_id=safe_id,
            subject=safe_subject,
            description=safe_description,
            type=safe_type,
            version=safe_version,
            sprint=safe_sprint,
            project_phase=safe_project_phase,
            status=safe_status,
            assignee=safe_assignee,
            responsible=safe_responsible,
            priority=safe_priority,
            category=safe_category,
            custom_fields=safe_custom_fields,
            parent_work_package_id=safe_parent,
            start_date=safe_start_date,
            due_date=safe_due_date,
            estimated_time=safe_estimated_time,
            remaining_time=safe_remaining_time,
            duration=safe_duration,
            confirm=confirm,
        )
    )


async def bulk_create_work_packages(
    ctx: Context,
    items: list[dict[str, Any]],
    confirm: bool = False,
) -> BulkWorkPackageWriteResult:
    """Create multiple work packages in one call.

    Each item in `items` must contain `project`, `type`, and `subject`. Optional fields per item:
    `description`, `version`, `project_phase`, `assignee`, `responsible`, `priority`, `category`,
    `custom_fields`, `parent_work_package_id`, `start_date` (YYYY-MM-DD), `due_date` (YYYY-MM-DD).

    With confirm=false (default) all items are validated and a preview is returned.
    With confirm=true all items are created. Failed items are reported in the result — the operation
    continues for remaining items regardless of individual failures.
    """
    client = _client_from_context(ctx)
    if not items:
        raise ValueError("items must not be empty.")
    safe_items: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object.")
        project = item.get("project")
        type_ = item.get("type")
        subject = item.get("subject")
        safe_parent_work_package_id = _validate_optional_work_package_ref(
            item.get("parent_work_package_id"), field_name=f"items[{i}].parent_work_package_id"
        )
        if not project:
            raise ValueError(f"items[{i}].project is required.")
        if not type_:
            raise ValueError(f"items[{i}].type is required.")
        if not subject:
            raise ValueError(f"items[{i}].subject is required.")
        safe_items.append(
            {
                "project": _validate_project_ref(str(project)),
                "type": _validate_required_query(str(type_), field_name=f"items[{i}].type", max_length=100),
                "subject": _validate_required_query(str(subject), field_name=f"items[{i}].subject", max_length=255),
                "description": _validate_optional_text(
                    item.get("description"), field_name=f"items[{i}].description", max_length=10_000
                ),
                "version": _validate_optional_query(
                    item.get("version"), field_name=f"items[{i}].version", max_length=100
                ),
                "project_phase": _validate_optional_query(
                    item.get("project_phase"), field_name=f"items[{i}].project_phase", max_length=100
                ),
                "assignee": _validate_optional_user_ref(item.get("assignee")),
                "responsible": _validate_optional_user_ref(item.get("responsible"), field_name="responsible"),
                "priority": _validate_optional_query(
                    item.get("priority"), field_name=f"items[{i}].priority", max_length=100
                ),
                "category": _validate_optional_query(
                    item.get("category"), field_name=f"items[{i}].category", max_length=100
                ),
                "custom_fields": _validate_optional_custom_fields(item.get("custom_fields")),
                "parent_work_package_id": safe_parent_work_package_id,
                "start_date": _validate_optional_date(item.get("start_date"), field_name=f"items[{i}].start_date"),
                "due_date": _validate_optional_date(item.get("due_date"), field_name=f"items[{i}].due_date"),
            }
        )
    return await _run_tool(client.bulk_create_work_packages(items=safe_items, confirm=confirm))


async def bulk_update_work_packages(
    ctx: Context,
    items: list[dict[str, Any]],
    confirm: bool = False,
) -> BulkWorkPackageWriteResult:
    """Update multiple work packages in one call.

    Each item in `items` must contain `work_package_id`. At least one other field must be present per item.
    Optional fields per item: `subject`, `description`, `type`, `version`, `project_phase`, `status`,
    `assignee`, `responsible`, `priority`, `category`, `custom_fields`, `parent_work_package_id`,
    `start_date` (YYYY-MM-DD), `due_date` (YYYY-MM-DD).

    With confirm=false (default) all items are validated and a preview is returned.
    With confirm=true all items are updated. Failed items are reported in the result — the operation
    continues for remaining items regardless of individual failures.
    """
    client = _client_from_context(ctx)
    if not items:
        raise ValueError("items must not be empty.")
    safe_items: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object.")
        work_package_id = item.get("work_package_id")
        if work_package_id is None:
            raise ValueError(f"items[{i}].work_package_id is required.")
        safe_id = _validate_work_package_ref(work_package_id, field_name=f"items[{i}].work_package_id")
        safe_subject = _validate_optional_query(item.get("subject"), field_name=f"items[{i}].subject", max_length=255)
        safe_description = _validate_optional_text(
            item.get("description"), field_name=f"items[{i}].description", max_length=10_000
        )
        safe_type = _validate_optional_query(item.get("type"), field_name=f"items[{i}].type", max_length=100)
        safe_version = _validate_optional_query(item.get("version"), field_name=f"items[{i}].version", max_length=100)
        safe_project_phase = _validate_optional_query(
            item.get("project_phase"), field_name=f"items[{i}].project_phase", max_length=100
        )
        safe_status = _validate_optional_query(item.get("status"), field_name=f"items[{i}].status", max_length=100)
        safe_assignee = _validate_optional_user_ref(item.get("assignee"))
        safe_responsible = _validate_optional_user_ref(item.get("responsible"), field_name="responsible")
        safe_priority = _validate_optional_query(
            item.get("priority"), field_name=f"items[{i}].priority", max_length=100
        )
        safe_category = _validate_optional_query(
            item.get("category"), field_name=f"items[{i}].category", max_length=100
        )
        safe_custom_fields = _validate_optional_custom_fields(item.get("custom_fields"))
        safe_parent_work_package_id = _validate_optional_work_package_ref(
            item.get("parent_work_package_id"), field_name=f"items[{i}].parent_work_package_id"
        )
        safe_start_date = _validate_optional_date(item.get("start_date"), field_name=f"items[{i}].start_date")
        safe_due_date = _validate_optional_date(item.get("due_date"), field_name=f"items[{i}].due_date")
        if not any(
            v is not None
            for v in (
                safe_subject,
                safe_description,
                safe_type,
                safe_version,
                safe_project_phase,
                safe_status,
                safe_assignee,
                safe_responsible,
                safe_priority,
                safe_category,
                safe_custom_fields,
                safe_start_date,
                safe_due_date,
                safe_parent_work_package_id,
            )
        ):
            raise ValueError(f"items[{i}]: at least one field to update is required.")
        safe_items.append(
            {
                "work_package_id": safe_id,
                "subject": safe_subject,
                "description": safe_description,
                "type": safe_type,
                "version": safe_version,
                "project_phase": safe_project_phase,
                "status": safe_status,
                "assignee": safe_assignee,
                "responsible": safe_responsible,
                "priority": safe_priority,
                "category": safe_category,
                "custom_fields": safe_custom_fields,
                "parent_work_package_id": safe_parent_work_package_id,
                "start_date": safe_start_date,
                "due_date": safe_due_date,
            }
        )
    return await _run_tool(client.bulk_update_work_packages(items=safe_items, confirm=confirm))


async def delete_work_package(
    ctx: Context,
    work_package_id: int | str,
    confirm: bool = False,
) -> WorkPackageWriteResult:
    """Prepare or delete a work package.

    The tool previews the target first. Set confirm=true to delete.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.delete_work_package(work_package_id=safe_id, confirm=confirm))


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
    parent_work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_parent_id = _validate_work_package_ref(parent_work_package_id, field_name="parent_work_package_id")
    safe_type = _validate_required_query(type, field_name="type", max_length=100)
    safe_subject = _validate_required_query(subject, field_name="subject", max_length=255)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_version = _validate_optional_query(version, field_name="version", max_length=100)
    safe_project_phase = _validate_optional_query(project_phase, field_name="project_phase", max_length=100)
    safe_assignee = _validate_optional_user_ref(assignee)
    safe_responsible = _validate_optional_user_ref(responsible, field_name="responsible")
    safe_priority = _validate_optional_query(priority, field_name="priority", max_length=100)
    safe_category = _validate_optional_query(category, field_name="category", max_length=100)
    safe_custom_fields = _validate_optional_custom_fields(custom_fields)
    safe_start_date = _validate_optional_date(start_date, field_name="start_date")
    safe_due_date = _validate_optional_date(due_date, field_name="due_date")
    return await _run_tool(
        client.create_subtask(
            parent_work_package_id=safe_parent_id,
            type=safe_type,
            subject=safe_subject,
            description=safe_description,
            version=safe_version,
            project_phase=safe_project_phase,
            assignee=safe_assignee,
            responsible=safe_responsible,
            priority=safe_priority,
            category=safe_category,
            custom_fields=safe_custom_fields,
            start_date=safe_start_date,
            due_date=safe_due_date,
            confirm=confirm,
        )
    )


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
    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
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

    Both work_package_id and related_to_work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    relation_type: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required.
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


async def delete_relation(
    ctx: Context,
    relation_id: int,
    confirm: bool = False,
) -> RelationWriteResult:
    """Prepare or delete a relation between work packages."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    return await _run_tool(client.delete_relation(relation_id=safe_id, confirm=confirm))


async def list_my_open_work_packages(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
) -> WorkPackageListResult:
    """List the current user's open assigned work packages."""
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_my_open_work_packages(offset=safe_offset, limit=safe_limit))


async def list_versions(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> VersionListResult:
    """List versions globally or for a specific project."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_versions(project=safe_project, offset=safe_offset, limit=safe_limit))


async def get_version(
    ctx: Context,
    version_id: int,
) -> VersionDetail:
    """Get a compact version summary by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    return await _run_tool(client.get_version(safe_id))


async def create_version(
    ctx: Context,
    project: str,
    name: str,
    description: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
    sharing: str | None = None,
    confirm: bool = False,
) -> VersionWriteResult:
    """Prepare or create a version for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_name = _validate_required_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_start_date = _validate_optional_date(start_date, field_name="start_date")
    safe_end_date = _validate_optional_date(end_date, field_name="end_date")
    safe_status = _validate_optional_choice(status, field_name="status", allowed_values={"open", "locked", "closed"})
    safe_sharing = _validate_optional_choice(
        sharing,
        field_name="sharing",
        allowed_values={"none", "descendants", "hierarchy", "tree"},
    )
    return await _run_tool(
        client.create_version(
            project=safe_project,
            name=safe_name,
            description=safe_description,
            start_date=safe_start_date,
            end_date=safe_end_date,
            status=safe_status,
            sharing=safe_sharing,
            confirm=confirm,
        )
    )


async def update_version(
    ctx: Context,
    version_id: int,
    name: str | None = None,
    description: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
    sharing: str | None = None,
    confirm: bool = False,
) -> VersionWriteResult:
    """Prepare or update a version."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    safe_start_date = _validate_optional_date(start_date, field_name="start_date")
    safe_end_date = _validate_optional_date(end_date, field_name="end_date")
    safe_status = _validate_optional_choice(status, field_name="status", allowed_values={"open", "locked", "closed"})
    safe_sharing = _validate_optional_choice(
        sharing,
        field_name="sharing",
        allowed_values={"none", "descendants", "hierarchy", "tree"},
    )
    if not any(
        value is not None
        for value in (safe_name, safe_description, safe_start_date, safe_end_date, safe_status, safe_sharing)
    ):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_version(
            version_id=safe_id,
            name=safe_name,
            description=safe_description,
            start_date=safe_start_date,
            end_date=safe_end_date,
            status=safe_status,
            sharing=safe_sharing,
            confirm=confirm,
        )
    )


async def delete_version(
    ctx: Context,
    version_id: int,
    confirm: bool = False,
) -> VersionWriteResult:
    """Prepare or delete a version."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    return await _run_tool(client.delete_version(version_id=safe_id, confirm=confirm))


async def list_boards(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> BoardListResult:
    """List saved OpenProject boards/queries, optionally scoped to a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search = _validate_optional_query(search, field_name="search", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_boards(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


async def get_board(
    ctx: Context,
    board_id: int,
) -> BoardDetail:
    """Get a saved OpenProject board/query by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.get_board(safe_id))


async def create_board(
    ctx: Context,
    name: str,
    project: str | None = None,
    public: bool | None = None,
    starred: bool | None = None,
    hidden: bool | None = None,
    include_subprojects: bool | None = None,
    show_hierarchies: bool | None = None,
    timeline_visible: bool | None = None,
    group_by: str | None = None,
    columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    highlighted_attributes: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or create a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_project = _validate_optional_project_ref(project)
    safe_group_by = _validate_optional_query(group_by, field_name="group_by", max_length=120)
    safe_columns = _validate_optional_string_list(columns, field_name="columns", max_items=50, item_max_length=120)
    safe_sort_by = _validate_optional_string_list(sort_by, field_name="sort_by", max_items=20, item_max_length=120)
    safe_highlighted = _validate_optional_string_list(
        highlighted_attributes,
        field_name="highlighted_attributes",
        max_items=20,
        item_max_length=120,
    )
    safe_filters = _validate_optional_filter_list(filters)
    return await _run_tool(
        client.create_board(
            name=safe_name,
            project=safe_project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=safe_group_by,
            columns=safe_columns,
            sort_by=safe_sort_by,
            highlighted_attributes=safe_highlighted,
            filters=safe_filters,
            confirm=confirm,
        )
    )


async def update_board(
    ctx: Context,
    board_id: int,
    name: str | None = None,
    project: str | None = None,
    public: bool | None = None,
    starred: bool | None = None,
    hidden: bool | None = None,
    include_subprojects: bool | None = None,
    show_hierarchies: bool | None = None,
    timeline_visible: bool | None = None,
    group_by: str | None = None,
    columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    highlighted_attributes: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or update a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_project = _validate_optional_project_ref(project)
    safe_group_by = _validate_optional_query(group_by, field_name="group_by", max_length=120)
    safe_columns = _validate_optional_string_list(columns, field_name="columns", max_items=50, item_max_length=120)
    safe_sort_by = _validate_optional_string_list(sort_by, field_name="sort_by", max_items=20, item_max_length=120)
    safe_highlighted = _validate_optional_string_list(
        highlighted_attributes,
        field_name="highlighted_attributes",
        max_items=20,
        item_max_length=120,
    )
    safe_filters = _validate_optional_filter_list(filters)
    if not any(
        value is not None
        for value in (
            safe_name,
            safe_project,
            public,
            starred,
            hidden,
            include_subprojects,
            show_hierarchies,
            timeline_visible,
            safe_group_by,
            safe_columns,
            safe_sort_by,
            safe_highlighted,
            safe_filters,
        )
    ):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_board(
            board_id=safe_id,
            name=safe_name,
            project=safe_project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=safe_group_by,
            columns=safe_columns,
            sort_by=safe_sort_by,
            highlighted_attributes=safe_highlighted,
            filters=safe_filters,
            confirm=confirm,
        )
    )


async def delete_board(
    ctx: Context,
    board_id: int,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or delete a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.delete_board(board_id=safe_id, confirm=confirm))


async def list_work_package_attachments(
    ctx: Context,
    work_package_id: int | str,
) -> AttachmentListResult:
    """List attachments on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_attachments(safe_id))


async def get_attachment(
    ctx: Context,
    attachment_id: int,
) -> AttachmentSummary:
    """Get a single attachment by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.get_attachment(safe_id))


async def create_work_package_attachment(
    ctx: Context,
    work_package_id: int | str,
    file_path: str,
    description: str | None = None,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or upload an attachment to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
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


async def delete_attachment(
    ctx: Context,
    attachment_id: int,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or delete an attachment."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.delete_attachment(attachment_id=safe_id, confirm=confirm))


async def list_time_entry_activities(ctx: Context) -> TimeEntryActivityListResult:
    """List available time entry activities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_time_entry_activities())


async def list_time_entries(
    ctx: Context,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    spent_on_from: str | None = None,
    spent_on_to: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> TimeEntryListResult:
    """List time entries with optional project, work package, user, and date filters.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_spent_on_from = _validate_optional_date(spent_on_from, field_name="spent_on_from")
    safe_spent_on_to = _validate_optional_date(spent_on_to, field_name="spent_on_to")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_time_entries(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            spent_on_from=safe_spent_on_from,
            spent_on_to=safe_spent_on_to,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


async def get_time_entry(
    ctx: Context,
    time_entry_id: int,
) -> TimeEntrySummary:
    """Get a single time entry by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    return await _run_tool(client.get_time_entry(safe_id))


async def create_time_entry(
    ctx: Context,
    activity: str,
    hours: str,
    spent_on: str,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or create a time entry.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    start_time/end_time are ISO 8601 date-times and require the instance setting
    "allow tracking of start and end times"; they are ignored otherwise.
    """
    client = _client_from_context(ctx)
    safe_activity = _validate_required_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_required_duration(hours, field_name="hours")
    safe_spent_on = _validate_required_date(spent_on, field_name="spent_on")
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_optional_datetime(end_time, field_name="end_time")
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
            end_time=safe_end_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


async def update_time_entry(
    ctx: Context,
    time_entry_id: int,
    user: str | None = None,
    activity: str | None = None,
    hours: str | None = None,
    spent_on: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or update a time entry. start_time/end_time are ISO 8601 date-times."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_activity = _validate_optional_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_optional_duration(hours, field_name="hours")
    safe_spent_on = _validate_optional_date(spent_on, field_name="spent_on")
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_optional_datetime(end_time, field_name="end_time")
    safe_comment = _validate_optional_text(comment, field_name="comment", max_length=10_000)
    if not any(
        value is not None
        for value in (
            safe_user,
            safe_activity,
            safe_hours,
            safe_spent_on,
            safe_start_time,
            safe_end_time,
            safe_comment,
            ongoing,
        )
    ):
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_time_entry(
            time_entry_id=safe_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            end_time=safe_end_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


async def delete_time_entry(
    ctx: Context,
    time_entry_id: int,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or delete a time entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    return await _run_tool(client.delete_time_entry(time_entry_id=safe_id, confirm=confirm))


async def get_work_package_relations(
    ctx: Context,
    work_package_id: int | str,
) -> RelationListResult:
    """Get all relations for a work package (blocks, relates to, duplicates, etc.).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.get_work_package_relations(safe_id))


async def get_work_package_activities(
    ctx: Context,
    work_package_id: int | str,
    limit: int | None = None,
    text_limit: int | None = None,
) -> ActivityListResult:
    """Get the activity log for a work package, most recent first.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.

    Comments are capped by default to keep the log compact; pass ``text_limit``
    to widen (or ``0``-based semantics via a larger value) the per-comment cap.
    When a comment is cut, ``comment_truncated`` is true and ``comment_length``
    reports its real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_limit = _validate_limit(limit)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    # Unset text_limit → keep the client's compact default cap for the activity
    # log (not the uncapped single-WP behavior). Only override when set.
    if safe_text_limit is None:
        return await _run_tool(client.get_work_package_activities(safe_id, limit=safe_limit))
    return await _run_tool(client.get_work_package_activities(safe_id, limit=safe_limit, text_limit=safe_text_limit))


async def list_work_package_reactions(
    ctx: Context,
    work_package_id: int | str,
) -> EmojiReactionListResult:
    """List emoji reactions across a work package's comment activities.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_reactions(safe_id))


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


async def list_reminders(ctx: Context) -> ReminderListResult:
    """List the current user's active reminders across all work packages."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_reminders())


async def create_work_package_reminder(
    ctx: Context,
    work_package_id: int | str,
    remind_at: str,
    note: str | None = None,
    confirm: bool = False,
) -> ReminderWriteResult:
    """Prepare or create a reminder on a work package.

    `remind_at` is an ISO 8601 date-time (e.g. 2026-12-01T09:00:00Z). Only one
    active reminder per work package is allowed; creating a second one fails.
    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_remind_at = _validate_required_datetime(remind_at, field_name="remind_at")
    safe_note = _validate_optional_text(note, field_name="note", max_length=2000)
    return await _run_tool(
        client.create_work_package_reminder(
            work_package_id=safe_id,
            remind_at=safe_remind_at,
            note=safe_note,
            confirm=confirm,
        )
    )


async def update_reminder(
    ctx: Context,
    reminder_id: int,
    remind_at: str | None = None,
    note: str | None = None,
    confirm: bool = False,
) -> ReminderWriteResult:
    """Prepare or update a reminder's time or note. At least one field is required."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(reminder_id, field_name="reminder_id")
    safe_remind_at = _validate_optional_datetime(remind_at, field_name="remind_at")
    safe_note = _validate_optional_text(note, field_name="note", max_length=2000)
    return await _run_tool(
        client.update_reminder(
            reminder_id=safe_id,
            remind_at=safe_remind_at,
            note=safe_note,
            confirm=confirm,
        )
    )


async def delete_reminder(
    ctx: Context,
    reminder_id: int,
    confirm: bool = False,
) -> ReminderWriteResult:
    """Prepare or delete a reminder; only deletes when called again with confirm=true."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(reminder_id, field_name="reminder_id")
    return await _run_tool(client.delete_reminder(reminder_id=safe_id, confirm=confirm))


async def add_project_favorite(
    ctx: Context,
    project: str,
    confirm: bool = False,
) -> FavoriteWriteResult:
    """Prepare or mark a project as a favorite; only writes when called again with confirm=true.

    project: numeric id (e.g., 7) or identifier (e.g., "opm-openproject-ce-mcp"), not display name.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.add_project_favorite(project=safe_project, confirm=confirm))


async def remove_project_favorite(
    ctx: Context,
    project: str,
    confirm: bool = False,
) -> FavoriteWriteResult:
    """Prepare or remove a project from favorites; only writes when called again with confirm=true.

    project: numeric id (e.g., 7) or identifier (e.g., "opm-openproject-ce-mcp"), not display name.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.remove_project_favorite(project=safe_project, confirm=confirm))


async def get_current_user(ctx: Context) -> CurrentUser:
    """Return the currently authenticated user's profile."""
    client = _client_from_context(ctx)
    return await _run_tool(client.get_current_user())


async def list_statuses(ctx: Context) -> StatusListResult:
    """List all available work package statuses.

    Read-only: statuses cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.list_statuses())


async def get_status(ctx: Context, status_id: int) -> StatusSummary:
    """Get a single work package status by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(status_id, field_name="status_id")
    return await _run_tool(client.get_status(safe_id))


async def list_priorities(ctx: Context) -> PriorityListResult:
    """List all available work package priorities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_priorities())


async def get_priority(ctx: Context, priority_id: int) -> PrioritySummary:
    """Get a single work package priority by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(priority_id, field_name="priority_id")
    return await _run_tool(client.get_priority(safe_id))


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


async def get_type(ctx: Context, type_id: int) -> TypeSummary:
    """Get a single work package type by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(type_id, field_name="type_id")
    return await _run_tool(client.get_type(safe_id))


async def list_work_package_watchers(
    ctx: Context,
    work_package_id: int | str,
) -> WatcherListResult:
    """List watchers of a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_watchers(safe_id))


async def add_work_package_watcher(
    ctx: Context,
    work_package_id: int | str,
    user_id: int,
    confirm: bool = False,
) -> WatcherWriteResult:
    """Prepare or add a watcher to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_user_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.add_work_package_watcher(safe_wp_id, safe_user_id, confirm=confirm))


async def remove_work_package_watcher(
    ctx: Context,
    work_package_id: int | str,
    user_id: int,
    confirm: bool = False,
) -> WatcherWriteResult:
    """Prepare or remove a watcher from a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_user_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.remove_work_package_watcher(safe_wp_id, safe_user_id, confirm=confirm))


async def list_notifications(
    ctx: Context,
    unread_only: bool = False,
    limit: int | None = None,
    offset: int = 1,
) -> NotificationListResult:
    """List in-app notifications for the current user."""
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_notifications(unread_only=unread_only, limit=safe_limit, offset=safe_offset))


async def mark_notification_read(ctx: Context, notification_id: int, confirm: bool = False) -> NotificationMarkResult:
    """Mark a single notification as read.

    Set confirm=true to write, or call without confirm=true first for a preview.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(notification_id, field_name="notification_id")
    return await _run_tool(client.mark_notification_read(safe_id, confirm=confirm))


async def mark_all_notifications_read(ctx: Context, confirm: bool = False) -> NotificationMarkResult:
    """Mark all unread notifications as read.

    Set confirm=true to write, or call without confirm=true first for a preview.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.mark_all_notifications_read(confirm=confirm))


async def create_user(
    ctx: Context,
    login: str,
    email: str,
    firstname: str,
    lastname: str,
    password: str | None = None,
    admin: bool = False,
    status: str = "active",
    language: str | None = None,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or create a new user (admin operation)."""
    client = _client_from_context(ctx)
    safe_login = _validate_required_query(login, field_name="login", max_length=100)
    safe_email = _validate_required_query(email, field_name="email", max_length=255)
    safe_firstname = _validate_required_query(firstname, field_name="firstname", max_length=255)
    safe_lastname = _validate_required_query(lastname, field_name="lastname", max_length=255)
    safe_status = _validate_optional_query(status, field_name="status", max_length=50) or "active"
    safe_language = _validate_optional_query(language, field_name="language", max_length=10)
    return await _run_tool(
        client.create_user(
            login=safe_login,
            email=safe_email,
            firstname=safe_firstname,
            lastname=safe_lastname,
            password=password,
            admin=admin,
            status=safe_status,
            language=safe_language,
            confirm=confirm,
        )
    )


async def update_user(
    ctx: Context,
    user_id: int,
    login: str | None = None,
    email: str | None = None,
    firstname: str | None = None,
    lastname: str | None = None,
    admin: bool | None = None,
    language: str | None = None,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or update an existing user (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    safe_login = _validate_optional_query(login, field_name="login", max_length=100)
    safe_email = _validate_optional_query(email, field_name="email", max_length=255)
    safe_firstname = _validate_optional_query(firstname, field_name="firstname", max_length=255)
    safe_lastname = _validate_optional_query(lastname, field_name="lastname", max_length=255)
    safe_language = _validate_optional_query(language, field_name="language", max_length=10)
    if all(v is None for v in (safe_login, safe_email, safe_firstname, safe_lastname, admin, safe_language)):
        raise ValueError("At least one field must be provided to update.")
    return await _run_tool(
        client.update_user(
            safe_id,
            login=safe_login,
            email=safe_email,
            firstname=safe_firstname,
            lastname=safe_lastname,
            admin=admin,
            language=safe_language,
            confirm=confirm,
        )
    )


async def delete_user(
    ctx: Context,
    user_id: int,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or delete a user (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.delete_user(safe_id, confirm=confirm))


async def lock_user(
    ctx: Context,
    user_id: int,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or lock a user account (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.lock_user(safe_id, confirm=confirm))


async def unlock_user(
    ctx: Context,
    user_id: int,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or unlock a user account (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.unlock_user(safe_id, confirm=confirm))


async def create_group(
    ctx: Context,
    name: str,
    user_ids: list[int] | None = None,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or create a new group (admin operation)."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    return await _run_tool(client.create_group(name=safe_name, user_ids=user_ids, confirm=confirm))


async def update_group(
    ctx: Context,
    group_id: int,
    name: str | None = None,
    add_user_ids: list[int] | None = None,
    remove_user_ids: list[int] | None = None,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or update an existing group (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    if all(v is None for v in (safe_name, add_user_ids, remove_user_ids)):
        raise ValueError("At least one field must be provided to update.")
    return await _run_tool(
        client.update_group(
            safe_id, name=safe_name, add_user_ids=add_user_ids, remove_user_ids=remove_user_ids, confirm=confirm
        )
    )


async def delete_group(
    ctx: Context,
    group_id: int,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or delete a group (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.delete_group(safe_id, confirm=confirm))


async def list_work_package_file_links(
    ctx: Context,
    work_package_id: int | str,
) -> FileLinkListResult:
    """List Nextcloud file links attached to a work package (Community Edition).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "OPM-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_file_links(safe_id))


async def delete_file_link(
    ctx: Context,
    file_link_id: int,
    confirm: bool = False,
) -> FileLinkWriteResult:
    """Prepare or delete a Nextcloud file link."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(file_link_id, field_name="file_link_id")
    return await _run_tool(client.delete_file_link(safe_id, confirm=confirm))


async def list_grids(
    ctx: Context,
    scope: str | None = None,
) -> GridListResult:
    """List dashboard grids, optionally filtered by scope (page path)."""
    client = _client_from_context(ctx)
    safe_scope = _validate_optional_query(scope, field_name="scope", max_length=500)
    return await _run_tool(client.list_grids(scope=safe_scope))


async def get_grid(ctx: Context, grid_id: int) -> GridSummary:
    """Get a single dashboard grid by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.get_grid(safe_id))


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
    if safe_name is None and safe_row_count is None and safe_column_count is None:
        raise ValueError("At least one field to update is required.")
    return await _run_tool(
        client.update_grid(
            grid_id=safe_id,
            name=safe_name,
            row_count=safe_row_count,
            column_count=safe_column_count,
            confirm=confirm,
        )
    )


async def delete_grid(
    ctx: Context,
    grid_id: int,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or delete a dashboard grid. Only deletes when called again with confirm=true."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.delete_grid(grid_id=safe_id, confirm=confirm))


async def get_my_preferences(ctx: Context) -> UserPreferences:
    """Return the current user's OpenProject preferences (language, timezone, sorting, …)."""
    client = _client_from_context(ctx)
    return await _run_tool(client.get_my_preferences())


async def update_my_preferences(
    ctx: Context,
    lang: str | None = None,
    time_zone: str | None = None,
    comment_sort_descending: bool | None = None,
    warn_on_leaving_unsaved: bool | None = None,
    auto_hide_popups: bool | None = None,
    confirm: bool = False,
) -> UserPreferencesWriteResult:
    """Prepare or update the current user's preferences (language, timezone, comment sort order, …).
    Set confirm=true to write."""
    client = _client_from_context(ctx)
    return await _run_tool(
        client.update_my_preferences(
            lang=lang,
            time_zone=time_zone,
            comment_sort_descending=comment_sort_descending,
            warn_on_leaving_unsaved=warn_on_leaving_unsaved,
            auto_hide_popups=auto_hide_popups,
            confirm=confirm,
        )
    )


async def render_text(
    ctx: Context,
    text: str,
    format: str = "markdown",
) -> RenderedText:
    """Render markdown or plain text to HTML using the OpenProject API. format: 'markdown' or 'plain'."""
    client = _client_from_context(ctx)
    safe_text = _validate_required_text(text, field_name="text", max_length=50_000)
    if format not in ("markdown", "plain"):
        raise ValueError("format must be 'markdown' or 'plain'.")
    return await _run_tool(client.render_text(text=safe_text, format=format))


async def list_help_texts(ctx: Context) -> HelpTextListResult:
    """List all help texts configured for work-package and project attributes."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_help_texts())


async def get_help_text(ctx: Context, help_text_id: int) -> HelpTextSummary:
    """Get a single help text by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(help_text_id, field_name="help_text_id")
    return await _run_tool(client.get_help_text(safe_id))


async def list_working_days(ctx: Context) -> WorkingDayListResult:
    """List the Mon–Sun working-day configuration (7 entries showing which weekdays are working days)."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_working_days())


async def list_non_working_days(
    ctx: Context,
    year: int | None = None,
) -> NonWorkingDayListResult:
    """List non-working days (public holidays / closures) for a given year, or the current year."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_non_working_days(year=year))


async def get_custom_option(ctx: Context, custom_option_id: int) -> CustomOptionSummary:
    """Fetch the label/value of a single custom field option by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(custom_option_id, field_name="custom_option_id")
    return await _run_tool(client.get_custom_option(safe_id))


async def list_relations(
    ctx: Context,
    relation_type: str | None = None,
) -> RelationListResult:
    """List all relations across the instance, optionally filtered by type (e.g. 'blocks', 'follows')."""
    client = _client_from_context(ctx)
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    return await _run_tool(client.list_relations(relation_type=safe_type))


async def update_relation(
    ctx: Context,
    relation_id: int,
    relation_type: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> RelationUpdateResult:
    """Prepare or update the type or description of a relation. Set confirm=true to write."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    safe_desc = _validate_optional_query(description, field_name="description", max_length=500) if description else None
    return await _run_tool(
        client.update_relation(
            relation_id=safe_id,
            relation_type=safe_type,
            description=safe_desc,
            confirm=confirm,
        )
    )


def _client_from_context(ctx: Context) -> OpenProjectClient:
    app_context = cast(Any, ctx.request_context.lifespan_context)
    return app_context.client


# Stable, machine-readable category prefixes so a calling agent can branch on the
# kind of failure rather than parsing free text. The prefix leads the message,
# which stays human-readable, e.g.
#   "[permission_denied] OpenProject work package write support is disabled. ..."
_ERROR_CATEGORY: dict[type[Exception], str] = {
    InvalidInputError: "validation_error",
    AuthenticationError: "auth_error",
    PermissionDeniedError: "permission_denied",
    NotFoundError: "not_found",
    TransportError: "transport_error",
    OpenProjectServerError: "server_error",
    OpenProjectError: "openproject_error",  # base fallback
}
_CATEGORY_PREFIX_RE = re.compile(r"^\[[a-z_]+\]\s")


def _prefix(category: str, message: str) -> str:
    if _CATEGORY_PREFIX_RE.match(message):
        return message  # already categorized; don't double-prefix
    return f"[{category}] {message}"


async def _run_tool(awaitable):
    try:
        return await awaitable
    except InvalidInputError as exc:
        # Validation failures surface as ValueError; everything else as RuntimeError.
        raise ValueError(_prefix("validation_error", str(exc))) from exc
    except OpenProjectError as exc:
        category = next(
            (cat for typ, cat in _ERROR_CATEGORY.items() if isinstance(exc, typ)),
            "openproject_error",
        )
        raise RuntimeError(_prefix(category, str(exc))) from exc


def _return_model(fn: Any) -> type | None:
    """Resolve a tool's return-annotation to its dataclass model, or None.

    ``from __future__ import annotations`` makes the return annotation a string, so
    we resolve it against this module's namespace (where the models are imported).
    """
    ann = fn.__annotations__.get("return")
    model = globals().get(ann) if isinstance(ann, str) else ann
    return model if is_dataclass(model) else None


def _returns_dataclass(fn: Any) -> bool:
    """True if the tool returns a dataclass result (so it can be serialized/trimmed)."""
    return _return_model(fn) is not None


def _returns_trimmable(fn: Any) -> bool:
    """True if a tool returns a result the context-reduction seam should trim.

    A result is trimmable when its model carries a field the seam acts on:
    ``results`` (list results → count/truncated drop + select), ``payload`` (write
    results → payload drop on confirm), or ``items`` (bulk results, whose nested
    per-item write results carry their own payload to drop). Detection inspects the
    model's fields, so it cannot drift from suffix conventions (e.g.
    RelationUpdateResult, ProjectCopyResult carry payload but are not *WriteResult).
    """
    model = _return_model(fn)
    if model is None:
        return False
    names = {f.name for f in dataclass_fields(model)}
    return bool(names & {"results", "payload", "items"})


def _to_payload(value: Any, *, select: frozenset[str] | None = None) -> Any:
    """Serialize a tool result to a trimmed plain dict for context reduction.

    Recursively turns dataclass instances into dicts while applying structural
    omissions that would otherwise cost fixed context on every call:

    - **payload** (OPM-66): dropped from a write result once ``confirmed`` is true
      (the success case), since the normalized ``result`` already carries the same
      information. It stays on preview/validation-error results, where the agent
      still needs it. Applied recursively, so nested bulk items are trimmed too.
    - **count / truncated** (OPM-71): dropped from list results — both are derivable
      (``count == len(results)``, ``truncated == next_offset is not None``).
    - **hidden keys** (OPM-72): removed entirely (not nulled) when the client tagged
      the instance with ``_hidden_keys``.

    ``select`` (OPM-65) is applied to the top-level ``results`` rows only, keeping
    just the requested fields per row.

    Non-dataclass values pass through unchanged, so tools (and test stubs) that
    already return plain dicts are untouched.
    """
    if is_dataclass(value) and not isinstance(value, type):
        drop_payload = getattr(value, "confirmed", None) is True and _has_field(value, "payload")
        is_list_result = _has_field(value, "results")
        hidden = getattr(value, "_hidden_keys", ())
        out: dict[str, Any] = {}
        for f in dataclass_fields(value):
            name = f.name
            if name in hidden:
                continue
            if name == "payload" and drop_payload:
                continue
            if is_list_result and name in ("count", "truncated"):
                continue
            child = getattr(value, name)
            if is_list_result and name == "results" and select is not None:
                out[name] = [_select_fields(row, select) for row in child]
            else:
                out[name] = _to_payload(child)
        return out
    if isinstance(value, list):
        return [_to_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_to_payload(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_payload(v) for k, v in value.items()}
    return value


def _has_field(value: Any, name: str) -> bool:
    return any(f.name == name for f in dataclass_fields(value))


def _select_fields(row: Any, select: frozenset[str]) -> Any:
    """Keep only the selected fields of a result row (dataclass), still trimmed."""
    if not is_dataclass(row) or isinstance(row, type):
        return _to_payload(row)
    hidden = getattr(row, "_hidden_keys", ())
    return {
        f.name: _to_payload(getattr(row, f.name))
        for f in dataclass_fields(row)
        if f.name in select and f.name not in hidden
    }


def _validate_select(select: list[str] | None, *, row_type: type) -> list[str] | None:
    """Validate a field-selection list against a result-row dataclass.

    Called in the tool body so invalid field names raise [validation_error] before
    the client call. Returns the cleaned list (or None). The trimming wrapper reads
    the same ``select`` kwarg and applies it after the result resolves.
    """
    if select is None:
        return None
    valid = {f.name for f in dataclass_fields(row_type)}
    chosen: list[str] = []
    for raw in select:
        name = str(raw).strip()
        if name not in valid:
            allowed = ", ".join(sorted(valid))
            raise ValueError(f"select field '{name}' is not a valid {row_type.__name__} field. Allowed: {allowed}.")
        if name not in chosen:
            chosen.append(name)
    if not chosen:
        raise ValueError("select must contain at least one field name.")
    return chosen


def _normalize_select(select: Any) -> frozenset[str] | None:
    """Turn a raw ``select`` kwarg into a field set for the trimming wrapper.

    Validation already happened in the tool body (_validate_select); here we only
    normalize the shape. Returns None when no usable selection is present.
    """
    if not select:
        return None
    return frozenset(str(name).strip() for name in select if str(name).strip())


def _categorize_tool_errors(fn):
    """Wrap a tool so every failure carries a category prefix.

    _run_tool already prefixes errors from the client call, but input validators
    in the tool body raise plain ValueError *before* _run_tool runs. This wrapper
    catches those and tags them [validation_error] too, so an agent sees a
    consistent, machine-readable category for every tool failure.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ValueError as exc:
            raise ValueError(_prefix("validation_error", str(exc))) from exc

    return wrapper


def _validate_optional_query(value: str | None, *, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _validate_optional_version(value: str | None) -> str | object | None:
    """Validate a version argument, mapping 'none' (any case) to CLEAR_VERSION.

    Returns None to leave the version unchanged, CLEAR_VERSION to unassign it, or
    the validated version name/id. Mirrors the parent 'none' un-parenting sentinel.
    """
    if value is None:
        return None
    if value.strip().lower() == "none":
        return CLEAR_VERSION
    return _validate_optional_query(value, field_name="version", max_length=100)


def _clearable(value: str | None, validate: Callable[[str], Any]) -> str | object | None:
    """Map a nullable association argument to a clear sentinel or a validated value.

    Returns None (leave unchanged), CLEAR (unassign, for 'none' in any case), or the
    result of ``validate(value)``. Shared by the fields that support clearing via
    'none' (assignee, responsible, category, project_phase, project parent).
    """
    if value is None:
        return None
    if value.strip().lower() == "none":
        return CLEAR
    return validate(value)


def _validate_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _validate_required_text(value: str, *, field_name: str, max_length: int) -> str:
    normalized = _validate_optional_text(value, field_name=field_name, max_length=max_length)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_custom_fields(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("custom_fields must be an object mapping field names to values.")
    if len(value) > 50:
        raise ValueError("custom_fields must contain at most 50 entries.")
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError("custom_fields keys must not be empty.")
        if len(key) > 120:
            raise ValueError("custom_fields keys must be at most 120 characters.")
        normalized[key] = _validate_custom_field_value(raw_value)
    return normalized


def _validate_custom_field_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 10_000:
            raise ValueError("custom_fields string values must be at most 10000 characters.")
        return value.strip()
    if isinstance(value, list):
        return [_validate_custom_field_value(item) for item in value]
    raise ValueError("custom_fields values must be strings, numbers, booleans, null, or lists of those values.")


def _validate_required_query(value: str, *, field_name: str, max_length: int) -> str:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=max_length)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_project_ref(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_project_ref(value)


def _validate_optional_project_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_project_identifier(value)


def _validate_project_ref(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("project is required.")
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name="project")
        return normalized
    if not PROJECT_REF_RE.fullmatch(normalized):
        raise ValueError(
            "project: numeric id (e.g., 7) or identifier (e.g., 'opm-openproject-ce-mcp'), not display name. Call list_projects."
        )
    return normalized


def _validate_project_identifier(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("identifier is required.")
    if not PROJECT_REF_RE.fullmatch(normalized):
        raise ValueError("identifier must be a valid project identifier.")
    return normalized


def _validate_work_package_ref(value: str, *, field_name: str = "work_package_id") -> str:
    normalized = " ".join(str(value).split())
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name=field_name)
        return normalized
    if not WORK_PACKAGE_REF_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name}: use internal id (e.g., 952) or display_id (e.g., 'OPM-51'), "
            f"not UI display number (e.g., 51)."
        )
    return normalized


def _validate_optional_work_package_ref(value: str | None, *, field_name: str = "work_package_id") -> str | None:
    if value is None:
        return None
    return _validate_work_package_ref(value, field_name=field_name)


def _validate_optional_user_ref(value: str | None, field_name: str = "assignee") -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if normalized.casefold() == "me":
        return "me"
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name=field_name)
        return normalized
    raise ValueError(f"{field_name}: 'me' or numeric user id (e.g., 42). Call list_users to find ids.")


def _validate_optional_user_or_principal_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if normalized.casefold() == "me":
        return "me"
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name="user")
        return normalized
    if len(normalized) > 255:
        raise ValueError("user must be at most 255 characters.")
    return normalized


def _validate_optional_date(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not DATE_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
    return normalized


def _validate_required_date(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_date(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_datetime(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not DATETIME_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ISO 8601 date-time, e.g. 2026-12-01T09:00:00Z.")
    return normalized


def _validate_required_datetime(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_datetime(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_duration(value: str | None, *, field_name: str) -> str | None:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=50)
    if normalized is None:
        return None
    if not ISO8601_DURATION_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must use a simple ISO 8601 duration like PT1H30M.")
    return normalized


def _validate_required_duration(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_duration(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_relation_type(value: str) -> str:
    normalized = _validate_required_query(value, field_name="relation_type", max_length=20).casefold()
    if not RELATION_TYPE_RE.fullmatch(normalized):
        raise ValueError(
            "relation_type must be one of: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required."
        )
    return normalized


def _validate_optional_non_negative_int(value: int | None, *, field_name: str) -> int | None:
    if value is None:
        return None
    # Type-safe: MCP args arrive as JSON, so a wrong type (e.g. "5", True) must
    # yield a clean ValueError, not a raw TypeError from the comparison (OPM-76).
    # bool is an int subclass, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be at least 0.")
    return value


def _validate_optional_date(value: str | None, field_name: str) -> str | None:
    """Validate ISO 8601 date (YYYY-MM-DD)."""
    if value is None:
        return None
    import datetime

    normalized = value.strip()
    try:
        datetime.date.fromisoformat(normalized)
        return normalized
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD format") from exc


def _validate_date_range(after: str | None, before: str | None, prefix: str) -> None:
    """Ensure after <= before for already-validated ISO date strings."""
    if after and before:
        import datetime

        after_date = datetime.date.fromisoformat(after)
        before_date = datetime.date.fromisoformat(before)
        if after_date > before_date:
            raise ValueError(f"{prefix}_after ({after}) must not be later than {prefix}_before ({before})")


def _validate_optional_date_range(dates: list[str] | None, field_name: str) -> list[str] | None:
    """Validate optional date range [start, end] in YYYY-MM-DD format."""
    if dates is None:
        return None
    if not isinstance(dates, list):
        raise ValueError(f"{field_name} must be a list of 2 dates")
    if len(dates) != 2:
        raise ValueError(f"{field_name} must contain exactly 2 dates [start, end]")

    # Validate each date using existing validator
    start = _validate_optional_date(dates[0], f"{field_name}[0]")
    end = _validate_optional_date(dates[1], f"{field_name}[1]")

    if start is None or end is None:
        raise ValueError(f"{field_name} dates cannot be empty")

    # Validate range using existing helper
    _validate_date_range(after=start, before=end, prefix=field_name)

    return [start, end]


def _validate_optional_text_limit(value: int | None) -> int | None:
    """Validate an explicit ``text_limit`` override.

    ``None`` means "no cap" (the default for a single work package). An explicit
    value must be a non-negative int; TEXT_LIMIT_MAX is a sanity ceiling that
    guards against typos like ``text_limit=99999999`` — it never applies to the
    uncapped default path.
    """
    limit = _validate_optional_non_negative_int(value, field_name="text_limit")
    if limit is not None and limit > TEXT_LIMIT_MAX:
        raise ValueError(f"text_limit must not exceed {TEXT_LIMIT_MAX}.")
    return limit


def _validate_required_string_list(
    values: list[str],
    *,
    field_name: str,
    max_items: int,
    item_max_length: int,
) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    if not values:
        raise ValueError(f"{field_name} must contain at least one value.")
    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} values.")
    normalized: list[str] = []
    for value in values:
        item = _validate_required_query(str(value), field_name=field_name, max_length=item_max_length)
        normalized.append(item)
    return normalized


def _validate_optional_string_list(
    values: list[str] | None,
    *,
    field_name: str,
    max_items: int,
    item_max_length: int,
) -> list[str] | None:
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} values.")
    normalized: list[str] = []
    for value in values:
        item = _validate_required_query(str(value), field_name=field_name, max_length=item_max_length)
        normalized.append(item)
    return normalized


def _validate_sort_by(values: list[str] | None) -> list[SortCriterion] | None:
    """Validate and parse sort_by list into list of SortCriterion objects.

    Validates format, field name pattern, and parses each item.
    Returns None if input is None.
    Raises ValueError if any item is invalid.
    """
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError("sort_by must be a list of strings")

    result = []
    for i, item in enumerate(values):
        if not isinstance(item, str):
            raise ValueError(f"sort_by[{i}] must be a string, got {type(item).__name__}")

        item = item.strip()
        if not item:
            raise ValueError(f"sort_by[{i}] cannot be empty")

        if ":" in item:
            parts = item.split(":", 1)
            field = parts[0].strip()
            direction = parts[1].strip().lower()

            if not field:
                raise ValueError(f"sort_by[{i}]: field name cannot be empty")
            if direction not in ("asc", "desc"):
                raise ValueError(f"sort_by[{i}]: direction must be 'asc' or 'desc', got '{direction}'")
        else:
            field = item
            direction = "asc"

        # Validate field name pattern (alphanumeric + underscore + dot for custom fields)
        if not field.replace("_", "").replace(".", "").isalnum():
            raise ValueError(
                f"sort_by[{i}]: field name '{field}' contains invalid characters "
                "(only alphanumeric, underscore, and dot allowed)"
            )

        result.append(SortCriterion(field=field, direction=direction))

    return result if result else None


def _validate_optional_filter_list(value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("filters must be a list of objects.")
    if len(value) > 50:
        raise ValueError("filters must contain at most 50 entries.")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("filters must be a list of objects.")
        normalized.append(_validate_json_object(item, field_name="filters"))
    return normalized


def _validate_json_object(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError(f"{field_name} keys must not be empty.")
        if len(key) > 120:
            raise ValueError(f"{field_name} keys must be at most 120 characters.")
        normalized[key] = _validate_json_value(raw_value, field_name=field_name)
    return normalized


def _validate_json_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 10_000:
            raise ValueError(f"{field_name} string values must be at most 10000 characters.")
        return value
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError(f"{field_name} lists must contain at most 100 items.")
        return [_validate_json_value(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        return _validate_json_object(value, field_name=field_name)
    raise ValueError(f"{field_name} values must be JSON-compatible scalars, lists, or objects.")


def _validate_optional_choice(
    value: str | None,
    *,
    field_name: str,
    allowed_values: set[str],
) -> str | None:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=100)
    if normalized is None:
        return None
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return normalized


def _validate_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    return _validate_positive_int(limit, field_name="limit")


def _validate_offset(offset: int) -> int:
    return _validate_positive_int(offset, field_name="offset")


def _validate_positive_int(value: int, *, field_name: str) -> int:
    # Type-safe: MCP args arrive as JSON, so a wrong type (e.g. "5", None, True)
    # must yield a clean ValueError, not a raw TypeError from the comparison
    # (OPM-76). bool is an int subclass, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return value


# Resolves every classified tool name (OPM-123) to its actual function object.
# Derived directly from the classification constants rather than listed a
# second time, so it can never silently diverge from them — a misspelled or
# renamed tool name raises KeyError here at import time instead of a tool
# silently vanishing from registration.
_TOOL_FUNCTIONS: dict[str, Callable] = {
    name: globals()[name]
    for name in (
        *PERSONAL_MUTATION_TOOLS,
        *(name for names in READ_TOOLS_BY_SCOPE.values() for name in names),
        *(name for names in WRITE_TOOLS_BY_SCOPE.values() for name in names),
        *ADMIN_WRITE_TOOLS,
    )
}
