"""HTTP-backed MeetingApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).

`normalize_meeting` is exported (not module-private) and reused by
`httpx_recurring_meeting_api.py` for `init_occurrence`'s response, which is a
full `MeetingRepresenter` payload (`status 201;
::API::V3::Meetings::MeetingRepresenter.create(call.result, ...)` --
`occurrences_by_recurring_meeting_api.rb`) -- adapter-to-adapter reuse of a
pure normalizer, not a Service->Adapter import (architecture boundaries
restrict Service->Adapter, not Adapter->Adapter reuse of a stateless
function), matching how `_text.py` helpers are already shared this way.

`duration` is a formatted string on read, a formatted string parsed
server-side on write (`meeting_representer.rb`:
`datetime_formatter.format_duration_from_hours`/`parse_duration_to_hours`) --
plain passthrough here, matching `TimeEntrySummary.hours`'s identical shape.
Do NOT confuse with RecurringMeeting's `duration` (a raw float read straight
off `template&.duration`, no formatter) -- see httpx_recurring_meeting_api.py.

`participants` is `_embedded.participants`, each a full UserRepresenter;
`recurringMeeting` link is present only when `recurring_meeting_id` is set on
a materialized-from-a-recurring-template meeting.

Uses the same message-first `_normalize_validation_errors` shape as
`httpx_board_api.py`/`httpx_membership_api.py`/`httpx_user_api.py` (not the
formattable-text-first `normalize_form_validation_errors` from `_text.py`):
Meeting's own writable fields (title/location/duration/state/sharing/notify/
startTime/participants) have no `formattable_property` field of their own
(that appears one layer down, on Agenda Items'/Outcomes' `notes`), so there is
no formattable-text validation-error shape to extract here.
"""

from __future__ import annotations

from typing import Any

from ...models import MeetingParticipantSummary, MeetingSummary
from ..ports.meeting_api import MeetingFormResult, MeetingRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_meeting(payload: dict[str, Any]) -> MeetingSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    author_link = links.get("author")
    recurring_meeting_link = links.get("recurringMeeting")
    embedded = payload.get("_embedded", {})
    raw_participants = embedded.get("participants", [])
    participants = [
        MeetingParticipantSummary(
            id=int(item["id"]),
            name=_trim_text(item.get("name"), limit=SUBJECT_LIMIT),
        )
        for item in raw_participants
        if isinstance(item, dict) and "id" in item
    ]
    return MeetingSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        location=_trim_text(payload.get("location"), limit=SUBJECT_LIMIT),
        lock_version=int(payload.get("lockVersion", 0)),
        start_time=payload.get("startTime"),
        end_time=payload.get("endTime"),
        duration=_trim_text(payload.get("duration"), limit=SUBJECT_LIMIT),
        state=_trim_text(payload.get("state"), limit=SUBJECT_LIMIT),
        sharing=_trim_text(payload.get("sharing"), limit=SUBJECT_LIMIT),
        template=bool(payload.get("template")),
        notify=bool(payload.get("notify")),
        author=_link_title(author_link),
        participants=participants,
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        recurring_meeting_id=(
            _id_from_href(recurring_meeting_link.get("href")) if isinstance(recurring_meeting_link, dict) else None
        ),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
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


class HttpxMeetingApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> MeetingRecord:
        return MeetingRecord(summary=normalize_meeting(payload), project_link=payload.get("_links", {}).get("project"))

    async def list_page(self, *, offset: int, limit: int, project_id: int | None) -> tuple[list[MeetingRecord], int]:
        params = {"offset": str(offset), "pageSize": str(limit)}
        if project_id is not None:
            params["filters"] = f'[{{"project_id":{{"operator":"=","values":["{project_id}"]}}}}]'
        payload = await self._transport.get_json("meetings", params=params)
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        records = [self._record(item) for item in elements]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, meeting_id: int) -> MeetingRecord:
        return self._record(await self._transport.get_json(f"meetings/{meeting_id}"))

    async def create_form(self, payload: dict[str, Any]) -> MeetingFormResult:
        return self._form_result(await self._transport.post_json("meetings/form", json_body=payload))

    async def update_form(self, meeting_id: int, payload: dict[str, Any]) -> MeetingFormResult:
        return self._form_result(await self._transport.post_json(f"meetings/{meeting_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> MeetingRecord:
        return self._record(await self._transport.post_json("meetings", json_body=payload))

    async def commit_update(self, meeting_id: int, payload: dict[str, Any]) -> MeetingRecord:
        return self._record(await self._transport.patch_json(f"meetings/{meeting_id}", json_body=payload))

    async def delete(self, meeting_id: int) -> None:
        await self._transport.delete(f"meetings/{meeting_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> MeetingFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return MeetingFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
