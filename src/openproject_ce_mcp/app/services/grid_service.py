"""Application Service for the Grids domain (ADR 0001).

Depends on the GridApi Protocol, never HttpxGridApi concretely (enforced by
the architecture-boundary test). No dedicated GridResolver: a `grid_id` is
always a numeric value already validated by tools.py.

No ProjectRefResolver seam: unlike every domain with a `project` filter
parameter, Grids never resolves a project ref -- `scope` is a raw href/path
string (e.g. "/my/page" or "/projects/6") passed straight through as a
filter value and/or an allowlist-check input, never resolved against a
project payload.

Grids shares the "project" read/write scope with Projects/News/Documents/
Categories/Views -- no dedicated OPENPROJECT_ENABLE_GRID_* flag exists.

Write-allowlist ordering, verified against client.py's original: the
grid_policy.ensure_grid_write_allowed check runs UNCONDITIONALLY at the top
of create()/update()/delete() (during preview AND confirm) -- it is not
confirm-gated. Only access.ensure_write_enabled (inside _finalize_write's
confirm branch) is confirm-gated. This mirrors MembershipService's existing
create()/update() ordering exactly.

_write_outcome.py's _finalize_write is used for create()/update() (2 write
actions sharing the identical form-based preview/commit shape -- the first
domain to hit this project's own "3+ write actions" threshold since
Memberships). delete() has no form step at all, so it stays an inline
preview/commit method like MembershipService.delete().

`create()`/`update()` call `hidden_fields.ensure_field_writable("grid",
<field>, ...)` for every field they write ("name", "scope", "row_count",
"column_count"). This is a DELIBERATE HARDENING found by a step-6
self-audit run during the Groups migration (the 15th domain): Grids was the
only full-CRUD domain among all migrated domains with no config entity
entry at all (`config.py`'s `HIDE_FIELD_ENV_BY_ENTITY` had no `"grid"` key,
so `OPENPROJECT_HIDE_GRID_FIELDS` never existed), meaning
`hidden_fields.field_hidden("grid", ...)` could never return True under any
configuration -- both the write guard AND the config entity were missing,
not just the guard call sites. Fixed by adding the `"grid"` config entry and
these calls, matching every other full-CRUD sibling.

`list()` pagination fix (found during the Statuses/Priorities/Types
migration's broader "N individual exceptions" audit, OPM-1627): this method
previously had no `offset`/`limit` params and never clamped or paginated at
all -- an unbounded fetch-all, unlike every other full-list migrated
sibling. Confirmed via git history this is a faithfully-ported pre-existing
gap from client.py's very first `list_grids` implementation (pre-dating this
domain's own migration), not a regression this migration introduced.
`GridListResult` moved from a bare `CollectionResult` to the standard
`PageResult` shape to match (see `app/ports/grid_api.py`'s module docstring
for the same note from the Port side).

Deliberate behavior CHANGE from client.py's original delete_grid (found via
an external Codex review of the unpushed Grids migration commit, before this
was pushed): the confirmed branch now returns `result=grid` (the deleted
grid's stamped summary), not `result=None`. The original client.py's
`delete_grid` returned `None` there -- but that was itself an outlier, not a
deliberate design choice: `delete_version`/`delete_membership`/
`delete_project` all returned the deleted entity's detail/summary on
confirmed delete since their very first (pre-app/-migration) implementation,
and `GridWriteResult.result: GridSummary | None` has always had the same
shape as those siblings' result fields. Traced back through git history to
Grids' very first commit -- `result=None` was present from day one, with no
commit message or code comment ever explaining why Grids alone should
differ. Kept the more-consistent, now-migrated behavior rather than
reverting to match the likely-accidental legacy quirk; noted here, in the
migration's commit message, and in CHANGELOG.md as a behavior-changing fix,
not a silent one.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import GridListResult, GridSummary, GridWriteResult
from ..pagination import clamp_limit, paginate_client
from ..policies import access, hidden_fields
from ..policies.grid_policy import (
    ensure_grid_read_allowed,
    ensure_grid_write_allowed,
    grid_read_allowed,
    grid_scope_href,
)
from ..ports.grid_api import GridApi
from ._write_outcome import _finalize_write, _WriteOutcome


class GridService:
    def __init__(
        self,
        *,
        api: GridApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("grid", value, settings=self._settings)

    async def list(self, *, scope: str | None = None, offset: int = 1, limit: int | None = None) -> GridListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        records = await self._api.list_all(scope_filter=scope, page_size=self._settings.max_results)
        results = [
            self._stamp(record.summary)
            for record in records
            if grid_read_allowed(
                record.scope_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        ]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=results)
        return GridListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, grid_id: int) -> GridSummary:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(grid_id)
        ensure_grid_read_allowed(
            record.scope_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.summary)

    async def create(
        self,
        *,
        name: str,
        scope: str,
        row_count: int | None = None,
        column_count: int | None = None,
        confirm: bool = False,
    ) -> GridWriteResult:
        ensure_grid_write_allowed(
            scope, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        hidden_fields.ensure_field_writable("grid", "name", settings=self._settings)
        hidden_fields.ensure_field_writable("grid", "scope", settings=self._settings)
        payload: dict[str, Any] = {"name": name, "_links": {"scope": {"href": scope}}}
        if row_count is not None:
            hidden_fields.ensure_field_writable("grid", "row_count", settings=self._settings)
            payload["rowCount"] = row_count
        if column_count is not None:
            hidden_fields.ensure_field_writable("grid", "column_count", settings=self._settings)
            payload["columnCount"] = column_count
        form = await self._api.create_form(payload)
        identity_scope = form.payload.get("_links", {}).get("scope", {}).get("href")
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"grid_id": None, "scope": identity_scope},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda summary: {"grid_id": summary.id, "scope": summary.scope},
            rejected_message="OpenProject rejected the proposed grid changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the grid. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Grid created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        grid_id: int,
        name: str | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
        confirm: bool = False,
    ) -> GridWriteResult:
        current = await self._api.get(grid_id)
        current_scope_href = grid_scope_href(current.scope_link)
        ensure_grid_write_allowed(
            current_scope_href, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        payload: dict[str, Any] = {}
        if name is not None:
            hidden_fields.ensure_field_writable("grid", "name", settings=self._settings)
            payload["name"] = name
        if row_count is not None:
            hidden_fields.ensure_field_writable("grid", "row_count", settings=self._settings)
            payload["rowCount"] = row_count
        if column_count is not None:
            hidden_fields.ensure_field_writable("grid", "column_count", settings=self._settings)
            payload["columnCount"] = column_count
        form = await self._api.update_form(grid_id, payload)
        identity_scope = form.payload.get("_links", {}).get("scope", {}).get("href") or current_scope_href
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"grid_id": grid_id, "scope": identity_scope},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=lambda p: self._api.commit_update(grid_id, p),
            committed_identity=lambda summary: {"grid_id": summary.id, "scope": summary.scope},
            rejected_message="OpenProject rejected the proposed grid changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the grid update. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Grid updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, grid_id: int, confirm: bool = False) -> GridWriteResult:
        current = await self._api.get(grid_id)
        current_scope_href = grid_scope_href(current.scope_link)
        ensure_grid_write_allowed(
            current_scope_href, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        grid = self._stamp(current.summary)
        payload = {"id": grid.id}

        if not confirm:
            return GridWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the grid. Ask for confirmation, then call again with confirm=true to delete it.",
                grid_id=grid.id,
                scope=grid.scope,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("project", settings=self._settings)
        await self._api.delete(grid_id)
        return GridWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Grid deleted successfully.",
            grid_id=grid.id,
            scope=grid.scope,
            payload=payload,
            validation_errors={},
            result=grid,
        )

    def _to_write_result(self, action: str, outcome: _WriteOutcome[GridSummary]) -> GridWriteResult:
        return GridWriteResult(
            action=action,
            confirmed=outcome.confirmed,
            requires_confirmation=outcome.requires_confirmation,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail) if outcome.detail else None,
            **outcome.identity,
        )
