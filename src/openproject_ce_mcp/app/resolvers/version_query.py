"""Shared Versions list/filter/paginate query (ADR 0001).

Lives in the Resolvers layer (not Services) so both `VersionService` (Service ->
Resolver is the sanctioned direction) and `VersionResolver` (same layer, sibling
module) can depend on it without either depending on the other.

Returns raw, UNMASKED `VersionSummary` pages -- access-gated, project-resolved,
allowlist-filtered, search-filtered, paginated -- but does NOT apply hidden-field
masking and does NOT build `VersionListResult`. Both are `VersionService`'s job
(masking never changes field *values*, only stamps a later-serialization-time
redaction marker, so deferring it to *after* this function returns is behaviorally
identical to masking eagerly during page-building, as the original inline
`list_versions` did).
"""

from __future__ import annotations

from ...config import Settings
from ...models import VersionSummary
from ..pagination import paginate_client, paginate_server
from ..policies import access
from ..policies.version_policy import version_payload_allowed
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.version_api import VersionApi


async def fetch_version_page(
    *,
    api: VersionApi,
    resolve_project_ref: ProjectRefResolver,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
    project: str | None,
    search: str | None,
    offset: int,
    limit: int,
    context: ProjectResolutionContext | None,
) -> tuple[list[VersionSummary], int, int | None, bool]:
    """Raw, unmasked version-summary page: (page_results, total, next_offset, truncated).

    access.ensure_read_enabled is called HERE (not by callers) so every caller gets
    the identical, redundant-per-page check the original _resolve_version_id already
    performed via its internal list_versions calls -- existing, tested behavior, not
    a redundancy to "fix" away.
    """
    access.ensure_read_enabled("version", settings=settings)
    effective_limit = min(limit, settings.max_page_size, settings.max_results)

    if project and not search:
        # GET /api/v3/versions has no project filter; use the project-scoped endpoint.
        # Access to the project is verified by resolve_project_ref, so per-item
        # allowlist checks are redundant and would fail because the definingProject
        # link only carries the title (display name), not the identifier. No
        # client-side filtering happens here, so exact server-side pagination is safe.
        project_payload = await resolve_project_ref(project, write=False, context=context)
        page = await api.list_for_project(int(project_payload["id"]), offset=offset, page_size=effective_limit)
        results = [r.summary for r in page.records]
        server_total = page.server_total if page.server_total is not None else len(results)
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=server_total)
        return results, server_total, next_offset, truncated

    if project:
        # search given: no server-side name filter exists for the project-scoped
        # endpoint either, so over-fetch this project's versions and filter/paginate
        # in memory instead of relying on exact server-side pagination.
        project_payload = await resolve_project_ref(project, write=False, context=context)
        page = await api.list_for_project(int(project_payload["id"]), offset=1, page_size=settings.max_results)
        results = [r.summary for r in page.records]
    else:
        # The global endpoint has no project filter, so results are filtered
        # client-side against OPENPROJECT_READ_PROJECTS. Fetch up to
        # settings.max_results in one request and paginate the filtered survivors in
        # memory instead. Bounded by max_results -- not a full multi-page walk.
        page = await api.list_global(offset=1, page_size=settings.max_results)
        results = [
            r.summary
            for r in page.records
            if version_payload_allowed(
                {"_links": {"definingProject": r.defining_project_link}},
                settings=settings,
                project_id_to_identifier=project_id_to_identifier,
            )
        ]

    if search:
        search_key = search.casefold()
        results = [item for item in results if search_key in (item.name or "").casefold()]

    return paginate_client(offset=offset, limit=effective_limit, results=results)
