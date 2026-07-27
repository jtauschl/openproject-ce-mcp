from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.grid_api import GridFormResult, GridRecord
from openproject_ce_mcp.app.services.grid_service import GridService
from openproject_ce_mcp.models import GridSummary
from openproject_ce_mcp.tools import _to_payload

BASE_URL = "https://op.example.com"


def _summary(
    grid_id: int = 1,
    *,
    scope: str | None = "/projects/6",
    row_count: int | None = 4,
    column_count: int | None = 6,
) -> GridSummary:
    return GridSummary(
        id=grid_id,
        row_count=row_count,
        column_count=column_count,
        scope=scope,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        url=f"/api/v3/grids/{grid_id}",
    )


def _record(*, scope_link: dict | None = None, **kwargs: object) -> GridRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    if scope_link is None and summary.scope is not None:
        scope_link = {"href": summary.scope}
    return GridRecord(summary=summary, scope_link=scope_link)


class _FakeGridApi:
    def __init__(self, records: list[GridRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[str | None] = []
        self.get_calls: list[int] = []
        self.create_form_calls: list[dict] = []
        self.update_form_calls: list[tuple[int, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.validation_errors: dict[str, str] = {}
        self.commit_result_scope: str | None = "/projects/6"

    async def list_all(self, *, scope_filter: str | None, page_size: int) -> list[GridRecord]:
        self.list_all_calls.append(scope_filter)
        return list(self._records.values())

    async def get(self, grid_id: int) -> GridRecord:
        self.get_calls.append(grid_id)
        if grid_id not in self._records:
            raise AssertionError(f"no fake record for grid_id {grid_id}")
        return self._records[grid_id]

    async def create_form(self, payload: dict) -> GridFormResult:
        self.create_form_calls.append(payload)
        return GridFormResult(payload=payload, validation_errors=self.validation_errors)

    async def update_form(self, grid_id: int, payload: dict) -> GridFormResult:
        self.update_form_calls.append((grid_id, payload))
        merged = {**payload, "_links": {"scope": {"href": self.commit_result_scope}}}
        return GridFormResult(payload=merged, validation_errors=self.validation_errors)

    async def commit_create(self, payload: dict) -> GridSummary:
        self.commit_create_calls.append(payload)
        return _summary(grid_id=42, scope=self.commit_result_scope)

    async def commit_update(self, grid_id: int, payload: dict) -> GridSummary:
        self.commit_update_calls.append((grid_id, payload))
        return _summary(grid_id=grid_id, scope=self.commit_result_scope)

    async def delete(self, grid_id: int) -> None:
        self.delete_calls.append(grid_id)


def _service(api: _FakeGridApi | None = None, *, settings=None) -> GridService:
    api = api or _FakeGridApi()
    return GridService(api=api, settings=settings or make_settings(), project_id_to_identifier={6: "demo"})


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert api.list_all_calls == [None]


@pytest.mark.asyncio
async def test_list_passes_scope_filter_through_to_the_api() -> None:
    api = _FakeGridApi()
    service = _service(api)

    await service.list(scope="/my/page")

    assert api.list_all_calls == ["/my/page"]


@pytest.mark.asyncio
async def test_list_excludes_project_scoped_grids_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_always_includes_my_page_grid_even_under_restrictive_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.list()

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list()

    assert api.list_all_calls == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    # normalize_grid previously never called _apply_hidden_fields at all, so
    # OPENPROJECT_HIDE_FIELDS for "grid" was a silent no-op pre-migration.
    # Re-anchored here at the Service layer -- this test's original version
    # lived in tests/unit/test_hidden_fields.py and called
    # client.normalize_grid directly, which no longer exists post-migration.
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("scope",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert result._hidden_keys == frozenset({"scope"})
    assert result.scope == "/projects/6"  # preserved on the dataclass
    serialized = _to_payload(result)
    assert "scope" not in serialized
    assert serialized["row_count"] == 4
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_row_count_hidden_by_grid_scope_not_project_scope() -> None:
    """Regression test for the entity="grid" vs "project" hide-field bug
    class (same bug class as OPM-266/OPM-306's News/Documents/TimeEntry
    findings)."""
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("row_count",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_grid_hidden = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    service_grid_hidden = _service(settings=settings_grid_hidden)
    result_grid_hidden = await service_grid_hidden.get(1)
    assert getattr(result_grid_hidden, "_hidden_keys", frozenset()) == {"row_count"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_allows_my_page_grid_under_restrictive_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert result.id == 1


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.create(name="My Grid", scope="/projects/6", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Grid", scope="/projects/6", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"row_count"}


@pytest.mark.asyncio
async def test_create_checks_write_allowlist_unconditionally_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="My Grid", scope="/projects/6", confirm=False)

    assert api.create_form_calls == []


@pytest.mark.asyncio
async def test_create_always_allows_my_page_scope_even_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Grid", scope="/my/page", confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_create_allows_missing_scope_when_both_read_and_write_wide_open() -> None:
    api = _FakeGridApi()
    service = _service(api)  # make_settings() defaults to read_projects=write_projects=("*",)

    result = await service.create(name="My Grid", scope="", confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_create_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("name",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="My Grid", scope="/projects/6", confirm=True)

    assert api.create_form_calls == []
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_scope_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("scope",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="My Grid", scope="/projects/6", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_row_count_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="My Grid", scope="/projects/6", row_count=4, confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_column_count_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("column_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="My Grid", scope="/projects/6", column_count=6, confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_does_not_check_row_count_or_column_count_when_not_provided() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count", "column_count")})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Grid", scope="/projects/6", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_create_calls) == 1


@pytest.mark.asyncio
async def test_update_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("name",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(grid_id=1, name="Renamed", confirm=True)

    assert api.update_form_calls == []
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_row_count_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(grid_id=1, row_count=8, confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_column_count_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("column_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(grid_id=1, column_count=8, confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_does_not_check_fields_the_caller_did_not_set() -> None:
    # A field hidden in config but NOT part of this update call must not
    # block it -- only fields actually present in the call are checked.
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.update(grid_id=1, name="Renamed", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_update_calls) == 1


@pytest.mark.asyncio
async def test_update_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.update(grid_id=1, name="Renamed", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.update(grid_id=1, name="Renamed", confirm=True)

    assert result.confirmed is True
    # commit_update is called with the FORM RESPONSE's payload (which the
    # fake echoes back with _links.scope merged in, simulating OpenProject's
    # /form endpoint returning the full resulting resource representation),
    # not the bare outgoing PATCH fields -- same shape _finalize_write uses
    # for every other domain's update().
    assert len(api.commit_update_calls) == 1
    committed_grid_id, committed_payload = api.commit_update_calls[0]
    assert committed_grid_id == 1
    assert committed_payload["name"] == "Renamed"


@pytest.mark.asyncio
async def test_update_checks_write_allowlist_using_the_fetched_grids_own_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/projects/6")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(grid_id=1, name="Renamed", confirm=False)

    assert api.update_form_calls == []


@pytest.mark.asyncio
async def test_update_allows_my_page_grid_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.update(grid_id=1, name="Renamed", confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_delete_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.delete(grid_id=1, confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.delete(grid_id=1, confirm=True)

    assert result.confirmed is True
    assert api.delete_calls == [1]
    assert result.result is not None


@pytest.mark.asyncio
async def test_delete_checks_write_allowlist_using_the_fetched_grids_own_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/projects/6")])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(grid_id=1, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_allows_my_page_grid_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.delete(grid_id=1, confirm=False)

    assert result.requires_confirmation is True
