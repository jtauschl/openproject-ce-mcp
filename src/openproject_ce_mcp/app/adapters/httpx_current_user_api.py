"""HTTP-backed CurrentUserApi adapter.

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

from typing import Any

from ...models import CurrentUser
from ..ports.current_user_api import CurrentUserRecord
from ..transport.protocol import Transport


def normalize_current_user(payload: dict[str, Any]) -> CurrentUser:
    """Pure HAL->model translation. Excludes hidden-field masking.

    Deliberately does NOT trim `name`/`login` (no SUBJECT_LIMIT truncation),
    unlike the sibling normalize_principal -- this asymmetry is intentional
    and must not be "fixed".
    """
    return CurrentUser(
        id=int(payload["id"]),
        name=payload.get("name"),
        login=payload.get("login"),
    )


class HttpxCurrentUserApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get_current_user(self) -> CurrentUserRecord:
        payload = await self._transport.get_json("users/me")
        return CurrentUserRecord(summary=normalize_current_user(payload))
