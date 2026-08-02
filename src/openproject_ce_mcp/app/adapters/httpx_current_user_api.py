"""HTTP-backed CurrentUserApi adapter.

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

from typing import Any

from ...models import CurrentUser
from ..ports.current_user_api import CurrentUserRecord
from ..transport.protocol import Transport
from ._text import web_url as _web_url


def normalize_current_user(payload: dict[str, Any], *, base_url: str) -> CurrentUser:
    """Pure HAL->model translation. Verbatim port of client.py's inline
    CurrentUser construction, minus the _apply_hidden_fields call.

    Deliberately does NOT trim `name`/`login` (no SUBJECT_LIMIT truncation),
    unlike the sibling normalize_principal -- this asymmetry is pre-existing
    and must not be "fixed" during migration.
    """
    return CurrentUser(
        id=int(payload["id"]),
        name=payload.get("name"),
        login=payload.get("login"),
        url=_web_url(f"users/{payload['id']}", base_url=base_url),
    )


class HttpxCurrentUserApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    async def get_current_user(self) -> CurrentUserRecord:
        payload = await self._transport.get_json("users/me")
        return CurrentUserRecord(summary=normalize_current_user(payload, base_url=self._base_url))
