"""HTTP-backed MeetingOutcomeApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). See
`app/ports/meeting_outcome_api.py`'s module docstring for the verified route
shapes and the critical `"agendaItem"` HAL-key finding.

`notes` uses `extract_formattable_text_with_meta` (a `formattable_property`
in source, same trio-hiding shape as Meeting Agenda Items' `notes`).
`author` is `skip_render` when absent (`author_id.nil?`), so its link key
may be entirely missing.

`_record`'s `text_limit` falls back to the constructor-bound default when
omitted -- `list_for_agenda_item` accepts a per-call override (used by
`MeetingOutcomeService.list_for_agenda_item`'s own `text_limit` parameter);
`get`/`create`/`update` intentionally do NOT, always using the
constructor-bound default, matching Meeting Agenda Items' identical shape.
"""

from __future__ import annotations

from typing import Any

from ...models import MeetingOutcomeSummary
from ..ports.meeting_outcome_api import MeetingOutcomeRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_meeting_outcome(payload: dict[str, Any], *, text_limit: int | None) -> MeetingOutcomeSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    agenda_item_link = links.get("agendaItem")
    author_link = links.get("author")
    work_package_link = links.get("workPackage")
    notes, notes_truncated, notes_length = _extract_formattable_text_with_meta(payload.get("notes"), limit=text_limit)
    return MeetingOutcomeSummary(
        id=int(payload["id"]),
        kind=_trim_text(payload.get("kind"), limit=SUBJECT_LIMIT),
        notes=_delimit_user_content(notes),
        notes_truncated=notes_truncated,
        notes_length=notes_length,
        author=_link_title(author_link),
        meeting_agenda_item_id=(
            _id_from_href(agenda_item_link.get("href")) if isinstance(agenda_item_link, dict) else None
        ),
        work_package_id=_id_from_href(work_package_link.get("href")) if isinstance(work_package_link, dict) else None,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxMeetingOutcomeApi:
    def __init__(self, transport: Transport, *, text_limit: int | None = None) -> None:
        self._transport = transport
        self._text_limit = text_limit

    def _record(self, payload: dict[str, Any], *, text_limit: int | None = None) -> MeetingOutcomeRecord:
        effective_text_limit = text_limit if text_limit is not None else self._text_limit
        return MeetingOutcomeRecord(summary=normalize_meeting_outcome(payload, text_limit=effective_text_limit))

    async def list_for_agenda_item(
        self, meeting_id: int, agenda_item_id: int, *, text_limit: int | None = None
    ) -> list[MeetingOutcomeRecord]:
        payload = await self._transport.get_json(f"meetings/{meeting_id}/agenda_items/{agenda_item_id}/outcomes")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        return [self._record(item, text_limit=text_limit) for item in elements]

    async def get(self, outcome_id: int) -> MeetingOutcomeRecord:
        return self._record(await self._transport.get_json(f"meeting_outcomes/{outcome_id}"))

    async def create(self, payload: dict[str, Any]) -> MeetingOutcomeRecord:
        return self._record(await self._transport.post_json("meeting_outcomes", json_body=payload))

    async def update(self, outcome_id: int, payload: dict[str, Any]) -> MeetingOutcomeRecord:
        return self._record(await self._transport.patch_json(f"meeting_outcomes/{outcome_id}", json_body=payload))

    async def delete(self, outcome_id: int) -> None:
        await self._transport.delete(f"meeting_outcomes/{outcome_id}")
