"""Application Service for the Relations domain.

Depends on the `RelationApi` Protocol (never `HttpxRelationApi` concretely --
enforced by the architecture-boundary test), on `WorkPackageLookupApi`
directly, on `WorkPackageIdResolver`, and on `WorkPackageProjectAllowedCheck`
-- matching Reminders' four-Protocol seam surface, for an analogous reason:

- `list_all()`/`list_for_work_package()` each fan out across TWO *different*
  work packages PER RELATION (`from` and `to`, not a single anchor) -- uses
  `WorkPackageProjectAllowedCheck` + a single `WorkPackageAllowedContext`
  (a request-scoped cache, avoiding a redundant fetch when relations share
  an endpoint work package). BOTH sides must pass, or a relation to a work
  package outside the read allowlist would leak that work package's
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
hold here. delete() implements its own inline preview/commit branching
directly (no shared cross-layer helper exists for this shape in
app/services/ yet).

`create()` validates the source work-package reference (traversal-segment
rejection) via the shared, pure `work_package_ref()` encoder BEFORE resolving
the target, so an invalid source reference is rejected before any I/O
happens against the target. The encoded return value itself is discarded
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
scope). Unlike FileLinkService.delete() (this domain's nearest template for
a manually-built delete preview/commit flow), create()/delete() here
deliberately do NOT call `access.ensure_read_enabled(...)` themselves --
only `list_all`/`list_for_work_package` and (implicitly, via the write gate
behind the confirm branch) `update()` do. Adding a read-enablement gate to
create()/update()/delete() would be a behavior change -- deliberately not
done.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from ...config import Settings
from ...models import (
    QueriedRelationPerspective,
    RelationListResult,
    RelationSummary,
    RelationUpdateResult,
    RelationWriteResult,
)
from ..api_href import api_href as _api_href
from ..errors import OpenProjectServerError
from ..pagination import effective_limit, fetch_bounded_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.relation_api import RelationApi, RelationRecord
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import (
    WorkPackageIdResolver,
    WorkPackageProjectAllowedBulkCheck,
    WorkPackageProjectAllowedCheck,
)
from ..ports.work_package_ref import work_package_ref as _validate_work_package_ref
from ..ports.work_package_resolution import WorkPackageAllowedContext

# Mirrors OpenProject's own Relation::TYPES hash (app/models/relation.rb):
# for a relation stored with this type, "from"-side is read as the type
# itself; "to"-side is read as the paired reverse label. Non-directional
# "relates" maps to itself on both sides. Only the canonical types that
# actually get persisted appear as keys (OpenProject's before_validation
# reverse_if_needed rewrites e.g. "precedes" to "follows" at creation time,
# swapping from_id/to_id, so a stored relation's type is always one of
# these six) -- an unrecognized type (a future OpenProject addition this
# client doesn't know about yet) falls back to leaving effective_type as
# the raw type unchanged on both sides, rather than guessing.
_RELATION_TYPE_FROM_TO_LABELS: dict[str, tuple[str, str]] = {
    "relates": ("relates", "relates"),
    "follows": ("follows", "precedes"),
    "blocks": ("blocks", "blocked"),
    "duplicates": ("duplicates", "duplicated"),
    "includes": ("includes", "partof"),
    "requires": ("requires", "required"),
}


def _queried_relation_perspective(
    *, queried_work_package_id: int, relation_type: str | None, from_id: int | None, to_id: int | None
) -> QueriedRelationPerspective | None:
    if from_id is None or to_id is None:
        return None
    if queried_work_package_id == from_id:
        direction = "from"
    elif queried_work_package_id == to_id:
        direction = "to"
    else:
        # The queried work package is neither end -- can't happen for a
        # relation returned by list_for_work_package's own `involved` filter,
        # but list_all() can pass an id that isn't actually involved in a
        # given RelationSummary if a caller builds one directly; stay safe.
        return None
    labels = _RELATION_TYPE_FROM_TO_LABELS.get(relation_type or "")
    effective_type = (labels[0] if direction == "from" else labels[1]) if labels else relation_type
    predecessor_id: int | None = None
    successor_id: int | None = None
    if relation_type == "follows":
        predecessor_id = to_id
        successor_id = from_id
    return QueriedRelationPerspective(
        queried_work_package_id=queried_work_package_id,
        direction=direction,
        effective_type=effective_type,
        predecessor_id=predecessor_id,
        successor_id=successor_id,
    )


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
        work_package_project_allowed_bulk: WorkPackageProjectAllowedBulkCheck,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._work_package_project_allowed = work_package_project_allowed
        self._work_package_project_allowed_bulk = work_package_project_allowed_bulk
        self._api_prefix = api_prefix

    def _stamp(self, summary: RelationSummary, *, queried_work_package_id: int | None = None) -> RelationSummary:
        if hidden_fields.field_hidden("work_package", "subject", settings=self._settings):
            summary = dataclasses.replace(summary, from_subject=None, to_subject=None)
        # queried_perspective embeds from_id/to_id (as predecessor_id/
        # successor_id and via direction) -- apply_hidden_fields below only
        # drops a top-level field key, it cannot see into this nested
        # dataclass, so a caller hiding "from_id"/"to_id" would otherwise
        # still leak the identical id back out through the nested field.
        # Skip computing queried_perspective at all when either raw id is
        # hidden, mirroring the from_subject/to_subject zeroing above.
        ids_hidden = hidden_fields.field_hidden(
            "relation", "from_id", settings=self._settings
        ) or hidden_fields.field_hidden("relation", "to_id", settings=self._settings)
        if queried_work_package_id is not None and not ids_hidden:
            perspective = _queried_relation_perspective(
                queried_work_package_id=queried_work_package_id,
                relation_type=summary.type,
                from_id=summary.from_id,
                to_id=summary.to_id,
            )
            summary = dataclasses.replace(summary, queried_perspective=perspective)
        return hidden_fields.apply_hidden_fields("relation", summary, settings=self._settings)

    def _relation_endpoints_allowed_sync(self, record: RelationRecord, outcomes: dict[str, bool | Exception]) -> bool:
        """Synchronous, sequential-order evaluation of a single relation's
        from/to outcomes, both already resolved (speculatively, possibly
        concurrently) by `_bulk_item_allowed` below. `from` is checked
        first, and `to` is never even considered (its outcome -- success OR
        exception -- is silently discarded) once `from` is missing/denied, so
        a sequential one-at-a-time evaluation would never reach `to` in that
        case either."""
        for link in (record.from_link, record.to_link):
            if not isinstance(link, dict) or not link.get("href"):
                return False
            outcome = outcomes[link["href"]]
            if isinstance(outcome, Exception):
                raise outcome
            if not outcome:
                return False
        return True

    async def _bulk_item_allowed(
        self, raw_elements: list[dict[str, Any]], *, cache: WorkPackageAllowedContext
    ) -> list[bool | Exception]:
        """Page-batching hook for `fetch_bounded_and_paginate`: collect every
        from/to href across the whole page, resolve them all concurrently in
        one bulk call, then evaluate each relation synchronously in
        sequential order/short-circuit semantics. `cache` is the SAME
        `WorkPackageAllowedContext` across every page of one `_list` call
        (passed in by the caller, not stored on `self`, so two concurrent
        `_list` calls on the same Service instance never share state) --
        repeated hrefs within a page, or across pages of the same top-level
        call, only trigger one resolution each.
        """
        records = [self._api.to_record(raw) for raw in raw_elements]
        hrefs = [
            link["href"]
            for record in records
            for link in (record.from_link, record.to_link)
            if isinstance(link, dict) and link.get("href")
        ]
        outcomes = await self._work_package_project_allowed_bulk(hrefs, context=cache)
        results: list[bool | Exception] = []
        for record in records:
            try:
                results.append(self._relation_endpoints_allowed_sync(record, outcomes))
            except Exception as exc:  # noqa: BLE001 -- deferred to the caller's sequential consumption, see docstring
                results.append(exc)
        return results

    async def _list(
        self, *, filters: str | None, offset: int, limit: int, queried_work_package_id: int | None = None
    ) -> RelationListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        allowlisted = not scope_policy.scope_allows_all(self._settings.read_projects)
        cache = WorkPackageAllowedContext()

        item_allowed_bulk = (lambda raw: self._bulk_item_allowed(raw, cache=cache)) if allowlisted else None

        page, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=lambda o, ps: self._api.fetch_page(offset=o, page_size=ps, filters=filters),
            normalize=lambda raw: self._stamp(
                self._api.to_record(raw).summary(), queried_work_package_id=queried_work_package_id
            ),
            item_allowed=None,
            item_allowed_bulk=item_allowed_bulk,
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
        # this before that fetch, not after.
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_limit = effective_limit(limit, settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id)
        filters = json.dumps([{"involved": {"operator": "=", "values": [str(resolved_id)]}}])
        return await self._list(
            filters=filters, offset=offset, limit=resolved_limit, queried_work_package_id=resolved_id
        )

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
        # any I/O, including the target resolution below. The encoded
        # return value is unused; RelationApi.create() re-encodes the raw
        # reference itself.
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
                state="preview",
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
            state="confirmed",
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
                state="preview",
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
            state="confirmed",
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
                state="preview",
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
            state="confirmed",
            ready=True,
            message="Relation deleted successfully.",
            relation_id=normalized.id,
            work_package_id=normalized.from_id,
            payload=payload,
            validation_errors={},
            result=None,
        )
