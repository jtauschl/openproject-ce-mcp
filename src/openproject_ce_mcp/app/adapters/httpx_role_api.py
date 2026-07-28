"""HTTP-backed RoleApi adapter (13th migrated domain).

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import RoleSummary
from ..ports.role_api import RoleRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_role(payload: dict[str, Any], *, base_url: str) -> RoleSummary:
    """Pure HAL->model translation. Verbatim port of client.py's normalize_role,
    minus the _apply_hidden_fields call. Roles have no `_links.self` title
    populated on the wire (verified against client.py's original, which never
    read a self link) -- the web URL is built from `id` directly, same as
    client.py's `_web_url(f"roles/{payload['id']}")`.
    """
    role_id = int(payload["id"])
    return RoleSummary(
        id=role_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Role {role_id}",
        url=urljoin(f"{base_url.rstrip('/')}/", f"roles/{role_id}"),
    )


class HttpxRoleApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    async def list_roles(self, *, offset: int, page_size: int) -> tuple[list[RoleRecord], int]:
        # NB (OPM-324): OpenProject's RolesAPI mounts Endpoints::Index with
        # RoleCollectionRepresenter, which subclasses UnpaginatedCollection (not
        # OffsetPaginatedCollection) -- verified against op-sources/17.6. The
        # server ignores offset/pageSize entirely and always returns every role,
        # `total` included. Sent here for interface symmetry / forward-compat
        # only; do not assume this call has already sliced the result. See
        # RoleService.list_roles for the client-side slicing this requires.
        payload = await self._transport.get_json("roles", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [
            RoleRecord(summary=normalize_role(item, base_url=self._base_url))
            for item in elements
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(records)))
        return records, total
