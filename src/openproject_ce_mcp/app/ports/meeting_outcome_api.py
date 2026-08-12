"""Meeting Outcomes Domain API port -- narrow, no universal gateway.

Requires OpenProject 17.6+ -- verified by directory diff: op-sources/17.4 and
17.5 have no `modules/meeting/lib/api/v3/meeting_outcomes/` directory at all;
17.6 and 17.7 do.

Verified against OpenProject 17.7 source
(`modules/meeting/lib/api/v3/meeting_outcomes/`): full CRUD lives on the
GLOBAL `meeting_outcomes` namespace (`meeting_outcomes_api.rb`) -- `POST
meeting_outcomes`, `GET/PATCH/DELETE meeting_outcomes/{id}`. No form endpoint
exists -- MeetingOutcomeService follows the flat inline preview/commit shape.

The global single-resource route's `after_validation` does
`MeetingOutcome.joins(meeting_agenda_item: { meeting: :project }).merge(
Meeting.visible).find(id)` -- an authoritative, two-hop server-side join
through agenda item to meeting to project. `get(outcome_id)` here is
therefore safe to fetch-then-check, resolving this domain's explicit
bypass-check question from this project's own authorization-bypass class
(the Wiki Page Links precedent): a caller cannot pass a mismatched claimed
parent because these bare-id endpoints have no caller-supplied parent at all.

`list_for_agenda_item` (`GET meetings/{meeting_id}/agenda_items/{agenda_item_id}/outcomes`,
mounted via `OutcomesByAgendaItemAPI` under `AgendaItemsByMeetingAPI`) is a
FULL NESTED path requiring both `meeting_id` and `agenda_item_id` -- the
route param is `api_v3_paths.meeting_agenda_item_outcomes(agenda_item_id,
meeting_id:)`. UNPAGINATED -- the handler takes no offset/pageSize params.

`meeting_agenda_item` link on MeetingOutcomeRepresenter renders under HAL key
`"agendaItem"` (`as: :agendaItem` in `meeting_outcome_representer.rb`), NOT
`"meetingAgendaItem"` -- verified directly against source; the naive guess
(following the model field's own name) would silently break this domain's
entire fetch-then-check authorization chain, since `update()`/`delete()`
extract `meeting_agenda_item_id` from this exact link to walk
agenda-item -> meeting -> project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MeetingOutcomeSummary


@dataclass(frozen=True)
class MeetingOutcomeRecord:
    """One outcome as read from the API: the normalized `summary`.

    No project link of its own -- an outcome belongs to a Meeting Agenda
    Item, which belongs to a Meeting, which belongs to a project. The
    Service walks this two-hop chain via injected MeetingAgendaItemApi and
    MeetingApi cross-domain Port dependencies.
    """

    summary: MeetingOutcomeSummary


class MeetingOutcomeApi(Protocol):
    """Narrow, Meeting-Outcomes-only Domain API port. MeetingOutcomeService
    depends on this Protocol, never on HttpxMeetingOutcomeApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_for_agenda_item(self, meeting_id: int, agenda_item_id: int) -> list[MeetingOutcomeRecord]: ...
    async def get(self, outcome_id: int) -> MeetingOutcomeRecord: ...
    async def create(self, payload: dict[str, Any]) -> MeetingOutcomeRecord: ...
    async def update(self, outcome_id: int, payload: dict[str, Any]) -> MeetingOutcomeRecord: ...
    async def delete(self, outcome_id: int) -> None: ...
