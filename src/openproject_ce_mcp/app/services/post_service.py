"""Application Service for the Forums Posts domain.

Depends on the PostApi Protocol, never HttpxPostApi concretely (enforced by
the architecture-boundary test). No dedicated PostResolver: like
Memberships/News/Documents/Wiki Pages, a `post_id` is always a numeric value
already validated by tools.py -- there is no semantic-reference resolution
for this domain to warrant a Resolver in the ADR sense.

Posts share the "project" read scope with Projects/News/Grids/Documents/Wiki
Pages -- there is no dedicated OPENPROJECT_ENABLE_POST_* flag, so the
access.ensure_read_enabled call here uses scope="project".

Get-only, no write state machine at all: the OpenProject v3 API exposes no
create/update/delete endpoint for posts, and there is no list endpoint
either, so this Service has exactly one method -- structurally identical to
WikiPageService. get() calls scope_policy.ensure_project_link_allowed
directly on the already-fetched record's own project_link, mirroring
WikiPageService.get()/DocumentService.get()'s reasoning for calling the
scope module directly rather than through a payload_allowed() bool wrapper
(no dedicated post_policy.py file -- same carve-out as Wiki Pages, per the
runbook's explicit note for domains with no client-side list-filtering).
"""

from __future__ import annotations

from ...config import Settings
from ...models import PostDetail
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.post_api import PostApi


class PostService:
    def __init__(
        self,
        *,
        api: PostApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def get(self, post_id: int) -> PostDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(post_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return hidden_fields.apply_hidden_fields("post", record.detail, settings=self._settings)
