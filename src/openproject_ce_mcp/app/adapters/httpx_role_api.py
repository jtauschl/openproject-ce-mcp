"""HTTP-backed RoleApi adapter.

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

from typing import Any

from ...models import RoleSummary
from ..ports.role_api import RoleRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_role(payload: dict[str, Any]) -> RoleSummary:
    """Pure HAL->model translation. Verbatim port of client.py's normalize_role,
    minus the _apply_hidden_fields call and the dead web `url` field (OpenProject's
    admin roles are Rails-routed `except: %i[show]` with no controller `show`
    action -- the constructed URL never resolved to a real page).
    """
    role_id = int(payload["id"])
    return RoleSummary(
        id=role_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Role {role_id}",
    )


class HttpxRoleApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_roles(self, *, offset: int, page_size: int) -> tuple[list[RoleRecord], int]:
        # NB: OpenProject's RolesAPI mounts Endpoints::Index with
        # RoleCollectionRepresenter, which subclasses UnpaginatedCollection (not
        # OffsetPaginatedCollection) -- verified against OpenProject's own API
        # implementation. The server ignores offset/pageSize entirely and always returns every role,
        # `total` included. Sent here for interface symmetry / forward-compat
        # only; do not assume this call has already sliced the result. See
        # RoleService.list_roles for the client-side slicing this requires.
        payload = await self._transport.get_json("roles", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [RoleRecord(summary=normalize_role(item)) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total
