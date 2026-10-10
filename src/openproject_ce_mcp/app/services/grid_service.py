"""Application Service for the Grids domain.

Depends on the GridApi Protocol, never HttpxGridApi concretely (enforced by
the architecture-boundary test). No dedicated GridResolver: a `grid_id` is
always a numeric value already validated by tools_grids.py.

A project scope is resolved through `ProjectLookupApi` only under a
restrictive allowlist, once per distinct reference per call: OpenProject maps
the identifier (or, from 17.3, a former identifier) to the project, and its
id, identifier and name are the allowlist candidates. Not found or forbidden
denies the grid; every other failure propagates.

Grids shares the "project" read/write scope with Projects/News/Documents/
Categories/Views -- no dedicated OPENPROJECT_ENABLE_GRID_* flag exists.

Write-allowlist ordering: the grid check (`_check`/`_check_record`, deciding
through grid_policy.ensure_grid_allowed) runs UNCONDITIONALLY at the top of
create()/update()/delete() (during preview AND confirm) -- it is not
confirm-gated. Only
access.ensure_write_enabled (inside _finalize_write's confirm branch) is
confirm-gated. This mirrors MembershipService's existing create()/update()
ordering exactly.

_write_outcome.py's _finalize_write is used for create()/update() (2 write
actions sharing the identical form-based preview/commit shape). delete() has
no form step at all, so it stays an inline preview/commit method like
MembershipService.delete().

`create()`/`update()` call `hidden_fields.ensure_field_writable("grid",
<field>, ...)` for every field they write ("name", "scope", "row_count",
"column_count"), matching every other full-CRUD sibling's write-guard
pattern; `config.py`'s `HIDE_FIELD_ENV_BY_ENTITY` carries a `"grid"` entry
(`OPENPROJECT_HIDE_GRID_FIELDS`) so `hidden_fields.field_hidden("grid", ...)`
can actually return True when configured.

`list()` clamps/paginates via `offset`/`limit` like every other full-list
migrated sibling -- an unbounded fetch-all would be unbounded work against
the server for large grid collections. `GridListResult` uses the standard
`PageResult` shape (see `app/ports/grid_api.py`'s module docstring for the
same note from the Port side).

On confirmed delete, `GridWriteResult.result` carries the deleted grid's
stamped summary, not `None` -- consistent with `delete_version`/
`delete_membership`/`delete_project`, which all return the deleted entity's
detail/summary on confirmed delete.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any

from ...config import Settings
from ...context_gather import gather_in_current_context
from ...models import GridListResult, GridSummary, GridWriteResult
from ..errors import InvalidInputError, NotFoundError, PermissionDeniedError
from ..pagination import clamp_limit, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies.grid_policy import (
    MyPageScope,
    ProjectScope,
    ResolvedProject,
    emitted_grid_scope,
    ensure_grid_allowed,
    needs_resolution,
    parse_grid_scope,
)
from ..policies.scope import PrefixMismatch
from ..ports.grid_api import GridApi, GridRecord
from ..ports.project_lookup_api import ProjectLookupApi
from ._write_outcome import _finalize_write, _WriteOutcome

# Bounds the project lookups one page of grids can start at once.
_CONCURRENT_SCOPE_LOOKUPS = 10

_Resolution = ResolvedProject | None | Exception


def _href(link: Any) -> Any:
    return link.get("href") if isinstance(link, dict) else None


class GridService:
    def __init__(
        self,
        *,
        api: GridApi,
        project_lookup: ProjectLookupApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
    ) -> None:
        self._api = api
        self._project_lookup = project_lookup
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    def _emitted_scope(self, scope_link: Any, *, write: bool) -> MyPageScope | ProjectScope:
        return emitted_grid_scope(_href(scope_link), write=write, settings=self._settings)

    async def _resolve(self, refs: Iterable[str], cache: dict[str, _Resolution]) -> None:
        slots = asyncio.Semaphore(_CONCURRENT_SCOPE_LOOKUPS)

        async def resolve_one(ref: str) -> None:
            async with slots:
                try:
                    record = await self._project_lookup.get(ref)
                except (NotFoundError, PermissionDeniedError):
                    cache[ref] = None
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 -- a deferred outcome, raised only where it is reached
                    cache[ref] = exc
                    return
            summary = record.summary
            cache[ref] = ResolvedProject(summary.id, summary.identifier or ref, summary.name)

        await gather_in_current_context(*(resolve_one(ref) for ref in dict.fromkeys(refs) if ref not in cache))

    def _authorize(
        self, scope: MyPageScope | ProjectScope, project_link: Any, *, write: bool, cache: dict[str, _Resolution]
    ) -> None:
        resolved = cache.get(scope.ref) if isinstance(scope, ProjectScope) else None
        if isinstance(resolved, Exception):
            raise resolved
        ensure_grid_allowed(
            scope,
            project_link=project_link,
            resolved=resolved,
            write=write,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

    def _read_outcome(self, record: GridRecord, cache: dict[str, _Resolution]) -> bool | Exception:
        """One grid's outcome in a page-batched list: a permission denial
        filters it out, any other failure is kept for the scan to raise only
        if it reaches that grid."""
        try:
            self._authorize(
                self._emitted_scope(record.scope_link, write=False), record.project_link, write=False, cache=cache
            )
        except PermissionDeniedError:
            return False
        except Exception as exc:  # noqa: BLE001 -- see docstring
            return exc
        return True

    async def _check(
        self, scope: MyPageScope | ProjectScope, project_link: Any, *, write: bool, cache: dict[str, _Resolution]
    ) -> None:
        if isinstance(scope, ProjectScope) and needs_resolution(write=write, settings=self._settings):
            await self._resolve([scope.ref], cache)
        self._authorize(scope, project_link, write=write, cache=cache)

    async def _check_record(self, record: GridRecord, *, write: bool) -> None:
        await self._check(
            self._emitted_scope(record.scope_link, write=write), record.project_link, write=write, cache={}
        )

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

        cache: dict[str, _Resolution] = {}
        resolve = needs_resolution(write=False, settings=self._settings)

        async def _page_allowed(records: list[GridRecord]) -> list[bool | Exception]:
            if resolve:
                scopes = (parse_grid_scope(_href(record.scope_link), settings=self._settings) for record in records)
                await self._resolve([scope.ref for scope in scopes if isinstance(scope, ProjectScope)], cache)
            return [self._read_outcome(record, cache) for record in records]

        # Scan server pages rather than a single fetch capped at
        # settings.max_results, which would silently hide any grid beyond
        # that server-side cap.
        raw_items, truncated = await scan_records_and_paginate(
            lambda o, ps: self._api.list_page(offset=o, page_size=ps, scope_filter=scope),
            item_allowed_bulk=_page_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective_limit,
            key=lambda r: r.summary.id,
        )
        results = [self._stamp(record.summary) for record in raw_items]
        total = len(results)
        return GridListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=offset + 1 if truncated else None,
            truncated=truncated,
            results=results,
        )

    async def get(self, grid_id: int) -> GridSummary:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(grid_id)
        await self._check_record(record, write=False)
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
        requested_scope = parse_grid_scope(scope, settings=self._settings)
        if requested_scope is None or isinstance(requested_scope, PrefixMismatch):
            raise InvalidInputError(
                "OpenProject grid scope must be /my/page, /projects/<identifier> or /projects/<identifier>/boards "
                "(after the instance's root path, if any)."
            )
        cache: dict[str, _Resolution] = {}
        await self._check(requested_scope, None, write=True, cache=cache)
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
        form_links = form.payload.get("_links", {})
        if not form.validation_errors:
            # The form renders scope and project from the project OpenProject
            # resolved, which is what the commit writes to.
            await self._check(
                self._emitted_scope(form_links.get("scope"), write=True),
                form_links.get("project"),
                write=True,
                cache=cache,
            )
        identity_scope = form_links.get("scope", {}).get("href")
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
        await self._check_record(current, write=True)
        current_scope_href = _href(current.scope_link)
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
        await self._check_record(current, write=True)
        grid = self._stamp(current.summary)
        payload = {"id": grid.id}

        async def _commit(p: dict[str, Any]) -> GridSummary:
            await self._api.delete(grid_id)
            return grid

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"grid_id": grid.id, "scope": grid.scope},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"grid_id": d.id, "scope": d.scope},
            rejected_message="",
            preview_message="OpenProject found the grid. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Grid deleted successfully.",
        )
        return self._to_write_result("delete", outcome)

    def _to_write_result(self, action: str, outcome: _WriteOutcome[GridSummary]) -> GridWriteResult:
        return GridWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail) if outcome.detail else None,
            **outcome.identity,
        )
