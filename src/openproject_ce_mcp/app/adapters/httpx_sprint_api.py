"""HTTP-backed SprintApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title`/`has_usable_id` are shared via
`app/adapters/_text.py`, same as Views' adapter.

No web `url` field: OpenProject's Backlogs module has no MVC layer for
sprints at all (`only: %i[index create update]`, no `show` route or
controller action), so there is no real page a `sprints/{id}` URL could
point to.

NotFoundError from the transport propagates unwrapped from every method here --
the three distinct "Backlogs module" messages are a Service-layer concern (see
sprint_service.py), mirroring the existing NotFoundError-rewrap precedent in
ProjectService rather than handling it in the adapter.
"""

from __future__ import annotations

from typing import Any

from ...models import SprintDetail, SprintSummary
from ..ports.sprint_api import SprintRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import has_usable_id as _has_usable_id
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def _defining_workspace_link(payload: dict[str, Any]) -> Any:
    """Prefer the raw `_links.definingWorkspace` link; if absent, synthesize
    one from the embedded object's own `_links.self` (+ name as a title
    fallback).
    """
    links = payload.get("_links", {})
    link = links.get("definingWorkspace")
    if isinstance(link, dict):
        return link
    embedded = payload.get("_embedded", {}).get("definingWorkspace")
    if isinstance(embedded, dict):
        self_link = embedded.get("_links", {}).get("self")
        if isinstance(self_link, dict):
            return {**self_link, "title": self_link.get("title") or embedded.get("name")}
    return None


def normalize_sprint(payload: dict[str, Any]) -> SprintSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service decision applied
    after this returns (mirrors Views' adapter).
    """
    links = payload.get("_links", {})
    status_link = links.get("status")
    workspace_link = _defining_workspace_link(payload)
    sprint_id = int(payload["id"])
    return SprintSummary(
        id=sprint_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Sprint {sprint_id}",
        status=_link_title(status_link),
        start_date=payload.get("startDate"),
        finish_date=payload.get("finishDate"),
        defining_workspace_id=_id_from_href(workspace_link.get("href")) if isinstance(workspace_link, dict) else None,
        defining_workspace=_link_title(workspace_link),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def summary_to_detail(summary: SprintSummary) -> SprintDetail:
    """SprintDetail is a bare subclass of SprintSummary with zero added
    fields, so this is a trivial field-for-field copy (unlike Views'
    detail, which adds `links`) -- built from the already-normalized
    `summary`, not the raw payload, mirroring `version_api.py`'s
    `summary_to_detail`. Building it via `normalize_sprint(payload, ...)` a
    second time instead would re-run the full HAL-parsing pipeline on every
    row of every list call for a value list callers never read (`.detail` is
    only read in `get()`); the same avoidable cost also applies to
    `httpx_view_api.py`.
    """
    return SprintDetail(
        id=summary.id,
        name=summary.name,
        status=summary.status,
        start_date=summary.start_date,
        finish_date=summary.finish_date,
        defining_workspace_id=summary.defining_workspace_id,
        defining_workspace=summary.defining_workspace,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


class HttpxSprintApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> SprintRecord:
        embedded = payload.get("_embedded", {}).get("definingWorkspace")
        summary = normalize_sprint(payload)
        return SprintRecord(
            summary=summary,
            detail=summary_to_detail(summary),
            defining_workspace_link=_defining_workspace_link(payload),
            defining_workspace_payload=embedded if isinstance(embedded, dict) else None,
            lookup_name=str(payload.get("name", "")),
        )

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[SprintRecord], int]:
        payload = await self._transport.get_json("sprints", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if _has_usable_id(item)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def list_for_project(self, project_id: int, *, offset: int, page_size: int) -> tuple[list[SprintRecord], int]:
        payload = await self._transport.get_json(
            f"projects/{project_id}/sprints", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if _has_usable_id(item)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, sprint_id: int) -> SprintRecord:
        return self._record(await self._transport.get_json(f"sprints/{sprint_id}"))
