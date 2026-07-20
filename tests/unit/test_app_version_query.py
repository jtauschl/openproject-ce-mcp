from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.ports.version_api import VersionPage, VersionRecord
from openproject_ce_mcp.app.resolvers.version_query import fetch_version_page
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
    """No I/O -- an in-memory VersionApi double."""

    def __init__(self, records: list[VersionRecord], *, server_total: int | None = None) -> None:
        self._records = records
        self._server_total = server_total
        self.list_for_project_calls: list[tuple[int, int, int]] = []
        self.list_global_calls: list[tuple[int, int]] = []

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> VersionPage:
        self.list_for_project_calls.append((project_id, offset, page_size))
        server_total = self._server_total if self._server_total is not None else len(self._records)
        return VersionPage(records=self._records, server_total=server_total)

    async def list_global(self, *, offset: int, page_size: int, text_limit: int | None = None) -> VersionPage:
        self.list_global_calls.append((offset, page_size))
        return VersionPage(records=self._records, server_total=None)

    async def get(self, version_id: int, *, text_limit: int | None = None): ...
    async def create_form(self, payload): ...
    async def update_form(self, version_id, payload): ...
    async def commit_create(self, payload): ...
    async def commit_update(self, version_id, payload): ...
    async def delete(self, version_id: int) -> None: ...


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": "demo", "name": "Demo"}


@pytest.mark.asyncio
async def test_project_scoped_uses_exact_server_pagination_and_stays_unmasked() -> None:
    records = [VersionRecord(summary=_summary(1, "v1.0"), defining_project_link=None)]
    api = _FakeVersionApi(records, server_total=25)

    results, total, next_offset, truncated = await fetch_version_page(
        api=api,
        resolve_project_ref=_resolve_project_ref,
        settings=make_settings(),
        project_id_to_identifier={},
        project="demo",
        search=None,
        offset=2,
        limit=10,
        context=None,
    )

    assert api.list_for_project_calls == [(6, 2, 10)]
    assert total == 25
    assert next_offset == 3
    assert truncated is True
    assert results[0].id == 1
    assert not hasattr(results[0], "_hidden_keys")  # unmasked -- masking is VersionService's job


@pytest.mark.asyncio
async def test_project_scoped_with_search_overfetches_and_filters_in_memory() -> None:
    records = [
        VersionRecord(summary=_summary(1, "Sprint 1"), defining_project_link=None),
        VersionRecord(summary=_summary(2, "Release 2"), defining_project_link=None),
    ]
    api = _FakeVersionApi(records)
    settings = make_settings()

    results, total, next_offset, truncated = await fetch_version_page(
        api=api,
        resolve_project_ref=_resolve_project_ref,
        settings=settings,
        project_id_to_identifier={},
        project="demo",
        search="release",
        offset=1,
        limit=10,
        context=None,
    )

    # over-fetch uses max_results as page_size, not the caller's limit
    assert api.list_for_project_calls == [(6, 1, settings.max_results)]
    assert total == 1
    assert next_offset is None
    assert truncated is False
    assert [r.id for r in results] == [2]


@pytest.mark.asyncio
async def test_global_branch_filters_by_allowlist_before_search_and_pagination() -> None:
    allowed = VersionRecord(summary=_summary(1, "Allowed"), defining_project_link={"href": "/api/v3/projects/6"})
    disallowed = VersionRecord(summary=_summary(2, "Blocked"), defining_project_link={"href": "/api/v3/projects/9"})
    api = _FakeVersionApi([allowed, disallowed])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    results, total, next_offset, truncated = await fetch_version_page(
        api=api,
        resolve_project_ref=_resolve_project_ref,
        settings=settings,
        project_id_to_identifier={6: "demo"},
        project=None,
        search=None,
        offset=1,
        limit=10,
        context=None,
    )

    assert [r.id for r in results] == [1]
    assert total == 1


@pytest.mark.asyncio
async def test_read_gate_enforced_even_without_project() -> None:
    from openproject_ce_mcp.app.errors import PermissionDeniedError

    api = _FakeVersionApi([])
    settings = dataclasses.replace(make_settings(), enable_version_read=False)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_VERSION_READ"):
        await fetch_version_page(
            api=api,
            resolve_project_ref=_resolve_project_ref,
            settings=settings,
            project_id_to_identifier={},
            project=None,
            search=None,
            offset=1,
            limit=10,
            context=None,
        )
