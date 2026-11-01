"""Application Service for the Wiki Page Links domain.

Depends on the `WikiPageLinkApi` Protocol (never `HttpxWikiPageLinkApi`
concretely -- enforced by the architecture-boundary test) and on
`WorkPackageRecordResolver`. Read/write scope reuses `"work_package"` (not a
dedicated `"wiki_page_link"` scope) -- the resource is entirely
work-package-scoped, matching Emoji Reactions'/Attachments' precedent.

Three distinct project-allowlist checks, one per method, mirroring
Attachments' exact pattern:

- `list_for_work_package()` uses `WorkPackageRecordResolver(ref, write=False)` --
  resolving the id already confirms the anchor work package is allowed
  against `OPENPROJECT_READ_PROJECTS` before its links are fetched.
- `create()` uses `WorkPackageRecordResolver(ref, write=True)` -- the link is
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
  paths -- this closes a real authorization bypass, not a
  defense-in-depth nicety. The same scan
  shows the link's type: `DELETE wiki_page_links/{id}` finds relation links
  only (`Wikis::RelationPageLink.find`), so `delete()` rejects an inline link
  as invalid input before the DELETE instead of letting its 404 read as a
  missing route.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ResolvedWorkPackage, WikiPageLinkListResult, WikiPageLinkSummary, WikiPageLinkWriteResult
from ..errors import InvalidInputError, NotFoundError
from ..pagination import clamp_limit, paginate_all, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..ports.current_user import CurrentUserLookup
from ..ports.wiki_page_link_api import WikiPageLinkApi, WikiPageLinkRecord
from ..ports.work_package_ref import WorkPackageRecordResolver
from ..version_gate import call_version_gated
from ._work_package_presentation import present_target
from ._write_outcome import _finalize_write, _WriteOutcome


class WikiPageLinkService:
    def __init__(
        self,
        *,
        api: WikiPageLinkApi,
        settings: Settings,
        resolve_work_package_record: WorkPackageRecordResolver,
        current_user: CurrentUserLookup,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_record = resolve_work_package_record
        self._current_user = current_user

    def _stamp(self, record: WikiPageLinkRecord) -> WikiPageLinkSummary:
        return hidden_fields.apply_hidden_fields("wiki_page_link", record.summary, settings=self._settings)

    async def _find_link_of_work_package(self, resolved_work_package_id: int, link_id: int) -> WikiPageLinkRecord:
        """Fail closed unless `link_id` is actually one of `resolved_work_package_id`'s
        own links -- resolving the work package id alone only proves the caller may
        delete links scoped to THAT work package, not that the caller-supplied
        `link_id` is one of them. Without this, a write-allowed anchor work package
        could be paired with an arbitrary link_id from a disallowed project."""
        # Gated with the delete's floor: below 17.5 this list 404s, and the
        # version the caller needs is the one DELETE requires (17.6).
        records = await paginate_all(
            lambda o, ps: call_version_gated(
                lambda: self._api.list_for_work_package(resolved_work_package_id, offset=o, page_size=ps),
                feature="Deleting wiki page links",
                floor="17.6",
            ),
            page_size=self._settings.max_page_size,
            key=lambda r: r.summary.id,
        )
        record = next((record for record in records if record.summary.id == link_id), None)
        if record is None:
            raise NotFoundError(
                f"OpenProject wiki page link {link_id} was not found on work package {resolved_work_package_id}."
            )
        return record

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
        resolved_id = (await self._resolve_work_package_record(work_package_id, write=False)).id

        raw_items, truncated = await scan_records_and_paginate(
            lambda o, ps: call_version_gated(
                lambda: self._api.list_for_work_package(resolved_id, offset=o, page_size=ps),
                feature="Listing wiki page links",
                floor="17.5",
            ),
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
        resolved = await self._resolve_work_package_record(work_package_id, write=True)
        resolved_id = resolved.id
        target = present_target(resolved.payload, settings=self._settings)
        hidden_fields.ensure_field_writable("wiki_page_link", "identifier", settings=self._settings)
        hidden_fields.ensure_field_writable("wiki_page_link", "provider", settings=self._settings)
        payload = {"identifier": identifier, "provider": provider}

        async def _commit(p: dict[str, Any]) -> WikiPageLinkSummary:
            current_user = await self._current_user()
            record = await call_version_gated(
                lambda: self._api.create(
                    resolved_id, identifier=identifier, provider=provider, author_id=current_user.id
                ),
                feature="Creating wiki page links",
                floor="17.7",
            )
            return self._stamp(record)

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"link_id": None, "work_package_id": resolved_id},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"link_id": d.id, "work_package_id": resolved_id},
            rejected_message="",
            preview_message=(
                "OpenProject is ready to create this wiki page link. Ask for confirmation, "
                "then call again with confirm=true."
            ),
            success_message="Wiki page link created successfully.",
        )
        return self._to_write_result("create", outcome, target=target)

    async def delete(
        self, work_package_id: int | str, link_id: int, *, confirm: bool = False
    ) -> WikiPageLinkWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved = await self._resolve_work_package_record(work_package_id, write=True)
        resolved_id = resolved.id
        target = present_target(resolved.payload, settings=self._settings)
        record = await self._find_link_of_work_package(resolved_id, link_id)
        # DELETE wiki_page_links/{id} looks the id up as a relation link only,
        # so it answers 404 for an inline link on every version.
        if record.summary.link_type == "inline":
            raise InvalidInputError(
                f"Wiki page link {link_id} on work package {resolved_id} is an inline link: OpenProject "
                "derives it from a wiki link in the work package's description or from a wiki page that "
                "mentions the work package, and offers no API to delete it. Remove the link from that "
                "text instead."
            )
        payload = {"id": link_id}

        async def _commit(p: dict[str, Any]) -> None:
            await call_version_gated(
                lambda: self._api.delete(link_id), feature="Deleting wiki page links", floor="17.6"
            )

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"link_id": link_id, "work_package_id": resolved_id},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"link_id": link_id, "work_package_id": resolved_id},
            rejected_message="",
            preview_message="Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Wiki page link deleted successfully.",
        )
        return self._to_write_result("delete", outcome, target=target)

    def _to_write_result(
        self,
        action: str,
        outcome: _WriteOutcome[WikiPageLinkSummary | None],
        *,
        target: ResolvedWorkPackage,
    ) -> WikiPageLinkWriteResult:
        return WikiPageLinkWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=outcome.detail,
            target=target,
            **outcome.identity,
        )
