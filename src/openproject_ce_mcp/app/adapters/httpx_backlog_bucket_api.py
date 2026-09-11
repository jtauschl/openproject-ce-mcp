"""HTTP-backed BacklogBucketApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title`/`has_usable_id` are shared via
`app/adapters/_text.py`, same as Sprints' adapter.

NotFoundError from the transport propagates unwrapped from every method here --
the "Backlogs module" messages are a Service-layer concern (see
backlog_bucket_service.py), mirroring the existing NotFoundError-rewrap
precedent in httpx_sprint_api.py.
"""

from __future__ import annotations

from typing import Any

from ...models import BacklogBucketDetail, BacklogBucketSummary
from ..ports.backlog_bucket_api import BacklogBucketRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import has_usable_id as _has_usable_id
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def _defining_workspace_link(payload: dict[str, Any]) -> Any:
    """Prefer the raw `_links.definingWorkspace` link; if absent, synthesize
    one from the embedded object's own `_links.self` (+ name as a title
    fallback). Verbatim port of httpx_sprint_api.py's helper of the same
    name -- `BacklogBucketRepresenter` uses the identical
    `associated_project as: :definingWorkspace` mechanism Sprints' representer
    uses in OpenProject's source.
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


def normalize_backlog_bucket(payload: dict[str, Any]) -> BacklogBucketSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service decision applied
    after this returns (mirrors Sprints' adapter). No `status`/`startDate`/
    `finishDate` fields -- OpenProject's `BacklogBucketRepresenter` only
    renders `id`, `name`, `definingWorkspace`, `createdAt`, `updatedAt`.
    """
    workspace_link = _defining_workspace_link(payload)
    bucket_id = int(payload["id"])
    return BacklogBucketSummary(
        id=bucket_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Backlog Bucket {bucket_id}",
        defining_workspace_id=_id_from_href(workspace_link.get("href")) if isinstance(workspace_link, dict) else None,
        defining_workspace=_link_title(workspace_link),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def summary_to_detail(summary: BacklogBucketSummary) -> BacklogBucketDetail:
    """BacklogBucketDetail is a bare subclass of BacklogBucketSummary with
    zero added fields, so this is a trivial field-for-field copy (unlike
    Views' detail, which adds `links`) -- built from the already-normalized
    `summary`, not the raw payload, mirroring `httpx_sprint_api.py`'s
    `summary_to_detail`.
    """
    return BacklogBucketDetail(
        id=summary.id,
        name=summary.name,
        defining_workspace_id=summary.defining_workspace_id,
        defining_workspace=summary.defining_workspace,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


class HttpxBacklogBucketApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> BacklogBucketRecord:
        embedded = payload.get("_embedded", {}).get("definingWorkspace")
        summary = normalize_backlog_bucket(payload)
        return BacklogBucketRecord(
            summary=summary,
            detail=summary_to_detail(summary),
            defining_workspace_link=_defining_workspace_link(payload),
            defining_workspace_payload=embedded if isinstance(embedded, dict) else None,
            lookup_name=str(payload.get("name", "")),
        )

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[BacklogBucketRecord], int]:
        payload = await self._transport.get_json(
            "backlog_buckets", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if _has_usable_id(item)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int
    ) -> tuple[list[BacklogBucketRecord], int]:
        payload = await self._transport.get_json(
            f"projects/{project_id}/backlog_buckets", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if _has_usable_id(item)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, backlog_bucket_id: int) -> BacklogBucketRecord:
        return self._record(await self._transport.get_json(f"backlog_buckets/{backlog_bucket_id}"))
