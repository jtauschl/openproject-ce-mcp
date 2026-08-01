"""Application Service for the Work Packages domain (ADR 0001).

Covers the full domain: list/search/list_my_open/get/get_batch (the original
READ-only slice) plus create/create_subtask/update/delete/bulk_create/
bulk_update/add_comment (the write-path migration, OPM-286's second
sub-step). Both slices live on this one class, not two -- ADR 0001 and the
"one Service per domain" convention every other full-CRUD sibling (Time
Entries, Versions, Memberships, Projects) already follows.

Depends on `WorkPackageApi` (never the concrete `HttpxWorkPackageApi` --
enforced by `tests/test_architecture_boundaries.py`), `ProjectRefResolver`,
`TypeRefResolver`, `VersionIdResolver`, `StatusRefResolver`,
`PriorityRefResolver`, `PrincipalRefResolver`, `AssigneeRefResolver`,
`SprintIdResolver`, `WorkPackageIdResolver`, `StatusPriorityTypeApi`,
`ActivityApi`, `CurrentUserLookup`, and `WorkPackageProjectAllowedCheck` (the
existing OPM-318 seam bound to `self._work_package_resolver.project_link_allowed`
-- `WorkPackageResolver` itself is untouched by this migration; this Service
becomes its ninth consumer, alongside the eight already-migrated domains that
depend on the same resolver via `app/ports/work_package_ref.py`'s seams).

`AssigneeRefResolver` is deliberately NOT `PrincipalRefResolver`: the write
path's assignee resolution accepts only "me" or a bare numeric id, never a
name search (a real, pre-existing behavioral asymmetry vs. the read-side
`assignee`/`assignee_me` list filters, which do accept names via
`PrincipalRefResolver`) -- see `app/ports/assignee_ref.py`'s module docstring.

`StatusPriorityTypeApi` (the Port, not `StatusPriorityTypeService`) is
injected directly for the auto-percentage/auto-remaining-time derivation's
status-detail lookup (`update()` needs the resolved status's `is_closed` flag,
not just a name/ref->id resolution) -- `StatusPriorityTypeService` must NOT
be used here, since it enforces `access.ensure_read_enabled("work_package")`,
while this internal lookup deliberately bypasses that gate (an instance can
have work-package writes enabled with reads disabled, and the auto-derivation
must still work, matching client.py's original comment on this exact point).

`ActivityApi` is injected directly (the same "Service depending on multiple
Ports" pattern `TimeEntryService` already uses) so `add_comment()` reuses the
EXISTING, already-migrated Activities normalizer instead of duplicating it
onto `WorkPackageApi` -- see `app/ports/activity_api.py`'s extended module
docstring.

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

Every READ method (`search`/`list`/`list_my_open`/`get`/`get_batch`) calls
`access.ensure_read_enabled("work_package", ...)` as its FIRST action, before
any `resolve_*` seam call -- verbatim behavioral port of client.py's
`search_work_packages`/`list_work_packages`/`list_my_open_work_packages`/
`get_work_package`, each of which gates before doing any resolution or HTTP
work. **The WRITE methods (`create`/`create_subtask`/`update`/`delete`/
`bulk_create`/`bulk_update`/`add_comment`) deliberately do NOT** -- verified
against client.py's flat originals, none of which ever called
`_ensure_read_enabled`. This is intentional: an instance can have
work-package writes enabled with reads entirely disabled, and every write
method must keep working in that configuration (the same reasoning already
documented for the auto-derivation's `status_api` bypass below).

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
import logging
from typing import Any

from ...config import Settings
from ...models import (
    ActivityWriteResult,
    BatchWorkPackageReadItemResult,
    BatchWorkPackageReadResult,
    BulkWorkPackageItemResult,
    BulkWorkPackageWriteResult,
    SortCriterion,
    WorkPackageDetail,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)
from ..api_href import api_href as _api_href
from ..errors import InvalidInputError, OpenProjectError, OpenProjectServerError, PermissionDeniedError
from ..pagination import effective_limit, paginate_server
from ..policies import access, hidden_fields
from ..policies import work_package_policy as _work_package_policy
from ..policies.scope import ensure_project_link_allowed, ensure_project_write_link_allowed, scope_allows_all
from ..policies.scope import id_from_href as _id_from_href
from ..ports.activity_api import ActivityApi
from ..ports.assignee_ref import AssigneeRefResolver
from ..ports.current_user import CurrentUserLookup
from ..ports.principal_ref import PrincipalRefResolver
from ..ports.priority_ref import PriorityRefResolver
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext, WorkPackageResolutionContext
from ..ports.sprint_ref import SprintIdResolver
from ..ports.status_priority_type_api import StatusPriorityTypeApi
from ..ports.status_ref import StatusRefResolver
from ..ports.type_ref import TypeRefResolver
from ..ports.version_ref import VersionIdResolver
from ..ports.work_package_api import WorkPackageApi
from ..ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck, work_package_ref
from ..ports.work_package_resolution import WorkPackageAllowedContext
from ._write_outcome import _finalize_write, _WriteOutcome

LOGGER = logging.getLogger(__name__)

BATCH_READ_MAX_IDS = 100

# Matches the flat write normalizer's default cap for create/update responses
# and the delete preview -- NOT the uncapped default get()'s own single-item
# path uses. Verified against client.py's normalize_work_package_detail.
FORMATTABLE_LIMIT = 1_200

# Sentinel for update(): distinguishes "clear the parent" (make the work
# package top-level via _links.parent = {"href": null}) from "leave unchanged"
# (None). A dedicated object avoids colliding with numeric ids or the
# resolve_work_package_id path, and cannot be confused with any valid parent
# reference. Canonical home for this domain's sentinels (re-exported
# unchanged from client.py -- see client.py's own CLEAR_PARENT import).
CLEAR_PARENT = object()

# Sentinel for create()/update(): distinguishes "clear the version" (unassign
# via _links.version = {"href": null}) from "leave unchanged" (None). Same
# rationale as CLEAR_PARENT -- it must bypass version-name resolution.
CLEAR_VERSION = object()

# Generic "clear this field" sentinel, shared by both nullable HAL-link fields
# (assignee, responsible, category, project_phase) and plain scalar fields
# (estimated_time, remaining_time, duration -- cleared via <field>: null
# directly in the payload). Distinguishes "clear this field" from "leave
# unchanged" (None). parent/version keep their own sentinels above for
# historical reasons; every other clearable field shares this one.
CLEAR = object()


def _narrow_cleared(value: Any, *, sentinel: object = None) -> Any:
    """Narrow a value after the caller has already ruled out None and a clear sentinel.

    Verbatim port of client.py's own `_narrow_cleared` (moved here as this
    domain's canonical home, re-exported unchanged from client.py). See that
    original's docstring for the full mypy-narrowing rationale.
    """
    if value is None or value is sentinel:
        raise AssertionError(f"_narrow_cleared: expected a resolved value, got the clear sentinel or None: {value!r}")
    return value


SUBJECT_LIMIT = 255


def _empty_list_result(*, offset: int, limit: int) -> WorkPackageListResult:
    return WorkPackageListResult(
        offset=offset, limit=limit, total=0, count=0, next_offset=None, truncated=False, results=[]
    )


def _trim_text(value: Any, *, limit: int = SUBJECT_LIMIT) -> str | None:
    """Local, deliberately duplicated (Services cannot import from Adapters,
    per ADR 0001 -- matches `app/services/project_service.py`'s own local copy)."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# id_from_href is NOT duplicated here -- it lives in app/policies/scope.py
# (imported below as _id_from_href), unified there once a 3rd identical copy
# appeared (see project_service.py's own equivalent comment).


def _bulk_item_result(*, index: int, result: WorkPackageWriteResult) -> BulkWorkPackageItemResult:
    """Verbatim port of client.py's own `_bulk_item_result`. "success" is
    defined purely by `result.ready` (i.e. no OpenProject validation errors),
    not by `result.confirmed` -- a `confirm=False` preview call that
    validates cleanly is intentionally reported as `success=True`."""
    if not result.ready:
        return BulkWorkPackageItemResult(index=index, success=False, error=result.message, result=result)
    return BulkWorkPackageItemResult(index=index, success=True, error=None, result=result)


def _bulk_summary_message(*, confirm: bool, succeeded: int, failed: int, total: int, verb: str, past_tense: str) -> str:
    """Verbatim port of client.py's own `_bulk_summary_message`."""
    if confirm:
        return (
            f"{succeeded} of {total} work packages {past_tense} successfully."
            if failed == 0
            else f"{succeeded} {past_tense}, {failed} failed."
        )
    return (
        f"Validated {succeeded} of {total} work packages. Call again with confirm=true to {verb} them."
        if failed == 0
        else f"{succeeded} validated, {failed} failed validation."
    )


def _log_bulk_cancellation(
    operation: str, *, confirm: bool, total: int, item_results: builtins.list[BulkWorkPackageItemResult]
) -> None:
    """Diagnostic logging only -- does not close the gap that the MCP caller
    receives no result on cancellation; must not overclaim whether an
    in-flight request reached OpenProject. Verbatim port of client.py's own
    `_log_bulk_cancellation`."""
    completed = len(item_results)
    completed_range = f"0-{completed - 1}" if completed else "none"
    if completed < total:
        if confirm:
            in_flight_desc = (
                f"item at index {completed} has an unknown outcome (may have been in flight when "
                "cancelled; not necessarily written to OpenProject)"
            )
        else:
            in_flight_desc = (
                f"item at index {completed} has an unknown validation outcome (was in flight when "
                "cancelled); confirm=false means no item in this call could have been written to "
                "OpenProject regardless"
            )
        not_started = max(0, total - completed - 1)
    else:
        in_flight_desc = "no item was in flight (all items already had a known outcome)"
        not_started = 0
    LOGGER.warning(
        "%s cancelled (confirm=%s): %d/%d item(s) completed before cancellation (indices %s); "
        "%s; %d item(s) were not yet attempted.",
        operation,
        confirm,
        completed,
        total,
        completed_range,
        in_flight_desc,
        not_started,
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
        resolve_assignee_id: AssigneeRefResolver,
        resolve_sprint_id: SprintIdResolver,
        resolve_work_package_id: WorkPackageIdResolver,
        status_api: StatusPriorityTypeApi,
        activity_api: ActivityApi,
        current_user: CurrentUserLookup,
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
        api_prefix: str,
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
        self._resolve_assignee_id = resolve_assignee_id
        self._resolve_sprint_id = resolve_sprint_id
        self._resolve_work_package_id = resolve_work_package_id
        self._status_api = status_api
        self._activity_api = activity_api
        self._current_user = current_user
        self._work_package_project_allowed = work_package_project_allowed
        self._api_prefix = api_prefix

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

    def _stamp_activity(self, summary: Any) -> Any:
        return hidden_fields.apply_hidden_fields("activity", summary, settings=self._settings)

    def _replace_and_restamp(self, entity: str, value: Any, **changes: Any) -> Any:
        """Like `dataclasses.replace()`, but preserves the `_hidden_keys` stamp.

        `dataclasses.replace()` rebuilds the instance via the constructor,
        which drops any `_hidden_keys` attribute `apply_hidden_fields`
        previously stamped onto it -- re-stamp so a configured hide-fields
        entry still takes effect on the replaced instance. Verbatim port of
        client.py's own `_replace_and_restamp` (already correct there:
        replace-then-stamp, in that order, in one call).
        """
        return hidden_fields.apply_hidden_fields(entity, dataclasses.replace(value, **changes), settings=self._settings)

    def _new_wp_context(self) -> WorkPackageResolutionContext:
        """Construct a fresh, per-call WorkPackageResolutionContext (never
        reused across calls; see ProjectResolutionContext's lifetime rule).
        `bulk_create`/`bulk_update` deliberately construct exactly one and
        share it across their whole loop instead (safe: the id cache is keyed
        by (project, kind, ref), never cross-project)."""
        return WorkPackageResolutionContext(ProjectResolutionContext(self._resolve_project_ref))

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

    # ------------------------------------------------------------------
    # Write paths (OPM-286 write-path migration).
    # ------------------------------------------------------------------

    async def _resolve_wp_ref_id(
        self,
        kind: str,
        ref: str,
        *,
        project: str,
        cache: WorkPackageResolutionContext | None,
        resolve: Any,
    ) -> str:
        """Cache-then-resolve wrapper around resolve_type_id/resolve_version_id/
        resolve_sprint_id. When `cache` is shared across a bulk call's items,
        a repeated name->id lookup for the same (project, kind, ref) is
        skipped instead of re-querying OpenProject once per item. Verbatim
        port of client.py's own `_resolve_wp_ref_id`."""
        if cache is not None:
            cached = cache.get_id(kind, project, ref)
            if cached is not None:
                return cached
        resolved = await resolve()
        if cache is not None:
            cache.store_id(kind, project, ref, resolved)
        return resolved

    async def _get_write_schema(
        self,
        *,
        project: str,
        type: str | None,
        work_package_id: int | str | None,
        draft_payload: dict[str, Any],
        lock_version: int | None,
        project_context: ProjectResolutionContext | None,
    ) -> dict[str, Any]:
        """Embedded schema probe (call #1 of up to 3 `/form` POSTs per
        `update()` -- see `app/ports/work_package_api.py`'s module docstring).
        Verbatim port of client.py's own `_get_write_schema`."""
        if work_package_id is not None:
            # OpenProject 17.x rejects the work-package form endpoint with a
            # "could not be updated due to conflicting modifications" (409)
            # error unless the current lockVersion is included, even for a
            # schema-only probe.
            schema_body = dict(draft_payload)
            if lock_version is not None:
                schema_body["lockVersion"] = lock_version
            form = await self._api.validate_update(str(work_package_id), schema_body)
            return self._api.parse_form(form).schema

        schema_payload = dict(draft_payload)
        schema_links = dict(schema_payload.get("_links", {}))
        if type is not None and "type" not in schema_links:
            # Latent/unreachable in current call patterns: _build_write_payload
            # already puts "type" in schema_links whenever `type` is given, so
            # this branch only fires for a hypothetical future caller that
            # doesn't. Still threaded through for consistency with every other
            # resolver call in this flow.
            type_id = await self._resolve_type_id(type, project=project, context=project_context)
            schema_links["type"] = {"href": _api_href(f"types/{type_id}", api_prefix=self._api_prefix)}
        if schema_links:
            schema_payload["_links"] = schema_links
        form = await self._api.validate_create(project, schema_payload)
        return self._api.parse_form(form).schema

    def _resolve_schema_option_href(self, schema: dict[str, Any], key: str, raw_value: Any) -> str:
        """Verbatim port of client.py's own `_resolve_schema_option_href`."""
        field = schema.get(key)
        if not isinstance(field, dict):
            raise InvalidInputError(f"OpenProject schema does not expose field '{key}' for this work package.")
        allowed_values = field.get("_embedded", {}).get("allowedValues", [])
        if not isinstance(allowed_values, list):
            raise InvalidInputError(f"OpenProject schema does not expose allowed values for field '{key}'.")

        normalized = str(raw_value).strip()
        if not normalized:
            raise InvalidInputError(f"{key} must not be empty.")

        for item in allowed_values:
            href = item.get("_links", {}).get("self", {}).get("href")
            if not href:
                continue
            item_id = _id_from_href(href)
            title = _trim_text(item.get("name") or item.get("_links", {}).get("self", {}).get("title"))
            if normalized.isdigit() and item_id is not None and int(normalized) == item_id:
                return str(href)
            if title and title.casefold() == normalized.casefold():
                return str(href)
        raise InvalidInputError(f"OpenProject value '{raw_value}' is not allowed for field '{key}'.")

    def _resolve_custom_field_key(self, schema: dict[str, Any], raw_key: str) -> str:
        """Verbatim port of client.py's own `_resolve_custom_field_key`."""
        normalized = str(raw_key).strip()
        if not normalized:
            raise InvalidInputError("custom field keys must not be empty.")
        if normalized in schema:
            return normalized
        if normalized.casefold().startswith("customfield") and normalized[11:].isdigit():
            candidate = f"customField{normalized[11:]}"
            if candidate in schema:
                return candidate
        for key, field in schema.items():
            if not key.startswith("customField") or not isinstance(field, dict):
                continue
            name = _trim_text(field.get("name"))
            if name and name.casefold() == normalized.casefold():
                return key
        raise InvalidInputError(f"OpenProject custom field '{raw_key}' is not available for this work package.")

    def _resolve_custom_field_links(self, field: dict[str, Any], raw_value: Any, key: str) -> builtins.list[str]:
        """Verbatim port of client.py's own `_resolve_custom_field_links`."""
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        hrefs = [self._resolve_schema_option_href({key: field}, key, value) for value in values]
        if not hrefs:
            raise InvalidInputError(f"OpenProject custom field '{key}' requires at least one value.")
        return hrefs

    def _apply_custom_fields(
        self,
        payload: dict[str, Any],
        links: dict[str, Any],
        schema: dict[str, Any],
        custom_fields: dict[str, Any],
    ) -> None:
        """Verbatim port of client.py's own `_apply_custom_fields`."""
        for raw_key, raw_value in custom_fields.items():
            hidden_fields.ensure_custom_field_input_writable(raw_key, settings=self._settings)
            schema_key = self._resolve_custom_field_key(schema, raw_key)
            field = schema[schema_key]
            hidden_fields.ensure_custom_field_writable(
                _trim_text(field.get("name")) or schema_key, schema_key, settings=self._settings
            )
            location = field.get("location")
            if location == "_links":
                hrefs = self._resolve_custom_field_links(field, raw_value, schema_key)
                if len(hrefs) == 1:
                    links[schema_key] = {"href": hrefs[0]}
                else:
                    links[schema_key] = [{"href": href} for href in hrefs]
            else:
                payload[schema_key] = raw_value

    async def _build_write_payload(
        self,
        *,
        project: str,
        type: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        version: Any = None,
        sprint: Any = None,
        project_phase: Any = None,
        status: str | None = None,
        assignee: Any = None,
        responsible: Any = None,
        priority: str | None = None,
        category: Any = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: Any = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: Any = None,
        remaining_time: Any = None,
        duration: Any = None,
        percentage_done: int | None = None,
        work_package_id: int | str | None = None,
        lock_version: int | None = None,
        resolution_context: WorkPackageResolutionContext | None = None,
    ) -> dict[str, Any]:
        """Build the HAL JSON payload for create()/update(). Verbatim port of
        client.py's own `_build_write_payload` -- see that method and
        `app/ports/work_package_api.py`'s module docstring for the full
        field-by-field / sentinel-handling rationale."""
        project_context = resolution_context.project_context if resolution_context is not None else None
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if custom_fields:
            for raw_key in custom_fields:
                hidden_fields.ensure_custom_field_input_writable(raw_key, settings=self._settings)

        if subject is not None:
            hidden_fields.ensure_field_writable("work_package", "subject", settings=self._settings)
            payload["subject"] = subject
        if description is not None:
            hidden_fields.ensure_field_writable("work_package", "description", settings=self._settings)
            payload["description"] = {"format": "markdown", "raw": description}
        if start_date is not None:
            hidden_fields.ensure_field_writable("work_package", "start_date", settings=self._settings)
            payload["startDate"] = start_date
        if due_date is not None:
            hidden_fields.ensure_field_writable("work_package", "due_date", settings=self._settings)
            payload["dueDate"] = due_date
        if estimated_time is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "estimated_time", settings=self._settings)
            payload["estimatedTime"] = None
        elif estimated_time is not None:
            hidden_fields.ensure_field_writable("work_package", "estimated_time", settings=self._settings)
            payload["estimatedTime"] = estimated_time
        if remaining_time is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "remaining_time", settings=self._settings)
            payload["remainingTime"] = None
        elif remaining_time is not None:
            hidden_fields.ensure_field_writable("work_package", "remaining_time", settings=self._settings)
            payload["remainingTime"] = remaining_time
        if percentage_done is not None:
            hidden_fields.ensure_field_writable("work_package", "percentage_done", settings=self._settings)
            payload["percentageDone"] = percentage_done
        if duration is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "duration", settings=self._settings)
            payload["duration"] = None
        elif duration is not None:
            hidden_fields.ensure_field_writable("work_package", "duration", settings=self._settings)
            payload["duration"] = duration

        if type is not None:
            hidden_fields.ensure_field_writable("work_package", "type", settings=self._settings)
            type_id = await self._resolve_wp_ref_id(
                "type",
                type,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_type_id(type, project=project, context=project_context),
            )
            links["type"] = {"href": _api_href(f"types/{type_id}", api_prefix=self._api_prefix)}
        if version is CLEAR_VERSION:
            hidden_fields.ensure_field_writable("work_package", "version", settings=self._settings)
            links["version"] = {"href": None}
        elif version is not None:
            hidden_fields.ensure_field_writable("work_package", "version", settings=self._settings)
            version_ref = _narrow_cleared(version, sentinel=CLEAR_VERSION)
            version_id = await self._resolve_wp_ref_id(
                "version",
                version_ref,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_version_id(version_ref, project=project, context=project_context),
            )
            links["version"] = {"href": _api_href(f"versions/{version_id}", api_prefix=self._api_prefix)}
        if sprint is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "sprint", settings=self._settings)
            links["sprint"] = {"href": None}
        elif sprint is not None:
            hidden_fields.ensure_field_writable("work_package", "sprint", settings=self._settings)
            sprint_ref = _narrow_cleared(sprint, sentinel=CLEAR)
            sprint_id = await self._resolve_wp_ref_id(
                "sprint",
                sprint_ref,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_sprint_id(sprint_ref, project=project, context=project_context),
            )
            links["sprint"] = {"href": _api_href(f"sprints/{sprint_id}", api_prefix=self._api_prefix)}
        if status is not None:
            hidden_fields.ensure_field_writable("work_package", "status", settings=self._settings)
            status_id = await self._resolve_status_id(status)
            links["status"] = {"href": _api_href(f"statuses/{status_id}", api_prefix=self._api_prefix)}
        if assignee is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "assignee", settings=self._settings)
            links["assignee"] = {"href": None}
        elif assignee is not None:
            hidden_fields.ensure_field_writable("work_package", "assignee", settings=self._settings)
            assignee_ref = _narrow_cleared(assignee, sentinel=CLEAR)
            assignee_id = await self._resolve_assignee_id(assignee_ref)
            links["assignee"] = {"href": _api_href(f"users/{assignee_id}", api_prefix=self._api_prefix)}
        if parent_work_package_id is CLEAR_PARENT:
            hidden_fields.ensure_field_writable("work_package", "parent", settings=self._settings)
            links["parent"] = {"href": None}
        elif parent_work_package_id is not None:
            hidden_fields.ensure_field_writable("work_package", "parent", settings=self._settings)
            links["parent"] = {
                "href": _api_href(f"work_packages/{parent_work_package_id}", api_prefix=self._api_prefix)
            }

        if responsible is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "responsible", settings=self._settings)
            links["responsible"] = {"href": None}
        if category is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "category", settings=self._settings)
            links["category"] = {"href": None}
        if project_phase is CLEAR:
            hidden_fields.ensure_field_writable("work_package", "project_phase", settings=self._settings)
            links["projectPhase"] = {"href": None}

        schema_needs = any(
            value is not None and value is not CLEAR
            for value in (responsible, priority, category, project_phase, custom_fields)
        )
        if schema_needs:
            if links:
                payload["_links"] = links
            schema = await self._get_write_schema(
                project=project,
                type=type,
                work_package_id=work_package_id,
                draft_payload=payload,
                lock_version=lock_version,
                project_context=project_context,
            )
            if responsible is not None and responsible is not CLEAR:
                hidden_fields.ensure_field_writable("work_package", "responsible", settings=self._settings)
                links["responsible"] = {"href": self._resolve_schema_option_href(schema, "responsible", responsible)}
            if priority is not None:
                hidden_fields.ensure_field_writable("work_package", "priority", settings=self._settings)
                links["priority"] = {"href": self._resolve_schema_option_href(schema, "priority", priority)}
            if category is not None and category is not CLEAR:
                hidden_fields.ensure_field_writable("work_package", "category", settings=self._settings)
                links["category"] = {"href": self._resolve_schema_option_href(schema, "category", category)}
            if project_phase is not None and project_phase is not CLEAR:
                hidden_fields.ensure_field_writable("work_package", "project_phase", settings=self._settings)
                links["projectPhase"] = {
                    "href": self._resolve_schema_option_href(schema, "projectPhase", project_phase)
                }
            if custom_fields:
                self._apply_custom_fields(payload, links, schema, custom_fields)

        if links:
            payload["_links"] = links
        return payload

    async def _to_write_result(self, action: str, outcome: _WriteOutcome[Any]) -> WorkPackageWriteResult:
        detail = None
        if outcome.detail is not None:
            # outcome.detail is a WorkPackageRecord (commit_create's/
            # commit_update's return shape, same lazy-detail shape get()
            # itself consumes) -- must call .to_detail() before any
            # dataclasses.replace()-based transform, which requires an actual
            # WorkPackageDetail instance, not the Record wrapping it.
            #
            # A freshly created/updated work package's children/ancestors are
            # rarely populated (a brand-new work package has none; an update
            # response echoes the same hierarchy links get() would), but
            # running the same allowlist filter here keeps the masking-order
            # contract identical to get()'s, rather than assuming it can
            # never matter. See get()'s own comment: _filter_hierarchy_allowlist
            # calls dataclasses.replace() whenever the read scope is
            # restricted, which would silently drop _stamp_detail's
            # _hidden_keys tag if stamping ran first -- filter first, stamp
            # last, matching get()'s established ordering exactly.
            filtered = await self._filter_hierarchy_allowlist(outcome.detail.to_detail())
            detail = self._stamp_detail(filtered)
        return WorkPackageWriteResult(
            action=action,
            confirmed=outcome.confirmed,
            requires_confirmation=outcome.requires_confirmation,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=detail,
            **outcome.identity,
        )

    async def create(
        self,
        *,
        project: str,
        type: str,
        subject: str,
        description: str | None = None,
        version: Any = None,
        project_phase: Any = None,
        assignee: Any = None,
        responsible: Any = None,
        priority: str | None = None,
        category: Any = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: str | None = None,
        remaining_time: str | None = None,
        duration: str | None = None,
        confirm: bool = False,
        wp_context: WorkPackageResolutionContext | None = None,
    ) -> WorkPackageWriteResult:
        # Deliberately NO access.ensure_read_enabled gate here -- the flat
        # create_work_package never gated on read-enablement either (verified
        # against client.py's original), so an instance can have work-package
        # writes enabled with reads entirely disabled and this must still work.
        # When a caller shares a wp_context across a bulk batch, route this
        # resolve through its cache too -- items sharing the same project then
        # only trigger one real project fetch for the whole batch, not one per
        # item. With no wp_context (the default, single-call case) this is
        # exactly the raw self._resolve_project_ref(project, write=True) call,
        # uncached.
        project_payload = await self._resolve_project_ref(
            project, write=True, context=wp_context.project_context if wp_context is not None else None
        )
        project_id = str(project_payload["id"])
        # Default: a fresh context per call. A bulk caller (bulk_create)
        # passes one shared across all its items instead.
        if wp_context is None:
            wp_context = self._new_wp_context()
        # write=True already implies read=True passed (write checks read
        # first), so both keys are safe to seed from the same payload -- this
        # is what lets the type/version resolvers below reuse it instead of
        # re-fetching.
        wp_context.project_context.seed(project_id, project_payload, write=True)
        wp_context.project_context.seed(project_id, project_payload, write=False)
        if parent_work_package_id is not None:
            # parent goes into a HAL link href, which resolves only by
            # numeric id. write=True: the new parent must itself be
            # write-authorized, not just readable -- otherwise a caller could
            # attach a writable work package under a parent they can only
            # read.
            parent_work_package_id = await self._resolve_work_package_id(parent_work_package_id, write=True)
        payload = await self._build_write_payload(
            project=project_id,
            type=type,
            subject=subject,
            description=description,
            version=version,
            project_phase=project_phase,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_work_package_id,
            start_date=start_date,
            due_date=due_date,
            estimated_time=estimated_time,
            remaining_time=remaining_time,
            duration=duration,
            resolution_context=wp_context,
        )
        form = await self._api.validate_create(project_id, payload)
        parsed = self._api.parse_form(form)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=parsed.payload,
            validation_errors=parsed.validation_errors,
            identity={"work_package_id": None, "project": project_payload.get("name")},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=lambda p: self._api.commit_create(p, text_limit=FORMATTABLE_LIMIT),
            committed_identity=lambda record: {
                "work_package_id": record.summary.id,
                "project": record.summary.project,
            },
            rejected_message="OpenProject rejected the proposed changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Work package created successfully.",
        )
        return await self._to_write_result("create", outcome)

    async def create_subtask(
        self,
        *,
        parent_work_package_id: int | str,
        type: str,
        subject: str,
        description: str | None = None,
        version: Any = None,
        project_phase: Any = None,
        assignee: Any = None,
        responsible: Any = None,
        priority: str | None = None,
        category: Any = None,
        custom_fields: dict[str, Any] | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        # Deliberately NO access.ensure_read_enabled gate -- see create()'s
        # identical comment.
        parent_record = await self._api.get(work_package_ref(parent_work_package_id))
        parent_payload = parent_record.payload
        # The parent link needs the numeric id (HAL hrefs don't resolve
        # displayId); read it back from the fetched parent rather than
        # reusing the semantic ref.
        parent_numeric_id = int(parent_payload["id"])
        parent_project_link = parent_payload.get("_links", {}).get("project")
        project_id = _id_from_href(parent_project_link.get("href") if parent_project_link else None)
        if project_id is None:
            # A server-data anomaly (an unexpected/malformed OpenProject
            # response), not a caller mistake -- OpenProjectServerError,
            # matching release/0.3.5's still-flat equivalent, not
            # InvalidInputError (reconciled 2026-08-01 after a cross-branch
            # parity audit found the two branches disagreed on this).
            raise OpenProjectServerError("OpenProject work package is missing a project link.")
        ensure_project_write_link_allowed(
            parent_project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )

        wp_context = self._new_wp_context()
        payload = await self._build_write_payload(
            project=str(project_id),
            type=type,
            subject=subject,
            description=description,
            version=version,
            project_phase=project_phase,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_numeric_id,
            start_date=start_date,
            due_date=due_date,
            resolution_context=wp_context,
        )
        form = await self._api.validate_create(str(project_id), payload)
        parsed = self._api.parse_form(form)
        parent_title = _trim_text(parent_project_link.get("title") if parent_project_link else None)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=parsed.payload,
            validation_errors=parsed.validation_errors,
            identity={"work_package_id": None, "project": parent_title},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=lambda p: self._api.commit_create(p, text_limit=FORMATTABLE_LIMIT),
            committed_identity=lambda record: {
                "work_package_id": record.summary.id,
                "project": record.summary.project,
            },
            rejected_message="OpenProject rejected the proposed changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the subtask. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Subtask created successfully.",
        )
        return await self._to_write_result("create", outcome)

    async def bulk_create(
        self, *, items: builtins.list[dict[str, Any]], confirm: bool = False
    ) -> BulkWorkPackageWriteResult:
        item_results: builtins.list[BulkWorkPackageItemResult] = []
        # Shared across every item in this bulk call (see
        # WorkPackageResolutionContext): items in the same project skip
        # repeating the same project fetch and type/version name->id lookups.
        # Discarded once this call returns -- never reused across separate
        # bulk_create calls.
        wp_context = self._new_wp_context()
        try:
            for i, item in enumerate(items):
                try:
                    result = await self.create(
                        project=item["project"],
                        type=item["type"],
                        subject=item["subject"],
                        description=item.get("description"),
                        version=item.get("version"),
                        project_phase=item.get("project_phase"),
                        assignee=item.get("assignee"),
                        responsible=item.get("responsible"),
                        priority=item.get("priority"),
                        category=item.get("category"),
                        custom_fields=item.get("custom_fields"),
                        parent_work_package_id=item.get("parent_work_package_id"),
                        start_date=item.get("start_date"),
                        due_date=item.get("due_date"),
                        estimated_time=item.get("estimated_time"),
                        remaining_time=item.get("remaining_time"),
                        duration=item.get("duration"),
                        confirm=confirm,
                        wp_context=wp_context,
                    )
                    item_results.append(_bulk_item_result(index=i, result=result))
                except Exception as exc:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))
        except asyncio.CancelledError:
            _log_bulk_cancellation(
                "bulk_create_work_packages", confirm=confirm, total=len(items), item_results=item_results
            )
            raise

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        message = _bulk_summary_message(
            confirm=confirm, succeeded=succeeded, failed=failed, total=len(items), verb="create", past_tense="created"
        )
        return BulkWorkPackageWriteResult(
            action="bulk_create",
            confirmed=confirm and failed == 0,
            requires_confirmation=requires_confirmation,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            message=message,
            items=item_results,
        )

    async def _auto_derive_progress_on_close(
        self,
        *,
        status: str | None,
        percentage_done: int | None,
        remaining_time: Any,
        payload: dict[str, Any],
        current: dict[str, Any],
    ) -> tuple[int | None, Any]:
        """Returns (auto_percentage, auto_remaining) -- both None if no
        auto-fill applies. Verbatim port of update_work_package's inline
        auto-derivation block (client.py:1712-1746).

        Only attempted when `status` is actually changing, to avoid an extra
        lookup on every plain field update. Resolves the status id already
        present in `payload["_links"]["status"]["href"]` (set by
        `_build_write_payload` when `status` was given) and fetches the full
        status via `self._status_api.get_status(status_id)` -- deliberately
        NOT `StatusPriorityTypeService`, which enforces
        `access.ensure_read_enabled("work_package")` and would incorrectly
        block this purely internal lookup on instances that have
        work-package writes enabled but reads disabled.
        """
        want_auto_percentage = percentage_done is None
        want_auto_remaining = remaining_time is None
        auto_percentage: int | None = None
        auto_remaining: Any = None
        if status is None or not (want_auto_percentage or want_auto_remaining):
            return auto_percentage, auto_remaining
        status_id = _id_from_href(payload.get("_links", {}).get("status", {}).get("href"))
        status_record = await self._status_api.get_status(int(status_id) if status_id is not None else 0)
        if status_record.summary.is_closed:
            auto_percentage = 100 if want_auto_percentage else None
            if want_auto_remaining:
                # OpenProject's own validation requires the OPPOSITE target
                # depending on whether an estimate exists: remainingTime must
                # be exactly "PT0H" when estimatedTime is set, but must be
                # null/absent when it isn't -- live-verified against real
                # OpenProject. "Effective" estimate: this same call's own
                # estimated_time if it set one, else the work package's
                # existing value from the pre-write GET.
                effective_estimated_time = (
                    payload.get("estimatedTime") if "estimatedTime" in payload else current.get("estimatedTime")
                )
                auto_remaining = "PT0H" if effective_estimated_time else CLEAR
        return auto_percentage, auto_remaining

    async def update(
        self,
        *,
        work_package_id: int | str,
        subject: str | None = None,
        description: str | None = None,
        type: str | None = None,
        version: Any = None,
        sprint: Any = None,
        project_phase: Any = None,
        status: str | None = None,
        assignee: Any = None,
        responsible: Any = None,
        priority: str | None = None,
        category: Any = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: Any = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: Any = None,
        remaining_time: Any = None,
        duration: Any = None,
        percentage_done: int | None = None,
        confirm: bool = False,
        wp_context: WorkPackageResolutionContext | None = None,
    ) -> WorkPackageWriteResult:
        # Deliberately NO access.ensure_read_enabled gate -- see create()'s
        # identical comment; this is also why the auto-derivation below reads
        # status via self._status_api directly rather than
        # StatusPriorityTypeService, which WOULD gate on read-enablement.
        ref = work_package_ref(work_package_id)
        if parent_work_package_id is not None and parent_work_package_id is not CLEAR_PARENT:
            # parent goes into a HAL link href, which resolves only by
            # numeric id. CLEAR_PARENT is a sentinel (un-parent) and must
            # pass through unresolved. write=True: the new parent must
            # itself be write-authorized, not just readable -- otherwise a
            # caller could reparent a writable work package under a parent
            # they can only read.
            parent_work_package_id = await self._resolve_work_package_id(
                _narrow_cleared(parent_work_package_id, sentinel=CLEAR_PARENT), write=True
            )
        current_record = await self._api.get(ref)
        current = current_record.payload
        project_id = _id_from_href(current.get("_links", {}).get("project", {}).get("href"))
        if project_id is None:
            # A server-data anomaly (an unexpected/malformed OpenProject
            # response), not a caller mistake -- OpenProjectServerError,
            # matching release/0.3.5's still-flat equivalent, not
            # InvalidInputError (reconciled 2026-08-01 after a cross-branch
            # parity audit found the two branches disagreed on this).
            raise OpenProjectServerError("OpenProject work package is missing a project link.")
        ensure_project_write_link_allowed(
            current.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        # Default: a fresh context per call. A bulk caller (bulk_update)
        # passes one shared across all its items instead.
        if wp_context is None:
            wp_context = self._new_wp_context()
        lock_version = current.get("lockVersion")
        payload = await self._build_write_payload(
            project=str(project_id),
            type=type,
            subject=subject,
            description=description,
            version=version,
            sprint=sprint,
            project_phase=project_phase,
            status=status,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_work_package_id,
            start_date=start_date,
            due_date=due_date,
            estimated_time=estimated_time,
            remaining_time=remaining_time,
            duration=duration,
            percentage_done=percentage_done,
            work_package_id=ref,
            lock_version=lock_version,
            resolution_context=wp_context,
        )

        auto_percentage, auto_remaining = await self._auto_derive_progress_on_close(
            status=status,
            percentage_done=percentage_done,
            remaining_time=remaining_time,
            payload=payload,
            current=current,
        )

        payload["lockVersion"] = lock_version
        form = await self._api.validate_update(ref, payload)

        if auto_percentage is not None or auto_remaining is not None:
            parsed_probe = self._api.parse_form(form)
            schema = parsed_probe.schema
            changed = False
            if (
                auto_percentage is not None
                and schema.get("percentageDone", {}).get("writable") is True
                and not hidden_fields.field_hidden("work_package", "percentage_done", settings=self._settings)
            ):
                payload["percentageDone"] = auto_percentage
                changed = True
            if (
                auto_remaining is not None
                and schema.get("remainingTime", {}).get("writable") is True
                and not hidden_fields.field_hidden("work_package", "remaining_time", settings=self._settings)
            ):
                payload["remainingTime"] = None if auto_remaining is CLEAR else auto_remaining
                changed = True
            if changed:
                payload["lockVersion"] = lock_version
                form = await self._api.validate_update(ref, payload)

        parsed = self._api.parse_form(form)
        project_name = _trim_text(current.get("_links", {}).get("project", {}).get("title"))
        outcome = await _finalize_write(
            confirm=confirm,
            payload=parsed.payload,
            validation_errors=parsed.validation_errors,
            identity={"work_package_id": ref, "project": project_name},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=lambda p: self._api.commit_update(ref, p, text_limit=FORMATTABLE_LIMIT),
            committed_identity=lambda record: {
                "work_package_id": record.summary.id,
                "project": record.summary.project,
            },
            rejected_message="OpenProject rejected the proposed changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Work package updated successfully.",
        )
        return await self._to_write_result("update", outcome)

    async def bulk_update(
        self, *, items: builtins.list[dict[str, Any]], confirm: bool = False
    ) -> BulkWorkPackageWriteResult:
        item_results: builtins.list[BulkWorkPackageItemResult] = []
        # Shared across every item in this bulk call (see
        # WorkPackageResolutionContext): items in the same project skip
        # repeating the same project fetch and type/version name->id lookups.
        # Discarded once this call returns -- never reused across separate
        # bulk_update calls.
        wp_context = self._new_wp_context()
        try:
            for i, item in enumerate(items):
                try:
                    result = await self.update(
                        work_package_id=item["work_package_id"],
                        subject=item.get("subject"),
                        description=item.get("description"),
                        type=item.get("type"),
                        version=item.get("version"),
                        sprint=item.get("sprint"),
                        project_phase=item.get("project_phase"),
                        status=item.get("status"),
                        assignee=item.get("assignee"),
                        responsible=item.get("responsible"),
                        priority=item.get("priority"),
                        category=item.get("category"),
                        custom_fields=item.get("custom_fields"),
                        parent_work_package_id=item.get("parent_work_package_id"),
                        start_date=item.get("start_date"),
                        due_date=item.get("due_date"),
                        estimated_time=item.get("estimated_time"),
                        remaining_time=item.get("remaining_time"),
                        duration=item.get("duration"),
                        percentage_done=item.get("percentage_done"),
                        confirm=confirm,
                        wp_context=wp_context,
                    )
                    item_results.append(_bulk_item_result(index=i, result=result))
                except Exception as exc:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))
        except asyncio.CancelledError:
            _log_bulk_cancellation(
                "bulk_update_work_packages", confirm=confirm, total=len(items), item_results=item_results
            )
            raise

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        message = _bulk_summary_message(
            confirm=confirm, succeeded=succeeded, failed=failed, total=len(items), verb="update", past_tense="updated"
        )
        return BulkWorkPackageWriteResult(
            action="bulk_update",
            confirmed=confirm and failed == 0,
            requires_confirmation=requires_confirmation,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            message=message,
            items=item_results,
        )

    async def delete(self, *, work_package_id: int | str, confirm: bool = False) -> WorkPackageWriteResult:
        # Deliberately NO access.ensure_read_enabled gate -- see create()'s
        # identical comment.
        ref = work_package_ref(work_package_id)
        record = await self._api.get(ref, text_limit=FORMATTABLE_LIMIT)
        ensure_project_write_link_allowed(
            record.payload.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        detail = self._stamp_detail(record.to_detail())
        payload = {"id": detail.id, "subject": detail.subject, "lockVersion": detail.lock_version}

        if not confirm:
            return WorkPackageWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete this work package. Ask for confirmation, then call again with confirm=true.",
                work_package_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=detail,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(ref)
        return WorkPackageWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Work package deleted successfully.",
            work_package_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=None,
        )

    async def _fill_missing_activity_user(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Best-effort: fill in a missing `_links.user` on a freshly-posted activity.

        The activities POST response can be leaner than a subsequent GET and
        omit `_links.user` entirely, even though the activity was persisted
        correctly. Re-fetches the canonical activity by id (via the injected
        `ActivityApi`, not a duplicated Adapter method -- see
        `app/ports/activity_api.py`'s module docstring) and merges in its
        `_links.user`. A failure here (404, permission, timeout, ...) must
        never turn an already-successful write into a reported error, so it
        is swallowed and just logged -- the caller then simply keeps user
        unset. Only attempted when the response carries a usable id and when
        `user` isn't configured hidden for activities anyway, since fetching
        it would just be discarded. Verbatim port of client.py's own
        `_fill_missing_activity_user`.
        """
        if hidden_fields.field_hidden("activity", "user", settings=self._settings):
            return activity
        activity_links = activity.get("_links", {})
        activity_id = activity.get("id")
        existing_user_title = _trim_text((activity_links.get("user") or {}).get("title"))
        if existing_user_title or not (isinstance(activity_id, int) and activity_id > 0):
            return activity
        try:
            fetched_activity = await self._activity_api.get_raw(activity_id)
        except OpenProjectError:
            LOGGER.warning(
                "add_comment: fallback fetch of activity %s for a missing user link failed; "
                "the comment was still saved, user stays unset.",
                activity_id,
            )
            return activity
        fetched_user_link = fetched_activity.get("_links", {}).get("user")
        if not fetched_user_link:
            return activity
        return {**activity, "_links": {**activity_links, "user": fetched_user_link}}

    async def add_comment(
        self,
        *,
        work_package_id: int | str,
        comment: str,
        internal: bool = False,
        notify: bool = False,
        confirm: bool = False,
    ) -> ActivityWriteResult:
        if comment is not None:
            hidden_fields.ensure_field_writable("activity", "comment", settings=self._settings)
        ref = work_package_ref(work_package_id)
        record = await self._api.get(ref)
        ensure_project_write_link_allowed(
            record.payload.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        payload = {"comment": {"raw": comment}, "internal": internal, "notify": notify}

        if not confirm:
            return ActivityWriteResult(
                action="comment",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to add this comment. Ask for confirmation, then call again with confirm=true.",
                work_package_id=ref,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        activity = await self._api.post_comment(ref, comment=comment, internal=internal, notify=notify)
        activity = await self._fill_missing_activity_user(activity)
        # OpenProject can aggregate a new note into an existing, more recent
        # journal entry (e.g. a prior status change) instead of always
        # creating a fresh one. When that happens, this endpoint's response
        # carries that other journal entry's field-change `details` and
        # `createdAt` alongside the comment. There is no reliable signal to
        # tell an aggregated response from a fresh one, so both are
        # suppressed unconditionally -- including for an ordinary,
        # non-aggregated comment, which sacrifices its own correct timestamp
        # too. `comment`/`id` are unaffected by this and still reflect the
        # activities POST response.
        raw_summary = self._activity_api.to_record(activity).to_summary(FORMATTABLE_LIMIT)
        normalized_activity = self._replace_and_restamp(
            "activity", raw_summary, details=None, details_truncated=False, created_at=None
        )
        return ActivityWriteResult(
            action="comment",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Comment added successfully.",
            work_package_id=ref,
            payload=payload,
            validation_errors={},
            result=normalized_activity,
        )
