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
  `work_package_id` is resolved with `write=True`, but that alone is NOT
  sufficient authorization for the delete -- OpenProject's own DELETE
  enforces `manage_wiki_page_links` against the LINK's actual project (via
  `model.linkable.project`), not against whatever `work_package_id` this
  MCP was told to check. A caller with write access to an allowed work
  package could otherwise pass an arbitrary `link_id` belonging to a
  disallowed project and have it deleted, bypassing `OPENPROJECT_WRITE_
  PROJECTS` entirely if the underlying API token happens to have broader
  server-side permissions than the MCP's own allowlist grants. `delete()`
  therefore scans the resolved work package's own links (reusing
  `list_for_work_package`'s scan) and fails closed with `NotFoundError` if
  `link_id` is not actually among them, on both the preview and confirmed
  paths -- this fixed a real authorization-bypass finding from this
  domain's step-6.5 review, not a defense-in-depth nicety.
"""

from __future__ import annotations

from ...config import Settings
from ...models import WikiPageLinkListResult, WikiPageLinkSummary, WikiPageLinkWriteResult
from ..errors import NotFoundError
from ..pagination import clamp_limit, paginate_all, scan_records_and_paginate
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

    async def _ensure_link_belongs_to_work_package(self, resolved_work_package_id: int, link_id: int) -> None:
        """Fail closed unless `link_id` is actually one of `resolved_work_package_id`'s
        own links -- resolving the work package id alone only proves the caller may
        delete links scoped to THAT work package, not that the caller-supplied
        `link_id` is one of them. Without this, a write-allowed anchor work package
        could be paired with an arbitrary link_id from a disallowed project."""
        records = await paginate_all(
            lambda o, ps: self._api.list_for_work_package(resolved_work_package_id, offset=o, page_size=ps),
            page_size=self._settings.max_page_size,
            key=lambda r: r.summary.id,
        )
        if not any(record.summary.id == link_id for record in records):
            raise NotFoundError(
                f"OpenProject wiki page link {link_id} was not found on work package {resolved_work_package_id}."
            )

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
        hidden_fields.ensure_field_writable("wiki_page_link", "identifier", settings=self._settings)
        hidden_fields.ensure_field_writable("wiki_page_link", "provider", settings=self._settings)
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
        await self._ensure_link_belongs_to_work_package(resolved_id, link_id)
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
