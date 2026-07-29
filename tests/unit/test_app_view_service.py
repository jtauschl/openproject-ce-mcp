from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.view_api import ViewRecord
from openproject_ce_mcp.app.services.view_service import ViewService
from openproject_ce_mcp.models import ViewDetail, ViewSummary

BASE_URL = "https://op.example.com"


def _summary(
    view_id: int = 1,
    *,
    project_id: int | None = 6,
    project: str | None = "Demo Project",
    view_type: str | None = "Team planner view",
    name: str = "Team Planner",
) -> ViewSummary:
    return ViewSummary(
        id=view_id,
        type=view_type,
        name=name,
        project_id=project_id,
        project=project,
        query_id=9,
        query="My Query",
        public=True,
        starred=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        url=f"{BASE_URL}/api/v3/views/{view_id}",
    )


def _detail(**kwargs: object) -> ViewDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return ViewDetail(
        id=summary.id,
        type=summary.type,
        name=summary.name,
        project_id=summary.project_id,
        project=summary.project,
        query_id=summary.query_id,
        query=summary.query,
        public=summary.public,
        starred=summary.starred,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        links=["project", "query"],
        url=summary.url,
    )


def _record(*, project_link: dict | None = None, **kwargs: object) -> ViewRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    if project_link is None and summary.project_id is not None:
        project_link = {"href": f"/api/v3/projects/{summary.project_id}"}
    return ViewRecord(summary=summary, detail=detail, project_link=project_link)


class _FakeViewApi:
    def __init__(self, records: list[ViewRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[int] = []
        self.get_calls: list[int] = []

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ViewRecord], int]:
        self.list_all_calls.append(page_size)
        records = list(self._records.values())
        return records, len(records)

    async def get(self, view_id: int) -> ViewRecord:
        self.get_calls.append(view_id)
        if view_id not in self._records:
            raise AssertionError(f"no fake record for view_id {view_id}")
        return self._records[view_id]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _service(
    api: _FakeViewApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> ViewService:
    api = api or _FakeViewApi()
    return ViewService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeViewApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(api.list_all_calls) == 1


@pytest.mark.asyncio
async def test_list_filters_by_project_candidate() -> None:
    api = _FakeViewApi(
        records=[
            _record(view_id=1, project_id=6, project="Demo Project"),
            _record(view_id=2, project_id=7, project="Other Project"),
        ]
    )
    service = _service(api)

    result = await service.list(project="demo")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_passes_write_false_to_resolve_project_ref() -> None:
    """list()'s project filter resolves via resolve_project_filter_candidates
    (project_scoped_list.py), which forwards straight to resolve_project_ref
    -- must ask for a READ-checked (write=False) resolution. Found missing
    during this domain's own step-6 self-audit; DocumentService.list() has
    the identical gap (same shared helper), fixed alongside this one.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeViewApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list(project="demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_filters_by_view_type() -> None:
    api = _FakeViewApi(
        records=[
            _record(view_id=1, view_type="Team planner view"),
            _record(view_id=2, view_type="Work packages table"),
        ]
    )
    service = _service(api)

    result = await service.list(view_type="team planner view")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_filters_by_search_term_in_name() -> None:
    api = _FakeViewApi(records=[_record(view_id=1, name="Sprint Board"), _record(view_id=2, name="Unrelated")])
    service = _service(api)

    result = await service.list(search="sprint")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_excludes_linked_views_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeViewApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_excludes_unlinked_views_when_scope_is_restrictive() -> None:
    """A view with no project link at all must be DENIED (not silently
    allowed, not silently dropped-as-a-no-op) once read_projects is
    restrictive -- verbatim behavior of client.py's original
    _ensure_view_payload_allowed, the one genuinely new case this domain
    introduces (no prior migrated domain has a nullable project link).
    """
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeViewApi(records=[_record(view_id=1, project_id=None, project=None, project_link=None)])
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_includes_unlinked_views_when_scope_allows_all() -> None:
    api = _FakeViewApi(records=[_record(view_id=1, project_id=None, project=None, project_link=None)])
    service = _service(api)  # make_settings() defaults to read_projects=("*",)

    result = await service.list()

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeViewApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list()

    assert api.list_all_calls == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"view": ("query",)})
    api = _FakeViewApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"query"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_query_hidden_by_view_scope_not_project_scope() -> None:
    """Regression test for the entity="view" vs "project" hide-field bug
    class (same bug class as the OPM-266 News hotfix and prior domains'
    findings). client.py's original normalize_view already used the
    correct "view" entity string, so this test only guards against a
    regression, not a fix.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("query",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_view_hidden = dataclasses.replace(make_settings(), hidden_fields={"view": ("query",)})
    service_view_hidden = _service(settings=settings_view_hidden)
    result_view_hidden = await service_view_hidden.get(1)
    assert getattr(result_view_hidden, "_hidden_keys", frozenset()) == {"query"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist_for_a_linked_view() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeViewApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_denies_an_unlinked_view_when_scope_is_restrictive() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeViewApi(records=[_record(view_id=1, project_id=None, project=None, project_link=None)])
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_allows_an_unlinked_view_when_scope_allows_all() -> None:
    api = _FakeViewApi(records=[_record(view_id=1, project_id=None, project=None, project_link=None)])
    service = _service(api)  # make_settings() defaults to read_projects=("*",)

    result = await service.get(1)

    assert result.id == 1


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeViewApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []
