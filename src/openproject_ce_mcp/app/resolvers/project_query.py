"""Shared Projects list/filter/paginate query.

Lives in the Resolvers layer (not Services) so both `ProjectService` (Service ->
Resolver is the sanctioned direction) and `ProjectResolver` (same layer, sibling
module -- ProjectResolver's name-search fallback calls this) can depend on it
without either depending on the other.

Returns raw, UNMASKED `ProjectSummary` pages -- access-gated, allowlist-filtered
(server-side filtering happens per-page since the read allowlist can only be
applied once each page's items are known), search-filtered, paginated -- but does
NOT apply hidden-field masking. That is `ProjectService`'s job (masking never
changes field *values*, only stamps a later-serialization-time redaction marker,
so deferring it to *after* this function returns is behaviorally identical to
masking eagerly during page-building).

Does NOT use the shared paginate_client/paginate_server helpers, because
client- and server-pagination units can differ and allowlist filtering
happens mid-page -- every call re-scans from server page 1, skipping the first
`(offset - 1) * effective_limit` already-seen allowed matches.
"""

from __future__ import annotations

from ...config import Settings
from ...models import ProjectSummary
from ..policies import access, project_policy
from ..policies.scope import payload_allowed
from ..ports.project_api import FORMATTABLE_LIMIT, ProjectApi, ProjectRecord


async def fetch_project_page(
    *,
    api: ProjectApi,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
    search: str | None,
    offset: int,
    limit: int,
    text_limit: int | None = FORMATTABLE_LIMIT,
) -> tuple[list[ProjectSummary], int, int | None, bool]:
    """Raw, unmasked project-summary page: (page_results, total, next_offset, truncated).

    access.ensure_read_enabled is called HERE (not by callers), matching
    fetch_version_page's convention.
    """
    access.ensure_read_enabled("project", settings=settings)
    effective_limit = min(limit, settings.max_page_size, settings.max_results)

    skip_count = (offset - 1) * effective_limit
    skipped = 0
    results: list[ProjectSummary] = []
    server_offset = 1
    server_page_size = settings.max_page_size

    # Collects (limit + 1) allowed results before deciding `truncated`, the
    # same early-stopping shape as scan_and_paginate/scan_records_and_paginate
    # -- the (limit + 1)-th allowed item is what proves a further match
    # genuinely exists. Stopping as soon as `limit` is reached (the previous
    # behavior here) could report truncated=True even when the limit-th
    # result was the very last match in the whole allowed collection, making
    # a follow-up call on the reported next_offset silently return nothing.
    while len(results) <= effective_limit:
        page = await api.list(
            server_offset=server_offset, server_page_size=server_page_size, search=search, text_limit=text_limit
        )
        if not page.records:
            break

        # Fail closed: only allowlisted projects are ever collected.
        def _record_allowed(record: ProjectRecord) -> bool:
            return payload_allowed(
                lambda: project_policy.ensure_project_read_allowed(
                    record.payload, settings=settings, project_id_to_identifier=project_id_to_identifier
                )
            )

        allowed_records = [record for record in page.records if _record_allowed(record)]

        for record in allowed_records:
            if skipped < skip_count:
                skipped += 1
                continue
            results.append(record.summary)
            if len(results) > effective_limit:
                break

        if len(results) > effective_limit:
            break
        if page.exhausted:
            break
        server_offset += 1

    truncated = len(results) > effective_limit
    if truncated:
        results = results[:effective_limit]
    total = len(results)
    next_offset = offset + 1 if truncated else None
    return results, total, next_offset, truncated
