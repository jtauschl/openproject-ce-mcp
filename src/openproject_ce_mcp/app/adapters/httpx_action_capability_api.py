"""HTTP-backed ActionCapabilityApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). `id_from_href`/
`slug_from_href`/`link_title`/`link_to_web_url`/`origin_from_url` would be
shared via `app/adapters/_text.py`, except `_text.py` has no `slug_from_href`
-- verified: only `app/policies/scope.py` defines it (as a private,
deliberately duplicated copy, per that module's own docstring), and it is not
re-exported from `_text.py` for adapter use. Ported here as a small adapter-local
free function instead of importing across the policies/adapters boundary,
verified byte-identical against client.py's real module-level `_slug_from_href`
(client.py:6521-6529) and `app/policies/scope.py`'s own copy.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from ...models import ActionSummary, CapabilitySummary
from ..ports.action_capability_api import ActionRecord, CapabilityRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _link_to_web_url
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def normalize_action(payload: dict[str, Any], *, base_url: str, origin: str) -> ActionSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_action, minus the
    _apply_hidden_fields call.
    """
    links = payload.get("_links", {})
    self_link = links.get("self", {})
    href = self_link.get("href") if isinstance(self_link, dict) else None
    action_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
    return ActionSummary(
        id=action_id,
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


def normalize_capability(payload: dict[str, Any], *, base_url: str, origin: str) -> CapabilitySummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_capability, minus the
    _apply_hidden_fields call.
    """
    links = payload.get("_links", {})
    self_link = links.get("self", {})
    action_link = links.get("action")
    principal_link = links.get("principal")
    context_link = links.get("context")
    href = self_link.get("href") if isinstance(self_link, dict) else None
    capability_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
    return CapabilitySummary(
        id=capability_id,
        action_id=_slug_from_href(action_link.get("href")) if isinstance(action_link, dict) else None,
        principal_id=_id_from_href(principal_link.get("href")) if isinstance(principal_link, dict) else None,
        principal_name=_link_title(principal_link),
        context=_link_title(context_link) if isinstance(context_link, dict) else None,
        url=_link_to_web_url(href, base_url=base_url, origin=origin),
    )


class HttpxActionCapabilityApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)

    async def list_actions(self, *, offset: int, page_size: int) -> tuple[list[ActionRecord], int]:
        payload = await self._transport.get_json("actions", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [
            ActionRecord(summary=normalize_action(item, base_url=self._base_url, origin=self._origin))
            for item in elements
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(records)))
        return records, total

    async def list_capabilities(
        self, *, filters: list[dict[str, object]], offset: int, page_size: int
    ) -> tuple[list[CapabilityRecord], int]:
        params = {
            "offset": str(offset),
            "pageSize": str(page_size),
            "filters": json.dumps(filters, separators=(",", ":")),
        }
        payload = await self._transport.get_json("capabilities", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [
            CapabilityRecord(summary=normalize_capability(item, base_url=self._base_url, origin=self._origin))
            for item in elements
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(records)))
        return records, total
