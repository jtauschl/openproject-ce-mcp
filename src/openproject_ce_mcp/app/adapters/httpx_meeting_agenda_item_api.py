"""HTTP-backed MeetingAgendaItemApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). See
`app/ports/meeting_agenda_item_api.py`'s module docstring for the verified
route shapes.

`notes` uses `extract_formattable_text_with_meta` (a `formattable_property`
in source, same trio-hiding shape as `TimeEntrySummary.comment`).
`outcome_ids` reads `_embedded.outcomes` (each a full nested
MeetingOutcomeRepresenter -- only `id` is extracted here, the Service's own
MeetingOutcomeService is the place to fetch full outcome detail).
`meeting_section_id` reads `_links.section` (HAL key `as: :section`, NOT
`meetingSection` -- verified against `meeting_agenda_item_representer.rb`).
`presenter` is `skip_render` when absent (no presenter set), so its link key
may be entirely missing from `_links`, not merely null.
"""

from __future__ import annotations

from typing import Any

from ...models import MeetingAgendaItemSummary
from ..ports.meeting_agenda_item_api import MeetingAgendaItemRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_meeting_agenda_item(payload: dict[str, Any], *, text_limit: int | None) -> MeetingAgendaItemSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    meeting_link = links.get("meeting")
    author_link = links.get("author")
    presenter_link = links.get("presenter")
    work_package_link = links.get("workPackage")
    section_link = links.get("section")
    notes, notes_truncated, notes_length = _extract_formattable_text_with_meta(payload.get("notes"), limit=text_limit)
    embedded = payload.get("_embedded", {})
    raw_outcomes = embedded.get("outcomes", [])
    outcome_ids = [int(item["id"]) for item in raw_outcomes if isinstance(item, dict) and "id" in item]
    return MeetingAgendaItemSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        notes=notes,
        notes_truncated=notes_truncated,
        notes_length=notes_length,
        position=payload.get("position"),
        duration_in_minutes=payload.get("durationInMinutes"),
        item_type=_trim_text(payload.get("itemType"), limit=SUBJECT_LIMIT),
        lock_version=int(payload.get("lockVersion", 0)),
        meeting_id=_id_from_href(meeting_link.get("href")) if isinstance(meeting_link, dict) else None,
        author=_link_title(author_link),
        presenter=_link_title(presenter_link),
        work_package_id=_id_from_href(work_package_link.get("href")) if isinstance(work_package_link, dict) else None,
        meeting_section_id=_id_from_href(section_link.get("href")) if isinstance(section_link, dict) else None,
        outcome_ids=outcome_ids,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxMeetingAgendaItemApi:
    def __init__(self, transport: Transport, *, text_limit: int | None = None) -> None:
        self._transport = transport
        self._text_limit = text_limit

    def _record(self, payload: dict[str, Any]) -> MeetingAgendaItemRecord:
        return MeetingAgendaItemRecord(summary=normalize_meeting_agenda_item(payload, text_limit=self._text_limit))

    async def list_for_meeting(self, meeting_id: int) -> list[MeetingAgendaItemRecord]:
        payload = await self._transport.get_json(f"meetings/{meeting_id}/agenda_items")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [self._record(item) for item in elements]

    async def list_for_work_package(self, work_package_id: int) -> list[MeetingAgendaItemRecord]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/meeting_agenda_items")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [self._record(item) for item in elements]

    async def get(self, agenda_item_id: int) -> MeetingAgendaItemRecord:
        return self._record(await self._transport.get_json(f"meeting_agenda_items/{agenda_item_id}"))

    async def create(self, payload: dict[str, Any]) -> MeetingAgendaItemRecord:
        return self._record(await self._transport.post_json("meeting_agenda_items", json_body=payload))

    async def update(self, agenda_item_id: int, payload: dict[str, Any]) -> MeetingAgendaItemRecord:
        return self._record(
            await self._transport.patch_json(f"meeting_agenda_items/{agenda_item_id}", json_body=payload)
        )

    async def delete(self, agenda_item_id: int) -> None:
        await self._transport.delete(f"meeting_agenda_items/{agenda_item_id}")
