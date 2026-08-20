"""HTTP-backed PrincipalApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_has_usable_id`
is shared via `app/adapters/_text.py`.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import PrincipalSummary
from ..ports.principal_api import PrincipalRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import has_usable_id as _has_usable_id
from ._text import trim_text as _trim_text


def normalize_principal(payload: dict[str, Any]) -> PrincipalSummary:
    """Pure HAL->model translation. Excludes hidden-field masking.

    No login/status fields: `list_principals` hits `GET /api/v3/principals`
    with no `select` parameter, which always takes the SQL fast-path
    representer (`UserSqlRepresenter`/`GroupSqlRepresenter`/
    `PlaceholderUserSqlRepresenter`, verified against op-sources 17.7) --
    none of those declare a `login` or `status` property, only
    `_type`/`id`/`name`/`email` (`firstname`/`lastname` conditionally).
    `login`/`status` exist only on the full single-resource `UserRepresenter`
    (`GET /users/{id}`), which this narrow principals-list port never calls.
    A prior version of this function read payload.get("login")/("status"),
    which were therefore always None for every principal.
    """
    principal_type = _trim_text(payload.get("_type"), limit=SUBJECT_LIMIT)
    principal_id = int(payload["id"])
    return PrincipalSummary(
        id=principal_id,
        type=principal_type,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Principal {principal_id}",
        email=_trim_text(payload.get("email"), limit=SUBJECT_LIMIT),
    )


class HttpxPrincipalApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

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
            PrincipalRecord(
                summary=normalize_principal(item),
                lookup_name=str(item.get("name", "")),
            )
            for item in elements
            if _has_usable_id(item)
        ]
        total = int(payload.get("total", len(records)))
        return records, total
