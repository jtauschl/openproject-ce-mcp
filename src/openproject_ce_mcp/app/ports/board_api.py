"""Boards Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import BoardDetail, BoardSummary
from ..form_result import FormResult


@dataclass(frozen=True)
class BoardRecord:
    """One board as read from the API: `summary`, a precomputed `detail`, and
    the raw `project` HAL link.

    `detail` is precomputed, not a lazy `to_detail` thunk: client.py's own
    original `normalize_board_detail` already builds `BoardDetail` by copying
    every field from the already-computed `summary` and adding a handful of
    detail-only fields (group_by/columns/sort_by/highlighted_attributes/
    timestamps/filters/timeline_zoom_level/highlighting_mode/created_at/
    updated_at) extracted from the raw payload once -- there is no divergent
    truncation limit applied to any shared field, so eager computation here
    is SAFE (no crash/masking-correctness risk the way an eager field would
    be for a domain whose list() filters records pre-normalization, e.g.
    Reminders/Notifications), mirroring ViewRecord's identical shape/
    rationale. "Wastes nothing" here means specifically that: no divergent
    truncation limit and no correctness risk -- NOT that it's free. An
    independent Codex review correctly noted `list()`'s own call path never
    reads `.detail` at all, so every list row still pays for parsing
    group_by/columns/sort_by/highlighted_attributes/filters (each its own
    HAL-link extraction) that's thrown away unless that row is later
    `get()`'d individually. Left as eager anyway: Boards/Views/Sprints are
    typically small per-project collections, and a lazy `Callable[[],
    BoardDetail]` thunk (Document's/News's/Reminder's shape) would add a
    layer of indirection to save a few HAL-link parses on lists that rarely
    exceed a few dozen rows -- a deliberate simplicity-over-marginal-CPU
    trade-off, not an oversight, but distinct from "free."

    `project_link` is carried as the RAW link dict, not just an extracted
    href/id, because `_ensure_board_payload_allowed`/
    `_ensure_board_write_payload_allowed` pass the whole raw link into
    `scope.ensure_project_link_allowed`/`ensure_project_write_link_allowed`,
    and `scope.project_candidates()` also reads `link.get("title")` off it,
    not just `href` -- a synthesized `{"href": ...}` would silently drop
    title-based matching (same rationale as GridRecord.scope_link).
    """

    summary: BoardSummary
    detail: BoardDetail
    project_link: dict[str, Any] | None


BoardFormResult = FormResult


class BoardApi(Protocol):
    """Narrow, Boards-only Domain API port. BoardService depends on this
    Protocol, never on HttpxBoardApi concretely (enforced by the
    architecture-boundary test).

    Full CRUD via OpenProject's `queries` resource (Boards have no dedicated
    `boards` endpoint -- `_type: "Query"`). `list_all`/`list_page` are two
    distinct methods, not one method with a filter flag, mirroring the two
    genuinely distinct HTTP shapes client.py's original `list_boards` used:
    a bounded-fetch-then-client-side-filter path, and a directly-paginated
    server-side path reachable only when no filtering is needed at all.
    """

    async def list_all(self, *, page_size: int) -> list[BoardRecord]: ...
    async def list_page(self, *, offset: int, limit: int) -> tuple[list[BoardRecord], int]: ...
    async def get(self, board_id: int) -> BoardRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> BoardFormResult: ...
    async def update_form(self, board_id: int, payload: dict[str, Any]) -> BoardFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> BoardDetail: ...
    async def commit_update(self, board_id: int, payload: dict[str, Any]) -> BoardDetail: ...
    async def delete(self, board_id: int) -> None: ...
