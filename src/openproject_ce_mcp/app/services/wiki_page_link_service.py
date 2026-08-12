"""Application Service for the Wiki Page Links domain.

Depends on the `WikiPageLinkApi` Protocol (never `HttpxWikiPageLinkApi`
concretely -- enforced by the architecture-boundary test) and on
`WorkPackageIdResolver`. Read/write scope reuses `"work_package"` (not a
dedicated `"wiki_page_link"` scope) -- the resource is entirely
work-package-scoped, matching Emoji Reactions'/Attachments' precedent.

Three distinct project-allowlist checks, one per method, mirroring
Attachments' exact pattern:

- `list_for_work_package()` uses `WorkPackageIdResolver(ref, write=False)` --
  resolving the id already confirms the anchor work package is allowed
  against `OPENPROJECT_READ_PROJECTS` before its links are fetched.
- `create()` uses `WorkPackageIdResolver(ref, write=True)` -- the link is
  created scoped to that work package, so its write-allowlist check IS the
  target work package's write-allowlist check. Also resolves the current
  user's id via the injected `CurrentUserLookup` seam and sends it as
  `author_id` -- verified live against source
  (`relation_page_link_representer.rb`): the server-side `author` link
  setter only runs when the request body's `_links.author` key is present at
  all, so omitting it leaves `author` unset rather than defaulted to the
  current user, which `RelationPageLinks::CreateContract` then rejects.
- `delete()` takes BOTH `work_package_id` and `link_id`: OpenProject's API
  has no single-resource GET for a wiki page link (only
  `DELETE wiki_page_links/{id}`), so the Service cannot discover a link's
  parent work package from the link id alone. The caller-supplied
  `work_package_id` is resolved with `write=True` before the delete is
  allowed to proceed -- this does NOT independently verify the given
  `link_id` actually belongs to that work package (OpenProject's own DELETE
  enforces that; a mismatched id simply 404s there), it only establishes
  that the caller is authorized to delete links scoped to that work package.
"""

from __future__ import annotations

from ...config import Settings
from ...models import WikiPageLinkListResult, WikiPageLinkSummary, WikiPageLinkWriteResult
from ..pagination import clamp_limit, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..ports.current_user import CurrentUserLookup
from ..ports.wiki_page_link_api import WikiPageLinkApi, WikiPageLinkRecord
from ..ports.work_package_ref import WorkPackageIdResolver


class WikiPageLinkService:
    def __init__(
        self,
        *,
        api: WikiPageLinkApi,
        settings: Settings,
        resolve_work_package_id: WorkPackageIdResolver,
        current_user: CurrentUserLookup,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_id = resolve_work_package_id
        self._current_user = current_user

    def _stamp(self, record: WikiPageLinkRecord) -> WikiPageLinkSummary:
        return hidden_fields.apply_hidden_fields("wiki_page_link", record.summary, settings=self._settings)

    async def list_for_work_package(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> WikiPageLinkListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)

        raw_items, truncated = await scan_records_and_paginate(
            lambda o, ps: self._api.list_for_work_package(resolved_id, offset=o, page_size=ps),
            item_allowed=lambda _record: True,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective_limit,
            key=lambda r: r.summary.id,
        )
        results = [self._stamp(record) for record in raw_items]
        total = len(results)
        return WikiPageLinkListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=offset + 1 if truncated else None,
            truncated=truncated,
            results=results,
        )

    async def create(
        self,
        work_package_id: int | str,
        *,
        identifier: str,
        provider: str,
        confirm: bool = False,
    ) -> WikiPageLinkWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        payload = {"identifier": identifier, "provider": provider}
        if not confirm:
            return WikiPageLinkWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this wiki page link. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                link_id=None,
                work_package_id=resolved_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        current_user = await self._current_user()
        record = await self._api.create(
            resolved_id, identifier=identifier, provider=provider, author_id=current_user.id
        )
        result = self._stamp(record)
        return WikiPageLinkWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Wiki page link created successfully.",
            link_id=result.id,
            work_package_id=resolved_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(
        self, work_package_id: int | str, link_id: int, *, confirm: bool = False
    ) -> WikiPageLinkWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        payload = {"id": link_id}
        if not confirm:
            return WikiPageLinkWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to delete it.",
                link_id=link_id,
                work_package_id=resolved_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(link_id)
        return WikiPageLinkWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Wiki page link deleted successfully.",
            link_id=link_id,
            work_package_id=resolved_id,
            payload=payload,
            validation_errors={},
            result=None,
        )
