"""Grids Domain API port (ADR 0001) -- narrow, no universal gateway."""

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

    async def list_all(self, *, scope_filter: str | None) -> list[GridRecord]: ...
    async def get(self, grid_id: int) -> GridRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> GridFormResult: ...
    async def update_form(self, grid_id: int, payload: dict[str, Any]) -> GridFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> GridSummary: ...
    async def commit_update(self, grid_id: int, payload: dict[str, Any]) -> GridSummary: ...
    async def delete(self, grid_id: int) -> None: ...
