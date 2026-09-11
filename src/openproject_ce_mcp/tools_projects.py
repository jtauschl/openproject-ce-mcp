"""Project-facing/core project tool handlers: list_projects, get_project,
get_project_admin_context, get_project_configuration, create_project,
copy_project, get_job_status, update_project, delete_project,
get_my_project_access, get_instance_configuration, list_project_phase_definitions,
get_project_phase_definition, get_project_phase, list_project_storages,
get_project_storage, set_project_favorite, get_project_work_package_context.

Not a full mirror of ``READ_TOOLS_BY_SCOPE["project"]`` in tools.py -- that
scope also gates other domains' tools (news, documents, views, grids, ...)
that live in their own modules. This module holds only the tools whose own
subject is a project (or a project-scoped, project-adjacent operation like
job status or instance configuration -- see tools.py's own comment on why
those are classified under "project").

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
eighteen public names: thirteen of them because existing tests
(`tests/unit/test_project_and_domain_tools.py`,
`tests/unit/test_work_package_tools.py`) import them directly from
`openproject_ce_mcp.tools`; the rest are re-exported alongside for
consistency, matching `tools_admin.py`'s precedent.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from .client import CLEAR
from .models import (
    FavoriteWriteResult,
    InstanceConfiguration,
    JobStatusDetail,
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
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _clearable,
    _require_at_least_one,
    _validate_limit,
    _validate_list_query_params,
    _validate_offset,
    _validate_optional_project_identifier,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_positive_int,
    _validate_project_identifier,
    _validate_project_ref,
    _validate_required_query,
    _validate_required_text,
    _validate_select,
)


@register_tool
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
    return await _run_tool(client.project.list(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
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
    return await _run_tool(client.project.get(safe_project, text_limit=safe_text_limit))


@register_tool
async def get_project_admin_context(
    ctx: Context,
    project: str,
) -> ProjectAdminContext:
    """Return project admin metadata such as lifecycle statuses, parent options, and writable fields."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.project_admin.get_admin_context(safe_project))


@register_tool
async def get_project_configuration(
    ctx: Context,
    project: str,
) -> ProjectConfiguration:
    """Return project-scoped configuration such as internal comment support."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.project.get_configuration(safe_project))


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


@register_tool
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


@register_tool
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
        client.project.copy(
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


@register_tool
async def get_job_status(
    ctx: Context,
    job_status_id: str,
) -> JobStatusDetail:
    """Get the current status of a background job such as project copy."""
    client = _client_from_context(ctx)
    # Job status ids are UUIDs (e.g. "32ac4e5e-1e49-4cbd-b70e-bc1c781d8af2"),
    # never a plain integer, on every supported OpenProject version.
    safe_id = _validate_required_text(job_status_id, field_name="job_status_id", max_length=64)
    return await _run_tool(client.job_status.get(safe_id))


@register_tool
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
    safe_parent = _clearable(parent, lambda v: _validate_optional_project_ref(v), sentinel=CLEAR)
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


@register_tool
async def delete_project(
    ctx: Context,
    project: str,
    confirm: bool = False,
) -> ProjectWriteResult:
    """Prepare or delete a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.project.delete(project_ref=safe_project, confirm=confirm))


@register_tool
async def get_my_project_access(
    ctx: Context,
    project: str,
) -> ProjectAccessSummary:
    """Return the current user's membership and inferred access hints for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.get_my_project_access(safe_project))


@register_tool
async def get_instance_configuration(ctx: Context) -> InstanceConfiguration:
    """Return instance-level OpenProject configuration and active feature flags."""
    client = _client_from_context(ctx)
    return await _run_tool(client.instance_configuration.get_instance_configuration())


@register_tool
async def list_project_phase_definitions(ctx: Context) -> ProjectPhaseDefinitionListResult:
    """List available project lifecycle phase definitions exposed by OpenProject."""
    client = _client_from_context(ctx)
    return await _run_tool(client.project.list_phase_definitions())


@register_tool
async def get_project_phase_definition(
    ctx: Context,
    phase_definition_id: int,
) -> ProjectPhaseDefinition:
    """Get a single project lifecycle phase definition by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(phase_definition_id, field_name="phase_definition_id")
    return await _run_tool(client.project.get_phase_definition(safe_id))


@register_tool
async def get_project_phase(
    ctx: Context,
    phase_id: int,
) -> ProjectPhase:
    """Get a single project lifecycle phase by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(phase_id, field_name="phase_id")
    return await _run_tool(client.project.get_phase(safe_id))


@register_tool
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
    return await _run_tool(
        client.project_storage.list_project_storages(project=safe_project, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_project_storage(
    ctx: Context,
    project_storage_id: int,
) -> ProjectStorageDetail:
    """Get a single project's link to a configured external file storage by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(project_storage_id, field_name="project_storage_id")
    return await _run_tool(client.project_storage.get_project_storage(safe_id))


@register_tool
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


@register_tool
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
    # add_project_favorite/remove_project_favorite collapse through the client's private
    # _set_project_favorite helper straight to project.set_favorite -- that helper adds no
    # logic beyond fixing the `favorite` bool literal, so this is an intentional
    # exception to the "pure single-hop delegation only" rule.
    return await _run_tool(client.project.set_favorite(safe_project, favorite=favorite, confirm=confirm))
