"""HTTP-backed QueryExecutionApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). No normalization here -- see the port module docstring for
why: allowlist filtering must happen on raw elements before normalization,
so this adapter returns raw HAL work-package elements straight from the
response's `_embedded.results._embedded.elements` path.
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
