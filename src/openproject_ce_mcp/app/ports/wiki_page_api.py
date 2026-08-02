"""Wiki Pages Domain API port -- narrow, no universal gateway.

Wiki pages have no collection endpoint in OpenProject v3
(/api/v3/wiki_pages/{id} exists; no /api/v3/wiki_pages or
/api/v3/projects/{id}/wiki_pages list) -- confirmed against
docs/architecture.md's existing "API stubs with no POST/DELETE endpoint"
table and client.py, which has no list_wiki_pages/create/update/delete
methods at all. WikiPageApi is therefore get-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import WikiPageDetail


@dataclass(frozen=True)
class WikiPageRecord:
    """One wiki page as read from the API: the normalized `detail` (there is
    no separate summary shape -- no list endpoint means no list-row
    truncation divergence to defer via a lazy to_detail(), unlike
    DocumentRecord/NewsRecord), plus the raw `project` HAL link (carried
    separately because the allowlist Policy check needs the raw link
    (href/id), which WikiPageDetail itself doesn't carry -- same rationale
    as DocumentRecord.project_link).
    """

    detail: WikiPageDetail
    project_link: dict[str, Any] | None


class WikiPageApi(Protocol):
    """Narrow, Wiki-Pages-only Domain API port. WikiPageService depends on
    this Protocol, never on HttpxWikiPageApi concretely (enforced by the
    architecture-boundary test).

    Get-only: the OpenProject v3 API exposes no collection/list endpoint and
    no create/update/delete for wiki pages -- no list_all/commit_*/delete
    methods exist on this Protocol.
    """

    async def get(self, wiki_page_id: int) -> WikiPageRecord: ...
