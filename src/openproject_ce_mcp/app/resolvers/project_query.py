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

from collections.abc import Mapping, Sequence
from typing import Any

from ...config import Settings
from ...models import ProjectSummary, SortCriterion
from ..policies import project_policy
from ..policies.scope import payload_allowed
from ..ports.project_api import FORMATTABLE_LIMIT, ProjectApi, ProjectRecord


async def fetch_project_records(
    *,
    api: ProjectApi,
    settings: Settings,
    search: str | None,
    offset: int,
    limit: int,
    text_limit: int | None = FORMATTABLE_LIMIT,
    custom_field_filters: Sequence[Mapping[str, Any]] = (),
    sort_by: Sequence[SortCriterion] | None = None,
) -> tuple[list[ProjectRecord], int, int | None, bool]:
    """Raw, unmasked project-record page: (page_results, total, next_offset, truncated).

    The project read gate belongs to the tool's service, not to this lookup, which a write of
    another domain also uses to resolve a project name.
    """
    effective_limit = min(limit, settings.max_page_size, settings.max_results)

    skip_count = (offset - 1) * effective_limit
    skipped = 0
    results: list[ProjectRecord] = []
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
            server_offset=server_offset,
            server_page_size=server_page_size,
            search=search,
            text_limit=text_limit,
            custom_field_filters=custom_field_filters,
            sort_by=sort_by,
        )
        if not page.records:
            break

        # Fail closed: only allowlisted projects are ever collected.
        def _record_allowed(record: ProjectRecord) -> bool:
            return payload_allowed(
                lambda: project_policy.ensure_project_read_allowed(record.payload, settings=settings)
            )

        allowed_records = [record for record in page.records if _record_allowed(record)]

        for record in allowed_records:
            if skipped < skip_count:
                skipped += 1
                continue
            results.append(record)
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


async def fetch_project_page(
    *,
    api: ProjectApi,
    settings: Settings,
    search: str | None,
    offset: int,
    limit: int,
    text_limit: int | None = FORMATTABLE_LIMIT,
) -> tuple[list[ProjectSummary], int, int | None, bool]:
    """The same page as identity-grade summaries, for the callers that resolve a project name or walk the
    projects without showing them: custom field values are never part of these."""
    records, total, next_offset, truncated = await fetch_project_records(
        api=api, settings=settings, search=search, offset=offset, limit=limit, text_limit=text_limit
    )
    return [record.summary for record in records], total, next_offset, truncated
