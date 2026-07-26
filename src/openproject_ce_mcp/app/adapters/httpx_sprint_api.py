"""HTTP-backed SprintApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title` are shared via `app/adapters/_text.py` (verified
against client.py's real module-level `_trim_text`/`_id_from_href`/
`_link_title` -- unchanged, safe to reuse, same as Views' adapter).

The `url` field is built via `urljoin` against the base URL directly (verbatim
port of client.py's `self._web_url(f"sprints/{id}")`) -- a **web UI** URL, not
an API path, unlike Views' adapter (which builds `api/v3/views/{id}`). Do not
conflate the two: Sprints' legacy normalizer always used the web-UI-URL
builder, never the API-path builder.

NotFoundError from the transport propagates unwrapped from every method here --
the three distinct "Backlogs module" messages are a Service-layer concern (see
sprint_service.py), mirroring the existing NotFoundError-rewrap precedent in
ProjectService rather than handling it in the adapter.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import SprintDetail, SprintSummary
from ..ports.sprint_api import SprintRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def _defining_workspace_link(payload: dict[str, Any]) -> Any:
    """Verbatim port of client.py's `_sprint_workspace_link`: prefer the raw
    `_links.definingWorkspace` link; if absent, synthesize one from the
    embedded object's own `_links.self` (+ name as a title fallback).
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


def normalize_sprint(payload: dict[str, Any], *, base_url: str) -> SprintSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_sprint, minus the
    _apply_hidden_fields call -- hidden-field masking is a Service decision
    applied after this returns (mirrors Views' adapter).
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
        url=urljoin(f"{base_url.rstrip('/')}/", f"sprints/{sprint_id}"),
    )


def summary_to_detail(summary: SprintSummary) -> SprintDetail:
    """SprintDetail is a bare subclass of SprintSummary with zero added
    fields, so this is a trivial field-for-field copy (unlike Views'
    detail, which adds `links`) -- built from the already-normalized
    `summary`, not the raw payload, mirroring `version_api.py`'s
    `summary_to_detail`. Building it via `normalize_sprint(payload, ...)` a
    second time (as this originally did) would re-run the full HAL-parsing
    pipeline on every row of every list call for a value list callers never
    read (`.detail` is only read in `get()`) -- found during the Sprints
    migration's step-6 efficiency audit, which also found the identical bug
    pre-existing in `httpx_view_api.py`.
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
        url=summary.url,
    )


class HttpxSprintApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    def _record(self, payload: dict[str, Any]) -> SprintRecord:
        embedded = payload.get("_embedded", {}).get("definingWorkspace")
        summary = normalize_sprint(payload, base_url=self._base_url)
        return SprintRecord(
            summary=summary,
            detail=summary_to_detail(summary),
            defining_workspace_link=_defining_workspace_link(payload),
            defining_workspace_payload=embedded if isinstance(embedded, dict) else None,
        )

    async def list_all(self, *, page_size: int) -> list[SprintRecord]:
        payload = await self._transport.get_json("sprints", params={"offset": "1", "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def list_for_project(self, project_id: int, *, page_size: int) -> list[SprintRecord]:
        records, _total = await self.list_for_project_page(project_id, offset=1, page_size=page_size)
        return records

    async def list_for_project_page(
        self, project_id: int, *, offset: int, page_size: int
    ) -> tuple[list[SprintRecord], int]:
        """Genuine server-paginated page (distinct request per `offset`), for
        `_resolve_sprint_id`'s exhaustive by-name search across every server
        page -- `list_for_project`'s single bounded fetch (mirrors
        `list_all`'s shape) cannot walk more pages than settings.max_results
        covers in one request.
        """
        payload = await self._transport.get_json(
            f"projects/{project_id}/sprints", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(elements)))
        return records, total

    async def get(self, sprint_id: int) -> SprintRecord:
        return self._record(await self._transport.get_json(f"sprints/{sprint_id}"))
