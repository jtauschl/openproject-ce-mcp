"""Application Service for the Wiki Pages domain.

Depends on the WikiPageApi Protocol, never HttpxWikiPageApi concretely
(enforced by the architecture-boundary test). No dedicated WikiPageResolver:
like Memberships/News/Documents, a `wiki_page_id` is always a numeric value
already validated by tools.py -- there is no semantic-reference resolution
for this domain to warrant a Resolver in the ADR sense.

Wiki pages share the "project" read scope with Projects/News/Grids/
Documents -- there is no dedicated OPENPROJECT_ENABLE_WIKI_* flag, so the
access.ensure_read_enabled call here uses scope="project" (verbatim
behavior of client.py's original _ensure_read_enabled("project") call).

Get-only, no write state machine at all: the OpenProject v3 API exposes no
create/update/delete endpoint for wiki pages, and there is no list endpoint
either, so this Service has exactly one method. No dedicated
wiki_page_policy.py file exists (see the runbook's explicit carve-out for
domains with no client-side list-filtering) -- get() calls
scope_policy.ensure_project_link_allowed directly on the already-fetched
record's own project_link, mirroring DocumentService.get() and
DocumentService.update()'s reasoning for calling the scope module directly
rather than through a payload_allowed() bool wrapper.

No ProjectRefResolver seam: get(wiki_page_id) takes no `project` filter
parameter at all (there is no list_wiki_pages to filter), so unlike
DocumentService/NewsService/VersionService there is nothing to resolve a
semantic project reference for.
"""

from __future__ import annotations

from ...config import Settings
from ...models import WikiPageDetail
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.wiki_page_api import WikiPageApi


class WikiPageService:
    def __init__(
        self,
        *,
        api: WikiPageApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def get(self, wiki_page_id: int) -> WikiPageDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(wiki_page_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return hidden_fields.apply_hidden_fields("wiki_page", record.detail, settings=self._settings)
