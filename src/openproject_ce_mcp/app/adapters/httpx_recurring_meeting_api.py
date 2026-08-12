"""HTTP-backed RecurringMeetingApi adapter (occurrences included).

No `httpx` import (depends on the `Transport` Protocol only). See
`app/ports/recurring_meeting_api.py`'s module docstring for the verified
route shapes.

`duration`/`location`/`notify` are read straight off `template&.duration`/
`template&.location`/`template&.notify` (`recurring_meeting_representer.rb`)
-- a RAW float/passthrough, NOT the same
`datetime_formatter.format_duration_from_hours` formatted-string getter
Meeting itself uses. `RecurringMeetingSummary.duration` is therefore typed
`float | None`, distinct from `MeetingSummary.duration: str | None` -- do not
conflate the two shapes.

`init_occurrence`'s response is a full Meeting HAL payload (see port
docstring) -- normalized via `normalize_meeting`, imported from
`httpx_meeting_api.py`. This is the one deliberate cross-adapter reuse in
this domain: Adapter->Adapter reuse of a stateless pure function is
permitted by the architecture boundaries (which restrict Service->Adapter
imports, not Adapter->Adapter), matching how `_text.py` helpers are already
shared this way across every adapter in this codebase.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import MeetingSummary, RecurringMeetingOccurrenceSummary, RecurringMeetingSummary
from ..ports.recurring_meeting_api import RecurringMeetingOccurrenceRecord, RecurringMeetingRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text
from .httpx_meeting_api import normalize_meeting


def normalize_recurring_meeting(payload: dict[str, Any]) -> RecurringMeetingSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    author_link = links.get("author")
    template_link = links.get("template")
    duration = payload.get("duration")
    return RecurringMeetingSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        frequency=_trim_text(payload.get("frequency"), limit=SUBJECT_LIMIT),
        monthly_day=payload.get("monthlyDay"),
        monthly_ordinal=_trim_text(payload.get("monthlyOrdinal"), limit=SUBJECT_LIMIT),
        monthly_weekday=_trim_text(payload.get("monthlyWeekday"), limit=SUBJECT_LIMIT),
        interval=payload.get("interval"),
        end_after=_trim_text(payload.get("endAfter"), limit=SUBJECT_LIMIT),
        end_date=payload.get("endDate"),
        iterations=payload.get("iterations"),
        time_zone=_trim_text(payload.get("timeZone"), limit=SUBJECT_LIMIT),
        start_time=payload.get("startTime"),
        location=_trim_text(payload.get("location"), limit=SUBJECT_LIMIT),
        duration=float(duration) if isinstance(duration, int | float) else None,
        notify=payload.get("notify") if isinstance(payload.get("notify"), bool) else None,
        author=_link_title(author_link),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        template_meeting_id=_id_from_href(template_link.get("href")) if isinstance(template_link, dict) else None,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_occurrence(payload: dict[str, Any]) -> RecurringMeetingOccurrenceSummary:
    links = payload.get("_links", {})
    meeting_link = links.get("meeting")
    return RecurringMeetingOccurrenceSummary(
        start_time=payload["startTime"],
        state=_trim_text(payload.get("state"), limit=SUBJECT_LIMIT) or "planned",
        meeting_id=_id_from_href(meeting_link.get("href")) if isinstance(meeting_link, dict) else None,
    )


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = None
        if isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


class HttpxRecurringMeetingApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> RecurringMeetingRecord:
        return RecurringMeetingRecord(
            summary=normalize_recurring_meeting(payload), project_link=payload.get("_links", {}).get("project")
        )

    async def list_page(
        self, *, offset: int, limit: int, project_id: int | None
    ) -> tuple[list[RecurringMeetingRecord], int]:
        params = {"offset": str(offset), "pageSize": str(limit)}
        if project_id is not None:
            params["filters"] = f'[{{"project_id":{{"operator":"=","values":["{project_id}"]}}}}]'
        payload = await self._transport.get_json("recurring_meetings", params=params)
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        records = [self._record(item) for item in elements]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, recurring_meeting_id: int) -> RecurringMeetingRecord:
        return self._record(await self._transport.get_json(f"recurring_meetings/{recurring_meeting_id}"))

    async def create(self, payload: dict[str, Any]) -> RecurringMeetingRecord:
        return self._record(await self._transport.post_json("recurring_meetings", json_body=payload))

    async def update(self, recurring_meeting_id: int, payload: dict[str, Any]) -> RecurringMeetingRecord:
        return self._record(
            await self._transport.patch_json(f"recurring_meetings/{recurring_meeting_id}", json_body=payload)
        )

    async def delete(self, recurring_meeting_id: int) -> None:
        await self._transport.delete(f"recurring_meetings/{recurring_meeting_id}")

    async def list_occurrences(
        self, recurring_meeting_id: int, *, filter: str, limit: int | None
    ) -> list[RecurringMeetingOccurrenceRecord]:
        params: dict[str, str] = {}
        if filter == "upcoming" and limit is not None:
            params["limit"] = str(limit)
        payload = await self._transport.get_json(
            f"recurring_meetings/{recurring_meeting_id}/occurrences/{filter}", params=params or None
        )
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [RecurringMeetingOccurrenceRecord(summary=normalize_occurrence(item)) for item in elements]

    async def init_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> MeetingSummary:
        encoded_start_time = quote(start_time, safe="")
        response = await self._transport.post_json(
            f"recurring_meetings/{recurring_meeting_id}/occurrences/{encoded_start_time}/init"
        )
        return normalize_meeting(response)

    async def cancel_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> None:
        encoded_start_time = quote(start_time, safe="")
        await self._transport.delete(f"recurring_meetings/{recurring_meeting_id}/occurrences/{encoded_start_time}")
