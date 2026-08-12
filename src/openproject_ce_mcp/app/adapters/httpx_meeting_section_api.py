"""HTTP-backed MeetingSectionApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). See
`app/ports/meeting_section_api.py`'s module docstring for the verified route
shapes.

No formattable-text field on MeetingSection (`meeting_section_representer.rb`
has only plain `id`/`title`/`position`/`backlog` properties, no
`formattable_property`).
"""

from __future__ import annotations

from typing import Any

from ...models import MeetingSectionSummary
from ..ports.meeting_section_api import MeetingSectionRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import trim_text as _trim_text


def normalize_meeting_section(payload: dict[str, Any]) -> MeetingSectionSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    meeting_link = links.get("meeting")
    return MeetingSectionSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        position=payload.get("position"),
        backlog=bool(payload.get("backlog")),
        meeting_id=_id_from_href(meeting_link.get("href")) if isinstance(meeting_link, dict) else None,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxMeetingSectionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> MeetingSectionRecord:
        return MeetingSectionRecord(summary=normalize_meeting_section(payload))

    async def list_for_meeting(self, meeting_id: int) -> list[MeetingSectionRecord]:
        payload = await self._transport.get_json(f"meetings/{meeting_id}/sections")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [self._record(item) for item in elements]

    async def get(self, section_id: int) -> MeetingSectionRecord:
        return self._record(await self._transport.get_json(f"meeting_sections/{section_id}"))

    async def create(self, payload: dict[str, Any]) -> MeetingSectionRecord:
        return self._record(await self._transport.post_json("meeting_sections", json_body=payload))

    async def update(self, section_id: int, payload: dict[str, Any]) -> MeetingSectionRecord:
        return self._record(await self._transport.patch_json(f"meeting_sections/{section_id}", json_body=payload))

    async def delete(self, section_id: int) -> None:
        await self._transport.delete(f"meeting_sections/{section_id}")
