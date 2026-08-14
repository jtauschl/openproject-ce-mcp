from __future__ import annotations

import datetime
import functools
import inspect
import re
from collections.abc import Callable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, cast

from mcp.server.mcpserver import Context, MCPServer

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
    ActionSummary,
    ActivityListResult,
    ActivitySummary,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BacklogBucketDetail,
    BacklogBucketListResult,
    BacklogBucketSummary,
    BatchWorkPackageReadResult,
    BoardDetail,
    BoardListResult,
    BoardSummary,
    BoardWriteResult,
    BulkWorkPackageWriteResult,
    CapabilityListResult,
    CapabilitySummary,
    CategoryListResult,
    CategorySummary,
    CostEntryListResult,
    CostEntrySummary,
    CostTypeSummary,
    CurrentUser,
    CustomOptionSummary,
    DocumentDetail,
    DocumentListResult,
    DocumentSummary,
    DocumentWriteResult,
    EmojiReactionListResult,
    EmojiReactionSummary,
    EmojiReactionWriteResult,
    FavoriteWriteResult,
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
    GroupDetail,
    GroupListResult,
    GroupSummary,
    GroupWriteResult,
    HelpTextListResult,
    HelpTextSummary,
    InstanceConfiguration,
    JobStatusDetail,
    MeetingAgendaItemListResult,
    MeetingAgendaItemSummary,
    MeetingAgendaItemWriteResult,
    MeetingListResult,
    MeetingOutcomeListResult,
    MeetingOutcomeSummary,
    MeetingOutcomeWriteResult,
    MeetingSectionListResult,
    MeetingSectionSummary,
    MeetingSectionWriteResult,
    MeetingSummary,
    MeetingWriteResult,
    MembershipListResult,
    MembershipSummary,
    MembershipWriteResult,
    NewsDetail,
    NewsListResult,
    NewsSummary,
    NewsWriteResult,
    NonWorkingDayListResult,
    NotificationListResult,
    NotificationMarkResult,
    NotificationSummary,
    PostDetail,
    PrincipalListResult,
    PrincipalSummary,
    PriorityListResult,
    PrioritySummary,
    ProjectAccessSummary,
    ProjectAdminContext,
    ProjectConfiguration,
    ProjectCopyResult,
    ProjectDetail,
    ProjectListResult,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectPhaseDefinitionListResult,
    ProjectStorageDetail,
    ProjectStorageListResult,
    ProjectStorageSummary,
    ProjectSummary,
    ProjectWorkPackageContext,
    ProjectWriteResult,
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
    RecurringMeetingListResult,
    RecurringMeetingOccurrenceListResult,
    RecurringMeetingOccurrenceWriteResult,
    RecurringMeetingSummary,
    RecurringMeetingWriteResult,
    RelationListResult,
    RelationSummary,
    RelationUpdateResult,
    RelationWriteResult,
    ReminderListResult,
    ReminderSummary,
    ReminderWriteResult,
    RenderedText,
    RoleListResult,
    RoleSummary,
    SortCriterion,
    SprintDetail,
    SprintListResult,
    SprintSummary,
    StatusListResult,
    StatusSummary,
    StorageDetail,
    StorageListResult,
    StorageSummary,
    StorageWriteResult,
    TimeEntryActivityListResult,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
    TypeListResult,
    TypeSummary,
    UserDetail,
    UserListResult,
    UserNonWorkingTimeListResult,
    UserNonWorkingTimeWriteResult,
    UserPreferences,
    UserPreferencesWriteResult,
    UserSummary,
    UserWorkingHoursListResult,
    UserWorkingHoursSummary,
    UserWorkingHoursWriteResult,
    UserWriteResult,
    VersionDetail,
    VersionListResult,
    VersionSummary,
    VersionWriteResult,
    ViewDetail,
    ViewListResult,
    ViewSummary,
    WatcherListResult,
    WatcherSummary,
    WatcherWriteResult,
    WikiPageDetail,
    WikiPageLinkListResult,
    WikiPageLinkWriteResult,
    WorkingDayListResult,
    WorkPackageCostsByTypeResult,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)
from .presentation import _to_payload
from .tools_validation import (
    _require_at_least_one,
    _validate_limit,
    _validate_list_query_params,
    _validate_offset,
    _validate_optional_query,
    _validate_positive_int,
)

# ISO 8601 date-time, e.g. 2026-12-01T09:00:00Z or with a +HH:MM offset. The
# fractional-second component is capped at 6 digits (microsecond precision) --
# datetime.fromisoformat() silently truncates anything beyond that, and
# _duration_between relies on fromisoformat's parsed value being the caller's
# actual intent, not a silently-rounded approximation of a sub-microsecond
# value the regex would otherwise have let through.
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
# Full ISO 8601 duration: either weeks alone ("P2W") or a year/month/day date part
# and/or a "T"-prefixed time part (hours/minutes/seconds) — the week designator
# cannot combine with anything else, per the ISO 8601 standard's own week-format
# rule. Live-verified 2026-07-17 against real OpenProject 16.6 (Docker test harness):
# "P1D"/"P2W"/"P1Y"/"P1M"/"P1Y2M3D"/"P1DT18H" are all accepted and echoed back
# unchanged (an earlier version of this regex rejected day-based values entirely,
# based on an incorrect assumption), while "P1W2D"/"P2WT3H" (week mixed with
# another designator) are rejected by OpenProject itself with a format error —
# confirmed here too, not just assumed from the standard. The seconds component
# additionally allows an optional decimal fraction (e.g. "PT7H30M15.5S") —
# verified directly against the `iso8601` Ruby gem OpenProject uses server-side
# (ISO8601::Duration.new(...), see time_entry_representer.rb's `hours=` setter):
# its grammar permits a fractional value on any single non-zero component, as
# long as it's the last one, which our own H/M-integer-only + optionally-
# fractional-S shape always satisfies.
ISO8601_DURATION_RE = re.compile(
    r"^P(?:\d+W|(?=\d|T)(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?)$"
)
PROJECT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A project-based work package reference: a project identifier followed by "-<number>"
# (e.g. PROJ-123). The numeric form is handled separately before this pattern applies.
WORK_PACKAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}-\d+$")
RELATION_TYPE_RE = re.compile(
    r"^(relates|duplicates|duplicated|blocks|blocked|precedes|follows|includes|partof|requires|required)$"
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
    # Register a tool with error-categorization applied, so every failure reaches
    # the agent with a stable [category] prefix.
    #
    # Tools that return a list/write/bulk result are routed through _to_payload for
    # context reduction: payload is dropped on confirmed writes,
    # count/truncated on lists, and `select` trims rows. Those tools are registered
    # with structured_output=False so the SDK does not build a fixed dataclass
    # output schema — it serializes the trimmed dict we return verbatim, letting us
    # omit keys. Detection is by the result model's fields, so no per-tool tagging
    # is needed and it cannot drift. Tool bodies are unchanged; they still return
    # their dataclass, which the wrapper trims.
    #
    # When any hide-field config is active, every dataclass-returning tool is
    # trimmed too, so single-entity reads (get_*) can drop hidden keys entirely
    # rather than emit them as null. This only widens schema loss when the
    # operator opted into hiding.
    hide_active = bool(settings.hidden_fields)

    def tool(fn):
        if not (_returns_trimmable(fn) or (hide_active and _returns_dataclass(fn))):
            return mcp.tool()(_categorize_tool_errors(fn))

        wrapped = _categorize_tool_errors(fn)
        # Whether this tool's own signature accepts `select` -- NOT whether its
        # return model happens to carry a `results`/`items` field. Some list
        # tools (e.g. list_statuses) return a `results`-bearing model but have
        # no `select` parameter at all, so relying on the return type alone
        # would wrongly treat them as select-driven and keep eliding their
        # None fields with no way for a caller to ask for them back.
        elide_none = "select" in inspect.signature(fn).parameters

        @functools.wraps(wrapped)
        async def trimming(*args, **kwargs):
            select = _normalize_select(kwargs.get("select"))
            return _to_payload(await wrapped(*args, **kwargs), select=select, elide_none=elide_none)

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

    select fields: id, name, identifier, active, public, status, parent_name,
    created_at, updated_at (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. Under a
    restrictive OPENPROJECT_READ_PROJECTS, total reflects only the allowed
    projects already scanned to fill this page, not a full count of all
    matches — the search stops as soon as it has enough, so an exact total
    would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=ProjectSummary)
    return await _run_tool(client.list_projects(search=safe_search, offset=safe_offset, limit=safe_limit))


async def get_project(
    ctx: Context,
    project: str,
    text_limit: int | None = None,
) -> ProjectDetail:
    """Get a project by id or identifier, including its ancestor chain.

    project: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display name.

    description/status_explanation are returned in full by default (single projects
    are not truncated). Pass ``text_limit`` to cap them at that many characters; when
    cut, ``description_truncated``/``status_explanation_truncated`` are true and
    ``description_length``/``status_explanation_length`` report the real length.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_project(safe_project, text_limit=safe_text_limit))


async def list_sprints(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> SprintListResult:
    """List Backlogs sprints, optionally filtered by name search.

    project: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display
    name. Omit it to list every sprint visible to the current token across all
    projects; pass it to list only sprints for that project.

    Requires the OpenProject Backlogs module; unavailable instances return a clear not-found message.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed sprints returned on THIS page, not a full count of
    all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=SprintSummary)
    if project is None:
        return await _run_tool(client.list_sprints(search=safe_search, offset=safe_offset, limit=safe_limit))
    safe_project = _validate_project_ref(project)
    return await _run_tool(
        client.list_project_sprints(safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


async def get_sprint(
    ctx: Context,
    sprint_id: int,
) -> SprintDetail:
    """Get a Backlogs sprint by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(sprint_id, field_name="sprint_id")
    return await _run_tool(client.get_sprint(safe_id))


async def list_backlog_buckets(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> BacklogBucketListResult:
    """List Backlogs backlog buckets, optionally filtered by name search.

    project: numeric id (e.g., 7), identifier (e.g., "my-project"), or display
    name. Omit it to list every backlog bucket visible to the current token
    across all projects; pass it to list only backlog buckets for that project.

    Requires the OpenProject Backlogs module and OpenProject 17.6 or newer;
    unavailable instances return a clear not-found message.

    select fields: id, name, defining_workspace_id, defining_workspace,
    created_at, updated_at (see server instructions for select's general
    semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed backlog buckets returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=BacklogBucketSummary)
    if project is None:
        return await _run_tool(client.list_backlog_buckets(search=safe_search, offset=safe_offset, limit=safe_limit))
    safe_project = _validate_project_ref(project)
    return await _run_tool(
        client.list_project_backlog_buckets(safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


async def get_backlog_bucket(
    ctx: Context,
    backlog_bucket_id: int,
) -> BacklogBucketDetail:
    """Get a Backlogs backlog bucket by id. Requires OpenProject 17.6 or newer."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(backlog_bucket_id, field_name="backlog_bucket_id")
    return await _run_tool(client.get_backlog_bucket(safe_id))


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


def _validate_project_descriptive_fields(
    *,
    description: str | None,
    status: str | None,
    status_explanation: str | None,
    parent: str | None,
) -> dict[str, Any]:
    """Shared field validation for create_project/copy_project -- byte-identical
    in both (plain, non-clearable validators). update_project uses different
    validator functions for these same field names and is NOT covered here.
    """
    return {
        "description": _validate_optional_text(description, field_name="description", max_length=10_000),
        "status": _validate_optional_query(status, field_name="status", max_length=100),
        "status_explanation": _validate_optional_text(
            status_explanation, field_name="status_explanation", max_length=10_000
        ),
        "parent": _validate_optional_project_ref(parent),
    }


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
    """Prepare or create a project.

    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    """
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_project_identifier(identifier)
    common = _validate_project_descriptive_fields(
        description=description, status=status, status_explanation=status_explanation, parent=parent
    )
    return await _run_tool(
        client.create_project(
            name=safe_name,
            identifier=safe_identifier,
            description=common["description"],
            public=public,
            active=active,
            status=common["status"],
            status_explanation=common["status_explanation"],
            parent=common["parent"],
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
    """Prepare or copy an existing project into a new project.

    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    """
    client = _client_from_context(ctx)
    safe_source_project = _validate_project_ref(source_project)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_project_identifier(identifier)
    common = _validate_project_descriptive_fields(
        description=description, status=status, status_explanation=status_explanation, parent=parent
    )
    return await _run_tool(
        client.copy_project(
            source_project=safe_source_project,
            name=safe_name,
            identifier=safe_identifier,
            description=common["description"],
            public=public,
            active=active,
            status=common["status"],
            status_explanation=common["status_explanation"],
            parent=common["parent"],
            confirm=confirm,
        )
    )


async def get_job_status(
    ctx: Context,
    job_status_id: str,
) -> JobStatusDetail:
    """Get the current status of a background job such as project copy."""
    client = _client_from_context(ctx)
    # Job status ids are UUIDs (e.g. "32ac4e5e-1e49-4cbd-b70e-bc1c781d8af2"),
    # never a plain integer, on every supported OpenProject version.
    safe_id = _validate_required_text(job_status_id, field_name="job_status_id", max_length=64)
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
    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_identifier = _validate_optional_project_identifier(identifier)
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=10_000)
    safe_status = _validate_optional_query(status, field_name="status", max_length=100)
    safe_status_explanation = _validate_optional_update_text(
        status_explanation, field_name="status_explanation", max_length=10_000
    )
    # parent: 'none' (any case) makes the project top-level; otherwise a project ref.
    safe_parent = _clearable(parent, lambda v: _validate_optional_project_ref(v))
    _require_at_least_one(
        safe_name,
        safe_identifier,
        safe_description,
        public,
        active,
        safe_status,
        safe_status_explanation,
        safe_parent,
        message="At least one field to update is required.",
    )
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


async def list_roles(
    ctx: Context,
    select: list[str] | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> RoleListResult:
    """List OpenProject roles visible to the current user.

    select fields: id, name (see server instructions for select's general semantics).
    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=RoleSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_roles(offset=safe_offset, limit=safe_limit))


async def list_principals(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> PrincipalListResult:
    """List users and groups that can be used for project memberships.

    select fields: id, name, type (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=PrincipalSummary)
    return await _run_tool(client.list_principals(search=safe_search, offset=safe_offset, limit=safe_limit))


async def list_users(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> UserListResult:
    """List users visible to the current token.

    select fields: id, name, login, email, status, admin, created_at, updated_at
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With search,
    total is only the count of matching users returned on THIS page, not a
    full count of all matches — the search stops as soon as it has enough,
    so an exact total would need an extra full walk. Page until next_offset
    is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
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
    select: list[str] | None = None,
) -> GroupListResult:
    """List groups visible to the current token.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With search,
    total is only the count of matching groups returned on THIS page, not a
    full count of all matches — the search stops as soon as it has enough,
    so an exact total would need an extra full walk. Page until next_offset
    is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=GroupSummary)
    return await _run_tool(client.list_groups(search=safe_search, offset=safe_offset, limit=safe_limit))


async def get_group(
    ctx: Context,
    group_id: int,
) -> GroupDetail:
    """Get a single group by id."""
    client = _client_from_context(ctx)
    safe_group_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.get_group(safe_group_id))


async def list_storages(
    ctx: Context,
    select: list[str] | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> StorageListResult:
    """List configured OpenProject external file storage connections (Nextcloud/OneDrive/Sharepoint).

    select fields: id, name, provider_type, host, configured, created_at, updated_at
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=StorageSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_storages(offset=safe_offset, limit=safe_limit))


async def get_storage(
    ctx: Context,
    storage_id: int,
) -> StorageDetail:
    """Get a single OpenProject external file storage connection by id."""
    client = _client_from_context(ctx)
    safe_storage_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.get_storage(safe_storage_id))


async def list_actions(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ActionListResult:
    """List API actions exposed by OpenProject.

    select fields: id, url (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=ActionSummary)
    return await _run_tool(client.list_actions(offset=safe_offset, limit=safe_limit))


async def list_capabilities(
    ctx: Context,
    project: str | None = None,
    capability_id: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> CapabilityListResult:
    """List API capabilities exposed by OpenProject.

    select fields: id, action_id, context (see server instructions for
    select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_capability_id = _validate_optional_query(capability_id, field_name="capability_id", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=CapabilitySummary)
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
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> MembershipListResult:
    """List memberships for a project, including principal and role names.

    select fields: id, principal_name, role_names (see server instructions for
    select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MembershipSummary)
    return await _run_tool(client.list_project_memberships(safe_project, offset=safe_offset, limit=safe_limit))


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
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ViewListResult:
    """List saved OpenProject views, optionally filtered by project, view subtype, or name search.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed views returned on THIS page, not a full count of all
    matches — the search stops as soon as it has enough, so an exact total
    would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_type = _validate_optional_query(type, field_name="type", max_length=120)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=ViewSummary)
    return await _run_tool(
        client.list_views(
            project=safe_project,
            view_type=safe_type,
            search=safe_search,
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
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> DocumentListResult:
    """List documents, optionally filtered to a single project or by title search.

    select fields: id, title (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed documents returned on THIS page, not a full count of
    all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=DocumentSummary)
    return await _run_tool(
        client.list_documents(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


async def get_document(
    ctx: Context,
    document_id: int,
    text_limit: int | None = None,
) -> DocumentDetail:
    """Get a single document by id.

    The description is returned in full by default (single documents are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``description_truncated`` is true and ``description_length``
    reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(document_id, field_name="document_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_document(safe_id, text_limit=safe_text_limit))


async def list_project_storages(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ProjectStorageListResult:
    """List a project's links to configured external file storages, optionally filtered to one project.

    Read-only in OpenProject's API -- no create/update/delete endpoint exists
    for this resource; manage the underlying connection with the storages
    tools instead.

    select fields: id, project, storage_name, project_folder_mode (see server
    instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=ProjectStorageSummary)
    return await _run_tool(client.list_project_storages(project=safe_project, offset=safe_offset, limit=safe_limit))


async def get_project_storage(
    ctx: Context,
    project_storage_id: int,
) -> ProjectStorageDetail:
    """Get a single project's link to a configured external file storage by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(project_storage_id, field_name="project_storage_id")
    return await _run_tool(client.get_project_storage(safe_id))


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
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=10_000)
    _require_at_least_one(safe_title, safe_description, message="At least one field to update is required.")
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
    select: list[str] | None = None,
) -> NewsListResult:
    """List news entries, optionally filtered by project or title/summary search.

    select fields: id, title (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed news entries returned on THIS page, not a full
    count of all matches — the search stops as soon as it has enough, so an
    exact total would need an extra full walk. Page until next_offset is
    null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=NewsSummary)
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
    text_limit: int | None = None,
) -> NewsDetail:
    """Get a single news entry by id.

    The description is returned in full by default (single news entries are
    not truncated). Pass ``text_limit`` to cap it at that many characters;
    when the text is cut, ``description_truncated`` is true and
    ``description_length`` reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_news(safe_id, text_limit=safe_text_limit))


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
    safe_summary = _validate_optional_update_text(summary, field_name="summary", max_length=500)
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=10_000)
    _require_at_least_one(
        safe_title, safe_summary, safe_description, message="At least one field to update is required."
    )
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
    text_limit: int | None = 50_000,
) -> WikiPageDetail:
    """Get a single wiki page by id.

    content is returned in full by default, capped at 50,000 characters (a
    wiki page's own upper bound). Pass ``text_limit`` to cap it further, or
    ``None`` for genuinely uncapped content; when the text is cut,
    ``content_truncated`` is true and ``content_length`` reports the real
    length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(wiki_page_id, field_name="wiki_page_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_wiki_page(safe_id, text_limit=safe_text_limit))


async def get_post(
    ctx: Context,
    post_id: int,
) -> PostDetail:
    """Get a single forum post by id.

    OpenProject's API exposes exactly one route for posts:
    GET /api/v3/posts/{id}. There is no collection/list endpoint for posts or
    forums at all in OpenProject's REST API -- a post's id must therefore
    come from elsewhere (e.g. a work package's activity/journal referencing
    a forum post, or a link copied from the OpenProject web UI). This MCP
    does not and cannot provide a list_posts or list_forums tool.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(post_id, field_name="post_id")
    return await _run_tool(client.get_post(safe_id))


async def list_work_package_wiki_links(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
) -> WikiPageLinkListResult:
    """List wiki pages linked to a work package.

    Requires OpenProject 17.6+ — the wiki_page_links endpoint does not exist
    on earlier versions and returns a [server_error].

    Known OpenProject server bug (confirmed on 16.6/17.6/17.7.1, tracked as
    OPM-399): this call returns a [server_error] whenever the work package
    actually has one or more wiki page links — only the empty-list case
    reliably works. create_work_package_wiki_link/delete_work_package_wiki_link
    are unaffected and fully functional.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_work_package_wiki_links(safe_id, offset=safe_offset, limit=safe_limit))


async def create_work_package_wiki_link(
    ctx: Context,
    work_package_id: int | str,
    identifier: str,
    provider: str,
    confirm: bool = False,
) -> WikiPageLinkWriteResult:
    """Prepare or create a link from a work package to a wiki page; only
    writes when called again with confirm=true.

    Requires OpenProject 17.6+ — the wiki_page_links endpoint does not exist
    on earlier versions and returns a [server_error].

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    identifier: the target wiki page's provider-specific identifier (not this
    MCP's own wiki_page_id — OpenProject's wiki-provider abstraction uses its
    own opaque page identifiers).
    provider: the wiki provider's universal identifier (e.g. "internal" for
    OpenProject's built-in wiki).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_identifier = _validate_required_query(identifier, field_name="identifier", max_length=255)
    safe_provider = _validate_required_query(provider, field_name="provider", max_length=255)
    return await _run_tool(
        client.create_work_package_wiki_link(
            safe_id, identifier=safe_identifier, provider=safe_provider, confirm=confirm
        )
    )


async def delete_work_package_wiki_link(
    ctx: Context,
    work_package_id: int | str,
    link_id: int,
    confirm: bool = False,
) -> WikiPageLinkWriteResult:
    """Prepare or delete a work package's wiki page link; only deletes when
    called again with confirm=true.

    Known OpenProject server bug (confirmed on 16.6/17.6/17.7.1, tracked as
    OPM-399): this call currently fails with a [server_error] whenever the
    given link actually exists — the same bug that breaks
    list_work_package_wiki_links, since this tool verifies link_id actually
    belongs to work_package_id before deleting (a real authorization check,
    not optional) by internally listing the work package's links first.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number
    — used to authorize the delete against that work package's project, since
    OpenProject has no single-resource GET for a wiki page link to discover
    its parent work package from link_id alone.
    link_id: the wiki page link's own id, from list_work_package_wiki_links.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_link_id = _validate_positive_int(link_id, field_name="link_id")
    return await _run_tool(client.delete_work_package_wiki_link(safe_wp_id, safe_link_id, confirm=confirm))


# --- Meetings ---


async def list_meetings(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingListResult:
    """List OpenProject meetings, optionally scoped to a project.

    Requires OpenProject 17.4+ — the meetings module's agenda/section/
    participant shape used here does not exist on 16.6, which only exposes
    an incompatible legacy "meeting contents" representation.

    project: identifier, name, or numeric id. Omit to list across all
    readable projects.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the
    returned next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meetings(project=safe_project, offset=safe_offset, limit=safe_limit))


async def get_meeting(ctx: Context, meeting_id: int) -> MeetingSummary:
    """Get a single OpenProject meeting by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.get_meeting(safe_id))


async def create_meeting(
    ctx: Context,
    project: str,
    title: str,
    location: str | None = None,
    start_time: str | None = None,
    duration: str | None = None,
    state: str | None = None,
    sharing: str | None = None,
    notify: bool | None = None,
    participant_user_refs: list[str] | None = None,
    confirm: bool = False,
) -> MeetingWriteResult:
    """Prepare or create an OpenProject meeting; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id — required, every meeting
    belongs to exactly one project.
    duration: an ISO 8601 duration like "PT1H30M" (hours/minutes only).
    state: meeting state (e.g. "open", "closed") — pass the value as
    returned by list_meetings/get_meeting.
    participant_user_refs: list of user references (numeric id, login, or
    name) to invite as participants.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_location = _validate_optional_text(location, field_name="location", max_length=255)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    safe_participants = _validate_participant_refs(participant_user_refs)
    return await _run_tool(
        client.create_meeting(
            project=safe_project,
            title=safe_title,
            location=safe_location,
            start_time=safe_start,
            duration=safe_duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=safe_participants,
            confirm=confirm,
        )
    )


async def update_meeting(
    ctx: Context,
    meeting_id: int,
    title: str | None = None,
    location: str | None = None,
    start_time: str | None = None,
    duration: str | None = None,
    state: str | None = None,
    sharing: str | None = None,
    notify: bool | None = None,
    participant_user_refs: list[str] | None = None,
    lock_version: int | None = None,
    confirm: bool = False,
) -> MeetingWriteResult:
    """Prepare or update an OpenProject meeting; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_location = _validate_optional_text(location, field_name="location", max_length=255)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    safe_participants = _validate_participant_refs(participant_user_refs)
    _require_at_least_one(
        safe_title,
        safe_location,
        safe_start,
        safe_duration,
        state,
        sharing,
        notify,
        safe_participants,
        lock_version,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_meeting(
            meeting_id=safe_id,
            title=safe_title,
            location=safe_location,
            start_time=safe_start,
            duration=safe_duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=safe_participants,
            lock_version=lock_version,
            confirm=confirm,
        )
    )


async def delete_meeting(ctx: Context, meeting_id: int, confirm: bool = False) -> MeetingWriteResult:
    """Prepare or delete an OpenProject meeting; only deletes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.delete_meeting(meeting_id=safe_id, confirm=confirm))


async def list_meeting_agenda_items(
    ctx: Context,
    meeting_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List agenda items of an OpenProject meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side (OpenProject returns every agenda
    item of the meeting in one response) — offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meeting_agenda_items(safe_id, offset=safe_offset, limit=safe_limit))


async def list_work_package_meeting_agenda_items(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List meeting agenda items linked to a work package.

    Requires OpenProject 17.4+.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_work_package_meeting_agenda_items(safe_id, offset=safe_offset, limit=safe_limit))


async def get_meeting_agenda_item(ctx: Context, agenda_item_id: int) -> MeetingAgendaItemSummary:
    """Get a single meeting agenda item by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.get_meeting_agenda_item(safe_id))


async def create_meeting_agenda_item(
    ctx: Context,
    meeting_id: int,
    title: str,
    notes: str | None = None,
    duration_in_minutes: int | None = None,
    item_type: str | None = None,
    work_package_id: int | str | None = None,
    meeting_section_id: int | None = None,
    confirm: bool = False,
) -> MeetingAgendaItemWriteResult:
    """Prepare or create a meeting agenda item; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.
    meeting_section_id: an existing section's id (from list_meeting_sections); optional.
    """
    client = _client_from_context(ctx)
    safe_meeting_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_notes = _validate_optional_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_section_id = (
        _validate_positive_int(meeting_section_id, field_name="meeting_section_id")
        if meeting_section_id is not None
        else None
    )
    return await _run_tool(
        client.create_meeting_agenda_item(
            meeting_id=safe_meeting_id,
            title=safe_title,
            notes=safe_notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=safe_work_package_id,
            meeting_section_id=safe_section_id,
            confirm=confirm,
        )
    )


async def update_meeting_agenda_item(
    ctx: Context,
    agenda_item_id: int,
    title: str | None = None,
    notes: str | None = None,
    duration_in_minutes: int | None = None,
    item_type: str | None = None,
    work_package_id: int | str | None = None,
    meeting_section_id: int | None = None,
    confirm: bool = False,
) -> MeetingAgendaItemWriteResult:
    """Prepare or update a meeting agenda item; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_notes = _validate_optional_update_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_section_id = (
        _validate_positive_int(meeting_section_id, field_name="meeting_section_id")
        if meeting_section_id is not None
        else None
    )
    _require_at_least_one(
        safe_title,
        safe_notes,
        duration_in_minutes,
        item_type,
        safe_work_package_id,
        safe_section_id,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_meeting_agenda_item(
            agenda_item_id=safe_id,
            title=safe_title,
            notes=safe_notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=safe_work_package_id,
            meeting_section_id=safe_section_id,
            confirm=confirm,
        )
    )


async def delete_meeting_agenda_item(
    ctx: Context, agenda_item_id: int, confirm: bool = False
) -> MeetingAgendaItemWriteResult:
    """Prepare or delete a meeting agenda item; only deletes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.delete_meeting_agenda_item(agenda_item_id=safe_id, confirm=confirm))


async def list_meeting_outcomes(
    ctx: Context,
    agenda_item_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingOutcomeListResult:
    """List outcomes of a meeting agenda item.

    Requires OpenProject 17.6+ — the meeting_outcomes endpoint does not exist
    on 17.4/17.5.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meeting_outcomes(safe_id, offset=safe_offset, limit=safe_limit))


async def get_meeting_outcome(ctx: Context, outcome_id: int) -> MeetingOutcomeSummary:
    """Get a single meeting outcome by id.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.get_meeting_outcome(safe_id))


async def create_meeting_outcome(
    ctx: Context,
    agenda_item_id: int,
    kind: str,
    notes: str | None = None,
    work_package_id: int | str | None = None,
    confirm: bool = False,
) -> MeetingOutcomeWriteResult:
    """Prepare or create a meeting outcome on an agenda item; only writes
    when called again with confirm=true.

    Requires OpenProject 17.6+.

    kind must be one of "information", "decision", "work_package" (OpenProject's
    real enum values — not e.g. "info" or "action", which OpenProject rejects
    with an internal server error rather than a clean validation error).
    "information"-kind outcomes require notes; "work_package"-kind outcomes
    require work_package_id.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.
    """
    client = _client_from_context(ctx)
    safe_agenda_item_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_kind = _validate_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_work_package_numeric_id = (
        int(safe_work_package_id) if safe_work_package_id is not None and safe_work_package_id.isdigit() else None
    )
    return await _run_tool(
        client.create_meeting_outcome(
            agenda_item_id=safe_agenda_item_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_numeric_id,
            confirm=confirm,
        )
    )


async def update_meeting_outcome(
    ctx: Context,
    outcome_id: int,
    kind: str | None = None,
    notes: str | None = None,
    work_package_id: int | str | None = None,
    confirm: bool = False,
) -> MeetingOutcomeWriteResult:
    """Prepare or update a meeting outcome; only writes when called again
    with confirm=true.

    Requires OpenProject 17.6+.

    kind, if given, must be one of "information", "decision", "work_package"
    (OpenProject's real enum values — not e.g. "info" or "action", which
    OpenProject rejects with an internal server error rather than a clean
    validation error).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    safe_kind = _validate_optional_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_update_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_work_package_numeric_id = (
        int(safe_work_package_id) if safe_work_package_id is not None and safe_work_package_id.isdigit() else None
    )
    _require_at_least_one(
        safe_kind, safe_notes, safe_work_package_numeric_id, message="At least one field to update is required."
    )
    return await _run_tool(
        client.update_meeting_outcome(
            outcome_id=safe_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_numeric_id,
            confirm=confirm,
        )
    )


async def delete_meeting_outcome(ctx: Context, outcome_id: int, confirm: bool = False) -> MeetingOutcomeWriteResult:
    """Prepare or delete a meeting outcome; only deletes when called again
    with confirm=true.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.delete_meeting_outcome(outcome_id=safe_id, confirm=confirm))


async def list_meeting_sections(
    ctx: Context,
    meeting_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingSectionListResult:
    """List sections of an OpenProject meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meeting_sections(safe_id, offset=safe_offset, limit=safe_limit))


async def get_meeting_section(ctx: Context, section_id: int) -> MeetingSectionSummary:
    """Get a single meeting section by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.get_meeting_section(safe_id))


async def create_meeting_section(
    ctx: Context,
    meeting_id: int,
    title: str,
    position: int | None = None,
    backlog: bool | None = None,
    confirm: bool = False,
) -> MeetingSectionWriteResult:
    """Prepare or create a meeting section; only writes when called again
    with confirm=true.

    Requires OpenProject 17.4+.

    backlog cannot be changed after creation via update_meeting_section —
    pass it only here, on create.
    """
    client = _client_from_context(ctx)
    safe_meeting_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    return await _run_tool(
        client.create_meeting_section(
            meeting_id=safe_meeting_id, title=safe_title, position=position, backlog=backlog, confirm=confirm
        )
    )


async def update_meeting_section(
    ctx: Context,
    section_id: int,
    title: str | None = None,
    position: int | None = None,
    confirm: bool = False,
) -> MeetingSectionWriteResult:
    """Prepare or update a meeting section's title/position; only writes
    when called again with confirm=true.

    Requires OpenProject 17.4+.

    backlog cannot be changed after creation — this tool does not accept it.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    _require_at_least_one(safe_title, position, message="At least one field to update is required.")
    return await _run_tool(
        client.update_meeting_section(section_id=safe_id, title=safe_title, position=position, confirm=confirm)
    )


async def delete_meeting_section(ctx: Context, section_id: int, confirm: bool = False) -> MeetingSectionWriteResult:
    """Prepare or delete a meeting section; only deletes when called again
    with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.delete_meeting_section(section_id=safe_id, confirm=confirm))


async def list_recurring_meetings(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> RecurringMeetingListResult:
    """List OpenProject recurring meeting series, optionally scoped to a project.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id. Omit to list across all
    readable projects.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the
    returned next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_recurring_meetings(project=safe_project, offset=safe_offset, limit=safe_limit))


async def get_recurring_meeting(ctx: Context, recurring_meeting_id: int) -> RecurringMeetingSummary:
    """Get a single OpenProject recurring meeting series by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.get_recurring_meeting(safe_id))


async def create_recurring_meeting(
    ctx: Context,
    project: str,
    title: str,
    frequency: str,
    start_time: str,
    interval: int | None = None,
    end_after: str | None = None,
    end_date: str | None = None,
    iterations: int | None = None,
    monthly_day: int | None = None,
    monthly_ordinal: str | None = None,
    monthly_weekday: str | None = None,
    confirm: bool = False,
) -> RecurringMeetingWriteResult:
    """Prepare or create an OpenProject recurring meeting series; only
    writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id — required, every recurring
    meeting belongs to exactly one project.
    frequency: e.g. "daily", "weekly", "monthly" — pass the value as
    returned by list_recurring_meetings/get_recurring_meeting.
    end_after: e.g. "date", "iterations", "never" — governs which of
    end_date/iterations is used.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_frequency = _validate_required_text(frequency, field_name="frequency", max_length=50)
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_date = _validate_optional_date(end_date, "end_date")
    return await _run_tool(
        client.create_recurring_meeting(
            project=safe_project,
            title=safe_title,
            frequency=safe_frequency,
            start_time=safe_start,
            interval=interval,
            end_after=end_after,
            end_date=safe_end_date,
            iterations=iterations,
            monthly_day=monthly_day,
            monthly_ordinal=monthly_ordinal,
            monthly_weekday=monthly_weekday,
            confirm=confirm,
        )
    )


async def update_recurring_meeting(
    ctx: Context,
    recurring_meeting_id: int,
    title: str | None = None,
    frequency: str | None = None,
    start_time: str | None = None,
    interval: int | None = None,
    end_after: str | None = None,
    end_date: str | None = None,
    iterations: int | None = None,
    confirm: bool = False,
) -> RecurringMeetingWriteResult:
    """Prepare or update an OpenProject recurring meeting series; only
    writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    Note: this does not affect meetings already materialized from this
    series (via init_recurring_meeting_occurrence) — update those directly
    with update_meeting.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_frequency = _validate_optional_query(frequency, field_name="frequency", max_length=50)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_end_date = _validate_optional_date(end_date, "end_date")
    _require_at_least_one(
        safe_title,
        safe_frequency,
        safe_start,
        interval,
        end_after,
        safe_end_date,
        iterations,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_recurring_meeting(
            recurring_meeting_id=safe_id,
            title=safe_title,
            frequency=safe_frequency,
            start_time=safe_start,
            interval=interval,
            end_after=end_after,
            end_date=safe_end_date,
            iterations=iterations,
            confirm=confirm,
        )
    )


async def delete_recurring_meeting(
    ctx: Context, recurring_meeting_id: int, confirm: bool = False
) -> RecurringMeetingWriteResult:
    """Prepare or delete an OpenProject recurring meeting series; only
    deletes when called again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.delete_recurring_meeting(recurring_meeting_id=safe_id, confirm=confirm))


_VALID_OCCURRENCE_FILTERS: set[str] = {"upcoming", "past", "cancelled", "open"}


async def list_recurring_meeting_occurrences(
    ctx: Context,
    recurring_meeting_id: int,
    filter: str = "upcoming",
    limit: int | None = None,
) -> RecurringMeetingOccurrenceListResult:
    """List virtual occurrences of a recurring meeting.

    Requires OpenProject 17.4+.

    filter: one of "upcoming", "past", "cancelled", "open".
    limit: only applies when filter="upcoming" (OpenProject default: 20);
    ignored for the other three filters, which always return their full set.
    Occurrences are virtual (synthesized from the recurrence rule) except
    where a real Meeting has already been materialized via
    init_recurring_meeting_occurrence — this list has no offset/pagination,
    unlike list_meetings/list_recurring_meetings.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_filter = _validate_optional_choice(filter, field_name="filter", allowed_values=_VALID_OCCURRENCE_FILTERS)
    if safe_filter is None:
        safe_filter = "upcoming"
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_recurring_meeting_occurrences(safe_id, filter=safe_filter, limit=safe_limit))


async def init_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: int,
    start_time: str,
    confirm: bool = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Prepare or materialize a virtual recurring-meeting occurrence into a
    real, standalone Meeting; only writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601, matching a
    start_time value from list_recurring_meeting_occurrences) — occurrences
    have no numeric id, they are addressed by this timestamp.
    On success, result is a full Meeting (use its id with get_meeting/
    update_meeting/delete_meeting), not an occurrence.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.init_recurring_meeting_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )


async def cancel_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: int,
    start_time: str,
    confirm: bool = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Prepare or cancel a virtual (not-yet-materialized) recurring-meeting
    occurrence; only writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601), matching
    init_recurring_meeting_occurrence's addressing scheme.

    If the occurrence has already been materialized into a real Meeting and
    is not itself cancelled, this fails with an error (delete_meeting the
    materialized meeting directly instead). If NOT yet materialized,
    OpenProject creates a new, PERMANENTLY cancelled Meeting server-side to
    record the cancellation — this call's result does not report that new
    meeting's id; list_meetings/list_recurring_meeting_occurrences(filter=
    "cancelled") can be used to find it afterward if needed.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.cancel_recurring_meeting_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )


async def list_user_non_working_times(
    ctx: Context,
    user_ref: str,
    year: int | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> UserNonWorkingTimeListResult:
    """List a user's per-user non-working-time date ranges (e.g. vacation),
    distinct from the instance-wide non-working days (list_non_working_days).

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7). Earlier versions return a [server_error] for this
    endpoint — the route does not exist before 17.3.

    OpenProject enforces this at the API level: you may always view your own
    schedule (user_ref="me"); viewing another user's requires the
    manage_working_times global permission, else OpenProject returns 404
    (not 403) to avoid confirming the user exists.

    user_ref: "me" for the current user, a numeric user id, or a login.
    year: filter to this calendar year; defaults to the current year.
    The collection is unpaginated on OpenProject's side — this MCP fetches
    the full requested year and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_year = _validate_optional_non_negative_int(year, field_name="year")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_user_non_working_times(safe_user, year=safe_year, offset=safe_offset, limit=safe_limit)
    )


async def create_user_non_working_time(
    ctx: Context,
    user_ref: str,
    start_date: str,
    end_date: str,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or create a non-working-time date range for a user; only
    writes when called again with confirm=true.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_non_working_times.

    user_ref: "me" for the current user, a numeric user id, or a login.
    start_date/end_date: ISO 8601 dates (YYYY-MM-DD).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_start = _validate_required_date(start_date, field_name="start_date")
    safe_end = _validate_required_date(end_date, field_name="end_date")
    return await _run_tool(
        client.create_user_non_working_time(safe_user, start_date=safe_start, end_date=safe_end, confirm=confirm)
    )


async def update_user_non_working_time(
    ctx: Context,
    user_ref: str,
    non_working_time_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or update a user's non-working-time date range; only writes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times. No single-item GET exists on OpenProject's
    side for this resource, but the update itself is addressed directly by
    id (no year or other date filter involved) — a non-existent id fails
    with a not-found error.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    safe_start = _validate_optional_date(start_date, field_name="start_date")
    safe_end = _validate_optional_date(end_date, field_name="end_date")
    return await _run_tool(
        client.update_user_non_working_time(
            safe_user, safe_id, start_date=safe_start, end_date=safe_end, confirm=confirm
        )
    )


async def delete_user_non_working_time(
    ctx: Context,
    user_ref: str,
    non_working_time_id: int,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or delete a user's non-working-time date range; only deletes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    return await _run_tool(client.delete_user_non_working_time(safe_user, safe_id, confirm=confirm))


async def list_user_working_hours(
    ctx: Context,
    user_ref: str,
    offset: int = 1,
    limit: int | None = None,
) -> UserWorkingHoursListResult:
    """List a user's recurring weekly working-hours schedules, ordered by
    valid_from descending (most recent first).

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7).

    Same self-service-or-manage_working_times authorization as
    list_user_non_working_times: OpenProject returns 404 (not 403) for an
    unauthorized cross-user request.

    user_ref: "me" for the current user, a numeric user id, or a login.
    The collection is unpaginated on OpenProject's side — this MCP fetches
    the full list and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_user_working_hours(safe_user, offset=safe_offset, limit=safe_limit))


async def get_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
) -> UserWorkingHoursSummary:
    """Get a single working-hours schedule entry for a user.

    Requires OpenProject 17.3+. Same authorization as
    list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.get_user_working_hours(safe_user, safe_id))


async def create_user_working_hours(
    ctx: Context,
    user_ref: str,
    valid_from: str,
    monday_hours: float | None = None,
    tuesday_hours: float | None = None,
    wednesday_hours: float | None = None,
    thursday_hours: float | None = None,
    friday_hours: float | None = None,
    saturday_hours: float | None = None,
    sunday_hours: float | None = None,
    availability_factor: float | None = None,
    confirm: bool = False,
) -> UserWorkingHoursWriteResult:
    """Prepare or create a new weekly working-hours schedule version for a
    user, effective from valid_from; only writes when called again with
    confirm=true.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_working_hours.

    user_ref: "me" for the current user, a numeric user id, or a login.
    valid_from: ISO 8601 date (YYYY-MM-DD) this schedule version takes effect.
    *_hours: hours worked on that weekday; omit any you don't want to set.
    availability_factor: fractional working-time factor (e.g. 0.5 for
    half-time), independent of the per-day hour values.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_valid_from = _validate_required_date(valid_from, field_name="valid_from")
    return await _run_tool(
        client.create_user_working_hours(
            safe_user,
            valid_from=safe_valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
            confirm=confirm,
        )
    )


async def update_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
    valid_from: str | None = None,
    monday_hours: float | None = None,
    tuesday_hours: float | None = None,
    wednesday_hours: float | None = None,
    thursday_hours: float | None = None,
    friday_hours: float | None = None,
    saturday_hours: float | None = None,
    sunday_hours: float | None = None,
    availability_factor: float | None = None,
    confirm: bool = False,
) -> UserWorkingHoursWriteResult:
    """Prepare or update a user's working-hours schedule entry; only writes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    safe_valid_from = _validate_optional_date(valid_from, field_name="valid_from")
    return await _run_tool(
        client.update_user_working_hours(
            safe_user,
            safe_id,
            valid_from=safe_valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
            confirm=confirm,
        )
    )


async def delete_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
    confirm: bool = False,
) -> UserWorkingHoursWriteResult:
    """Prepare or delete a user's working-hours schedule entry; only deletes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.delete_user_working_hours(safe_user, safe_id, confirm=confirm))


async def execute_query(
    ctx: Context,
    query_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> WorkPackageListResult:
    """Execute a saved OpenProject query by id and return its resolved work packages.

    query_id: the query's own numeric id — obtain it from get_view/list_views's
    query_id field, or from list_boards/get_board (a board's id IS its
    underlying query id, since OpenProject Boards are Query resources).

    Runs the query server-side (OpenProject resolves its stored filters/sort/
    group_by and returns real work packages, not just the query's
    definition) — no client-side filter translation happens here. Results are
    still filtered against this MCP's own OPENPROJECT_READ_PROJECTS allowlist
    before being returned, since the query itself executes with the API
    token's full server-side permissions.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_query_id = _validate_positive_int(query_id, field_name="query_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.execute_query(safe_query_id, offset=safe_offset, limit=safe_limit))


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

    Date filters, sort_by/group_by, select, pagination (offset/limit/total),
    include_sums, and each result's custom_fields/custom_comments (raw-key
    custom-field values/comments, capped and hide-matched exactly as
    documented) all work exactly as documented on list_work_packages — see
    that tool's docstring for the full field lists and semantics. One
    difference: total is the real matching count only when scope is
    unrestricted or an explicit project was given (list_work_packages's
    server-side allowed-project filter for the no-project+restricted-scope
    case does not apply here); otherwise total/groups/total_sums fall back
    to this page's data, same safety guarantee either way.

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
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
            include_sums=include_sums,
            custom_field_filters=safe_custom_field_filters,
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
    include_sums: bool = False,
    custom_field_filters: dict[str, dict[str, Any]] | None = None,
) -> WorkPackageListResult:
    """List work packages with structured filters and no free-text query requirement.

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
            sort_by=safe_sort_by,
            group_by=safe_group_by,
            offset=safe_offset,
            limit=safe_limit,
            include_sums=include_sums,
            custom_field_filters=safe_custom_field_filters,
        )
    )


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

    # Validate input
    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    if not ids:
        raise ValueError("ids list cannot be empty")

    # Validate and deduplicate while preserving order
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
        "version": _validate_optional_version(version, field_name=f"{field_prefix}version"),
        "sprint": _clearable(
            sprint, lambda v: _validate_optional_query(v, field_name=f"{field_prefix}sprint", max_length=100)
        ),
        "project_phase": _clearable(
            project_phase,
            lambda v: _validate_optional_query(v, field_name=f"{field_prefix}project_phase", max_length=100),
        ),
        "status": _validate_optional_query(status, field_name=f"{field_prefix}status", max_length=100),
        "assignee": _clearable(
            assignee, lambda v: _validate_optional_user_ref(v, field_name=f"{field_prefix}assignee")
        ),
        "responsible": _clearable(
            responsible, lambda v: _validate_optional_user_ref(v, field_name=f"{field_prefix}responsible")
        ),
        "priority": _validate_optional_query(priority, field_name=f"{field_prefix}priority", max_length=100),
        "category": _clearable(
            category, lambda v: _validate_optional_query(v, field_name=f"{field_prefix}category", max_length=100)
        ),
        "custom_fields": _validate_optional_custom_fields(custom_fields),
        "parent": _clearable_ref(
            parent, functools.partial(_validate_work_package_ref, field_name=parent_field_name), sentinel=CLEAR_PARENT
        ),
        "start_date": _validate_optional_date(start_date, field_name=f"{field_prefix}start_date"),
        "due_date": _validate_optional_date(due_date, field_name=f"{field_prefix}due_date"),
        "estimated_time": _clearable_duration(estimated_time, field_name=f"{field_prefix}estimated_time"),
        "remaining_time": _clearable_duration(remaining_time, field_name=f"{field_prefix}remaining_time"),
        "duration": _clearable_duration(duration, field_name=f"{field_prefix}duration"),
        "percentage_done": _validate_optional_percentage_done(
            percentage_done, field_name=f"{field_prefix}percentage_done"
        ),
    }


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


async def list_versions(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> VersionListResult:
    """List versions globally or for a specific project, optionally filtered by a
    case-insensitive name substring.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. Without project,
    total is only the count of allowed versions returned on THIS page, not a
    full count of all matches — the search stops as soon as it has enough, so
    an exact total would need an extra full walk. Page until next_offset is
    null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=VersionSummary)
    return await _run_tool(
        client.list_versions(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


async def get_version(
    ctx: Context,
    version_id: int,
    text_limit: int | None = None,
) -> VersionDetail:
    """Get a version by id, including its full description.

    The description is returned in full by default (single versions are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``description_truncated`` is true and ``description_length``
    reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.get_version(safe_id, text_limit=safe_text_limit))


def _validate_version_schedule_fields(
    *,
    start_date: str | None,
    end_date: str | None,
    status: str | None,
    sharing: str | None,
) -> dict[str, Any]:
    """Shared field validation for create_version/update_version -- byte-identical
    in both, unlike work-packages: these 4 fields have no clearable-vs-plain
    split between create and update.
    """
    return {
        "start_date": _validate_optional_date(start_date, field_name="start_date"),
        "end_date": _validate_optional_date(end_date, field_name="end_date"),
        "status": _validate_optional_choice(status, field_name="status", allowed_values={"open", "locked", "closed"}),
        "sharing": _validate_optional_choice(
            sharing,
            field_name="sharing",
            allowed_values={"none", "descendants", "hierarchy", "tree"},
        ),
    }


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
    """Prepare or create a version for a project.

    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_name = _validate_required_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    common = _validate_version_schedule_fields(start_date=start_date, end_date=end_date, status=status, sharing=sharing)
    return await _run_tool(
        client.create_version(
            project=safe_project,
            name=safe_name,
            description=safe_description,
            start_date=common["start_date"],
            end_date=common["end_date"],
            status=common["status"],
            sharing=common["sharing"],
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
    """Prepare or update a version.

    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=10_000)
    common = _validate_version_schedule_fields(start_date=start_date, end_date=end_date, status=status, sharing=sharing)
    _require_at_least_one(
        safe_name,
        safe_description,
        common["start_date"],
        common["end_date"],
        common["status"],
        common["sharing"],
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_version(
            version_id=safe_id,
            name=safe_name,
            description=safe_description,
            start_date=common["start_date"],
            end_date=common["end_date"],
            status=common["status"],
            sharing=common["sharing"],
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
    select: list[str] | None = None,
) -> BoardListResult:
    """List saved OpenProject boards/queries, optionally scoped to a project.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With project,
    search, or a restrictive OPENPROJECT_READ_PROJECTS, total is only the
    count of allowed boards returned on THIS page, not a full count of all
    matches — the search stops as soon as it has enough, so an exact total
    would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=BoardSummary)
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


def _validate_board_query_fields(
    *,
    project: str | None,
    group_by: str | None,
    columns: list[str] | None,
    sort_by: list[str] | None,
    highlighted_attributes: list[str] | None,
    filters: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Shared field validation for create_board/update_board -- byte-identical
    in both.
    """
    return {
        "project": _validate_optional_project_ref(project),
        "group_by": _validate_optional_query(group_by, field_name="group_by", max_length=120),
        "columns": _validate_optional_string_list(columns, field_name="columns", max_items=50, item_max_length=120),
        "sort_by": _validate_optional_string_list(sort_by, field_name="sort_by", max_items=20, item_max_length=120),
        "highlighted_attributes": _validate_optional_string_list(
            highlighted_attributes,
            field_name="highlighted_attributes",
            max_items=20,
            item_max_length=120,
        ),
        "filters": _validate_optional_filter_list(filters),
    }


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
    common = _validate_board_query_fields(
        project=project,
        group_by=group_by,
        columns=columns,
        sort_by=sort_by,
        highlighted_attributes=highlighted_attributes,
        filters=filters,
    )
    return await _run_tool(
        client.create_board(
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=common["group_by"],
            columns=common["columns"],
            sort_by=common["sort_by"],
            highlighted_attributes=common["highlighted_attributes"],
            filters=common["filters"],
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
    common = _validate_board_query_fields(
        project=project,
        group_by=group_by,
        columns=columns,
        sort_by=sort_by,
        highlighted_attributes=highlighted_attributes,
        filters=filters,
    )
    _require_at_least_one(
        safe_name,
        common["project"],
        public,
        starred,
        hidden,
        include_subprojects,
        show_hierarchies,
        timeline_visible,
        common["group_by"],
        common["columns"],
        common["sort_by"],
        common["highlighted_attributes"],
        common["filters"],
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_board(
            board_id=safe_id,
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=common["group_by"],
            columns=common["columns"],
            sort_by=common["sort_by"],
            highlighted_attributes=common["highlighted_attributes"],
            filters=common["filters"],
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
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> AttachmentListResult:
    """List attachments on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, title, file_name, description (see server instructions
    for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=AttachmentSummary)
    return await _run_tool(client.list_work_package_attachments(safe_id, offset=safe_offset, limit=safe_limit))


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
    select: list[str] | None = None,
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
        )
    )


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


async def delete_time_entry(
    ctx: Context,
    time_entry_id: int,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or delete a time entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    return await _run_tool(client.delete_time_entry(time_entry_id=safe_id, confirm=confirm))


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


async def list_reminders(ctx: Context, select: list[str] | None = None) -> ReminderListResult:
    """List the current user's active reminders across all work packages.

    select fields: id, remind_at (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=ReminderSummary)
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
    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
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
    safe_note = _validate_optional_update_text(note, field_name="note", max_length=2000)
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


async def set_project_favorite(
    ctx: Context,
    project: str,
    favorite: bool,
    confirm: bool = False,
) -> FavoriteWriteResult:
    """Prepare or mark/unmark a project as a favorite; only writes when called again with confirm=true.

    project: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display name.
    favorite=true marks it as a favorite; favorite=false removes it.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    if favorite:
        return await _run_tool(client.add_project_favorite(project=safe_project, confirm=confirm))
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


async def list_notifications(
    ctx: Context,
    unread_only: bool = False,
    limit: int | None = None,
    offset: int = 1,
    select: list[str] | None = None,
) -> NotificationListResult:
    """List in-app notifications for the current user.

    select fields: id, subject, reason, read, work_package_id (see server
    instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=NotificationSummary)
    return await _run_tool(client.list_notifications(unread_only=unread_only, limit=safe_limit, offset=safe_offset))


async def mark_notifications_read(
    ctx: Context, notification_id: int | None = None, confirm: bool = False
) -> NotificationMarkResult:
    """Mark a single notification, or all unread notifications, as read.

    notification_id: mark just this notification read. Omit it (default) to
    mark every currently unread notification read instead.
    Set confirm=true to write, or call without confirm=true first for a preview.
    """
    client = _client_from_context(ctx)
    if notification_id is None:
        return await _run_tool(client.mark_all_notifications_read(confirm=confirm))
    safe_id = _validate_positive_int(notification_id, field_name="notification_id")
    return await _run_tool(client.mark_notification_read(safe_id, confirm=confirm))


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
    _require_at_least_one(
        safe_login,
        safe_email,
        safe_firstname,
        safe_lastname,
        admin,
        safe_language,
        message="At least one field must be provided to update.",
    )
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


async def set_user_locked(
    ctx: Context,
    user_id: int,
    locked: bool,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or lock/unlock a user account (admin operation).

    locked=true locks the account; locked=false unlocks it. Preview/confirm
    behavior is identical either way.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    if locked:
        return await _run_tool(client.lock_user(safe_id, confirm=confirm))
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
    _require_at_least_one(
        safe_name, add_user_ids, remove_user_ids, message="At least one field must be provided to update."
    )
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


async def create_storage(
    ctx: Context,
    name: str,
    provider_type: str,
    host: str | None = None,
    authentication_method: str | None = None,
    tenant_id: str | None = None,
    drive_id: str | None = None,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or create an external file storage connection (admin operation).

    provider_type must be one of "Nextcloud", "OneDrive", "Sharepoint". Field
    requirements differ genuinely by provider, per OpenProject's own
    validation (not pre-checked here beyond provider_type itself):
    - Nextcloud: host required; authentication_method required, one of
      "two_way_oauth2" or "oauth2_sso". OpenProject synchronously probes the
      host for live Nextcloud reachability/setup-completeness at
      confirm=true -- an unreachable or non-Nextcloud host is rejected there.
    - OneDrive: host must be omitted; tenant_id required (a GUID, or the
      literal string "consumers").
    - Sharepoint: host required, matching "https://<tenant>/sites/<site>";
      tenant_id required (same format as OneDrive).

    Creating a OneDrive or Sharepoint storage on a Community Edition instance
    without an Enterprise token is rejected by OpenProject itself at
    confirm=true with a clear validation error; Nextcloud is unrestricted.
    """
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_provider_type = _validate_required_query(provider_type, field_name="provider_type", max_length=100)
    safe_host = _validate_optional_query(host, field_name="host", max_length=255)
    safe_authentication_method = _validate_optional_query(
        authentication_method, field_name="authentication_method", max_length=100
    )
    safe_tenant_id = _validate_optional_query(tenant_id, field_name="tenant_id", max_length=100)
    safe_drive_id = _validate_optional_query(drive_id, field_name="drive_id", max_length=255)
    return await _run_tool(
        client.create_storage(
            name=safe_name,
            provider_type=safe_provider_type,
            host=safe_host,
            authentication_method=safe_authentication_method,
            tenant_id=safe_tenant_id,
            drive_id=safe_drive_id,
            confirm=confirm,
        )
    )


async def update_storage(
    ctx: Context,
    storage_id: int,
    name: str | None = None,
    host: str | None = None,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or update an external file storage connection (admin operation).

    Changing host on a Nextcloud storage re-runs OpenProject's live
    host-reachability/setup-completeness probe at confirm=true.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_host = _validate_optional_query(host, field_name="host", max_length=255)
    _require_at_least_one(safe_name, safe_host, message="At least one field must be provided to update.")
    return await _run_tool(client.update_storage(storage_id=safe_id, name=safe_name, host=safe_host, confirm=confirm))


async def delete_storage(
    ctx: Context,
    storage_id: int,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or delete an external file storage connection (admin operation).

    Deleting a storage cascades: every project's link to it (project_storages)
    is deleted along with it, and for a storage with automatically-managed
    project folders, OpenProject may also issue a remote folder-deletion call
    against the external storage itself.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.delete_storage(safe_id, confirm=confirm))


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
    """Return the current user's OpenProject preferences (timezone, sorting, popups, …).

    Note: language is a User attribute, not a preference -- use update_user's
    "language" field to change it.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.get_my_preferences())


async def update_my_preferences(
    ctx: Context,
    time_zone: str | None = None,
    comment_sort_descending: bool | None = None,
    warn_on_leaving_unsaved: bool | None = None,
    auto_hide_popups: bool | None = None,
    confirm: bool = False,
) -> UserPreferencesWriteResult:
    """Prepare or update the current user's preferences (timezone, comment sort order, popups, …).
    Set confirm=true to write.

    Note: language is a User attribute, not a preference -- use update_user's
    "language" field to change it.
    """
    client = _client_from_context(ctx)
    return await _run_tool(
        client.update_my_preferences(
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
    # ann is the function's own return-type annotation (source-defined), never attacker-controlled input.
    # nosemgrep: python.lang.security.dangerous-globals-use.dangerous-globals-use
    model = globals().get(ann) if isinstance(ann, str) else ann
    return model if isinstance(model, type) and is_dataclass(model) else None


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

    Also trimmable when the tool's own signature accepts ``select`` directly,
    even if its return model has none of those three fields -- this is the
    bare single-entity case (e.g. get_work_package → WorkPackageDetail): the
    model itself has no results/items for select to act on, but
    _to_payload's top-level-select branch (see presentation.py) still needs
    the trimming wrapper to run at all in order to reach select in the first
    place.
    """
    if "select" in inspect.signature(fn).parameters:
        return True
    model = _return_model(fn)
    if model is None:
        return False
    names = {f.name for f in dataclass_fields(model)}
    return bool(names & {"results", "payload", "items"})


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


def _validate_optional_version(value: str | None, *, field_name: str = "version") -> str | object | None:
    """Validate a version argument, mapping 'none' (any case) to CLEAR_VERSION.

    Returns None to leave the version unchanged, CLEAR_VERSION to unassign it, or
    the validated version name/id. Mirrors the parent 'none' un-parenting sentinel.
    """
    return _clearable(
        value,
        functools.partial(_validate_optional_query, field_name=field_name, max_length=100),
        sentinel=CLEAR_VERSION,
    )


def _clearable(value: str | None, validate: Callable[[str], Any], *, sentinel: object = CLEAR) -> str | object | None:
    """Map a nullable optional argument to a clear sentinel or a validated value.

    Returns None (leave unchanged), ``sentinel`` (clear the field, for 'none' in any
    case), or the result of ``validate(value)``. Shared by any field that supports
    clearing via 'none' — both HAL-link associations (assignee, responsible, category,
    project_phase, sprint, project parent) and plain scalar fields (estimated_time,
    remaining_time, duration); ``validate`` decides what a non-'none' value means.
    ``sentinel`` defaults to the generic ``CLEAR``; pass a field-specific sentinel
    (e.g. ``CLEAR_VERSION``) where the caller needs to distinguish which field was
    cleared. Use ``_clearable_ref`` instead for a field whose validator genuinely
    accepts a numeric value too (currently only work-package refs).

    ``value`` is declared str-only: every real caller's field is str-typed at the MCP
    tool boundary. A non-str scalar (e.g. a bare JSON number) can still reach here
    from bulk_update_work_packages' untyped ``items: list[dict[str, Any]]`` — the
    ``isinstance`` check below is a runtime safety net for that case (mypy sees `Any`
    there and can't catch it statically), not something this function's own str-only
    contract needs to express. The validator itself (e.g. `_validate_optional_query`)
    is responsible for rejecting a non-str value cleanly if one slips through.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return sentinel
    return validate(value)


def _clearable_ref(
    value: int | str | None, validate: Callable[[int | str], Any], *, sentinel: object = CLEAR
) -> str | object | None:
    """Like ``_clearable``, but for a validator that accepts a numeric ref directly.

    Only ``_validate_work_package_ref`` needs this today (parent/
    parent_work_package_id can legitimately be a JSON int, not just a display-id
    string) — everything else goes through the str-only ``_clearable``.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return sentinel
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


def _validate_optional_update_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
    """Like _validate_optional_text, but preserves an explicit empty string.

    None still means "not provided, leave unchanged"; an explicit "" means
    "clear this field" and is passed through as "" instead of collapsing to
    None. Use only for persisted, genuinely clearable update fields — not for
    create tools (where "" traditionally means "no value given") or transient
    fields like a membership notification message.
    """
    if value is None:
        return None
    normalized = value.strip()
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


# Matches either "cf_<N>" (CustomField#column_name, the actual OpenProject
# filter key) or "customField<N>" (CustomField#attribute_name(:camel_case),
# the JSON/PATCH key used by the read/write value paths) -- OPM-109 accepts
# both forms transparently and always normalizes to "cf_<N>" on the wire, so
# callers never need to know the two are different strings for the same
# field. The id itself must be a positive integer with no leading zero
# (OpenProject's own CustomField ids start at 1; "cf_0"/"cf_01" cannot refer
# to a real field, and left-padding could otherwise let "cf_01" and "cf_1"
# collide silently after normalization).
_CF_FILTER_KEY_PATTERN = re.compile(r"^(cf_|customField)([1-9]\d*)$", re.ASCII)

# Union of every operator symbol legal for AT LEAST ONE CE-realistic custom
# field format (see docs/filters.md's "Custom-Field Filters" section for the
# full per-format breakdown and source citations). This is intentionally the
# union, not a per-format set -- tools.py validators are Settings-free and
# have no network access to look up a given cf_<N>'s actual field_format, so
# a symbol outside this union is rejected here (cheap, unambiguous), while an
# operator that IS in the union but illegal for the specific field's format
# is left to OpenProject's own validation (a clean 400, mapped to
# InvalidInputError by app/transport/errors.py) -- see work_package_service.py's
# _apply_custom_field_filters for the format-aware part of this split.
_CF_FILTER_OPERATOR_SYMBOLS = frozenset(
    {
        "=",
        "~",
        "!",
        "!~",
        ">=",
        "<=",
        "&=",
        "*",
        "!*",
        "<t+",
        ">t+",
        "t+",
        "t",
        "w",
        ">t-",
        "<t-",
        "t-",
        "=d",
        "<>d",
    }
)

_CF_FILTER_MAX_ENTRIES = 20
_CF_FILTER_MAX_VALUES = 100
_CF_FILTER_MAX_VALUE_LENGTH = 1_000


def _validate_custom_field_filters(
    value: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]] | None:
    """Validate custom_field_filters shape and normalize keys to cf_<N>.

    Accepts "cf_<N>" or "customField<N>" keys (both forms always accepted
    transparently) and rejects any other key shape immediately, before any
    network call. Each value must be {"operator": str, "values": list[str]},
    with the operator drawn from the union of all legal CE custom-field
    filter operators (see _CF_FILTER_OPERATOR_SYMBOLS above).

    This is deliberately syntax-only, matching every other tools.py validator
    in this module (see _validate_optional_custom_fields): per-field
    format/operator legality and OPENPROJECT_HIDE_CUSTOM_FIELDS rejection
    both require Settings and/or format knowledge this layer does not have,
    and happen in work_package_service.py's _apply_custom_field_filters
    instead.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(
            "custom_field_filters must be an object mapping 'cf_<N>'/'customField<N>' keys to filter specs."
        )
    if len(value) > _CF_FILTER_MAX_ENTRIES:
        raise ValueError(f"custom_field_filters must contain at most {_CF_FILTER_MAX_ENTRIES} entries.")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, spec in value.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"custom_field_filters keys must be strings, got {type(raw_key).__name__}.")
        match = _CF_FILTER_KEY_PATTERN.match(raw_key)
        if not match:
            raise ValueError(
                f"custom_field_filters key '{raw_key}' must be of the form 'cf_<N>' or 'customField<N>' "
                "(N a positive integer, no leading zero)."
            )
        cf_key = f"cf_{match.group(2)}"
        if cf_key in normalized:
            raise ValueError(
                f"custom_field_filters has two keys that both resolve to '{cf_key}' "
                "(cf_<N> and customField<N> forms cannot be combined for the same field)."
            )
        if not isinstance(spec, dict):
            raise ValueError(f"custom_field_filters['{raw_key}'] must be an object with 'operator' and 'values'.")
        extra_keys = set(spec) - {"operator", "values"}
        if extra_keys:
            raise ValueError(
                f"custom_field_filters['{raw_key}'] has unsupported key(s): {sorted(extra_keys)}. "
                "Only 'operator' and 'values' are accepted."
            )
        if "operator" not in spec or "values" not in spec:
            raise ValueError(f"custom_field_filters['{raw_key}'] must be an object with 'operator' and 'values'.")
        operator = spec["operator"]
        values = spec["values"]
        if not isinstance(operator, str) or not operator:
            raise ValueError(f"custom_field_filters['{raw_key}'].operator must be a non-empty string.")
        if operator not in _CF_FILTER_OPERATOR_SYMBOLS:
            raise ValueError(
                f"custom_field_filters['{raw_key}'].operator '{operator}' is not a recognized "
                f"custom-field filter operator. Valid operators: {sorted(_CF_FILTER_OPERATOR_SYMBOLS)}."
            )
        if not isinstance(values, list):
            raise ValueError(f"custom_field_filters['{raw_key}'].values must be a list of strings.")
        if len(values) > _CF_FILTER_MAX_VALUES:
            raise ValueError(
                f"custom_field_filters['{raw_key}'].values must contain at most {_CF_FILTER_MAX_VALUES} items."
            )
        for item in values:
            if not isinstance(item, str):
                raise ValueError(f"custom_field_filters['{raw_key}'].values must be a list of strings.")
            if len(item) > _CF_FILTER_MAX_VALUE_LENGTH:
                raise ValueError(
                    f"custom_field_filters['{raw_key}'].values items must be at most "
                    f"{_CF_FILTER_MAX_VALUE_LENGTH} characters."
                )
        normalized[cf_key] = {"operator": operator, "values": list(values)}
    return normalized


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
    if PROJECT_REF_RE.fullmatch(normalized):
        return normalized
    # Not identifier-shaped (e.g. contains spaces) — pass through as a display-name
    # candidate. Resolution (including "not found"/"ambiguous" errors) happens
    # server-side in OpenProjectClient._resolve_project_ref, which can actually check.
    if len(normalized) > 255:
        raise ValueError("project must be 255 characters or fewer.")
    return normalized


def _validate_project_identifier(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("identifier is required.")
    if not PROJECT_REF_RE.fullmatch(normalized):
        raise ValueError("identifier must be a valid project identifier.")
    return normalized


def _validate_work_package_ref(value: int | str, *, field_name: str = "work_package_id") -> str:
    normalized = " ".join(str(value).split())
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name=field_name)
        return normalized
    if not WORK_PACKAGE_REF_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name}: use internal id (e.g., 952) or display_id (e.g., 'PROJ-51'), "
            f"not UI display number (e.g., 51)."
        )
    return normalized


def _validate_optional_work_package_ref(value: int | str | None, *, field_name: str = "work_package_id") -> str | None:
    if value is None:
        return None
    return _validate_work_package_ref(value, field_name=field_name)


def _validate_optional_user_ref(value: str | None, field_name: str = "assignee") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        # See _validate_optional_query for why this guard exists.
        raise ValueError(f"{field_name} must be a string.")
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


def _validate_participant_refs(value: list[str] | None) -> list[str] | None:
    """`_validate_optional_user_or_principal_ref`, but for a list where every
    element is required (an empty/blank participant reference is a genuine
    input error, unlike the single-ref case where an empty value means
    "not provided")."""
    if value is None:
        return None
    validated: list[str] = []
    for ref in value:
        safe_ref = _validate_optional_user_or_principal_ref(ref)
        if safe_ref is None:
            raise ValueError("participant_user_refs entries must not be empty.")
        validated.append(safe_ref)
    return validated


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


def _pad_fractional_seconds(value: str) -> str:
    """Pad a `.d{1,6}` fractional-seconds fragment to exactly 6 digits.

    Python's `datetime.fromisoformat` only accepts 0, 3, or 6 fractional
    digits before 3.11 (this project supports 3.10+); DATETIME_RE already
    allows any count from 1 to 6 (matching what OpenProject itself accepts),
    so a value like "09:00:07.5Z" must be normalized to "09:00:07.500000Z"
    before parsing, not just have "Z" swapped for "+00:00".
    """
    return re.sub(r"\.(\d{1,6})(?=Z|[+-]\d{2}:\d{2}$)", lambda m: f".{m.group(1):0<6}", value)


def _duration_between(start_time: str, end_time: str) -> str:
    """Compute an ISO 8601 duration string for end_time - start_time.

    Used by create_time_entry_until/update_time_entry_until to derive `hours`
    locally, since OpenProject's own API never accepts `end_time` as a write
    field (see ISO8601_DURATION_RE's comment and the create_time_entry
    docstring). Uses timedelta's own exact integer fields (days/seconds/
    microseconds), never total_seconds() -- a float -- for the whole-unit
    breakdown, so the hours/minutes/seconds split is exact by construction.
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
    # Only the seconds component ever carries a fractional part (ISO 8601
    # duration semantics; see ISO8601_DURATION_RE's comment). `microseconds` is
    # an exact integer (0-999999) added to the already-whole `seconds`, then
    # formatted with a fixed decimal count (never `%g`/`str(float)`), avoiding
    # both scientific notation on tiny fractions and any rounding-induced carry.
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


def _clearable_duration(value: str | None, *, field_name: str) -> str | object | None:
    """Validate a duration argument, mapping 'none' (any case) to CLEAR.

    Returns None to leave the field unchanged, CLEAR to clear it, or the validated
    ISO 8601 duration. Shared by estimated_time/remaining_time/duration on
    update_work_package and bulk_update_work_packages.
    """
    return _clearable(value, lambda v: _validate_optional_duration(v, field_name=field_name))


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
    # yield a clean ValueError, not a raw TypeError from the comparison.
    # bool is an int subclass, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be at least 0.")
    return value


def _validate_optional_percentage_done(value: int | None, *, field_name: str = "percentage_done") -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if not 0 <= value <= 100:
        raise ValueError(f"{field_name} must be between 0 and 100.")
    return value


def _validate_optional_date(value: str | None, field_name: str) -> str | None:
    """Validate ISO 8601 date (YYYY-MM-DD)."""
    if value is None:
        return None
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


# Verified live against a real OpenProject 17.5 instance (curl against
# GET /work_packages?sortBy=.../groupBy=...) and cross-checked against
# OpenProject's own query property/project-phase select definitions -- these
# are the standard (non-custom-field) attributes OpenProject actually
# accepts, not a guess at plausible names. assignee/assignedTo/
# percentage_done etc. are accepted aliases alongside the canonical Rails
# attribute name; both are included here rather than normalized, since the
# client sends the field straight through unchanged.
_SORTABLE_WORK_PACKAGE_FIELDS = frozenset(
    {
        "id",
        "project",
        "subject",
        "type",
        "status",
        "priority",
        "author",
        "assigned_to",
        "assignee",
        "responsible",
        "updated_at",
        "category",
        "version",
        "start_date",
        "due_date",
        "estimated_hours",
        "estimated_time",
        "remaining_hours",
        "remaining_time",
        "done_ratio",
        "percentage_done",
        "created_at",
        "duration",
        "project_phase",
        "story_points",
    }
)

# Subset of _SORTABLE_WORK_PACKAGE_FIELDS that OpenProject also accepts for
# groupBy -- confirmed by live-testing every entry above (e.g. due_date and
# estimated_hours/estimated_time sort fine but reject with "Can't group by"
# on group_by; parent/subject/id/created_at/updated_at/duration/start_date
# have no groupable column at all in property_select.rb).
_GROUPABLE_WORK_PACKAGE_FIELDS = frozenset(
    {
        "project",
        "type",
        "status",
        "priority",
        "author",
        "assigned_to",
        "assignee",
        "responsible",
        "category",
        "version",
        "done_ratio",
        "percentage_done",
        "project_phase",
    }
)

# A custom field's wire identifier is cf_<id> (the numeric id assigned when the
# field was created on this instance, per CustomField#column_name) -- inherently
# instance-specific and impossible to enumerate statically, so this pattern is
# allowed through without membership-checking against the sets above. Whether a
# given custom field is actually sortable/groupable (its field_format and other
# per-field settings determine that server-side) is left to OpenProject's own
# validation, same as before this ticket.
_CUSTOM_FIELD_PATTERN = re.compile(r"cf_\d+")


def _describe_valid_fields(allowed: frozenset[str]) -> str:
    return ", ".join(sorted(allowed)) + ", or a custom field's cf_<id> identifier"


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
        if field not in _SORTABLE_WORK_PACKAGE_FIELDS and not _CUSTOM_FIELD_PATTERN.fullmatch(field):
            raise ValueError(
                f"sort_by[{i}]: unknown field '{field}'. "
                f"Valid fields are: {_describe_valid_fields(_SORTABLE_WORK_PACKAGE_FIELDS)}."
            )

        result.append(SortCriterion(field=field, direction=direction))

    return result if result else None


def _validate_group_by(value: str | None) -> str | None:
    """Validate group_by against OpenProject's actual groupable work-package columns."""
    normalized = _validate_optional_query(value, field_name="group_by", max_length=120)
    if normalized is None:
        return None
    if normalized not in _GROUPABLE_WORK_PACKAGE_FIELDS and not _CUSTOM_FIELD_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"group_by: unknown field '{normalized}'. "
            f"Valid fields are: {_describe_valid_fields(_GROUPABLE_WORK_PACKAGE_FIELDS)}."
        )
    return normalized


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


def _validate_choice(
    value: str,
    *,
    field_name: str,
    allowed_values: set[str],
) -> str:
    normalized = _validate_required_text(value, field_name=field_name, max_length=100)
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return normalized


# Real enum values from MeetingOutcome (op-sources: modules/meeting/app/models/
# meeting_outcome.rb) -- OpenProject itself rejects any other value with an
# internal server error (500), not a clean 422, so this must be checked
# client-side rather than left to the server's own validation.
_MEETING_OUTCOME_KINDS = {"information", "decision", "work_package"}


# Resolves every classified tool name to its actual function object.
# Derived directly from the classification constants rather than listed a
# second time, so it can never silently diverge from them — a misspelled or
# renamed tool name raises KeyError here at import time instead of a tool
# silently vanishing from registration.
_TOOL_FUNCTIONS: dict[str, Callable] = {
    # name comes from this module's own tool-classification constants below, never attacker-controlled input.
    # nosemgrep: python.lang.security.dangerous-globals-use.dangerous-globals-use
    name: globals()[name]
    for name in (
        *PERSONAL_MUTATION_TOOLS,
        *ATTACHMENT_UPLOAD_TOOLS,
        *(name for names in READ_TOOLS_BY_SCOPE.values() for name in names),
        *(name for names in WRITE_TOOLS_BY_SCOPE.values() for name in names),
    )
}
