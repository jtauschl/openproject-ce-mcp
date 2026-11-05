"""Versions domain MCP tool handlers: list_versions, get_version, create_version,
update_version, delete_version.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and, for now,
re-exports these five names so existing test imports keep working unchanged
(a deliberate, temporary transition step, not the long-term shape).
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    ProjectListResult,
    ProjectSummary,
    VersionDetail,
    VersionListResult,
    VersionSummary,
    VersionWriteResult,
)
from .tool_params import Confirm, Limit, Offset, OptionalProjectRef, ProjectRef, select_field
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_list_query_params,
    _validate_optional_choice,
    _validate_optional_date,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_positive_int,
    _validate_project_ref,
    _validate_required_query,
    _validate_select,
)

_VERSION_ID = "Numeric version id, as returned by list_versions."
_NAME = "Display name, at most 60 characters."
_DATE = "ISO 8601 date (YYYY-MM-DD)."
_STATUS = 'One of "open", "locked", "closed".'
_SHARING = 'One of "none", "descendants", "hierarchy", "tree".'


@register_tool
async def list_versions(
    ctx: Context,
    project: OptionalProjectRef = None,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(VersionSummary)] = None,
) -> VersionListResult:
    """List versions globally or for a specific project, optionally filtered by a
    case-insensitive name substring.

    Without project, total is only the count of allowed versions returned on THIS page, not a full count of all
    matches; the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until
    next_offset is null."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=VersionSummary)
    return await _run_tool(
        client.version.list(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


@register_tool
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
    return await _run_tool(client.version.get(safe_id, text_limit=safe_text_limit))


@register_tool
async def list_version_projects(
    ctx: Context,
    version_id: int,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(ProjectSummary)] = None,
) -> ProjectListResult:
    """List the projects a version is shared with, limited to projects the read scope covers.

    A version defined outside OPENPROJECT_READ_PROJECTS is refused. total is the count of allowed projects returned
    on THIS page, not a full count; page until next_offset is null."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    _, safe_offset, safe_limit = _validate_list_query_params(None, offset, limit)
    _validate_select(select, row_type=ProjectSummary)
    return await _run_tool(client.version.list_projects(safe_id, offset=safe_offset, limit=safe_limit))


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


@register_tool
async def create_version(
    ctx: Context,
    project: ProjectRef,
    name: Annotated[str, Field(description=_NAME)],
    description: Annotated[str | None, Field(description="Plain text, not Markdown.")] = None,
    start_date: Annotated[str | None, Field(description=_DATE)] = None,
    end_date: Annotated[str | None, Field(description=_DATE)] = None,
    status: Annotated[str | None, Field(description=_STATUS)] = None,
    sharing: Annotated[str | None, Field(description=_SHARING)] = None,
    confirm: Confirm = False,
) -> VersionWriteResult:
    """Create a version for a project.

    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`
    and `error_codes` (OpenProject's error classes, the same in every language).
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_name = _validate_required_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_text(
        description, field_name="description", max_length=None, wrapped_on_read=True
    )
    common = _validate_version_schedule_fields(start_date=start_date, end_date=end_date, status=status, sharing=sharing)
    return await _run_tool(
        client.version.create(
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


@register_tool
async def update_version(
    ctx: Context,
    version_id: Annotated[int, Field(description=_VERSION_ID)],
    name: Annotated[str | None, Field(description=_NAME)] = None,
    description: Annotated[str | None, Field(description='Plain text, not Markdown; "" clears it.')] = None,
    start_date: Annotated[str | None, Field(description=_DATE)] = None,
    end_date: Annotated[str | None, Field(description=_DATE)] = None,
    status: Annotated[str | None, Field(description=_STATUS)] = None,
    sharing: Annotated[str | None, Field(description=_SHARING)] = None,
    confirm: Confirm = False,
) -> VersionWriteResult:
    """Update a version.

    Omitted fields stay unchanged.
    A rejected validation preview is not a tool error; inspect `ready` and
    `validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`
    and `error_codes` (OpenProject's error classes, the same in every language).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=60)
    safe_description = _validate_optional_update_text(
        description, field_name="description", max_length=None, wrapped_on_read=True
    )
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
        client.version.update(
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


@register_tool
async def delete_version(
    ctx: Context,
    version_id: Annotated[int, Field(description=_VERSION_ID)],
    confirm: Confirm = False,
) -> VersionWriteResult:
    """Delete a version; this cannot be undone.

    Rejected while any work package, in any project, uses it (17.8+: also as its "found in" version).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    return await _run_tool(client.version.delete(version_id=safe_id, confirm=confirm))
