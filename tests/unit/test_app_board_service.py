from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.board_api import BoardFormResult, BoardRecord
from openproject_ce_mcp.app.services.board_service import BoardService
from openproject_ce_mcp.models import BoardDetail, BoardSummary

BASE_URL = "https://op.example.com"


def _summary(
    board_id: int = 1,
    *,
    project_id: int | None = 6,
    project: str | None = "Demo",
    name: str = "Sprint Board",
) -> BoardSummary:
    return BoardSummary(
        id=board_id,
        name=name,
        project_id=project_id,
        project=project,
        public=True,
        hidden=False,
        starred=False,
        include_subprojects=False,
        show_hierarchies=False,
        timeline_visible=False,
        filter_count=0,
        can_update=True,
        can_delete=True,
        url=f"{BASE_URL}/work_packages?query_id={board_id}",
    )


def _detail(**kwargs: object) -> BoardDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return BoardDetail(
        id=summary.id,
        name=summary.name,
        project_id=summary.project_id,
        project=summary.project,
        public=summary.public,
        hidden=summary.hidden,
        starred=summary.starred,
        include_subprojects=summary.include_subprojects,
        show_hierarchies=summary.show_hierarchies,
        timeline_visible=summary.timeline_visible,
        timeline_zoom_level=None,
        highlighting_mode=None,
        group_by=None,
        columns=[],
        sort_by=[],
        highlighted_attributes=[],
        timestamps=[],
        filters=[],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        url=summary.url,
    )


def _record(*, project_link: dict | None = None, **kwargs: object) -> BoardRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    if project_link is None and summary.project_id is not None:
        project_link = {"href": f"/api/v3/projects/{summary.project_id}", "title": summary.project}
    return BoardRecord(summary=summary, detail=detail, project_link=project_link)


class _FakeBoardApi:
    def __init__(self, records: list[BoardRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[int] = []
        self.list_page_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []
        self.create_form_calls: list[dict] = []
        self.update_form_calls: list[tuple[int, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.validation_errors: dict[str, str] = {}
        self.commit_result_project_id: int | None = 6
        self.commit_result_project: str | None = "Demo"

    async def list_all(self, *, page_size: int) -> list[BoardRecord]:
        self.list_all_calls.append(page_size)
        return list(self._records.values())

    async def list_page(self, *, offset: int, limit: int) -> tuple[list[BoardRecord], int]:
        self.list_page_calls.append((offset, limit))
        records = list(self._records.values())
        return records, len(records)

    async def get(self, board_id: int) -> BoardRecord:
        self.get_calls.append(board_id)
        if board_id not in self._records:
            raise AssertionError(f"no fake record for board_id {board_id}")
        return self._records[board_id]

    async def create_form(self, payload: dict) -> BoardFormResult:
        self.create_form_calls.append(payload)
        merged = {
            **payload,
            "_links": {
                **payload.get("_links", {}),
                "project": {"href": f"/api/v3/projects/{self.commit_result_project_id}"}
                | ({"title": self.commit_result_project} if self.commit_result_project else {}),
            },
        }
        return BoardFormResult(payload=merged, validation_errors=self.validation_errors)

    async def update_form(self, board_id: int, payload: dict) -> BoardFormResult:
        self.update_form_calls.append((board_id, payload))
        return BoardFormResult(payload=payload, validation_errors=self.validation_errors)

    async def commit_create(self, payload: dict) -> BoardDetail:
        self.commit_create_calls.append(payload)
        return _detail(board_id=42, project_id=self.commit_result_project_id, project=self.commit_result_project)

    async def commit_update(self, board_id: int, payload: dict) -> BoardDetail:
        self.commit_update_calls.append((board_id, payload))
        return _detail(board_id=board_id, project_id=self.commit_result_project_id, project=self.commit_result_project)

    async def delete(self, board_id: int) -> None:
        self.delete_calls.append(board_id)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo", "_links": {}}


def _service(
    api: _FakeBoardApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> BoardService:
    api = api or _FakeBoardApi()
    return BoardService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        resolve_project_ref=resolve_project_ref,
        api_prefix="/api/v3/",
        origin="https://op.example.com",
    )


# --- list() -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_uses_server_side_path_when_scope_allows_all_and_no_filter() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert api.list_page_calls == [(1, 20)]
    assert api.list_all_calls == []


@pytest.mark.asyncio
async def test_list_uses_client_side_path_when_project_filter_given() -> None:
    api = _FakeBoardApi(
        records=[
            _record(board_id=1, project_id=6, project="Demo"),
            _record(board_id=2, project_id=7, project="Other"),
        ]
    )
    service = _service(api)

    result = await service.list(project="demo")

    assert [item.id for item in result.results] == [1]
    assert api.list_all_calls == [100]
    assert api.list_page_calls == []


@pytest.mark.asyncio
async def test_list_filters_by_search_term_in_name() -> None:
    api = _FakeBoardApi(records=[_record(board_id=1, name="Sprint Board"), _record(board_id=2, name="Unrelated")])
    service = _service(api)

    result = await service.list(search="sprint")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_returns_empty_under_empty_read_projects() -> None:
    # Regression: use_client_side_filtering must not be gated on
    # bool(allowed_projects) -- an empty read_projects tuple must still
    # filter client-side down to zero results, not skip filtering entirely.
    settings = dataclasses.replace(make_settings(), read_projects=())
    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="Demo")])
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.count == 0
    assert api.list_all_calls == [100]


@pytest.mark.asyncio
async def test_list_passes_write_false_to_resolve_project_ref() -> None:
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeBoardApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list(project="demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_excludes_boards_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_board_read=False)
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list()

    assert api.list_all_calls == []
    assert api.list_page_calls == []


# --- get() --------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"board": ("group_by",)})
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"group_by"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_name_hidden_by_board_scope_not_project_scope() -> None:
    """Regression test for the entity="board" vs "project" hide-field bug
    class (same bug class hit by prior domains' hotfixes)."""
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("name",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_board_hidden = dataclasses.replace(make_settings(), hidden_fields={"board": ("name",)})
    service_board_hidden = _service(settings=settings_board_hidden)
    result_board_hidden = await service_board_hidden.get(1)
    assert getattr(result_board_hidden, "_hidden_keys", frozenset()) == {"name"}


@pytest.mark.asyncio
async def test_get_denies_a_board_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_board_read=False)
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


# --- create() -------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.create(name="My Board", project="demo", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"board": ("public",)})
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Board", project="demo", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"public"}


@pytest.mark.asyncio
async def test_create_commit_result_is_a_board_detail_not_a_board_summary() -> None:
    # Regression: BoardWriteResult.result is typed BoardDetail (models.py),
    # but BoardApi.commit_create/commit_update once returned BoardSummary --
    # a plain isinstance would still "work" via duck typing in Python, but a
    # BoardSummary is missing every BoardDetail-only field (group_by,
    # columns, sort_by, highlighted_attributes, filters, timestamps,
    # timeline_zoom_level, highlighting_mode), so any consumer serializing
    # the confirmed result (e.g. the MCP structured-output layer) against
    # the BoardDetail schema would fail. Assert a detail-only field is
    # actually present and correctly typed, not just that .result is truthy.
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.create(name="My Board", project="demo", confirm=True)

    assert isinstance(result.result, BoardDetail)
    assert hasattr(result.result, "group_by")
    assert hasattr(result.result, "columns")


@pytest.mark.asyncio
async def test_create_resolves_project_with_write_true() -> None:
    # create() authorizes the project via one write=True resolve_project_ref
    # call up front, then _build_write_payload separately resolves the
    # project id (write=False) to build the "_links.project" href -- two
    # calls total, verbatim behavior of client.py's original create_board
    # (_get_project_payload(project, write=True) then _resolve_project_id
    # via _project_resolver.resolve_id(..., write=False)).
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeBoardApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.create(name="My Board", project="demo", confirm=False)

    assert calls == [True, False]


@pytest.mark.asyncio
async def test_create_global_board_requires_fully_open_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), write_projects=("*",))
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS|OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="Global Board", project=None, confirm=False)

    assert api.create_form_calls == []


@pytest.mark.asyncio
async def test_create_global_board_denied_when_only_read_is_fully_open() -> None:
    # The mirror case of test_create_global_board_requires_fully_open_scope:
    # read_projects="*" alone is also not sufficient -- both scopes must be
    # fully open, checked as a single `and`, so either side being restrictive
    # denies identically.
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS|OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="Global Board", project=None, confirm=False)

    assert api.create_form_calls == []


@pytest.mark.asyncio
async def test_create_global_board_allowed_when_both_scopes_fully_open() -> None:
    api = _FakeBoardApi()
    service = _service(api)  # make_settings() defaults to read_projects=write_projects=("*",)

    result = await service.create(name="Global Board", project=None, confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_create_project_bound_board_unaffected_by_global_board_rule() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), write_projects=("demo",))
    api = _FakeBoardApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Board", project="demo", confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_create_sets_show_hierarchies_false_when_group_by_given_without_explicit_value() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    await service.create(name="My Board", project="demo", group_by="status", confirm=False)

    assert api.create_form_calls[0]["showHierarchies"] is False


@pytest.mark.asyncio
async def test_create_respects_explicit_show_hierarchies_even_with_group_by() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    await service.create(name="My Board", project="demo", group_by="status", show_hierarchies=True, confirm=False)

    assert api.create_form_calls[0]["showHierarchies"] is True


@pytest.mark.asyncio
async def test_create_omits_links_key_when_no_link_fields_given() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    await service.create(name="My Board", project=None, public=True, confirm=False)

    assert "_links" not in api.create_form_calls[0]


# --- update() ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.update(board_id=1, name="Renamed", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_sets_show_hierarchies_false_when_group_by_given_without_explicit_value() -> None:
    # _build_write_payload is shared logic between create() and update() --
    # the create()-only pin above doesn't transitively prove update()'s own
    # call site passes through correctly, so this is asserted directly here too.
    api = _FakeBoardApi()
    service = _service(api)

    await service.update(board_id=1, group_by="status", confirm=False)

    assert api.update_form_calls[0][1]["showHierarchies"] is False


@pytest.mark.asyncio
async def test_update_respects_explicit_show_hierarchies_even_with_group_by() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    await service.update(board_id=1, group_by="status", show_hierarchies=True, confirm=False)

    assert api.update_form_calls[0][1]["showHierarchies"] is True


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.update(board_id=1, name="Renamed", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_update_calls) == 1
    committed_board_id, committed_payload = api.commit_update_calls[0]
    assert committed_board_id == 1
    assert committed_payload["name"] == "Renamed"


@pytest.mark.asyncio
async def test_update_denies_a_board_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="Demo")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(board_id=1, name="Renamed", confirm=False)

    assert api.update_form_calls == []


@pytest.mark.asyncio
async def test_update_denies_reparenting_into_a_project_outside_write_allowlist() -> None:
    # Regression: the CURRENT board's project (A, writable) passing
    # ensure_board_write_allowed must NOT be sufficient authorization for a
    # reparent target (B, not writable) -- _build_write_payload's own
    # resolve_project_ref(project, write=False) call only resolves B's id
    # for the outgoing href, it never authorizes writing INTO B. Without an
    # explicit write=True check on the target, update(project="B") would
    # silently move the board out of the caller's write-allowlist.
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    calls: list[tuple[str, bool]] = []

    async def resolve_project_ref_by_name(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append((project_ref, write))
        from openproject_ce_mcp.app.policies import scope as scope_policy_module

        project_id = 6 if project_ref == "demo" else 7
        payload = {"id": project_id, "identifier": project_ref, "name": project_ref.title()}
        if write:
            scope_policy_module.ensure_project_write_link_allowed(
                {"href": f"/api/v3/projects/{project_id}", "identifier": project_ref},
                settings=settings,
                project_id_to_identifier={6: "demo", 7: "other"},
            )
        return payload

    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="demo")])
    service = _service(api, settings=settings, resolve_project_ref=resolve_project_ref_by_name)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(board_id=1, project="other", confirm=False)

    assert api.update_form_calls == []


@pytest.mark.asyncio
async def test_update_and_delete_raise_the_same_error_when_both_scopes_restrictive() -> None:
    """Pins the NET behavior of update()'s write-then-read vs. delete()'s
    read-then-write call ordering when both scopes are restrictive at once
    -- the one setup that can distinguish the two orderings from each other,
    since a single-restricted-scope test can't (either ordering raises the
    same single error either way).

    Both currently raise a READ_PROJECTS error, not because either Service
    method literally checks read first, but because
    `scope.ensure_project_write_link_allowed` (the function BOTH
    `board_policy.ensure_board_write_allowed` calls) performs its own
    internal read-check before its write-check (see `scope.py`). So
    update()'s call to the write-gate raises READ_PROJECTS from *inside*
    that gate, before update()'s own separate read-gate call is ever
    reached -- net-equivalent to delete()'s literal read-then-write Service-
    level ordering. This test would catch a regression where one of the two
    methods' write-gate call stopped performing its internal read pre-check
    (e.g. a future refactor swapping in a write-only primitive), even though
    it can't distinguish the current (functionally moot) Service-level call
    order.
    """
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="Demo")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS") as update_exc:
        await service.update(board_id=1, name="Renamed", confirm=False)
    assert api.update_form_calls == []

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS") as delete_exc:
        await service.delete(board_id=1, confirm=False)
    assert api.delete_calls == []

    assert str(update_exc.value) == str(delete_exc.value)


# --- delete() ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.delete(board_id=1, confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeBoardApi()
    service = _service(api)

    result = await service.delete(board_id=1, confirm=True)

    assert result.confirmed is True
    assert api.delete_calls == [1]
    assert result.result is not None


@pytest.mark.asyncio
async def test_delete_denies_a_board_outside_read_allowlist() -> None:
    """delete() checks read-then-write (opposite order from update()) --
    verified against client.py's original delete_board. A read-scope
    denial must surface even before the write check runs."""
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("*",))
    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="Demo")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.delete(board_id=1, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_a_board_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeBoardApi(records=[_record(board_id=1, project_id=6, project="Demo")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(board_id=1, confirm=False)

    assert api.delete_calls == []
