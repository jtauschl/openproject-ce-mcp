"""HTTP-backed ViewApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title` are shared via `app/adapters/_text.py` (verified
against client.py's real module-level `_trim_text`/`_id_from_href`/
`_link_title` -- unchanged, safe to reuse).

The `url` field is built via `urljoin` against the *API* path
`api/v3/views/{id}` (verbatim port of client.py's
`self._web_url(f"api/v3/views/{id}")`), same inline pattern as Categories'
adapter -- not a `_link_to_web_url` call, since this is a locally-built
relative path, not a server-supplied href.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import ViewDetail, ViewSummary
from ..ports.view_api import ViewRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_view(payload: dict[str, Any], *, base_url: str) -> ViewSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_view, minus the
    _apply_hidden_fields call -- hidden-field masking is a Service decision
    applied after this returns. Note `type` reads the HAL discriminator key
    `_type` (underscore-prefixed), not `type`.
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    query_link = links.get("query")
    view_id = int(payload["id"])
    return ViewSummary(
        id=view_id,
        type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"View {view_id}",
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        query_id=_id_from_href(query_link.get("href")) if isinstance(query_link, dict) else None,
        query=_link_title(query_link),
        public=bool(payload.get("public")),
        starred=bool(payload.get("starred")),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        url=urljoin(f"{base_url.rstrip('/')}/", f"api/v3/views/{view_id}"),
    )


def summary_to_detail(summary: ViewSummary, *, links: list[str]) -> ViewDetail:
    """Reuses every field from an already-normalized `summary` (not the raw
    payload) and adds exactly one extra field (`links`) -- no second/different
    truncation limit is applied anywhere, unlike Documents' description.

    Built from `summary` rather than by re-running `normalize_view` on the raw
    payload a second time (the original version of this function did that) --
    doubling `_trim_text`/`_id_from_href`/`_link_title` work on every row of
    every `list_all` call for a value list callers never read (`.detail` is
    only read in `get()`). Found during the Sprints migration's step-6
    efficiency audit, which flagged this as a pre-existing bug here too,
    mirroring `version_api.py`'s `summary_to_detail` pattern.
    """
    return ViewDetail(
        id=summary.id,
        type=summary.type,
        name=summary.name,
        project_id=summary.project_id,
        project=summary.project,
        query_id=summary.query_id,
        query=summary.query,
        public=summary.public,
        starred=summary.starred,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        links=links,
        url=summary.url,
    )


class HttpxViewApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    def _record(self, payload: dict[str, Any]) -> ViewRecord:
        summary = normalize_view(payload, base_url=self._base_url)
        return ViewRecord(
            summary=summary,
            detail=summary_to_detail(summary, links=sorted(payload.get("_links", {}).keys())),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ViewRecord], int]:
        payload = await self._transport.get_json("views", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, view_id: int) -> ViewRecord:
        return self._record(await self._transport.get_json(f"views/{view_id}"))
