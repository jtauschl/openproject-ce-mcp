"""Meeting Agenda Items Domain API port -- narrow, no universal gateway.

Verified against OpenProject 17.7 source
(`modules/meeting/lib/api/v3/meeting_agenda_items/`): full CRUD lives on the
GLOBAL `meeting_agenda_items` namespace (`meeting_agenda_items_api.rb`) --
`POST meeting_agenda_items`, `GET/PATCH/DELETE meeting_agenda_items/{id}`. No
form endpoint exists for this domain (confirmed: no `create_form_api.rb`/
`update_form_api.rb` under this directory) -- MeetingAgendaItemService follows
the flat inline preview/commit shape (WikiPageLinkService's precedent), not
Meeting's form-based shape.

The global single-resource route's `after_validation` does
`MeetingAgendaItem.joins(meeting: :project).merge(Meeting.visible).find(id)`
-- an authoritative, server-side join through to the parent Meeting's
project. `get(agenda_item_id)` here is therefore safe to fetch-then-check:
the returned record's `meeting_id` is not a caller-supplied "claimed parent"
that must be independently cross-verified (contrast Wiki Page Links'
`delete(work_package_id, link_id)`, which has no such join and must scan the
claimed parent's own links to verify `link_id` actually belongs to it).

Two additional READ-ONLY scoped list views, each mounted differently:
- `list_for_meeting`: `GET meetings/{meeting_id}/agenda_items` (mounted under
  `meetings_api.rb`'s `route_param :id` block via `AgendaItemsByMeetingAPI`).
  UNPAGINATED -- the handler takes no offset/pageSize params at all
  (`agenda_items_by_meeting_api.rb`'s `get do ... end` block).
- `list_for_work_package`: `GET work_packages/{id}/meeting_agenda_items`
  (mounted from the work-package side by
  `MeetingAgendaItemsByWorkPackageAPI` -- the exact WP-side mount point isn't
  visible in this partial checkout's `lib/api/v3/work_packages/
  work_packages_api.rb`, which also lacks Wiki Page Links'/File Links'
  mounts; the path name follows this project's own already-verified-live
  `work_packages/{id}/wiki_page_links` convention). Also UNPAGINATED
  (`MeetingAgendaItemsByWorkPackageAPI`'s `get do ... end` block takes no
  params).

Both scoped list methods return plain lists, not `(records, total)` tuples --
the Service applies limit/offset client-side via `paginate_client`
(`app/pagination.py`), the one helper for "server already returned
everything, slice client-side" (scan_records_and_paginate/paginate_all both
assume the fetcher itself accepts offset/page_size and could usefully
re-fetch, which is pointless here since there is no paging knob to turn).

`meeting_section` link renders under HAL key `"section"` (`as: :section` in
`meeting_agenda_item_representer.rb`), not `"meetingSection"` -- verified
directly against source; the naive guess would silently break section-id
extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MeetingAgendaItemSummary


@dataclass(frozen=True)
class MeetingAgendaItemRecord:
    """One agenda item as read from the API: the normalized `summary`.

    No project link of its own -- an agenda item belongs to a Meeting, which
    belongs to a project. The Service resolves the parent Meeting's project
    via an injected MeetingApi dependency (the cross-domain Port precedent
    this project already established for WorkPackageService->ActivityApi /
    FileLinkService->WorkPackageLookupApi).
    """

    summary: MeetingAgendaItemSummary


class MeetingAgendaItemApi(Protocol):
    """Narrow, Meeting-Agenda-Items-only Domain API port.
    MeetingAgendaItemService depends on this Protocol, never on
    HttpxMeetingAgendaItemApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_meeting(self, meeting_id: int) -> list[MeetingAgendaItemRecord]: ...
    async def list_for_work_package(self, work_package_id: int) -> list[MeetingAgendaItemRecord]: ...
    async def get(self, agenda_item_id: int) -> MeetingAgendaItemRecord: ...
    async def create(self, payload: dict[str, Any]) -> MeetingAgendaItemRecord: ...
    async def update(self, agenda_item_id: int, payload: dict[str, Any]) -> MeetingAgendaItemRecord: ...
    async def delete(self, agenda_item_id: int) -> None: ...
