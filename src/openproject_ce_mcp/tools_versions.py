"""Versions domain MCP tool handlers: list_versions, get_version, create_version,
update_version, delete_version.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and, for now,
re-exports these five names so existing test imports keep working unchanged
(a deliberate, temporary transition step, not the long-term shape).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from .models import VersionDetail, VersionListResult, VersionSummary, VersionWriteResult
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


@register_tool
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
    version_id: int,
    confirm: bool = False,
) -> VersionWriteResult:
    """Prepare or delete a version."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(version_id, field_name="version_id")
    return await _run_tool(client.version.delete(version_id=safe_id, confirm=confirm))
