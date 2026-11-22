"""Application Service for starring saved queries.

`starred` belongs to the query itself, not to the caller: starring a public query changes it for everyone. The
query is therefore judged like any other write: a query of a project needs that project in
OPENPROJECT_WRITE_PROJECTS and a public query without a project (a global one) needs the write scope `*`. A
private query is personal and may be starred only by its owner; a query whose owner cannot be told is refused.

OpenProject offers the `star` link only to a caller who may star the query and the `unstar` link only to one who
may unstar it, so the link of the wanted state is the permission check; the preview reads it as well, and a
preview never promises a write the confirmed call would refuse. A query already in the wanted state changes
nothing and is not written.

Read and write scope reuse "work_package": a saved query is a work package view.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings
from ...models import QueryStarResult
from ..errors import PermissionDeniedError
from ..policies import access
from ..policies import scope as scope_policy
from ..ports.current_user import CurrentUserLookup
from ..ports.query_star_api import QueryStarApi
from ._error_masking import redacted_server_errors
from ._payload_masking import stamped_results


@stamped_results
@redacted_server_errors("view")
class QueryStarService:
    def __init__(
        self,
        *,
        api: QueryStarApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        current_user: CurrentUserLookup,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._current_user = current_user

    async def set_starred(self, query_id: int, *, starred: bool, confirm: bool = False) -> QueryStarResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        access.ensure_write_enabled("work_package", settings=self._settings)
        record = await self._api.get(query_id)
        if not record.public and record.owner_id != (await self._current_user()).id:
            raise PermissionDeniedError(f"Query {query_id} is private and belongs to another user.")
        if record.project_link is not None or record.public:
            scope_policy.ensure_project_write_link_allowed_if_present(
                record.project_link,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        word = "starred" if starred else "unstarred"
        if record.starred == starred:
            return QueryStarResult(
                action="set_starred",
                state="confirmed" if confirm else "preview",
                ready=True,
                message=f"The query is already {word}; nothing changes.",
                query_id=query_id,
                starred=starred,
            )
        if not (record.can_star if starred else record.can_unstar):
            raise PermissionDeniedError(
                f"OpenProject does not allow this user to {'star' if starred else 'unstar'} query {query_id}."
            )
        if not confirm:
            return QueryStarResult(
                action="set_starred",
                state="preview",
                ready=True,
                message=f"Ask for confirmation, then call again with confirm=true to mark the query {word}.",
                query_id=query_id,
                starred=starred,
            )
        await self._api.set_starred(query_id, starred=starred)
        return QueryStarResult(
            action="set_starred",
            state="confirmed",
            ready=True,
            message=f"Query marked {word}.",
            query_id=query_id,
            starred=starred,
        )
