"""HTTP-backed QueryExecutionApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). No normalization here -- see the port module docstring for
why: allowlist filtering must happen on raw elements before normalization,
so this adapter returns raw HAL work-package elements straight from the
response's `_embedded.results._embedded.elements` path.

KNOWN SERVER LIMITATION for manually-sorted queries (verified against source,
`app/services/api/v3/work_package_collection_from_query_service.rb`'s
`handle_offset_paging_params`): when the target query is manually sorted
(`query.manually_sorted?`), OpenProject FORCES `offset=1` and `pageSize=
Setting.forced_single_page_size` (default 250) server-side, ignoring
whatever `offset`/`pageSize` this adapter actually sends. A manually-sorted
query with more than 250 matches is therefore capped at its first 250
results through this endpoint -- the Service's scan loop's repeated-page
guard correctly stops rather than looping forever, but any results beyond
that cap are silently unreachable, not surfaced as `truncated`. Not fixable
client-side without an extra request to read the query's own sort
configuration first; accepted as a known limitation rather than adding that
extra round-trip to every call.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from ..ports.query_execution_api import QueryResultPage
from ..stored_query import StoredFilter, StoredQuery, StoredSort
from ..transport.protocol import Transport


class HttpxQueryExecutionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def execute(self, query_id: int, *, offset: int, page_size: int) -> QueryResultPage:
        payload = await self._transport.get_json(
            f"queries/{query_id}",
            params={"offset": str(offset), "pageSize": str(page_size)},
        )
        results = payload.get("_embedded", {}).get("results", {})
        elements = [item for item in results.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        total = results.get("total")
        return QueryResultPage(
            raw_elements=elements,
            server_total=total if isinstance(total, int) else None,
            definition=_stored_query(payload),
        )


# OpenProject renders a project link from the workspace type of the project (`/projects` and on 17.x `/programs` or
# `/portfolios`), all in one id space.
_PROJECT_HREF = re.compile(r"/(?:projects|programs|portfolios)/[1-9][0-9]*\Z")


def _slug(link: Any) -> str | None:
    """The last path segment of a `{"href": ...}` link, URL-unescaped (`/api/v3/queries/operators/%3D` is `=`)."""
    href = link.get("href") if isinstance(link, dict) else None
    return (unquote(href.rsplit("/", 1)[-1]) if isinstance(href, str) else "") or None


def _stored_query(payload: dict[str, Any]) -> StoredQuery | None:
    """The definition a response carries, or None when any member the policy judges is missing or has a shape this
    reader does not know: the caller then cannot tell what the server selected or ordered by."""
    links = payload.get("_links")
    raw_filters, include_subprojects = payload.get("filters"), payload.get("includeSubprojects")
    if not isinstance(links, dict) or not isinstance(raw_filters, list) or not isinstance(include_subprojects, bool):
        return None
    raw_sorts, group_link, project_link = links.get("sortBy"), links.get("groupBy"), links.get("project")
    if not isinstance(raw_sorts, list) or not isinstance(group_link, dict) or "href" not in group_link:
        return None
    if not isinstance(project_link, dict) or "href" not in project_link:
        return None
    project_href = project_link["href"]
    if project_href is not None and not (isinstance(project_href, str) and _PROJECT_HREF.search(project_href)):
        return None
    filters = []
    for item in raw_filters:
        item_links = item.get("_links") if isinstance(item, dict) else None
        key, operator = (
            (_slug(item_links.get("filter")), _slug(item_links.get("operator")))
            if isinstance(item_links, dict)
            else (None, None)
        )
        if key is None or operator is None:
            return None
        filters.append(StoredFilter(key=key, operator=operator))
    sorts = []
    for item in raw_sorts:
        column, _, direction = (_slug(item) or "").rpartition("-")
        if not column or direction not in ("asc", "desc"):
            return None
        sorts.append(StoredSort(column=column, direction=direction))
    group = _slug(group_link)
    if group_link["href"] is not None and group is None:
        return None
    return StoredQuery(
        filters=tuple(filters),
        sort_by=tuple(sorts),
        group_by=group,
        include_subprojects=include_subprojects,
        project_scoped=project_href is not None,
    )
