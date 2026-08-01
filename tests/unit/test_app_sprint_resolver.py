from __future__ import annotations

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, NotFoundError
from openproject_ce_mcp.app.ports.sprint_api import SprintRecord
from openproject_ce_mcp.app.resolvers.sprint_resolver import SprintResolver
from openproject_ce_mcp.models import SprintDetail, SprintSummary

BASE_URL = "https://op.example.com"


def _summary(sprint_id: int, name: str, *, defining_workspace_id: int | None = 1) -> SprintSummary:
    return SprintSummary(
        id=sprint_id,
        name=name,
        status="In Planning",
        start_date="2026-07-09",
        finish_date="2026-07-10",
        defining_workspace_id=defining_workspace_id,
        defining_workspace="Demo Project",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        url=f"{BASE_URL}/sprints/{sprint_id}",
    )


def _record(sprint_id: int, name: str, *, defining_workspace_id: int | None = 1) -> SprintRecord:
    summary = _summary(sprint_id, name, defining_workspace_id=defining_workspace_id)
    detail = SprintDetail(**summary.__dict__)
    link = (
        {"href": f"/api/v3/projects/{defining_workspace_id}", "title": "Demo Project"}
        if defining_workspace_id is not None
        else None
    )
    return SprintRecord(summary=summary, detail=detail, defining_workspace_link=link, defining_workspace_payload=None)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 1, "identifier": "demo"}


class _FakeSprintApi:
    def __init__(self, *, pages: list[tuple[list[SprintRecord], int]] | None = None) -> None:
        self._pages = pages or []
        self.calls: list[tuple[int, int]] = []

    async def list_for_project(self, project_id: int, *, offset: int, page_size: int) -> tuple[list[SprintRecord], int]:
        self.calls.append((offset, page_size))
        if offset - 1 < len(self._pages):
            return self._pages[offset - 1]
        # Server that ignores offset and always returns the first page --
        # exercises the repeated-page-ids termination safeguard.
        return self._pages[0]

    async def get(self, sprint_id: int) -> SprintRecord:
        raise NotFoundError("not used in these tests")


@pytest.mark.asyncio
async def test_resolve_id_numeric_short_circuits_via_get() -> None:
    class _NumericApi(_FakeSprintApi):
        async def get(self, sprint_id: int) -> SprintRecord:
            assert sprint_id == 5
            return _record(5, "Sprint 5")

    resolver = SprintResolver(
        api=_NumericApi(),
        resolve_project_ref=_resolve_project_ref,
        settings=make_settings(),
        project_id_to_identifier={},
    )
    assert await resolver.resolve_id("5", project="demo") == "5"


@pytest.mark.asyncio
async def test_resolve_id_matches_by_case_insensitive_name() -> None:
    api = _FakeSprintApi(pages=[([_record(1, "Sprint 1"), _record(2, "Sprint 2")], 2)])
    resolver = SprintResolver(
        api=api, resolve_project_ref=_resolve_project_ref, settings=make_settings(), project_id_to_identifier={}
    )
    assert await resolver.resolve_id("sprint 2", project="demo") == "2"


@pytest.mark.asyncio
async def test_resolve_id_raises_when_not_found() -> None:
    api = _FakeSprintApi(pages=[([_record(1, "Sprint 1")], 1)])
    resolver = SprintResolver(
        api=api, resolve_project_ref=_resolve_project_ref, settings=make_settings(), project_id_to_identifier={}
    )
    with pytest.raises(InvalidInputError, match="was not found in project"):
        await resolver.resolve_id("Ghost", project="demo")


@pytest.mark.asyncio
async def test_resolve_id_raises_when_ambiguous() -> None:
    api = _FakeSprintApi(pages=[([_record(1, "Sprint 1"), _record(2, "Sprint 1")], 2)])
    resolver = SprintResolver(
        api=api, resolve_project_ref=_resolve_project_ref, settings=make_settings(), project_id_to_identifier={}
    )
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("Sprint 1", project="demo")


@pytest.mark.asyncio
async def test_resolve_id_pages_across_multiple_server_pages() -> None:
    api = _FakeSprintApi(
        pages=[
            ([_record(1, "Sprint 1"), _record(2, "Sprint 2")], 4),
            ([_record(3, "Sprint 3"), _record(4, "Sprint 4")], 4),
        ]
    )
    settings = make_settings()
    import dataclasses

    settings = dataclasses.replace(settings, max_page_size=2)
    resolver = SprintResolver(
        api=api, resolve_project_ref=_resolve_project_ref, settings=settings, project_id_to_identifier={}
    )
    assert await resolver.resolve_id("Sprint 4", project="demo") == "4"
    assert len(api.calls) == 2


@pytest.mark.asyncio
async def test_resolve_id_terminates_when_server_ignores_offset_and_repeats_the_first_page() -> None:
    """Regression test for the repeated-page-ids termination safeguard: a
    server that silently ignores offset/pageSize and always returns the
    first page must not cause an infinite loop -- ported byte-for-byte from
    the flat _resolve_sprint_id, this is the single most important behavior
    to preserve exactly during this migration."""
    api = _FakeSprintApi(pages=[([_record(1, "Sprint 1"), _record(2, "Sprint 2")], 4)])
    settings = make_settings()
    import dataclasses

    settings = dataclasses.replace(settings, max_page_size=2)
    resolver = SprintResolver(
        api=api, resolve_project_ref=_resolve_project_ref, settings=settings, project_id_to_identifier={}
    )
    with pytest.raises(InvalidInputError, match="was not found in project"):
        await resolver.resolve_id("Ghost", project="demo")
    # Must have stopped after detecting the repeated page, not looped forever.
    assert len(api.calls) == 2
