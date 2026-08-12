"""Meetings Domain API port -- narrow, no universal gateway.

Verified against `/api/v3/meetings` (OpenProject 17.7 source,
`modules/meeting/lib/api/v3/meetings/meetings_api.rb`): the ONLY sub-resource
of this domain with a genuine form-based write path (`create_form_api.rb`/
`update_form_api.rb`, both mounting `Endpoints::CreateForm`/`UpdateForm`,
distinct from the flat `Endpoints::Create`/`Update` the other four
sub-resources use). MeetingService therefore follows BoardService's
form-based create()/update() shape, not WikiPageLinkService's flat shape.

A Meeting always belongs to exactly one project (`associated_project` in
`meeting_representer.rb`, no optional-link handling) -- unlike Boards, there
is no "global meeting" case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MeetingSummary
from ..form_result import FormResult


@dataclass(frozen=True)
class MeetingRecord:
    """One meeting as read from the API: the normalized `summary` plus the
    raw `project` HAL link (needed by scope_policy.ensure_project_*_link_allowed,
    which reads `link.get("title")` off the raw dict, not just an extracted id).
    """

    summary: MeetingSummary
    project_link: dict[str, Any] | None


MeetingFormResult = FormResult


class MeetingApi(Protocol):
    """Narrow, Meetings-only Domain API port. MeetingService depends on this
    Protocol, never on HttpxMeetingApi concretely (enforced by the
    architecture-boundary test).

    Also depended on directly by MeetingAgendaItemService/MeetingOutcomeService/
    MeetingSectionService/RecurringMeetingService (occurrences) as a named
    cross-domain Port dependency -- the same precedent this project already
    established for WorkPackageService->ActivityApi and
    FileLinkService/EmojiReactionService->WorkPackageLookupApi: those four
    sub-resource domains have no project of their own, only a parent Meeting,
    so they resolve their own project-allowlist check by fetching the parent
    Meeting through this Port.
    """

    async def list_page(
        self, *, offset: int, limit: int, project_id: int | None
    ) -> tuple[list[MeetingRecord], int]: ...
    async def get(self, meeting_id: int) -> MeetingRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> MeetingFormResult: ...
    async def update_form(self, meeting_id: int, payload: dict[str, Any]) -> MeetingFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> MeetingRecord: ...
    async def commit_update(self, meeting_id: int, payload: dict[str, Any]) -> MeetingRecord: ...
    async def delete(self, meeting_id: int) -> None: ...
