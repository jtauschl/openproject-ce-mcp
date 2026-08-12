"""Meeting Sections Domain API port -- narrow, no universal gateway.

Verified against OpenProject 17.7 source
(`modules/meeting/lib/api/v3/meeting_sections/`): full CRUD lives on the
GLOBAL `meeting_sections` namespace (`meeting_sections_api.rb`) -- `POST
meeting_sections`, `GET/PATCH/DELETE meeting_sections/{id}`. No form endpoint
exists for this domain -- MeetingSectionService follows the flat inline
preview/commit shape, same as Meeting Agenda Items.

The global single-resource route's `after_validation` does
`MeetingSection.joins(meeting: :project).merge(Meeting.visible).find(id)` --
the same authoritative server-side join pattern as Meeting Agenda Items, so
fetch-then-check via `get()` is safe here too.

`list_for_meeting` (`GET meetings/{meeting_id}/sections`, mounted via
`SectionsByMeetingAPI` under `meetings_api.rb`) is UNPAGINATED -- the handler
takes no offset/pageSize params at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MeetingSectionSummary


@dataclass(frozen=True)
class MeetingSectionRecord:
    """One section as read from the API: the normalized `summary`.

    No project link of its own -- a section belongs to a Meeting. The
    Service resolves the parent Meeting's project via an injected MeetingApi
    dependency, the same cross-domain Port precedent Meeting Agenda Items
    uses.
    """

    summary: MeetingSectionSummary


class MeetingSectionApi(Protocol):
    """Narrow, Meeting-Sections-only Domain API port. MeetingSectionService
    depends on this Protocol, never on HttpxMeetingSectionApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_for_meeting(self, meeting_id: int) -> list[MeetingSectionRecord]: ...
    async def get(self, section_id: int) -> MeetingSectionRecord: ...
    async def create(self, payload: dict[str, Any]) -> MeetingSectionRecord: ...
    async def update(self, section_id: int, payload: dict[str, Any]) -> MeetingSectionRecord: ...
    async def delete(self, section_id: int) -> None: ...
