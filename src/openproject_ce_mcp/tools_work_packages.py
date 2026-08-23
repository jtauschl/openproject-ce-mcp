"""Work package MCP tool handlers: search_work_packages, list_work_packages,
get_work_package, get_work_packages, create_work_package, update_work_package,
bulk_create_work_packages, bulk_update_work_packages, delete_work_package,
create_subtask, add_work_package_comment, list_my_open_work_packages,
get_work_package_activities, list_work_package_reactions,
toggle_activity_emoji_reaction.

This is the final OPM-395 Part A domain migration: every other domain
originally named "work_package_*" (relations, attachments, watchers,
time_entries, costs, github/gitlab integrations, ...) turned out to be a
conceptually separate domain and already migrated to its own module in an
earlier session. What remains here is genuine work-package CRUD/read/comment
core -- previously deferred pending its own app/-layer CRUD migration, which
is now complete: twelve of these functions delegate to
`app/services/work_package_service.py`'s `WorkPackageService`,
`get_work_package_activities` delegates to `ActivityService`, and the two
reaction tools delegate to `EmojiReactionService`. Only input validation,
`select` validation, and bulk-item shaping remain at this presentation layer.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
fifteen public names: thirteen because existing tests
(`tests/test_trimming.py`, `tests/unit/test_tool_validation.py`,
`tests/unit/test_work_package_tools.py`) import them directly from
`openproject_ce_mcp.tools`, the rest re-exported alongside for consistency.
"""

from __future__ import annotations

import functools
from typing import Any

from mcp.server.mcpserver import Context

from .client import BATCH_READ_MAX_IDS, CLEAR, CLEAR_PARENT, CLEAR_VERSION
from .models import (
    ActivityListResult,
    ActivitySummary,
    ActivityWriteResult,
    BatchWorkPackageReadResult,
    BulkWorkPackageWriteResult,
    EmojiReactionListResult,
    EmojiReactionSummary,
    EmojiReactionWriteResult,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
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
    _validate_required_query,
    _validate_required_text,
    _validate_select,
    _validate_sort_by,
    _validate_work_package_ref,
)


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
        client.work_package.search(
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
        client.work_package.list(
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
    return await _run_tool(client.work_package.get(safe_id, text_limit=safe_text_limit))


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

    return await _run_tool(client.work_package.get_batch(ids=unique_ids, text_limit=safe_text_limit))


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
        client.work_package.create(
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
        client.work_package.update(
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
    return await _run_tool(client.work_package.bulk_create(items=safe_items, confirm=confirm))


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
    return await _run_tool(client.work_package.bulk_update(items=safe_items, confirm=confirm))


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
    return await _run_tool(client.work_package.delete(work_package_id=safe_id, confirm=confirm))


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
        client.work_package.create_subtask(
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
        client.work_package.add_comment(
            work_package_id=safe_id,
            comment=safe_comment,
            internal=internal,
            notify=notify,
            confirm=confirm,
        )
    )


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
    return await _run_tool(client.work_package.list_my_open(offset=safe_offset, limit=safe_limit))


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
    return await _run_tool(client.activity.list_for_work_package(safe_id, limit=safe_limit, text_limit=safe_text_limit))


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
    return await _run_tool(client.emoji_reaction.list_for_work_package(safe_id))


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
    return await _run_tool(client.emoji_reaction.toggle(safe_id, safe_reaction, confirm=confirm))
