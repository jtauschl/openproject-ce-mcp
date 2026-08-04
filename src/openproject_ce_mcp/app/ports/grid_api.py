"""Grids Domain API port -- narrow, no universal gateway.

`list_page`'s `page_size`/`offset` params are a pagination bugfix found
during the Statuses/Priorities/Types migration's broader "N individual
exceptions" audit: client.py's original `list_grids` never sent an
offset/pageSize param at all, an unbounded fetch-all unlike every other
full-list migrated sibling (Boards/Sprints/Views/etc.), which all clamp via
`clamp_limit` and paginate. Confirmed via git history this was NOT a
regression introduced by the Grids migration itself -- the very first,
pre-layered-migration `client.py` implementation already had this shape.
`GridListResult` moved from a bare `CollectionResult` to the standard
`PageResult` shape (offset/limit/total/next_offset/truncated) to match.

`list_page` replaced the earlier single-shot `list_all(scope_filter,
page_size) -> list[GridRecord]` (OPM-373 Phase 5): that method fetched one
bounded page and never walked further, so `offset`/`limit` reduced neither
server load nor response size -- results were sliced client-side out of a
single, always-capped-at-`max_results` fetch. `list_page` follows the same
`(offset, page_size) -> (records, total)` shape `SprintApi.list_all`/
`list_for_project` already use, letting `GridService.list()` scan multiple
server pages via `scan_records_and_paginate` when needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import GridSummary
from ..form_result import FormResult


@dataclass(frozen=True)
class GridRecord:
    """One grid as read from the API: the normalized `summary` plus the raw
    `scope` HAL link. `scope_link` must be carried as the RAW link dict, not
    just an extracted href string -- client.py's original
    `_ensure_grid_payload_allowed` passes the whole raw link to
    `_ensure_project_link_allowed`, and `scope.project_candidates()` also
    reads `link.get("title")` off it, not just `href`; a synthesized
    `{"href": ...}` would silently drop any title-based matching.
    """

    summary: GridSummary
    scope_link: dict[str, Any] | None


GridFormResult = FormResult


class GridApi(Protocol):
    """Narrow, Grids-only Domain API port. GridService depends on this
    Protocol, never on HttpxGridApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_page(
        self, *, offset: int, page_size: int, scope_filter: str | None
    ) -> tuple[list[GridRecord], int]: ...
    async def get(self, grid_id: int) -> GridRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> GridFormResult: ...
    async def update_form(self, grid_id: int, payload: dict[str, Any]) -> GridFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> GridSummary: ...
    async def commit_update(self, grid_id: int, payload: dict[str, Any]) -> GridSummary: ...
    async def delete(self, grid_id: int) -> None: ...
