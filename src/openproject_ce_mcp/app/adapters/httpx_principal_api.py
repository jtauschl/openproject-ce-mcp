"""HTTP-backed PrincipalApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

import json
from typing import Any

from ...models import PrincipalSummary
from ..ports.principal_api import PrincipalRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text
from ._text import web_url as _web_url


def normalize_principal(payload: dict[str, Any], *, base_url: str) -> PrincipalSummary:
    """Pure HAL->model translation. Verbatim port of client.py's
    normalize_principal, minus the _apply_hidden_fields call.

    The URL path branches on `_type` (`groups/{id}` vs `users/{id}`) -- a
    real conditional, not a constant, since `principals` is a combined
    search over both users and groups.
    """
    principal_type = _trim_text(payload.get("_type"), limit=SUBJECT_LIMIT)
    principal_id = int(payload["id"])
    path_prefix = "groups" if principal_type == "Group" else "users"
    return PrincipalSummary(
        id=principal_id,
        type=principal_type,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Principal {principal_id}",
        login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
        email=_trim_text(payload.get("email"), limit=SUBJECT_LIMIT),
        status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
        url=_web_url(f"{path_prefix}/{principal_id}", base_url=base_url),
    )


class HttpxPrincipalApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    async def list_principals(
        self, *, search: str | None, offset: int, page_size: int
    ) -> tuple[list[PrincipalRecord], int]:
        filters: list[dict[str, Any]] = []
        if search:
            filters.append({"name": {"operator": "~", "values": [search]}})
        payload = await self._transport.get_json(
            "principals",
            params={
                "offset": str(offset),
                "pageSize": str(page_size),
                "filters": json.dumps(filters, separators=(",", ":")),
            },
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [
            PrincipalRecord(summary=normalize_principal(item, base_url=self._base_url))
            for item in elements
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(records)))
        return records, total
