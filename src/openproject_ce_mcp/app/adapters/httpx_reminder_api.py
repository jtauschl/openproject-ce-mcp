"""HTTP-backed ReminderApi adapter (ADR 0001, OPM-318 fourth consumer).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`id_from_href`/`link_to_web_url`/`SUBJECT_LIMIT`
come from `app/adapters/_text.py` -- verified against client.py's real
`normalize_reminder` (client.py:2930-2943): this normalizer needs `trim_text`
(note/creator truncation), `id_from_href` (work_package_id from the
`remindable` link), and `link_to_web_url` (same-origin-checked `self` link
-> web URL).
"""

from __future__ import annotations

from typing import Any

from ...models import ReminderSummary
from ..ports.reminder_api import ReminderRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_to_web_url as _link_to_web_url
from ._text import trim_text as _trim_text


def normalize_reminder(payload: dict[str, Any], *, base_url: str, origin: str) -> ReminderSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_reminder, minus the
    _apply_hidden_fields call -- masking is a Service-layer concern applied
    after this returns (same pattern as every other migrated normalize_*).
    """
    links = payload.get("_links", {})
    creator = payload.get("_embedded", {}).get("creator", {})
    return ReminderSummary(
        id=int(payload["id"]),
        remind_at=payload.get("remindAt"),
        note=_trim_text(payload.get("note"), limit=SUBJECT_LIMIT),
        work_package_id=_id_from_href(links.get("remindable", {}).get("href")),
        creator=_trim_text(creator.get("name"), limit=SUBJECT_LIMIT) if isinstance(creator, dict) else None,
        url=_link_to_web_url(links.get("self", {}).get("href"), base_url=base_url, origin=origin),
    )


class HttpxReminderApi:
    def __init__(self, transport: Transport, *, base_url: str, origin: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = origin

    def _record(self, payload: dict[str, Any]) -> ReminderRecord:
        # `summary` is lazy (see ReminderRecord's docstring): list_all()'s
        # caller filters records by remindable_link BEFORE ever reading
        # .summary, matching client.py's original "filter raw, normalize
        # survivors" order -- an eager field here would normalize (and
        # potentially KeyError on) records the Service is about to discard.
        return ReminderRecord(
            summary=lambda: normalize_reminder(payload, base_url=self._base_url, origin=self._origin),
            remindable_link=payload.get("_links", {}).get("remindable"),
        )

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ReminderRecord], int]:
        payload = await self._transport.get_json(
            "reminders", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, reminder_id: int) -> ReminderRecord:
        return self._record(await self._transport.get_json(f"reminders/{reminder_id}"))

    async def get_remindable_link(self, reminder_id: int) -> dict[str, Any] | None:
        payload = await self._transport.get_json(f"reminders/{reminder_id}")
        return payload.get("_links", {}).get("remindable")

    async def create(self, work_package_id: int, payload: dict[str, Any]) -> ReminderRecord:
        response = await self._transport.post_json(f"work_packages/{work_package_id}/reminders", json_body=payload)
        return self._record(response)

    async def update(self, reminder_id: int, payload: dict[str, Any]) -> ReminderRecord:
        response = await self._transport.patch_json(f"reminders/{reminder_id}", json_body=payload)
        return self._record(response)

    async def delete(self, reminder_id: int) -> None:
        await self._transport.delete(f"reminders/{reminder_id}")
