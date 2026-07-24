from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
from openproject_ce_mcp.app.resolvers.project_query import fetch_project_page
from openproject_ce_mcp.models import ProjectDetail, ProjectSummary


def _summary(project_id: int, name: str, *, identifier: str | None = None) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        name=name,
        identifier=identifier,
        active=True,
        description=None,
        url=f"https://op.example.com/projects/{project_id}",
    )


def _record(project_id: int, name: str, *, identifier: str | None = None) -> ProjectRecord:
    summary = _summary(project_id, name, identifier=identifier)
    return ProjectRecord(
        summary=summary,
        to_detail=lambda: ProjectDetail(**vars(summary)),
        payload={"id": project_id, "name": name, "identifier": identifier or name},
    )


class _FakeProjectApi:
    """No I/O -- an in-memory ProjectApi double, one page of records per call."""

    def __init__(self, pages: list[ProjectPage]) -> None:
        self._pages = pages
        self.list_calls: list[tuple[int, int, str | None]] = []

    async def list(
        self, *, server_offset: int, server_page_size: int, search: str | None, text_limit=None
    ) -> ProjectPage:
        self.list_calls.append((server_offset, server_page_size, search))
        index = min(server_offset - 1, len(self._pages) - 1)
        return self._pages[index]

    async def get(self, project_ref: str, *, text_limit=None): ...
    async def create_form(self, payload): ...
    async def update_form(self, project_id, payload): ...
    async def commit_create(self, payload): ...
    async def commit_update(self, project_id, payload): ...
    async def delete(self, project_id): ...
    async def get_schema(self, *, project_id, draft_payload): ...
    async def list_available_parent_projects(self, project_id, *, schema): ...
    async def get_configuration(self, project_id): ...
    async def list_phase_definitions(self): ...
    async def get_phase_definition(self, phase_definition_id): ...
    async def get_phase(self, phase_id): ...
    async def set_favorite(self, project_id, *, favorite): ...
    async def copy_form(self, project_id, payload): ...
    async def commit_copy(self, project_id, payload): ...


@pytest.mark.asyncio
async def test_single_page_returns_all_records_and_reports_exhaustion() -> None:
    page = ProjectPage(records=[_record(1, "Alpha"), _record(2, "Beta")], server_total=2, exhausted=True)
    api = _FakeProjectApi([page])

    results, total, next_offset, truncated = await fetch_project_page(
        api=api, settings=make_settings(), project_id_to_identifier={}, search=None, offset=1, limit=10
    )

    assert [r.id for r in results] == [1, 2]
    assert total == 2
    assert next_offset is None
    assert truncated is False


@pytest.mark.asyncio
async def test_skips_already_seen_results_for_offset_greater_than_one() -> None:
    page = ProjectPage(
        records=[_record(1, "Alpha"), _record(2, "Beta"), _record(3, "Gamma")], server_total=3, exhausted=True
    )
    api = _FakeProjectApi([page])

    results, total, next_offset, truncated = await fetch_project_page(
        api=api, settings=make_settings(), project_id_to_identifier={}, search=None, offset=2, limit=1
    )

    # offset=2, limit=1 -> skip the first 1 already-seen result, return the 2nd
    assert [r.id for r in results] == [2]
    assert total == 1


@pytest.mark.asyncio
async def test_stops_mid_page_when_limit_reached_without_checking_exhaustion() -> None:
    # Page reports NOT exhausted, but we already have enough results mid-page --
    # must still report truncated=True (there's more), not fabricate exhaustion.
    page = ProjectPage(records=[_record(1, "Alpha"), _record(2, "Beta")], server_total=2, exhausted=False)
    api = _FakeProjectApi([page])

    results, total, next_offset, truncated = await fetch_project_page(
        api=api, settings=make_settings(), project_id_to_identifier={}, search=None, offset=1, limit=1
    )

    assert [r.id for r in results] == [1]
    assert truncated is True
    assert next_offset == 2
    # Only one server call made -- stopped mid-page, no second page fetched.
    assert len(api.list_calls) == 1


@pytest.mark.asyncio
async def test_advances_to_next_server_page_when_not_yet_exhausted() -> None:
    page1 = ProjectPage(records=[_record(1, "Alpha")], server_total=2, exhausted=False)
    page2 = ProjectPage(records=[_record(2, "Beta")], server_total=2, exhausted=True)
    api = _FakeProjectApi([page1, page2])
    settings = make_settings()

    results, total, next_offset, truncated = await fetch_project_page(
        api=api, settings=settings, project_id_to_identifier={}, search=None, offset=1, limit=settings.max_page_size
    )

    assert [r.id for r in results] == [1, 2]
    assert len(api.list_calls) == 2
    assert api.list_calls[1][0] == 2  # second server_offset


@pytest.mark.asyncio
async def test_passes_search_through_to_the_port() -> None:
    page = ProjectPage(records=[], server_total=0, exhausted=True)
    api = _FakeProjectApi([page])

    await fetch_project_page(
        api=api, settings=make_settings(), project_id_to_identifier={}, search="demo", offset=1, limit=10
    )

    assert api.list_calls[0][2] == "demo"


@pytest.mark.asyncio
async def test_filters_out_records_outside_the_read_allowlist() -> None:
    # Regression test: fetch_project_page must apply the read allowlist to each
    # record it collects (verbatim port of client.py's
    # `projects = [p for p in projects if self._project_payload_allowed(p)]`) --
    # an earlier version of this function silently skipped this filter entirely.
    allowed = _record(1, "Allowed", identifier="allowed")
    denied = _record(2, "Denied", identifier="denied")
    page = ProjectPage(records=[allowed, denied], server_total=2, exhausted=True)
    api = _FakeProjectApi([page])
    settings = dataclasses.replace(make_settings(), read_projects=("allowed",))

    results, total, next_offset, truncated = await fetch_project_page(
        api=api, settings=settings, project_id_to_identifier={}, search=None, offset=1, limit=10
    )

    assert [r.id for r in results] == [1]
    assert total == 1


@pytest.mark.asyncio
async def test_read_gate_enforced() -> None:
    api = _FakeProjectApi([ProjectPage(records=[], server_total=0, exhausted=True)])
    settings = dataclasses.replace(make_settings(), enable_project_read=False)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_PROJECT_READ"):
        await fetch_project_page(
            api=api, settings=settings, project_id_to_identifier={}, search=None, offset=1, limit=10
        )
