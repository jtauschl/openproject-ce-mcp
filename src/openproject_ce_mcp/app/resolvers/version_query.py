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

from collections.abc import Awaitable, Callable

from ...config import Settings
from ...models import VersionSummary
from ..pagination import paginate_client, paginate_server
from ..policies import access
from ..policies.version_policy import version_payload_allowed
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.version_api import FORMATTABLE_LIMIT, VersionApi, VersionPage, VersionRecord


async def _fetch_all_pages(
    fetch_page: Callable[[int], Awaitable[VersionPage]], *, page_size: int
) -> list[VersionRecord]:
    """Walk every server page of a VersionPage-returning fetcher to completion.

    Terminates on a short page (fewer records than requested page_size), not on
    a possibly-absent/inconsistent server_total -- a single bounded fetch
    (this function's predecessor) silently hid any version beyond
    settings.max_results once the endpoint's real result count exceeded it.
    """
    records: list[VersionRecord] = []
    offset = 1
    while True:
        page = await fetch_page(offset)
        records.extend(page.records)
        if len(page.records) < page_size:
            break
        offset += 1
    return records


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
    text_limit: int | None = FORMATTABLE_LIMIT,
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
        page = await api.list_for_project(
            int(project_payload["id"]), offset=offset, page_size=effective_limit, text_limit=text_limit
        )
        results = [r.summary for r in page.records]
        server_total = page.server_total if page.server_total is not None else len(results)
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=server_total)
        return results, server_total, next_offset, truncated

    if project:
        # search given: no server-side name filter exists for the project-scoped
        # endpoint either, so a full walk of every server page is required -- a
        # single bounded fetch would silently hide any version beyond that cap.
        project_payload = await resolve_project_ref(project, write=False, context=context)
        project_id = int(project_payload["id"])
        records = await _fetch_all_pages(
            lambda offset: api.list_for_project(
                project_id, offset=offset, page_size=settings.max_page_size, text_limit=text_limit
            ),
            page_size=settings.max_page_size,
        )
        results = [r.summary for r in records]
    else:
        # The global endpoint has no project filter, so results are filtered
        # client-side against OPENPROJECT_READ_PROJECTS -- a full walk of every
        # server page is required, or any version beyond a single bounded
        # fetch's cap would be silently hidden.
        records = await _fetch_all_pages(
            lambda offset: api.list_global(offset=offset, page_size=settings.max_page_size, text_limit=text_limit),
            page_size=settings.max_page_size,
        )
        results = [
            r.summary
            for r in records
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
