"""Wiki Page Links Domain API port.

Links a work package to a wiki page (OpenProject's `wiki_page_links`
resource, requires OpenProject 17.6+ -- the route/endpoint only exists from
17.6 onward; 17.4/17.5 carry the representer but no reachable route). Full
CRUD minus update: list, create, delete -- no `PATCH`.

No `to_detail`: `WikiPageLinkSummary` is the only normalized shape this
domain has, matching `AttachmentSummary`'s/`FileLinkSummary`'s shape.

`list_for_work_package` uses the work-package-scoped endpoint (`GET
work_packages/{id}/wiki_page_links`), which is paginated (`PageLinkCollectionRepresenter`
inherits from OpenProject's `OffsetPaginatedCollection`) -- returns one page
at a time (`offset`/`page_size` -> `(records, total)`), scanned by the
Service via `scan_records_and_paginate`, matching every other list domain's
shape.

`create` uses the same work-package-scoped endpoint (`POST
work_packages/{id}/wiki_page_links`), not the global `POST
/wiki_page_links`: the scoped endpoint lets OpenProject set `linkable`
server-side from the URL, rather than this MCP constructing that HAL link
itself in the request body.

`create` requires `author_id` -- verified against source
(`relation_page_link_representer.rb`'s `fetch_and_set_author`): the
`_links.author` setter only runs when the request body actually contains an
`author` link key at all; a request that omits it entirely leaves `author`
unset (not defaulted to the current user, despite the setter's non-admin
branch assigning `current_user` when it DOES run), which
`RelationPageLinks::CreateContract#author_must_be_user` then rejects
(`author == user` fails against nil). So the caller must resolve its own
current-user id and send `_links.author` explicitly on every create.

`delete` has no matching single-resource GET on OpenProject's side (only
`DELETE wiki_page_links/{id}`) -- the Service must already know the link's
parent work package (from a prior `list_for_work_package` call) before it can
authorize a delete against that work package's project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import WikiPageLinkSummary


@dataclass(frozen=True)
class WikiPageLinkRecord:
    """One wiki page link as read from the API: the normalized `summary`."""

    summary: WikiPageLinkSummary


class WikiPageLinkApi(Protocol):
    """Narrow, Wiki-Page-Links-only Domain API port. WikiPageLinkService
    depends on this Protocol, never on HttpxWikiPageLinkApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WikiPageLinkRecord], int]: ...
    async def create(
        self, work_package_id: int, *, identifier: str, provider: str, author_id: int
    ) -> WikiPageLinkRecord: ...
    async def delete(self, link_id: int) -> None: ...
