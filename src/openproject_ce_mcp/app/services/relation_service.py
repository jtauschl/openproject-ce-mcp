"""Application Service for the Relations domain (ADR 0001).

Depends on the `RelationApi` Protocol (never `HttpxRelationApi` concretely --
enforced by the architecture-boundary test), on `WorkPackageLookupApi`
directly, on `WorkPackageIdResolver`, and on `WorkPackageProjectAllowedCheck`
-- matching Reminders' four-Protocol seam surface, for an analogous reason:

- `list_all()`/`list_for_work_package()` each fan out across TWO *different*
  work packages PER RELATION (`from` and `to`, not a single anchor) -- uses
  `WorkPackageProjectAllowedCheck` + a single `WorkPackageAllowedContext`
  (a request-scoped cache, avoiding a redundant fetch when relations share
  an endpoint work package), verbatim behavior of client.py's original
  `_relation_endpoints_allowed`. BOTH sides must pass, or a relation to a
  work package outside the read allowlist would leak that work package's
  id/subject through to_id/to_subject even though it isn't independently
  readable.
- `create()` takes a genuine caller-supplied target reference
  (`related_to_work_package_id`) -- uses `WorkPackageIdResolver(ref,
  write=True)`: OpenProject authorizes relation creation primarily via the
  `from` work package's project, but this server's own WRITE_PROJECTS
  contract must also hold for the `to` target (a caller with write on one
  project must not be able to link it to a work package in a project they
  can only read).
- `update()`/`delete()` both need the relation's OWN `from` work package
  first (an already-concrete href once the relation is fetched, not a
  caller-supplied reference) -- uses `WorkPackageLookupApi.get_by_href()` +
  a direct `scope_policy.ensure_project_write_link_allowed` call, the same
  shape as Reminders' update()/delete().

No shared `_write_outcome.py` state machine: create()/update()/delete() are
structurally too different from each other to share one state machine --
create() takes different params than update(), delete() has no request body
at all, and NONE of the three go through a `<domain>/form` endpoint (relation
creation POSTs a body directly; there is no schema-validation form step) --
`_finalize_write`'s own documented precondition ("2+ write actions sharing
the same preview/commit/reject shape via a <domain>/form endpoint") does not
hold here. delete() reimplements client.py's original inline preview/commit
branching directly (no shared cross-layer helper exists for this shape in
app/services/ yet -- client.py's own `_finalize_delete` stays a client.py-
private helper shared across still-flat domains).

`create()` validates the source work-package reference (traversal-segment
rejection) via the shared, pure `work_package_ref()` encoder BEFORE resolving
the target -- verbatim behavior of client.py's original
`create_work_package_relation`, which calls `_work_package_ref(work_package_id)`
synchronously first, so an invalid source reference is rejected before any
I/O happens against the target. The encoded return value itself is discarded
here (only the validation side effect matters) -- the raw reference is passed
through to `RelationApi.create()` unchanged, which re-encodes it itself when
building the outgoing POST path (see httpx_relation_api.py's module
docstring for why encoding must happen there, not be threaded through
pre-encoded).

RelationSummary.from_subject/to_subject additionally honor the work_package
entity's OWN subject hide list (not just relation's), since those two fields
are borrowed titles of a *different* entity -- `_stamp` nulls them out via
`dataclasses.replace` BEFORE applying `hidden_fields.apply_hidden_fields`,
never after: `apply_hidden_fields` stamps a dynamic `_hidden_keys` attribute
onto the instance, and `dataclasses.replace()` builds a brand-new instance
via the constructor, silently dropping that attribute again if it ran first.

Read/write scope reuses `"work_package"` (not a dedicated `"relation"`
scope) -- verbatim behavior of client.py's `_ensure_read_enabled`/
`_ensure_write_enabled("work_package")` calls; tools.py's scope tables are
unchanged by this migration. Unlike FileLinkService.delete() (this domain's
nearest template for a manually-built delete preview/commit flow),
create_work_package_relation/delete_relation's *original* client.py methods
never call `access.ensure_read_enabled(...)` themselves -- only
`get_work_package_relations` and (implicitly, via the write gate behind the
confirm branch) `update_relation` do. Introducing a read-enablement gate at
the top of create()/update()/delete() here would be a behavior change, not a
structural port -- deliberately not done.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from ...config import Settings
from ...models import RelationListResult, RelationSummary, RelationUpdateResult, RelationWriteResult
from ..api_href import api_href as _api_href
from ..errors import OpenProjectServerError
from ..pagination import effective_limit, fetch_bounded_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.relation_api import RelationApi, RelationRecord
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
from ..ports.work_package_ref import work_package_ref as _validate_work_package_ref
from ..ports.work_package_resolution import WorkPackageAllowedContext


class RelationService:
    def __init__(
        self,
        *,
        api: RelationApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._work_package_project_allowed = work_package_project_allowed
        self._api_prefix = api_prefix

    def _stamp(self, summary: RelationSummary) -> RelationSummary:
        if hidden_fields.field_hidden("work_package", "subject", settings=self._settings):
            summary = dataclasses.replace(summary, from_subject=None, to_subject=None)
        return hidden_fields.apply_hidden_fields("relation", summary, settings=self._settings)

    async def _relation_endpoints_allowed(self, record: RelationRecord, cache: WorkPackageAllowedContext) -> bool:
        for link in (record.from_link, record.to_link):
            if not isinstance(link, dict) or not link.get("href"):
                return False
            if not await self._work_package_project_allowed(link["href"], context=cache):
                return False
        return True

    async def _list(self, *, filters: str | None, offset: int, limit: int) -> RelationListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        allowlisted = not scope_policy.scope_allows_all(self._settings.read_projects)
        cache = WorkPackageAllowedContext()

        async def item_allowed(raw: dict[str, Any]) -> bool:
            if not allowlisted:
                return True
            record = self._api.to_record(raw)
            return await self._relation_endpoints_allowed(record, cache)

        page, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=lambda o, ps: self._api.fetch_page(offset=o, page_size=ps, filters=filters),
            normalize=lambda raw: self._stamp(self._api.to_record(raw).summary()),
            item_allowed=item_allowed,
            post_filter=None,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=limit,
        )
        return RelationListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def list_all(
        self, *, relation_type: str | None = None, offset: int = 1, limit: int | None = None
    ) -> RelationListResult:
        resolved_limit = effective_limit(limit, settings=self._settings)
        filters = None
        if relation_type is not None:
            filters = json.dumps([{"type": {"operator": "=", "values": [relation_type]}}])
        return await self._list(filters=filters, offset=offset, limit=resolved_limit)

    async def list_for_work_package(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> RelationListResult:
        # Gate before resolving the anchor -- resolving it already issues a
        # work-package GET, and the original get_work_package_relations checks
        # this before that fetch, not after (Codex-found migration drift).
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_limit = effective_limit(limit, settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id)
        filters = json.dumps([{"involved": {"operator": "=", "values": [str(resolved_id)]}}])
        return await self._list(filters=filters, offset=offset, limit=resolved_limit)

    async def _fetch_source_work_package(self, from_link: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(from_link, dict) or not from_link.get("href"):
            raise OpenProjectServerError("OpenProject relation is missing its source work package link.")
        return await self._work_package_lookup_api.get_by_href(from_link["href"])

    async def create(
        self,
        *,
        work_package_id: int | str,
        related_to_work_package_id: int | str,
        relation_type: str,
        description: str | None = None,
        lag: int | None = None,
        confirm: bool = False,
    ) -> RelationWriteResult:
        # Validate the source reference (traversal-segment rejection) before
        # any I/O, including the target resolution below -- exact original
        # ordering. The encoded return value is unused; RelationApi.create()
        # re-encodes the raw reference itself.
        _validate_work_package_ref(work_package_id)
        related_numeric_id = await self._resolve_work_package_id(related_to_work_package_id, write=True)
        work_package = await self._work_package_lookup_api.get(str(work_package_id))
        scope_policy.ensure_project_write_link_allowed(
            work_package.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        source_numeric_id = int(work_package["id"])
        hidden_fields.ensure_field_writable("relation", "type", settings=self._settings)
        payload: dict[str, Any] = {
            "type": relation_type,
            "_links": {"to": {"href": _api_href(f"work_packages/{related_numeric_id}", api_prefix=self._api_prefix)}},
        }
        if description is not None:
            hidden_fields.ensure_field_writable("relation", "description", settings=self._settings)
            payload["description"] = description
        if lag is not None:
            payload["lag"] = lag

        preview_payload = payload | {"to_work_package_id": related_numeric_id}
        if not confirm:
            return RelationWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create this relation. Ask for confirmation, then call again with confirm=true.",
                relation_id=None,
                work_package_id=source_numeric_id,
                payload=preview_payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        record = await self._api.create(str(work_package_id), payload)
        result = self._stamp(record.summary())
        return RelationWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation created successfully.",
            relation_id=result.id,
            work_package_id=source_numeric_id,
            payload=preview_payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        *,
        relation_id: int,
        relation_type: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> RelationUpdateResult:
        current = await self._api.get(relation_id)
        work_package = await self._fetch_source_work_package(current.from_link)
        scope_policy.ensure_project_write_link_allowed(
            work_package.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        existing = self._stamp(current.summary())
        body: dict[str, Any] = {}
        if relation_type is not None:
            hidden_fields.ensure_field_writable("relation", "type", settings=self._settings)
            body["type"] = relation_type
        if description is not None:
            hidden_fields.ensure_field_writable("relation", "description", settings=self._settings)
            body["description"] = description
        if not confirm:
            return RelationUpdateResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=f"Ready to update relation {relation_id}. Call again with confirm=true.",
                relation_id=relation_id,
                payload=body,
                result=existing,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        record = await self._api.update(relation_id, body)
        detail = self._stamp(record.summary())
        return RelationUpdateResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation updated successfully.",
            relation_id=relation_id,
            payload=body,
            result=detail,
        )

    async def delete(self, *, relation_id: int, confirm: bool = False) -> RelationWriteResult:
        current = await self._api.get(relation_id)
        work_package = await self._fetch_source_work_package(current.from_link)
        scope_policy.ensure_project_write_link_allowed(
            work_package.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        normalized = self._stamp(current.summary())
        payload = {
            "id": normalized.id,
            "type": normalized.type,
            "from_id": normalized.from_id,
            "to_id": normalized.to_id,
        }
        if not confirm:
            return RelationWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete this relation. Ask for confirmation, then call again with confirm=true.",
                relation_id=normalized.id,
                work_package_id=normalized.from_id,
                payload=payload,
                validation_errors={},
                result=normalized,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(relation_id)
        return RelationWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation deleted successfully.",
            relation_id=normalized.id,
            work_package_id=normalized.from_id,
            payload=payload,
            validation_errors={},
            result=None,
        )
