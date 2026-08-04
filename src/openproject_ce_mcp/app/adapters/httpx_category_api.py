"""HTTP-backed CategoryApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title` are shared via `app/adapters/_text.py` (verified
against client.py's real module-level `_trim_text`/`_id_from_href`/
`_link_title` -- unchanged, safe to reuse).

No `url` field: it used to be a client-constructed API path
(`api/v3/categories/{id}`) -- not a server-supplied href, so it was dropped
per the "no constructed output URLs" rule.

`get(category_id)` uses OpenProject's real `GET /api/v3/categories/{id}`
endpoint (verified against OpenProject's own API implementation).
"""

from __future__ import annotations

from typing import Any

from ...models import CategorySummary
from ..ports.category_api import CategoryRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_category(payload: dict[str, Any], *, project_id: int | None, project_name: str | None) -> CategorySummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_category, minus the
    _apply_hidden_fields call -- hidden-field masking is a Policy/Service
    decision applied after this returns, not something the adapter does.
    """
    category_id = int(payload["id"])
    links = payload.get("_links", {})
    default_assignee_link = links.get("defaultAssignee")
    return CategorySummary(
        id=category_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Category {category_id}",
        project_id=project_id,
        project=project_name,
        is_default=bool(payload.get("isDefault")),
        default_assignee_id=_id_from_href(
            default_assignee_link.get("href") if isinstance(default_assignee_link, dict) else None
        ),
        default_assignee=_link_title(default_assignee_link),
    )


class HttpxCategoryApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[CategoryRecord]:
        # project_name is trimmed here (not by the Service caller) -- verbatim
        # port of client.py's `_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)`,
        # which normalize_category has always applied as part of HAL/text
        # normalization, not as a Service-layer concern.
        trimmed_project_name = _trim_text(project_name, limit=SUBJECT_LIMIT)
        payload = await self._transport.get_json(f"projects/{project_id}/categories")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            CategoryRecord(
                summary=normalize_category(item, project_id=project_id, project_name=trimmed_project_name),
                project_link=None,
            )
            for item in elements
            if isinstance(item, dict)
        ]

    async def get(self, category_id: int) -> CategoryRecord:
        payload = await self._transport.get_json(f"categories/{category_id}")
        links = payload.get("_links", {})
        project_link = links.get("project")
        project_id = _id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None
        project_name = _link_title(project_link)
        return CategoryRecord(
            summary=normalize_category(payload, project_id=project_id, project_name=project_name),
            project_link=project_link,
        )
