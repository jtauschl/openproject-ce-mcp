"""Grids Domain API port -- narrow, no universal gateway.

`list_page` sends real `offset`/`pageSize` parameters and returns the
standard `PageResult` shape (offset/limit/total/next_offset/truncated),
matching every other full-list domain (Boards/Sprints/Views/etc.), which all
clamp via `clamp_limit` and paginate. It follows the same
`(offset, page_size) -> (records, total)` shape `SprintApi.list_all`/
`list_for_project` use, letting `GridService.list()` scan multiple server
pages via `scan_records_and_paginate` when needed -- this reduces server
load and response size compared to a single-shot, always-capped fetch that
slices the requested `offset`/`limit` window out client-side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import GridSummary
from ..form_result import FormResult


@dataclass(frozen=True)
class GridRecord:
    """One grid as read from the API: the normalized `summary` plus the raw
    `scope` and `project` HAL links. Both stay raw: the grid policy checks
    every project reference a grid carries, and the project link's title is
    an allowlist candidate. `project_link` is None before OpenProject 17.1
    and for grids without a project.
    """

    summary: GridSummary
    scope_link: dict[str, Any] | None
    project_link: dict[str, Any] | None


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
