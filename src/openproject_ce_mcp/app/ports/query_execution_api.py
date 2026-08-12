"""Saved Query execution Domain API port.

`GET /api/v3/queries/{id}` already embeds the fully-resolved work packages
inline (`_embedded.results._embedded.elements`), with `offset`/`pageSize`
query params controlling pagination of that embedded result -- OpenProject
runs the query's own filters/sort/group_by server-side and returns real work
package HAL resources, not merely the query's stored filter definition. No
client-side filter translation is needed.

Returns RAW, UNNORMALIZED elements (mirroring `WorkPackageApi.list()`'s own
`WorkPackagePage.raw_elements` contract) -- allowlist filtering must happen
BEFORE normalization, same reasoning as Work Packages' own list(). The
Service normalizes survivors via the injected `WorkPackageApi.to_record()`
(never by importing `normalize_work_package_summary` directly from
`httpx_work_package_api.py`, which would violate the Service->Port-only
dependency rule enforced by `tests/test_architecture_boundaries.py`).

The raw server-reported `total` on `_embedded.results` is deliberately NOT
exposed as a page-level total here -- it can leak the existence of matches in
projects the caller cannot see (the query executes with the API token's full
server-side permissions, not scoped to OPENPROJECT_READ_PROJECTS). The
Service computes its own, allowlist-safe total from the filtered survivors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class QueryResultPage:
    raw_elements: list[dict[str, Any]]  # UNFILTERED, UNNORMALIZED raw HAL work-package elements


class QueryExecutionApi(Protocol):
    """Narrow, Query-execution-only Domain API port. QueryExecutionService
    depends on this Protocol, never on HttpxQueryExecutionApi concretely
    (enforced by the architecture-boundary test).
    """

    async def execute(self, query_id: int, *, offset: int, page_size: int) -> QueryResultPage: ...
