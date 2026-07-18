from __future__ import annotations

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.version_api import VersionPage, VersionRecord
from openproject_ce_mcp.app.resolvers.version_resolver import VersionResolver
from openproject_ce_mcp.models import VersionSummary


def _summary(version_id: int, name: str) -> VersionSummary:
    return VersionSummary(
        id=version_id,
        name=name,
        status="open",
        sharing=None,
        start_date=None,
        end_date=None,
        defining_project="Demo",
        description=None,
        url=f"https://op.example.com/versions/{version_id}",
    )


class _FakeVersionApi:
    def __init__(self, records: list[VersionRecord]) -> None:
        self._records = records

    async def list_for_project(self, project_id: int, *, offset: int, page_size: int) -> VersionPage:
        return VersionPage(records=self._records, server_total=len(self._records))

    async def list_global(self, *, offset: int, page_size: int) -> VersionPage:
        return VersionPage(records=self._records, server_total=None)

    async def get(self, version_id: int) -> VersionRecord:
        for record in self._records:
            if record.summary.id == version_id:
                return record
        raise AssertionError(f"no fake record for id {version_id}")

    async def create_form(self, payload): ...
    async def update_form(self, version_id, payload): ...
    async def commit_create(self, payload): ...
    async def commit_update(self, version_id, payload): ...
    async def delete(self, version_id: int) -> None: ...


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": "demo", "name": "Demo"}


def _resolver(records: list[VersionRecord]) -> VersionResolver:
    return VersionResolver(
        api=_FakeVersionApi(records),
        resolve_project_ref=_resolve_project_ref,
        settings=make_settings(),
        project_id_to_identifier={6: "demo"},
    )


@pytest.mark.asyncio
async def test_resolve_by_numeric_id_within_project() -> None:
    records = [VersionRecord(summary=_summary(8, "v1.0"), defining_project_link=None)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("8", project="demo")

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_within_project() -> None:
    records = [VersionRecord(summary=_summary(8, "v1.0"), defining_project_link=None)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("v1.0", project="demo")

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_numeric_id_not_available_in_project_raises() -> None:
    records = [VersionRecord(summary=_summary(8, "v1.0"), defining_project_link=None)]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="is not available in project"):
        await resolver.resolve_id("999", project="demo")


@pytest.mark.asyncio
async def test_resolve_ambiguous_name_within_project_raises() -> None:
    records = [
        VersionRecord(summary=_summary(1, "v1.0"), defining_project_link=None),
        VersionRecord(summary=_summary(2, "v1.0"), defining_project_link=None),
    ]
    resolver = _resolver(records)

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("v1.0", project="demo")


@pytest.mark.asyncio
async def test_resolve_numeric_id_without_project_checks_allowlist() -> None:
    link = {"href": "/api/v3/projects/6", "title": "Demo"}
    records = [VersionRecord(summary=_summary(8, "v1.0"), defining_project_link=link)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("8", project=None)

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_without_project_uses_search() -> None:
    records = [VersionRecord(summary=_summary(8, "v1.0"), defining_project_link=None)]
    resolver = _resolver(records)

    result = await resolver.resolve_id("v1.0", project=None)

    assert result == "8"


@pytest.mark.asyncio
async def test_resolve_by_name_without_project_not_found_raises() -> None:
    resolver = _resolver([])

    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_id("nope", project=None)
