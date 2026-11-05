from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.ports.version_api import VersionRecord
from openproject_ce_mcp.app.services.version_service import VersionService
from openproject_ce_mcp.models import ProjectSummary, VersionSummary
from openproject_ce_mcp.presentation import _to_payload

IDENTIFIERS = {6: "demo", 7: "other", 8: "third"}


def _project(project_id: int, *, description: str | None = "text") -> ProjectRecord:
    identifier = IDENTIFIERS[project_id]
    summary = ProjectSummary(
        id=project_id, name=identifier.title(), identifier=identifier, active=True, description=description
    )
    return ProjectRecord(
        summary=summary,
        to_detail=lambda: pytest.fail("a list row never needs the detail shape"),
        payload={"id": project_id, "identifier": identifier, "name": identifier.title()},
    )


class _FakeVersionApi:
    def __init__(self, defining_project_link: dict[str, Any] | None) -> None:
        self._link = defining_project_link
        self.get_calls: list[int] = []

    async def get(self, version_id: int, **kwargs: object) -> VersionRecord:
        self.get_calls.append(version_id)
        summary = VersionSummary(
            id=version_id,
            name="1.0",
            status="open",
            sharing="system",
            start_date=None,
            end_date=None,
            defining_project="Demo",
            description=None,
        )
        return VersionRecord(summary=summary, defining_project_link=self._link, lookup_name="1.0", payload={})


class _FakeProjectApi:
    def __init__(self, pages: list[ProjectPage]) -> None:
        self._pages = pages
        self.calls: list[tuple[int, int, int]] = []

    async def list_for_version(
        self, version_id: int, *, server_offset: int, server_page_size: int, **kwargs: object
    ) -> ProjectPage:
        self.calls.append((version_id, server_offset, server_page_size))
        return self._pages[server_offset - 1]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": "demo", "name": "Demo"}


DEMO_LINK = {"href": "/api/v3/projects/6", "title": "Demo"}
OTHER_LINK = {"href": "/api/v3/projects/7", "title": "Other"}


def _service(
    pages: list[ProjectPage], *, link: dict[str, Any] | None = DEMO_LINK, **overrides: Any
) -> tuple[VersionService, _FakeVersionApi, _FakeProjectApi]:
    version_api = _FakeVersionApi(link)
    project_api = _FakeProjectApi(pages)
    settings = dataclasses.replace(make_settings(), **overrides)
    service = VersionService(
        api=version_api,
        settings=settings,
        project_id_to_identifier=IDENTIFIERS,
        resolve_project_ref=_resolve_project_ref,
        api_prefix="api/v3/",
        project_api=project_api,
    )
    return service, version_api, project_api


def _single_page(*records: ProjectRecord) -> list[ProjectPage]:
    return [ProjectPage(records=list(records), server_total=len(records), exhausted=True)]


@pytest.mark.asyncio
async def test_rows_outside_the_read_scope_are_dropped() -> None:
    service, _, _ = _service(_single_page(_project(6), _project(7), _project(8)), read_projects=("demo", "third"))

    result = await service.list_projects(5)

    assert [project.identifier for project in result.results] == ["demo", "third"]
    assert result.count == 2


@pytest.mark.asyncio
async def test_a_version_defined_outside_the_read_scope_names_no_project() -> None:
    service, version_api, project_api = _service(_single_page(_project(6)), link=OTHER_LINK, read_projects=("demo",))

    with pytest.raises(PermissionDeniedError):
        await service.list_projects(5)

    assert version_api.get_calls == [5]
    assert project_api.calls == []


@pytest.mark.asyncio
async def test_a_version_without_a_defining_project_link_is_denied_under_a_restricted_scope() -> None:
    service, _, project_api = _service(_single_page(_project(6)), link=None, read_projects=("demo",))

    with pytest.raises(PermissionDeniedError):
        await service.list_projects(5)

    assert project_api.calls == []


@pytest.mark.asyncio
async def test_hidden_project_fields_are_masked() -> None:
    service, _, _ = _service(_single_page(_project(6)), hidden_fields={"project": ("description",)})

    result = await service.list_projects(5)

    assert "description" not in _to_payload(result.results[0])
    assert result.results[0].description_truncated is False


@pytest.mark.asyncio
async def test_the_page_is_cut_at_the_limit_and_points_to_the_next_one() -> None:
    service, _, _ = _service(_single_page(_project(6), _project(7), _project(8)), read_projects=("*",))

    first = await service.list_projects(5, limit=2)
    second = await service.list_projects(5, offset=2, limit=2)

    assert [p.id for p in first.results] == [6, 7]
    assert (first.truncated, first.next_offset) == (True, 2)
    assert [p.id for p in second.results] == [8]
    assert (second.truncated, second.next_offset) == (False, None)


@pytest.mark.asyncio
async def test_a_server_that_returns_every_row_at_once_is_read_a_single_time() -> None:
    service, _, project_api = _service(_single_page(_project(6), _project(7)), read_projects=("*",))

    result = await service.list_projects(5, limit=10)

    assert [p.id for p in result.results] == [6, 7]
    assert len(project_api.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", ["enable_version_read", "enable_project_read"])
async def test_both_read_switches_are_required(switch: str) -> None:
    service, version_api, _ = _service(_single_page(_project(6)), **{switch: False})

    with pytest.raises(PermissionDeniedError):
        await service.list_projects(5)

    assert version_api.get_calls == []
