"""HTTP-backed BoardApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). Boards are
backed by OpenProject's `queries` resource (`_type: "Query"`), not a
dedicated `boards` endpoint -- every HTTP call targets `queries`/
`queries/{id}`/`queries/form`/`queries/{id}/form`.

`_board_web_url` hand-builds a work-package-list WEB url
(`{base_url}/work_packages?query_id={id}`), not an `api/v3/...` href --
this does NOT match `_text.py`'s `link_to_web_url` shape (which derives a
web URL from a server-supplied API href), so it stays a local one-off,
verbatim-ported from client.py's original.

`_normalize_board_filter`/`_normalize_filter_values`/
`_normalize_query_link_list`/`_normalize_query_link_label` are Boards-only
HAL shapes with no sibling analog -- ported verbatim from client.py's
module-level methods, deliberately not unified with anything.

`_resolve_query_reference_href` (client.py:6621-6641) is pure logic with no
I/O -- it stays in `board_service.py`, not this adapter, mirroring how other
Services own their pure write-payload-building helpers directly.

`_can_update_from_links` is shared via `app/adapters/_text.py`, joining it
as the 3rd byte-identical copy (alongside Document/News) once Boards was
migrated.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import BoardDetail, BoardFilter, BoardSummary
from ..ports.board_api import BoardFormResult, BoardRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import can_update_from_links as _can_update_from_links
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    return href.rstrip("/").rsplit("/", maxsplit=1)[-1] or None


def _normalize_filter_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = (
                _link_title(item.get("_links", {}).get("self"))
                or _trim_text(item.get("name"), limit=SUBJECT_LIMIT)
                or _trim_text(item.get("title"), limit=SUBJECT_LIMIT)
                or _trim_text(item.get("href"), limit=SUBJECT_LIMIT)
            )
        else:
            text = _trim_text(item, limit=SUBJECT_LIMIT)
        if text:
            normalized.append(text)
    return normalized


def _normalize_board_filter(payload: dict[str, Any]) -> BoardFilter:
    links = payload.get("_links", {})
    return BoardFilter(
        key=_slug_from_href(links.get("filter", {}).get("href")),
        name=_link_title(links.get("filter")),
        operator=_link_title(links.get("operator")) or _slug_from_href(links.get("operator", {}).get("href")),
        values=_normalize_filter_values(links.get("values")),
    )


def _normalize_query_link_label(value: Any) -> str | None:
    if isinstance(value, dict):
        return _link_title(value) or _slug_from_href(value.get("href"))
    return _trim_text(value, limit=SUBJECT_LIMIT)


def _normalize_query_link_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        label = _normalize_query_link_label(item)
        if label:
            normalized.append(label)
    return normalized


def _board_web_url(payload: dict[str, Any], *, base_url: str) -> str:
    board_id = int(payload["id"])
    return urljoin(f"{base_url.rstrip('/')}/", f"work_packages?query_id={board_id}")


def normalize_board(payload: dict[str, Any], *, base_url: str) -> BoardSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_board, minus the
    _apply_hidden_fields call -- hidden-field masking is a Service decision
    applied after this returns.
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    filters = payload.get("filters", [])
    if not isinstance(filters, list):
        filters = []
    return BoardSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Board {payload['id']}",
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        public=bool(payload.get("public")),
        hidden=bool(payload.get("hidden")),
        starred=bool(payload.get("starred")),
        include_subprojects=bool(payload.get("includeSubprojects")),
        show_hierarchies=bool(payload.get("showHierarchies")),
        timeline_visible=bool(payload.get("timelineVisible")),
        filter_count=len(filters),
        can_update=_can_update_from_links(links),
        can_delete=bool(links.get("delete")),
        url=_board_web_url(payload, base_url=base_url),
    )


def summary_to_detail(summary: BoardSummary, *, payload: dict[str, Any]) -> BoardDetail:
    """Reuses every field from an already-normalized `summary` (not the raw
    payload) and adds the detail-only fields extracted from the raw payload
    once -- no second/different truncation limit is applied to any shared
    field. Built from `summary` rather than by re-running `normalize_board`'s
    field extraction a second time (client.py's original `normalize_board_detail`
    did call `normalize_board` internally, but that recomputes every summary
    field from the raw payload again) -- mirrors `view_api.py`'s
    `summary_to_detail` pattern, avoiding the double-normalization bug class
    found in Views'/Sprints' adapters during the Sprints migration's step-6
    efficiency audit.
    """
    links = payload.get("_links", {})
    return BoardDetail(
        id=summary.id,
        name=summary.name,
        project_id=summary.project_id,
        project=summary.project,
        public=summary.public,
        hidden=summary.hidden,
        starred=summary.starred,
        include_subprojects=summary.include_subprojects,
        show_hierarchies=summary.show_hierarchies,
        timeline_visible=summary.timeline_visible,
        timeline_zoom_level=_trim_text(payload.get("timelineZoomLevel"), limit=SUBJECT_LIMIT),
        highlighting_mode=_trim_text(payload.get("highlightingMode"), limit=SUBJECT_LIMIT),
        group_by=_normalize_query_link_label(links.get("groupBy")),
        columns=_normalize_query_link_list(links.get("columns")),
        sort_by=_normalize_query_link_list(links.get("sortBy")),
        highlighted_attributes=_normalize_query_link_list(links.get("highlightedAttributes")),
        timestamps=[str(item) for item in payload.get("timestamps", []) if str(item).strip()],
        filters=[_normalize_board_filter(item) for item in payload.get("filters", []) if isinstance(item, dict)],
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        url=summary.url,
    )


class HttpxBoardApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    def _record(self, payload: dict[str, Any]) -> BoardRecord:
        summary = normalize_board(payload, base_url=self._base_url)
        return BoardRecord(
            summary=summary,
            detail=summary_to_detail(summary, payload=payload),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_all(self, *, page_size: int) -> list[BoardRecord]:
        payload = await self._transport.get_json("queries", params={"offset": "1", "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def list_page(self, *, offset: int, limit: int) -> tuple[list[BoardRecord], int]:
        payload = await self._transport.get_json("queries", params={"offset": str(offset), "pageSize": str(limit)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, board_id: int) -> BoardRecord:
        return self._record(await self._transport.get_json(f"queries/{board_id}"))

    async def create_form(self, payload: dict[str, Any]) -> BoardFormResult:
        return self._form_result(await self._transport.post_json("queries/form", json_body=payload))

    async def update_form(self, board_id: int, payload: dict[str, Any]) -> BoardFormResult:
        return self._form_result(await self._transport.post_json(f"queries/{board_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> BoardDetail:
        response = await self._transport.post_json("queries", json_body=payload)
        return summary_to_detail(normalize_board(response, base_url=self._base_url), payload=response)

    async def commit_update(self, board_id: int, payload: dict[str, Any]) -> BoardDetail:
        response = await self._transport.patch_json(f"queries/{board_id}", json_body=payload)
        return summary_to_detail(normalize_board(response, base_url=self._base_url), payload=response)

    async def delete(self, board_id: int) -> None:
        await self._transport.delete(f"queries/{board_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> BoardFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return BoardFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = None
        if isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized
