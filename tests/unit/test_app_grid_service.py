from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import http_request_counter, policy_observation
from openproject_ce_mcp.app.errors import (
    AuthenticationError,
    CapabilityDisabledError,
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
    ProjectLinkPrefixError,
    ProjectScopeDeniedError,
    TransportError,
)
from openproject_ce_mcp.app.ports.grid_api import GridFormResult, GridRecord
from openproject_ce_mcp.app.services.grid_service import GridService
from openproject_ce_mcp.models import GridSummary, ProjectSummary
from openproject_ce_mcp.presentation import _to_payload

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
    )


def _record(*, scope_link: dict | None = None, project_link: dict | None = None, **kwargs: object) -> GridRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    if scope_link is None and summary.scope is not None:
        scope_link = {"href": summary.scope}
    return GridRecord(summary=summary, scope_link=scope_link, project_link=project_link)


@dataclasses.dataclass
class _Resolved:
    summary: ProjectSummary


class _FakeProjectLookup:
    """OpenProject's own resolution of a grid scope reference: identifier or id."""

    def __init__(self, projects: list[tuple[int, str, str]] | None = None) -> None:
        self._projects = projects if projects is not None else [(6, "demo", "Demo")]
        self.get_calls: list[str] = []

    async def list(self, **kwargs: object):
        raise AssertionError("grid checks never list projects")

    async def get(self, project_ref: str, **kwargs: object) -> _Resolved:
        self.get_calls.append(project_ref)
        for project_id, identifier, name in self._projects:
            if project_ref in (str(project_id), identifier):
                return _Resolved(
                    ProjectSummary(id=project_id, name=name, identifier=identifier, active=True, description=None)
                )
        raise NotFoundError(f"no project {project_ref}")


class _FakeGridApi:
    def __init__(self, records: list[GridRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_page_calls: list[str | None] = []
        self.get_calls: list[int] = []
        self.create_form_calls: list[dict] = []
        self.update_form_calls: list[tuple[int, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.validation_errors: dict[str, str] = {}
        self.commit_result_scope: str | None = "/projects/6"

    async def list_page(self, *, offset: int, page_size: int, scope_filter: str | None) -> tuple[list[GridRecord], int]:
        self.list_page_calls.append(scope_filter)
        # A single-page fake is sufficient for these Service-level tests --
        # scan_records_and_paginate's own multi-page scanning behavior is
        # covered by test_app_pagination.py, not re-tested per Service.
        if offset > 1:
            return [], len(self._records)
        records = list(self._records.values())
        return records, len(records)

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


def _service(
    api: _FakeGridApi | None = None, *, settings=None, projects: _FakeProjectLookup | None = None
) -> GridService:
    api = api or _FakeGridApi()
    return GridService(
        api=api,
        project_lookup=projects or _FakeProjectLookup(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert api.list_page_calls == [None]


@pytest.mark.asyncio
async def test_list_passes_scope_filter_through_to_the_api() -> None:
    api = _FakeGridApi()
    service = _service(api)

    await service.list(scope="/my/page")

    assert api.list_page_calls == ["/my/page"]


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

    with pytest.raises(CapabilityDisabledError):
        await service.list()

    assert api.list_page_calls == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    # OPENPROJECT_HIDE_GRID_FIELDS must actually take effect on grid reads,
    # not be a silent no-op.
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
    class (same bug class as the News/Documents/TimeEntry
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

    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_READ_PROJECTS"):
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

    with pytest.raises(CapabilityDisabledError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.create(name="My Grid", scope="/projects/6", confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"grid": ("row_count",)})
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Grid", scope="/projects/6", confirm=True)

    assert result.state == "confirmed"
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"row_count"}


@pytest.mark.asyncio
async def test_create_checks_write_allowlist_unconditionally_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.create(name="My Grid", scope="/projects/6", confirm=False)

    assert api.create_form_calls == []


@pytest.mark.asyncio
async def test_create_always_allows_my_page_scope_even_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi()
    service = _service(api, settings=settings)

    result = await service.create(name="My Grid", scope="/my/page", confirm=False)

    assert result.state == "preview"


@pytest.mark.parametrize(
    "scope", ["", "/projects/demo/settings", "https://evil.example.com/projects/demo", "/x/my/page"]
)
@pytest.mark.asyncio
async def test_create_rejects_a_scope_of_no_known_shape_even_when_wide_open(scope: str) -> None:
    api = _FakeGridApi()
    service = _service(api)  # make_settings() defaults to read_projects=write_projects=("*",)

    with pytest.raises(InvalidInputError, match="grid scope must be"):
        await service.create(name="My Grid", scope=scope, confirm=False)

    assert api.create_form_calls == []


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

    assert result.state == "confirmed"
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

    assert result.state == "confirmed"
    assert len(api.commit_update_calls) == 1


@pytest.mark.asyncio
async def test_update_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.update(grid_id=1, name="Renamed", confirm=False)

    assert result.state == "preview"
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.update(grid_id=1, name="Renamed", confirm=True)

    assert result.state == "confirmed"
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

    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(grid_id=1, name="Renamed", confirm=False)

    assert api.update_form_calls == []


@pytest.mark.asyncio
async def test_update_allows_my_page_grid_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.update(grid_id=1, name="Renamed", confirm=False)

    assert result.state == "preview"


@pytest.mark.asyncio
async def test_delete_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.delete(grid_id=1, confirm=False)

    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeGridApi()
    service = _service(api)

    result = await service.delete(grid_id=1, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [1]
    assert result.result is not None


@pytest.mark.asyncio
async def test_delete_checks_write_allowlist_using_the_fetched_grids_own_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/projects/6")])
    service = _service(api, settings=settings)

    with pytest.raises(ProjectScopeDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(grid_id=1, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_allows_my_page_grid_under_fully_restrictive_write_projects() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",), write_projects=("other",))
    api = _FakeGridApi(records=[_record(grid_id=1, scope="/my/page")])
    service = _service(api, settings=settings)

    result = await service.delete(grid_id=1, confirm=False)

    assert result.state == "preview"


def _restricted(read: tuple[str, ...] = ("demo",), write: tuple[str, ...] = ("demo",)):
    return dataclasses.replace(make_settings(), read_projects=read, write_projects=write)


class _FailingProjectLookup(_FakeProjectLookup):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def get(self, project_ref: str, **kwargs: object) -> _Resolved:
        self.get_calls.append(project_ref)
        raise self._error


@pytest.mark.asyncio
async def test_list_resolves_each_distinct_scope_project_once_per_call() -> None:
    api = _FakeGridApi(
        [
            _record(grid_id=1, scope="/projects/demo"),
            _record(grid_id=2, scope="/projects/demo/boards"),
            _record(grid_id=3, scope="/projects/secret"),
            _record(grid_id=4, scope="/my/page"),
        ]
    )
    projects = _FakeProjectLookup([(6, "demo", "Demo"), (9, "secret", "Secret")])

    result = await _service(api, settings=_restricted(), projects=projects).list()

    assert [grid.id for grid in result.results] == [1, 2, 4]
    assert sorted(projects.get_calls) == ["demo", "secret"]


@pytest.mark.asyncio
async def test_list_needs_no_project_lookup_when_wide_open() -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/projects/demo/boards")])
    projects = _FakeProjectLookup()

    result = await _service(api, projects=projects).list()

    assert [grid.id for grid in result.results] == [1]
    assert projects.get_calls == []


@pytest.mark.asyncio
async def test_a_scope_project_is_matched_by_its_name_and_by_a_former_identifier() -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/projects/old-demo")])
    projects = _FakeProjectLookup([(6, "old-demo", "Demo Project")])

    result = await _service(api, settings=_restricted(read=("Demo Project",)), projects=projects).list()

    assert [grid.id for grid in result.results] == [1]


@pytest.mark.parametrize("error", [NotFoundError("gone"), PermissionDeniedError("hidden")])
@pytest.mark.asyncio
async def test_a_scope_project_openproject_does_not_resolve_hides_the_grid(error: Exception) -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/projects/demo"), _record(grid_id=2, scope="/my/page")])

    result = await _service(api, settings=_restricted(), projects=_FailingProjectLookup(error)).list()

    assert [grid.id for grid in result.results] == [2]


@pytest.mark.parametrize(
    "error", [TransportError("down"), OpenProjectServerError("boom"), AuthenticationError("token")]
)
@pytest.mark.asyncio
async def test_any_other_lookup_failure_propagates_instead_of_hiding_grids(error: Exception) -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/projects/demo")])

    with pytest.raises(type(error)):
        await _service(api, settings=_restricted(), projects=_FailingProjectLookup(error)).list()


@pytest.mark.asyncio
async def test_a_lookup_failure_for_a_grid_the_scan_never_reaches_is_not_raised() -> None:
    # limit=1 reads one grid past the page to decide `truncated`; the third is never reached.
    api = _FakeGridApi(
        [
            _record(grid_id=1, scope="/my/page"),
            _record(grid_id=2, scope="/my/page"),
            _record(grid_id=3, scope="/projects/demo"),
        ]
    )

    result = await _service(api, settings=_restricted(), projects=_FailingProjectLookup(TransportError("down"))).list(
        limit=1
    )

    assert [grid.id for grid in result.results] == [1]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_a_grid_scope_under_another_root_path_is_a_configuration_error() -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/openproject/projects/demo")])

    with pytest.raises(ProjectLinkPrefixError, match="/openproject/api/v3/"):
        await _service(api).get(1)


@pytest.mark.asyncio
async def test_create_rechecks_the_scope_openproject_resolved_before_preview() -> None:
    api = _FakeGridApi()

    async def resolved_elsewhere(payload: dict) -> GridFormResult:
        api.create_form_calls.append(payload)
        return GridFormResult(
            payload={**payload, "_links": {"scope": {"href": "/projects/secret"}}}, validation_errors={}
        )

    api.create_form = resolved_elsewhere  # type: ignore[method-assign]
    projects = _FakeProjectLookup([(6, "demo", "Demo"), (9, "secret", "Secret")])

    with pytest.raises(ProjectScopeDeniedError):
        await _service(api, settings=_restricted(), projects=projects).create(name="G", scope="/projects/demo")

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rechecks_the_project_link_of_the_form() -> None:
    api = _FakeGridApi()

    async def with_foreign_project(payload: dict) -> GridFormResult:
        links = {**payload["_links"], "project": {"href": "https://evil.example.com/api/v3/projects/6"}}
        return GridFormResult(payload={**payload, "_links": links}, validation_errors={})

    api.create_form = with_foreign_project  # type: ignore[method-assign]

    with pytest.raises(ProjectScopeDeniedError):
        await _service(api).create(name="G", scope="/projects/demo", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_shows_validation_errors_without_rechecking_an_incomplete_form() -> None:
    api = _FakeGridApi()
    api.validation_errors = {"scope": "is invalid"}

    async def without_links(payload: dict) -> GridFormResult:
        return GridFormResult(payload={"name": payload["name"]}, validation_errors=api.validation_errors)

    api.create_form = without_links  # type: ignore[method-assign]

    result = await _service(api).create(name="G", scope="/projects/demo")

    assert result.validation_errors == {"scope": "is invalid"}


@pytest.mark.asyncio
async def test_update_and_delete_check_the_grids_own_project_link() -> None:
    api = _FakeGridApi([_record(grid_id=1, scope="/projects/demo", project_link={"href": "/api/v3/projects/9"})])
    projects = _FakeProjectLookup([(6, "demo", "Demo")])
    service = _service(api, settings=_restricted(), projects=projects)

    with pytest.raises(ProjectScopeDeniedError):
        await service.update(grid_id=1, name="Renamed", confirm=True)
    with pytest.raises(ProjectScopeDeniedError):
        await service.delete(grid_id=1, confirm=True)

    assert api.commit_update_calls == []
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_a_grid_without_a_known_scope_is_denied_and_recorded_on_the_service_path() -> None:
    api = _FakeGridApi([_record(grid_id=1, scope=None)])
    service = _service(api, settings=_restricted())
    policy_observation.reset()

    with pytest.raises(ProjectScopeDeniedError, match="scope that is not a project"):
        await service.get(1)

    assert policy_observation.current_policy_decision() == "project_scope_read_denied"
    assert policy_observation.current_project_scope() is None


@pytest.mark.asyncio
async def test_grid_scope_lookups_count_toward_the_calls_http_requests() -> None:
    class _CountingLookup(_FakeProjectLookup):
        async def get(self, project_ref: str, **kwargs: object) -> _Resolved:
            http_request_counter.increment()
            return await super().get(project_ref, **kwargs)

    api = _FakeGridApi([_record(grid_id=1, scope="/projects/demo"), _record(grid_id=2, scope="/projects/secret")])
    projects = _CountingLookup([(6, "demo", "Demo"), (9, "secret", "Secret")])
    http_request_counter.reset()

    await _service(api, settings=_restricted(), projects=projects).list()

    assert http_request_counter.current() == 2


@pytest.mark.parametrize("action", ["update", "delete"])
@pytest.mark.asyncio
async def test_a_write_to_a_grid_without_a_known_scope_records_a_write_denial(action: str) -> None:
    api = _FakeGridApi([_record(grid_id=1, scope=None)])
    service = _service(api, settings=_restricted())
    policy_observation.reset()

    with pytest.raises(ProjectScopeDeniedError, match="scope that is not a project"):
        if action == "update":
            await service.update(grid_id=1, name="Renamed", confirm=True)
        else:
            await service.delete(grid_id=1, confirm=True)

    assert policy_observation.current_policy_decision() == "project_scope_write_denied"
    assert policy_observation.current_project_scope() is None
