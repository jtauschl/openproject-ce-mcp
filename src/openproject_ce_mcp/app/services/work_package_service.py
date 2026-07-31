"""Application Service for the Work Packages domain -- READ-only slice (ADR 0001).

Covers list/search/list_my_open/get/get_batch only. Write methods
(create/update/delete/bulk_*/add_comment/create_subtask) are a later, separate
migration step and are NOT implemented here; client.py's flat write paths are
untouched by this Service.

Depends on `WorkPackageApi` (never the concrete `HttpxWorkPackageApi` --
enforced by `tests/test_architecture_boundaries.py`), `ProjectRefResolver`,
`TypeRefResolver`, `VersionIdResolver`, `StatusRefResolver`,
`PriorityRefResolver`, `PrincipalRefResolver`, `CurrentUserLookup`, and
`WorkPackageProjectAllowedCheck` (the existing OPM-318 seam bound to
`self._work_package_resolver.project_link_allowed` -- `WorkPackageResolver`
itself is untouched by this migration; this Service becomes its ninth
consumer, alongside the eight already-migrated domains that depend on the
same resolver via `app/ports/work_package_ref.py`'s seams).

`search()`/`list()` stay two separate methods (not one parametrized method):
they have non-overlapping required/exclusive parameters in client.py today
(`search` is required for `search_work_packages` and has no `type`/`version`/
`version_status`; `list_work_packages` has no `search`), and `tools.py`
registers them as two separate MCP tools already -- 1:1 parity with the
Service layer is the simpler, less surprising mapping. Both call the shared
private `_list_collection` helper (the 1:1 replacement for client.py's
`_list_work_package_collection` + `_build_work_package_list_result` +
`_work_package_collection_page`), so the actual overlap logic (pagination,
total-trust derivation, allowlist filtering) exists exactly once.

`_list_collection` normalizes only allowlist-survivING raw elements (per
`app/ports/work_package_api.py`'s module docstring) -- filtering happens
BEFORE normalization, the opposite order from Projects/Versions, because this
domain filters a heterogeneous per-item project link rather than a
single already-known scope.

Every public method calls `access.ensure_read_enabled("work_package", ...)`
as its FIRST action, before any `resolve_*` seam call -- verbatim behavioral
port of client.py's `search_work_packages`/`list_work_packages`/
`list_my_open_work_packages`/`get_work_package`, each of which gates before
doing any resolution or HTTP work.

`_stamp`/`_stamp_detail` zero `description_truncated`/`description_length`
(plus, for `WorkPackageSummary` only, `has_description`) when the
`description` field itself is hidden -- mirrors `_stamp_project`
(`app/services/project_service.py`) and `TimeEntryService._stamp`'s
`comment`-metadata handling. Without this, `apply_hidden_fields` alone would
drop the `description` text but leave its truncation/length/has_description
siblings computed from the TRUE, unmasked text, leaking its existence/length
even though the adapter's own extraction (unlike client.py's original
`_visible_formattable_text_with_meta`) is not hidden-field-aware by design
(masking is a Service concern in the migrated architecture).
"""

from __future__ import annotations

import asyncio
import builtins
import dataclasses
import datetime
from typing import Any

from ...config import Settings
from ...models import (
    BatchWorkPackageReadItemResult,
    BatchWorkPackageReadResult,
    SortCriterion,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
)
from ..errors import InvalidInputError, OpenProjectError, PermissionDeniedError
from ..pagination import effective_limit, paginate_server
from ..policies import access, hidden_fields
from ..policies import work_package_policy as _work_package_policy
from ..policies.scope import ensure_project_link_allowed, scope_allows_all
from ..ports.current_user import CurrentUserLookup
from ..ports.principal_ref import PrincipalRefResolver
from ..ports.priority_ref import PriorityRefResolver
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.status_ref import StatusRefResolver
from ..ports.type_ref import TypeRefResolver
from ..ports.version_ref import VersionIdResolver
from ..ports.work_package_api import WorkPackageApi
from ..ports.work_package_ref import WorkPackageProjectAllowedCheck
from ..ports.work_package_resolution import WorkPackageAllowedContext

BATCH_READ_MAX_IDS = 100


def _empty_list_result(*, offset: int, limit: int) -> WorkPackageListResult:
    return WorkPackageListResult(
        offset=offset, limit=limit, total=0, count=0, next_offset=None, truncated=False, results=[]
    )


class WorkPackageService:
    def __init__(
        self,
        *,
        api: WorkPackageApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
        resolve_type_id: TypeRefResolver,
        resolve_version_id: VersionIdResolver,
        resolve_status_id: StatusRefResolver,
        resolve_priority_id: PriorityRefResolver,
        resolve_principal_id: PrincipalRefResolver,
        current_user: CurrentUserLookup,
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._resolve_type_id = resolve_type_id
        self._resolve_version_id = resolve_version_id
        self._resolve_status_id = resolve_status_id
        self._resolve_priority_id = resolve_priority_id
        self._resolve_principal_id = resolve_principal_id
        self._current_user = current_user
        self._work_package_project_allowed = work_package_project_allowed

    def _stamp(self, summary: WorkPackageSummary) -> WorkPackageSummary:
        if hidden_fields.field_hidden("work_package", "description", settings=self._settings):
            summary = dataclasses.replace(
                summary, description_truncated=False, description_length=None, has_description=False
            )
        return hidden_fields.apply_hidden_fields("work_package", summary, settings=self._settings)

    def _stamp_detail(self, detail: WorkPackageDetail) -> WorkPackageDetail:
        if hidden_fields.field_hidden("work_package", "description", settings=self._settings):
            detail = dataclasses.replace(detail, description_truncated=False, description_length=None)
        return hidden_fields.apply_hidden_fields("work_package", detail, settings=self._settings)

    def _payload_allowed(self, payload: dict[str, Any]) -> bool:
        return _work_package_policy.work_package_payload_allowed(
            payload, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )

    async def _list_collection(
        self,
        *,
        project_id: int | None,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
        sort_by: list[SortCriterion] | None,
        group_by: str | None,
        total_is_scope_safe: bool,
    ) -> WorkPackageListResult:
        del project_id  # unused: filters already carry any project_id constraint; kept
        # for signature symmetry with client.py's original, which also never
        # read it inside _list_work_package_collection.
        if not self._settings.read_projects:
            # Defense-in-depth: both public callers already guard on this
            # before reaching here, but this must stay correct on its own for
            # any future caller (verbatim behavioral port of client.py's
            # _list_work_package_collection).
            return _empty_list_result(offset=offset, limit=limit)
        page = await self._api.list(filters=filters, offset=offset, limit=limit, sort_by=sort_by, group_by=group_by)
        raw_items = [item for item in page.raw_elements if self._payload_allowed(item)]
        results = [
            self._stamp(self._api.to_record(item, text_limit=self._settings.text_limit).summary) for item in raw_items
        ]
        server_total = page.server_total if page.server_total is not None else len(results)
        total_trustworthy = total_is_scope_safe and len(raw_items) == len(page.raw_elements)
        if total_trustworthy:
            next_offset, truncated = paginate_server(offset=offset, limit=limit, total=server_total)
            total = server_total
        else:
            # Pagination hints must not be derived from the untrustworthy
            # server total either -- that would leak the existence of
            # disallowed-project matches just as much as exposing the total
            # itself. "Is there more to page through" is instead based purely
            # on whether this raw server page came back full.
            total = len(results)
            next_offset = (offset + 1) if len(page.raw_elements) == limit else None
            truncated = len(page.raw_elements) == limit
        return WorkPackageListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    def _apply_date_filters(
        self,
        filters: list[dict[str, Any]],
        *,
        created_on: str | None,
        created_between: list[str] | None,
        updated_on: str | None,
        updated_between: list[str] | None,
        due_on: str | None,
        due_between: list[str] | None,
    ) -> None:
        def _validate_date(date_str: str, field_name: str) -> str:
            normalized = date_str.strip()
            try:
                datetime.date.fromisoformat(normalized)
                return normalized
            except ValueError as exc:
                raise InvalidInputError(f"{field_name} must be in YYYY-MM-DD format: {exc}") from exc

        def _validate_range(dates: list[str], field_name: str) -> list[str]:
            if len(dates) != 2:
                raise InvalidInputError(f"{field_name} must contain exactly 2 dates [start, end]")
            start, end = _validate_date(dates[0], field_name), _validate_date(dates[1], field_name)
            if start > end:
                raise InvalidInputError(f"{field_name} start date must be <= end date")
            return [start, end]

        if created_on and created_between:
            raise InvalidInputError("Cannot specify both created_on and created_between")
        if updated_on and updated_between:
            raise InvalidInputError("Cannot specify both updated_on and updated_between")
        if due_on and due_between:
            raise InvalidInputError("Cannot specify both due_on and due_between")

        if created_on:
            filters.append({"created_at": {"operator": "=d", "values": [_validate_date(created_on, "created_on")]}})
        if created_between:
            filters.append(
                {"created_at": {"operator": "<>d", "values": _validate_range(created_between, "created_between")}}
            )
        if updated_on:
            filters.append({"updated_at": {"operator": "=d", "values": [_validate_date(updated_on, "updated_on")]}})
        if updated_between:
            filters.append(
                {"updated_at": {"operator": "<>d", "values": _validate_range(updated_between, "updated_between")}}
            )
        if due_on:
            filters.append({"due_date": {"operator": "=d", "values": [_validate_date(due_on, "due_on")]}})
        if due_between:
            filters.append({"due_date": {"operator": "<>d", "values": _validate_range(due_between, "due_between")}})

    async def search(
        self,
        *,
        search: str,
        project: str | None = None,
        status: str | None = None,
        open_only: bool = False,
        assignee_me: bool = False,
        assignee: str | None = None,
        priority: str | None = None,
        created_on: str | None = None,
        created_between: list[str] | None = None,
        updated_on: str | None = None,
        updated_between: list[str] | None = None,
        due_on: str | None = None,
        due_between: list[str] | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective = effective_limit(limit, settings=self._settings)
        if not self._settings.read_projects:
            return _empty_list_result(offset=offset, limit=effective)
        filters: list[dict[str, Any]] = [{"subject_or_id": {"operator": "**", "values": [search]}}]
        project_id: int | None = None
        total_is_scope_safe = scope_allows_all(self._settings.read_projects)
        if project is not None:
            project_payload = await self._resolve_project_ref(project)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
            total_is_scope_safe = True
        if status:
            status_id = await self._resolve_status_id(status)
            filters.append({"status_id": {"operator": "=", "values": [status_id]}})
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self._current_user()
            filters.append({"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}})
        if assignee and not assignee_me:
            assignee_id = await self._resolve_principal_id(assignee)
            filters.append({"assigned_to_id": {"operator": "=", "values": [assignee_id]}})
        if priority:
            priority_id = await self._resolve_priority_id(priority)
            filters.append({"priority_id": {"operator": "=", "values": [priority_id]}})
        self._apply_date_filters(
            filters,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
        )
        return await self._list_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective,
            sort_by=sort_by,
            group_by=group_by,
            total_is_scope_safe=total_is_scope_safe,
        )

    async def list(
        self,
        *,
        project: str | None = None,
        type: str | None = None,
        version: str | None = None,
        version_status: str | None = None,
        open_only: bool = False,
        assignee_me: bool = False,
        assignee: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        created_on: str | None = None,
        created_between: list[str] | None = None,
        updated_on: str | None = None,
        updated_between: list[str] | None = None,
        due_on: str | None = None,
        due_between: list[str] | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective = effective_limit(limit, settings=self._settings)
        if not self._settings.read_projects:
            return _empty_list_result(offset=offset, limit=effective)
        filters: list[dict[str, Any]] = []
        project_id: int | None = None
        # Bounded to this single call: avoids re-fetching/re-checking the same
        # project when both type and version filters are given alongside
        # project (verbatim behavioral port of client.py's original
        # list_work_packages, which built this same per-call context).
        resolution_context = ProjectResolutionContext(self._resolve_project_ref)
        total_is_scope_safe = scope_allows_all(self._settings.read_projects)
        if project is not None:
            project_payload = await self._resolve_project_ref(project, context=resolution_context)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
            total_is_scope_safe = True
        elif not total_is_scope_safe:
            allowed_ids = [str(pid) for pid in self._project_id_to_identifier]
            if not allowed_ids:
                raise PermissionDeniedError(
                    "OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS."
                )
            filters.append({"project_id": {"operator": "=", "values": allowed_ids}})
            total_is_scope_safe = True
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self._current_user()
            filters.append({"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}})
        if type:
            type_id = await self._resolve_type_id(type, project=project, context=resolution_context)
            filters.append({"type_id": {"operator": "=", "values": [type_id]}})
        if version:
            version_id = await self._resolve_version_id(version, project=project, context=resolution_context)
            filters.append({"version_id": {"operator": "=", "values": [version_id]}})
        if version_status:
            status_operator = {"open": "o", "closed": "c", "locked": "l"}[version_status]
            filters.append({"version_id": {"operator": status_operator, "values": []}})
        if assignee and not assignee_me:
            assignee_id = await self._resolve_principal_id(assignee)
            filters.append({"assigned_to_id": {"operator": "=", "values": [assignee_id]}})
        if status:
            status_id = await self._resolve_status_id(status)
            filters.append({"status_id": {"operator": "=", "values": [status_id]}})
        if priority:
            priority_id = await self._resolve_priority_id(priority)
            filters.append({"priority_id": {"operator": "=", "values": [priority_id]}})
        self._apply_date_filters(
            filters,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
        )
        return await self._list_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective,
            sort_by=sort_by,
            group_by=group_by,
            total_is_scope_safe=total_is_scope_safe,
        )

    async def list_my_open(self, *, offset: int = 1, limit: int | None = None) -> WorkPackageListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective = effective_limit(limit, settings=self._settings)
        if not self._settings.read_projects:
            return _empty_list_result(offset=offset, limit=effective)
        current_user = await self._current_user()
        filters = [
            {"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}},
            {"status_id": {"operator": "o", "values": []}},
        ]
        # This query has no server-side project filter at all, so the server
        # total counts matches across every project regardless of the
        # allowlist -- only trust it when the scope is unrestricted.
        total_is_scope_safe = scope_allows_all(self._settings.read_projects)
        return await self._list_collection(
            project_id=None,
            filters=filters,
            offset=offset,
            limit=effective,
            sort_by=None,
            group_by=None,
            total_is_scope_safe=total_is_scope_safe,
        )

    async def _filter_hierarchy_allowlist(self, detail: WorkPackageDetail) -> WorkPackageDetail:
        """Drop children/ancestors entries outside OPENPROJECT_READ_PROJECTS.
        Verbatim behavioral port of client.py's `_filter_hierarchy_allowlist`,
        using the existing `WorkPackageProjectAllowedCheck` seam (bound to
        `self._work_package_resolver.project_link_allowed`, unchanged) rather
        than a new resolver -- this Service becomes a ninth consumer of the
        SAME resolver the eight already-migrated domains already share.

        Also re-derives `children_truncated`/`ancestors_truncated` (a
        pre-existing bug ported from client.py's original, fixed here): the
        Adapter computes those flags from the RAW, unfiltered element count
        (server reported more than the adapter's children/ancestors limit),
        before this filter ever runs. If any raw entry gets dropped by the
        allowlist filter below, the true flag no longer describes what the
        caller can actually see -- and, worse, if EVERY entry beyond the
        limit was itself out-of-scope, leaving the flag True after filtering
        down to fewer (or zero) visible entries would disclose the mere
        existence of hierarchy members the caller isn't allowed to see (the
        same class of leak Codex found in the Attachments migration's
        container-check bug, just for a boolean flag instead of an id).
        `truncated` is only kept True when the allowlist filter removed
        NOTHING (every raw entry survived), i.e. the flag still means exactly
        what the caller would derive by counting the visible list alone --
        no Service-layer knowledge of the Adapter's specific limit constant
        needed (Services must not import Adapters, per ADR 0001).
        """
        if scope_allows_all(self._settings.read_projects):
            return detail
        cache = WorkPackageAllowedContext()

        async def keep(
            entries: builtins.list[dict[str, str | None]] | None,
        ) -> builtins.list[dict[str, str | None]] | None:
            if not entries:
                return entries
            filtered = []
            for entry in entries:
                href = entry.get("href")
                if not href:
                    continue
                if await self._work_package_project_allowed(href, context=cache):
                    filtered.append(entry)
            return filtered or None

        original_children_count = len(detail.children) if detail.children else 0
        original_ancestors_count = len(detail.ancestors) if detail.ancestors else 0
        children = await keep(detail.children)
        ancestors = await keep(detail.ancestors)
        children_count = len(children) if children else 0
        ancestors_count = len(ancestors) if ancestors else 0
        return dataclasses.replace(
            detail,
            children=children,
            ancestors=ancestors,
            children_truncated=detail.children_truncated and children_count == original_children_count,
            ancestors_truncated=detail.ancestors_truncated and ancestors_count == original_ancestors_count,
        )

    async def get(self, work_package_ref: int | str, *, text_limit: int | None = None) -> WorkPackageDetail:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(str(work_package_ref), text_limit=text_limit)
        ensure_project_link_allowed(
            record.payload.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        detail = await self._filter_hierarchy_allowlist(record.to_detail())
        # Hidden-field stamping MUST run after _filter_hierarchy_allowlist, not
        # before: apply_hidden_fields sets `_hidden_keys` as a dynamic
        # (non-dataclass-field) attribute, and dataclasses.replace() -- which
        # _filter_hierarchy_allowlist calls whenever the scope is restricted --
        # builds a brand-new instance carrying only the declared dataclass
        # fields, silently dropping `_hidden_keys`. Stamping first meant every
        # get()/get_batch() call under a restricted (non-"*") read_projects
        # scope returned an UNMASKED detail, leaking any hidden work_package
        # field (e.g. description) regardless of whether children/ancestors
        # were even present on that particular work package.
        return self._stamp_detail(detail)

    async def get_batch(
        self, *, ids: builtins.list[int | str], text_limit: int | None = None
    ) -> BatchWorkPackageReadResult:
        if not ids:
            raise ValueError("ids list cannot be empty")
        if len(ids) > BATCH_READ_MAX_IDS:
            raise ValueError(
                f"Maximum {BATCH_READ_MAX_IDS} work packages per batch (got {len(ids)}). Split into multiple calls."
            )

        async def fetch_one(work_package_ref: int | str) -> tuple[int | str, WorkPackageDetail | None, str | None]:
            try:
                work_package = await self.get(work_package_ref, text_limit=text_limit)
                return (work_package_ref, work_package, None)
            except (OpenProjectError, InvalidInputError) as e:
                # httpx.HTTPError deliberately not caught here (unlike
                # client.py's original): every httpx.HTTPError/TimeoutException
                # is already translated to a typed TransportError (an
                # OpenProjectError subclass) by HttpxTransport before it could
                # ever reach this Service -- a raw httpx.HTTPError was dead
                # code in the original, and importing httpx here would violate
                # ADR 0001's httpx-confinement rule (only the Transport module
                # may import httpx directly).
                return (work_package_ref, None, str(e))

        results = await asyncio.gather(*[fetch_one(ref) for ref in ids])

        items: builtins.list[BatchWorkPackageReadItemResult] = []
        succeeded = 0
        failed = 0
        for input_id, work_package, error in results:
            if work_package is not None:
                succeeded += 1
                items.append(
                    BatchWorkPackageReadItemResult(id=input_id, success=True, work_package=work_package, error=None)
                )
            else:
                failed += 1
                items.append(BatchWorkPackageReadItemResult(id=input_id, success=False, work_package=None, error=error))

        if failed == 0:
            message = f"Successfully fetched all {succeeded} work packages."
        elif succeeded == 0:
            message = f"Failed to fetch all {failed} work packages."
        else:
            message = f"Fetched {succeeded} work packages successfully, {failed} failed."

        return BatchWorkPackageReadResult(
            action="batch_read",
            total=len(ids),
            succeeded=succeeded,
            failed=failed,
            message=message,
            results=items,
        )
