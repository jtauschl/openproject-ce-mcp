"""HTTP-backed UserPreferencesApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). No `_text.py`
imports: verified against client.py:4482-4492's normalize_user_preferences --
every field is a direct `payload.get(...)`, no trimming/id-extraction/
link-title logic and no HAL `_links` block at all on this payload shape.
"""

from __future__ import annotations

from typing import Any

from ...models import UserPreferences
from ..ports.user_preferences_api import UserPreferencesRecord
from ..transport.protocol import Transport


def normalize_user_preferences(payload: dict[str, Any]) -> UserPreferences:
    """Pure HAL->model translation. Verbatim port of client.py's
    normalize_user_preferences -- there was no _apply_hidden_fields call to
    strip here, the original had none at all (masking is a new capability
    this migration adds at the Service layer, not something being preserved).

    No "id"/"lang"/"notificationsReminderTime"/"updatedAt": OpenProject's real
    UserPreferenceRepresenter has none of these fields (verified live) --
    language lives on the User resource, not preferences, and there is no
    equivalent of the other three at all.
    """
    return UserPreferences(
        time_zone=payload.get("timeZone"),
        comment_sort_descending=payload.get("commentSortDescending"),
        warn_on_leaving_unsaved=payload.get("warnOnLeavingUnsaved"),
        auto_hide_popups=payload.get("autoHidePopups"),
    )


class HttpxUserPreferencesApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self) -> UserPreferencesRecord:
        payload = await self._transport.get_json("my_preferences")
        return UserPreferencesRecord(detail=normalize_user_preferences(payload))

    async def commit_update(self, payload: dict[str, Any]) -> UserPreferences:
        response = await self._transport.patch_json("my_preferences", json_body=payload)
        return normalize_user_preferences(response)
