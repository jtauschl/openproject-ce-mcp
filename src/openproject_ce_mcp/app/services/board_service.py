"""Application Service for the Boards domain (ADR 0001).

Depends on the BoardApi Protocol, never HttpxBoardApi concretely (enforced by
the architecture-boundary test). No dedicated BoardResolver: a `board_id` is
always a numeric value already validated by tools.py.

Boards have their own dedicated OPENPROJECT_ENABLE_BOARD_READ/_WRITE flags
(unlike Views/Grids/Categories, which share the generic "project" scope) --
`access.ensure_read_enabled`/`ensure_write_enabled` are called with
scope="board" throughout, verbatim behavior of client.py's original
`_ensure_read_enabled("board")`/write-category flag mapping.

List filtering follows Views'/Documents'/News' shape (ProjectRefResolver +
project_scoped_list.py), not Grids' raw-scope-string shape: client.py's
`project: str | None` parameter on `list_boards`/`create_board` is a genuine
project reference needing resolution against a real project payload, unlike
Grids' `scope` (an arbitrary href/path passed straight through).

Client-side vs. server-side list branching is verbatim-ported from
client.py's `list_boards`: the server-paginated path is reachable only when
`project is None`, no `search`, and `read_projects` is fully open ("*") --
NOT simply "no allowed_projects filter needed"; an empty `read_projects`
tuple must still filter client-side down to zero results (regression pinned
by `test_list_boards_returns_empty_under_empty_read_projects`).

Write-allowlist ordering, verified against client.py's original: `update()`
calls `ensure_board_write_allowed` before `board_policy.ensure_board_read_allowed`;
`delete()` calls them in the OPPOSITE order -- both call orderings preserved
exactly as found in client.py, not unified, since the original is
inconsistent between the two methods and this migration's contract is
behavior-preservation, not cleanup. NOTE: net-observable behavior is
IDENTICAL either way under a doubly-restrictive scope --
`ensure_board_write_allowed` (= `scope.ensure_project_write_link_allowed`)
performs its own internal read-check before its write-check, so calling it
first (as `update()` does) still surfaces a READ_PROJECTS error before
`update()`'s own separate read-gate call is ever reached, same as `delete()`'s
literal read-then-write ordering. Pinned by
`test_update_and_delete_raise_the_same_error_when_both_scopes_restrictive`.

The "global board" rule (an unscoped board write requires BOTH
read_projects and write_projects fully open) has no per-link allowlist
check to delegate to -- there is no link at all for an unscoped board -- so
it is verbatim-ported directly into `create()`, not part of board_policy.py.

`_write_outcome.py`'s `_finalize_write` is used for create()/update() (2
write actions sharing the identical form-based preview/commit shape, the
same "2+ actions" threshold Grids/Memberships hit). delete() has no form
step at all, so it stays an inline preview/commit method like
GridService.delete()/MembershipService.delete().
"""

from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import urlparse

from ...config import Settings
from ...models import BoardDetail, BoardListResult, BoardWriteResult
from ..api_href import api_href as _api_href
from ..errors import InvalidInputError, PermissionDeniedError
from ..origin import origin_from_url as _origin_from_url
from ..pagination import clamp_limit, paginate_client, paginate_server
from ..policies import access, board_policy, hidden_fields
from ..policies import scope as scope_policy
from ..ports.board_api import BoardApi
from ..ports.project_ref import ProjectRefResolver
from ._write_outcome import _finalize_write, _WriteOutcome
from .project_scoped_list import resolve_project_filter_candidates, summary_matches_project_candidates


class BoardService:
    def __init__(
        self,
        *,
        api: BoardApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
        api_prefix: str,
        origin: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._api_prefix = api_prefix
        self._origin = origin

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("board", value, settings=self._settings)

    def _resolve_query_reference_href(self, reference: str, *, kind: str) -> str:
        normalized = str(reference).strip()
        if not normalized:
            raise InvalidInputError(f"{kind.replace('_', ' ')} values must not be empty.")

        if normalized.startswith("http://") or normalized.startswith("https://"):
            parsed = urlparse(normalized)
            if _origin_from_url(normalized) != self._origin:
                raise InvalidInputError(
                    f"OpenProject {kind.replace('_', ' ')} references must stay on the same origin."
                )
            return parsed.path

        if normalized.startswith("/"):
            return normalized

        if kind == "sort_by":
            return _api_href(f"queries/sort_bys/{normalized}", api_prefix=self._api_prefix)
        if kind == "group_by":
            return _api_href(f"queries/group_bys/{normalized}", api_prefix=self._api_prefix)
        return _api_href(f"queries/columns/{normalized}", api_prefix=self._api_prefix)

    async def list(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> BoardListResult:
        access.ensure_read_enabled("board", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        use_client_side_filtering = (
            project is not None or bool(search) or not scope_policy.scope_allows_all(self._settings.read_projects)
        )

        if use_client_side_filtering:
            project_candidates = await resolve_project_filter_candidates(
                project, resolve_project_ref=self._resolve_project_ref
            )
            records = await self._api.list_all(page_size=self._settings.max_results)
            results = [
                self._stamp(record.summary)
                for record in records
                if board_policy.board_read_allowed(
                    record.project_link,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                )
            ]
            if project_candidates is not None:
                results = [item for item in results if summary_matches_project_candidates(item, project_candidates)]
            if search:
                search_key = search.casefold()
                results = [item for item in results if search_key in (item.name or "").casefold()]

            page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=results)
            return BoardListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(page),
                next_offset=next_offset,
                truncated=truncated,
                results=page,
            )

        records, total = await self._api.list_page(offset=offset, limit=effective_limit)
        results = [self._stamp(record.summary) for record in records]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return BoardListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get(self, board_id: int) -> BoardDetail:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get(board_id)
        board_policy.ensure_board_read_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.detail)

    async def create(
        self,
        *,
        name: str,
        project: str | None = None,
        public: bool | None = None,
        starred: bool | None = None,
        hidden: bool | None = None,
        include_subprojects: bool | None = None,
        show_hierarchies: bool | None = None,
        timeline_visible: bool | None = None,
        group_by: str | None = None,
        columns: builtins.list[str] | None = None,
        sort_by: builtins.list[str] | None = None,
        highlighted_attributes: builtins.list[str] | None = None,
        filters: builtins.list[dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> BoardWriteResult:
        if project is not None:
            await self._resolve_project_ref(project, write=True)
        elif not (
            scope_policy.scope_allows_all(self._settings.read_projects)
            and scope_policy.scope_allows_all(self._settings.write_projects)
        ):
            raise PermissionDeniedError(
                "Project-scoped board writes require a project unless both OPENPROJECT_READ_PROJECTS and "
                "OPENPROJECT_WRITE_PROJECTS are '*'."
            )

        payload = await self._build_write_payload(
            name=name,
            project=project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=group_by,
            columns=columns,
            sort_by=sort_by,
            highlighted_attributes=highlighted_attributes,
            filters=filters,
        )
        form = await self._api.create_form(payload)
        identity_project = form.payload.get("_links", {}).get("project", {}).get("title")
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"board_id": None, "project": identity_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("board", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda summary: {"board_id": summary.id, "project": summary.project},
            rejected_message="OpenProject rejected the proposed board changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the board. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Board created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        board_id: int,
        name: str | None = None,
        project: str | None = None,
        public: bool | None = None,
        starred: bool | None = None,
        hidden: bool | None = None,
        include_subprojects: bool | None = None,
        show_hierarchies: bool | None = None,
        timeline_visible: bool | None = None,
        group_by: str | None = None,
        columns: builtins.list[str] | None = None,
        sort_by: builtins.list[str] | None = None,
        highlighted_attributes: builtins.list[str] | None = None,
        filters: builtins.list[dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> BoardWriteResult:
        current = await self._api.get(board_id)
        board_policy.ensure_board_write_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        board_policy.ensure_board_read_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        if project is not None:
            # A project re-parent target is a DIFFERENT project from the one
            # current.project_link was just checked against above -- that
            # check alone would let a caller move a board into a project
            # outside OPENPROJECT_WRITE_PROJECTS, since _build_write_payload's
            # own resolve_project_ref call below only resolves the target
            # (write=False, for href-building), it never authorizes it.
            await self._resolve_project_ref(project, write=True)
        payload = await self._build_write_payload(
            name=name,
            project=project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=group_by,
            columns=columns,
            sort_by=sort_by,
            highlighted_attributes=highlighted_attributes,
            filters=filters,
        )
        form = await self._api.update_form(board_id, payload)
        identity_project = form.payload.get("_links", {}).get("project", {}).get("title") or current.summary.project
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"board_id": board_id, "project": identity_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("board", settings=self._settings),
            commit=lambda p: self._api.commit_update(board_id, p),
            committed_identity=lambda summary: {"board_id": summary.id, "project": summary.project},
            rejected_message="OpenProject rejected the proposed board changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the board update. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Board updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, board_id: int, confirm: bool = False) -> BoardWriteResult:
        current = await self._api.get(board_id)
        board_policy.ensure_board_read_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        board_policy.ensure_board_write_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        board = self._stamp(current.detail)
        payload = {"id": board.id, "name": board.name}

        if not confirm:
            return BoardWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the board. Ask for confirmation, then call again with confirm=true to delete it.",
                board_id=board.id,
                project=board.project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("board", settings=self._settings)
        await self._api.delete(board_id)
        return BoardWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Board deleted successfully.",
            board_id=board.id,
            project=board.project,
            payload=payload,
            validation_errors={},
            result=board,
        )

    async def _build_write_payload(
        self,
        *,
        name: str | None,
        project: str | None,
        public: bool | None,
        starred: bool | None,
        hidden: bool | None,
        include_subprojects: bool | None,
        show_hierarchies: bool | None,
        timeline_visible: bool | None,
        group_by: str | None,
        columns: builtins.list[str] | None,
        sort_by: builtins.list[str] | None,
        highlighted_attributes: builtins.list[str] | None,
        filters: builtins.list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if name is not None:
            hidden_fields.ensure_field_writable("board", "name", settings=self._settings)
            payload["name"] = name
        if public is not None:
            hidden_fields.ensure_field_writable("board", "public", settings=self._settings)
            payload["public"] = public
        if starred is not None:
            hidden_fields.ensure_field_writable("board", "starred", settings=self._settings)
            payload["starred"] = starred
        if hidden is not None:
            hidden_fields.ensure_field_writable("board", "hidden", settings=self._settings)
            payload["hidden"] = hidden
        if include_subprojects is not None:
            hidden_fields.ensure_field_writable("board", "include_subprojects", settings=self._settings)
            payload["includeSubprojects"] = include_subprojects

        effective_show_hierarchies = show_hierarchies
        if group_by is not None and show_hierarchies is None:
            effective_show_hierarchies = False
        if effective_show_hierarchies is not None:
            hidden_fields.ensure_field_writable("board", "show_hierarchies", settings=self._settings)
            payload["showHierarchies"] = effective_show_hierarchies

        if timeline_visible is not None:
            hidden_fields.ensure_field_writable("board", "timeline_visible", settings=self._settings)
            payload["timelineVisible"] = timeline_visible
        if filters is not None:
            hidden_fields.ensure_field_writable("board", "filters", settings=self._settings)
            payload["filters"] = filters

        if project is not None:
            hidden_fields.ensure_field_writable("board", "project", settings=self._settings)
            project_payload = await self._resolve_project_ref(project, write=False)
            links["project"] = {"href": _api_href(f"projects/{project_payload['id']}", api_prefix=self._api_prefix)}
        if group_by is not None:
            hidden_fields.ensure_field_writable("board", "group_by", settings=self._settings)
            links["groupBy"] = {"href": self._resolve_query_reference_href(group_by, kind="group_by")}
        if columns is not None:
            hidden_fields.ensure_field_writable("board", "columns", settings=self._settings)
            links["columns"] = [{"href": self._resolve_query_reference_href(item, kind="column")} for item in columns]
        if sort_by is not None:
            hidden_fields.ensure_field_writable("board", "sort_by", settings=self._settings)
            links["sortBy"] = [{"href": self._resolve_query_reference_href(item, kind="sort_by")} for item in sort_by]
        if highlighted_attributes is not None:
            hidden_fields.ensure_field_writable("board", "highlighted_attributes", settings=self._settings)
            links["highlightedAttributes"] = [
                {"href": self._resolve_query_reference_href(item, kind="column")} for item in highlighted_attributes
            ]

        if links:
            payload["_links"] = links
        return payload

    def _to_write_result(self, action: str, outcome: _WriteOutcome[BoardDetail]) -> BoardWriteResult:
        return BoardWriteResult(
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
