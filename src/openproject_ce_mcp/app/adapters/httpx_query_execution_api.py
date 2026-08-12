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

from ..ports.query_execution_api import QueryResultPage
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
        return QueryResultPage(raw_elements=elements)
