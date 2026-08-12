"""Recurring Meetings (+ virtual Occurrences) Domain API port.

Verified against OpenProject 17.7 source
(`modules/meeting/lib/api/v3/recurring_meetings/`): full CRUD on the global
`recurring_meetings` namespace (`recurring_meetings_api.rb`) -- `GET/POST
recurring_meetings`, `GET/PATCH/DELETE recurring_meetings/{id}`, all via the
flat `Endpoints::Index/Create/Show/Update/Delete` (no form endpoint mounted
anywhere in this module -- confirmed by grep). List IS paginated
(`OffsetPaginatedCollection`, same as Meetings).

Occurrences are genuinely virtual: `Occurrence`
(`recurring_meetings/occurrence.rb`) is a plain Ruby object, not an
ActiveRecord model -- `start_time`/`recurring_meeting_id`/`meeting_id`
(nullable)/`meeting_state` (nullable, defaults to "planned"). Mounted under
`OccurrencesByRecurringMeetingAPI`:
- `GET .../occurrences/upcoming?limit=N` (default 20, server-side capped;
  computed from the recurrence rule PLUS any already-materialized meetings).
- `GET .../occurrences/past` / `.../cancelled` / `.../open` -- no params at
  all, always return everything.
None of these four carry an offset/pageSize envelope -- NOT genuine
pagination, hence RecurringMeetingOccurrenceListResult is deliberately not a
PageResult subclass (see models.py).
- `POST .../occurrences/{start_time}/init` -- materializes the occurrence
  into a real, permanent Meeting; on success returns status 201 with a FULL
  `MeetingRepresenter` payload (`::API::V3::Meetings::MeetingRepresenter.
  create(call.result, ...)`), not an Occurrence payload. Gated by
  `authorize_in_project(:create_meetings, ...)`.
- `DELETE .../occurrences/{start_time}` -- cancels a not-yet-materialized
  occurrence. Gated by `authorize_in_project(:edit_meetings, ...)`. If the
  occurrence is ALREADY materialized and not itself cancelled, OpenProject
  409s ("Cannot cancel an already instantiated occurrence. Delete the
  meeting instead.") -- surfaces naturally via the transport's existing
  4xx->InvalidInputError mapping, no special-casing needed here. If NOT yet
  materialized, OpenProject silently `create!`s a new, PERMANENT cancelled
  Meeting row and returns 204 with NO body -- there is no way to recover that
  new meeting's id from this response alone (a real data-creation side
  effect behind what reads like a pure "cancel", flagged explicitly in this
  domain's docstrings/tests/tool docs so callers -- and this MCP's own
  integration-test cleanup -- are not caught by surprise).

`start_time` is the occurrence's sole address (no numeric id exists) --
passed as an ISO 8601 string path segment; httpx's URL builder percent-encodes
it safely (same as every other adapter's string path-segment interpolation
in this codebase, no manual encoding needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MeetingSummary, RecurringMeetingOccurrenceSummary, RecurringMeetingSummary


@dataclass(frozen=True)
class RecurringMeetingRecord:
    summary: RecurringMeetingSummary
    project_link: dict[str, Any] | None


@dataclass(frozen=True)
class RecurringMeetingOccurrenceRecord:
    summary: RecurringMeetingOccurrenceSummary


class RecurringMeetingApi(Protocol):
    """Narrow, Recurring-Meetings-only Domain API port
    (occurrences included). RecurringMeetingService depends on this
    Protocol, never on HttpxRecurringMeetingApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_page(
        self, *, offset: int, limit: int, project_id: int | None
    ) -> tuple[list[RecurringMeetingRecord], int]: ...
    async def get(self, recurring_meeting_id: int) -> RecurringMeetingRecord: ...
    async def create(self, payload: dict[str, Any]) -> RecurringMeetingRecord: ...
    async def update(self, recurring_meeting_id: int, payload: dict[str, Any]) -> RecurringMeetingRecord: ...
    async def delete(self, recurring_meeting_id: int) -> None: ...
    async def list_occurrences(
        self, recurring_meeting_id: int, *, filter: str, limit: int | None
    ) -> list[RecurringMeetingOccurrenceRecord]: ...
    async def init_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> MeetingSummary: ...
    async def cancel_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> None: ...
