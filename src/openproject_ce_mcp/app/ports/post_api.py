"""Forums Posts Domain API port -- narrow, no universal gateway.

Posts have exactly one route in OpenProject v3: `GET /api/v3/posts/{id}`
(lib/api/v3/posts/posts_api.rb, verified against 17.7 source). There is no
collection/list endpoint (no `/api/v3/posts`, no project-scoped
`/api/v3/projects/{id}/posts`, no separate "forums" resource at all in the
API), and no create/update/delete route either. PostApi is therefore
get-only, mirroring WikiPageApi's exact shape (see app/ports/wiki_page_api.py).

Callers must already know a post's id (e.g. from a work package's activity
referencing a forum post, or from the OpenProject web UI) -- there is no way
to discover post ids through this MCP or through OpenProject's own API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import PostDetail


@dataclass(frozen=True)
class PostRecord:
    """One post as read from the API: the normalized `detail` (no separate
    summary shape -- no list endpoint means no list-row truncation divergence
    to defer, unlike DocumentRecord/NewsRecord; same rationale as
    WikiPageRecord), plus the raw `project` HAL link (carried separately
    because the allowlist Policy check needs the raw link (href/id), which
    PostDetail itself doesn't carry -- same rationale as
    DocumentRecord.project_link/WikiPageRecord.project_link).
    """

    detail: PostDetail
    project_link: dict[str, Any] | None


class PostApi(Protocol):
    """Narrow, Posts-only Domain API port. PostService depends on this
    Protocol, never on HttpxPostApi concretely (enforced by the
    architecture-boundary test).

    Get-only: the OpenProject v3 API exposes no collection/list endpoint and
    no create/update/delete for posts -- no list_all/commit_*/delete methods
    exist on this Protocol.
    """

    async def get(self, post_id: int) -> PostRecord: ...
