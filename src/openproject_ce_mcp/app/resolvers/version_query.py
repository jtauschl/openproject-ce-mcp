"""Shared Versions list/filter/paginate query.

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
from ..pagination import paginate_client
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

    Some project-scoped sub-collection endpoints (verified live: a project's
    versions endpoint) silently ignore both offset and page size and always
    return every element -- without the seen-ids check below, the
    short-page break above never triggers and this loops forever, re-fetching
    the same full page.
    """
    records: list[VersionRecord] = []
    seen_ids: set[int] = set()
    offset = 1
    while True:
        page = await fetch_page(offset)
        page_ids = {r.summary.id for r in page.records}
        if records and page_ids and page_ids <= seen_ids:
            break
        seen_ids.update(page_ids)
        records.extend(page.records)
        if len(page.records) < page_size:
            break
        offset += 1
    return records


async def fetch_visible_version_records(
    *,
    api: VersionApi,
    resolve_project_ref: ProjectRefResolver,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
    project: str | None,
    context: ProjectResolutionContext | None,
    text_limit: int | None = FORMATTABLE_LIMIT,
) -> list[VersionRecord]:
    """Every visible VersionRecord (access-gated, project-resolved,
    allowlist-filtered), no search filter, no pagination slicing -- the
    record-preserving core `fetch_version_page` (below, the public
    summary-projection API `VersionService.list()` depends on) and
    `VersionResolver` (which needs `VersionRecord.lookup_name`, not just
    `.summary`, for exact-name matching) both build on.

    access.ensure_read_enabled is called HERE (not by callers) so every caller gets
    the identical, redundant-per-page check the original _resolve_version_id already
    performed via its internal list_versions calls -- existing, tested behavior, not
    a redundancy to "fix" away.
    """
    access.ensure_read_enabled("version", settings=settings)

    if project:
        # GET /api/v3/versions has no project filter; use the project-scoped endpoint.
        # Access to the project is verified by resolve_project_ref, so per-item
        # allowlist checks are redundant and would fail because the definingProject
        # link only carries the title (display name), not the identifier. This
        # endpoint's collection is genuinely unpaginated server-side (verified
        # against op-sources' VersionCollectionRepresenter < UnpaginatedCollection,
        # via VersionsByProjectAPI) -- offset/pageSize params are silently ignored
        # and every element is always returned regardless, so a single bounded
        # fetch would over-fetch (return every version, not just the requested
        # page) while reporting misleading pagination metadata. Walk (a no-op
        # single request, since the server already returns everything) and slice
        # client-side, same as the search/global branches below (this also
        # covers the search-given case: no server-side name filter exists on
        # this endpoint either).
        project_payload = await resolve_project_ref(project, write=False, context=context)
        project_id = int(project_payload["id"])
        return await _fetch_all_pages(
            lambda offset: api.list_for_project(
                project_id, offset=offset, page_size=settings.max_page_size, text_limit=text_limit
            ),
            page_size=settings.max_page_size,
        )

    # The global endpoint has no project filter, so results are filtered
    # client-side against OPENPROJECT_READ_PROJECTS -- a full walk of every
    # server page is required, or any version beyond a single bounded
    # fetch's cap would be silently hidden.
    records = await _fetch_all_pages(
        lambda offset: api.list_global(offset=offset, page_size=settings.max_page_size, text_limit=text_limit),
        page_size=settings.max_page_size,
    )
    return [
        r
        for r in records
        if version_payload_allowed(
            {"_links": {"definingProject": r.defining_project_link}},
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    ]


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

    A summary-projecting wrapper around `fetch_visible_version_records` --
    `VersionService.list()` (the only caller) needs `VersionSummary` rows to
    build `VersionListResult`, not the underlying `VersionRecord`s.
    """
    effective_limit = min(limit, settings.max_page_size, settings.max_results)
    records = await fetch_visible_version_records(
        api=api,
        resolve_project_ref=resolve_project_ref,
        settings=settings,
        project_id_to_identifier=project_id_to_identifier,
        project=project,
        context=context,
        text_limit=text_limit,
    )
    results = [r.summary for r in records]

    if search:
        search_key = search.casefold()
        results = [item for item in results if search_key in (item.name or "").casefold()]

    return paginate_client(offset=offset, limit=effective_limit, results=results)
