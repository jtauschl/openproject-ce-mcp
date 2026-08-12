from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.query_execution_api import QueryResultPage
from openproject_ce_mcp.app.ports.work_package_api import WorkPackageRecord
from openproject_ce_mcp.app.services.query_execution_service import QueryExecutionService
from openproject_ce_mcp.models import WorkPackageSummary

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 2: "secret"}


def _raw_wp(wp_id: int, *, project_href: str = "/api/v3/projects/1", project_title: str = "Demo") -> dict:
    return {
        "id": wp_id,
        "subject": f"WP {wp_id}",
        "_links": {"project": {"href": project_href, "title": project_title}},
    }


def _summary(wp_id: int) -> WorkPackageSummary:
    return WorkPackageSummary(
        id=wp_id,
        display_id=None,
        subject=f"WP {wp_id}",
        type=None,
        status=None,
        priority=None,
        project_phase=None,
        assignee=None,
        responsible=None,
        project="Demo",
        version=None,
        sprint=None,
        start_date=None,
        due_date=None,
        description=None,
        has_description=False,
        description_truncated=False,
        description_length=None,
        estimated_time=None,
        derived_estimated_time=None,
        spent_time=None,
        remaining_time=None,
        derived_remaining_time=None,
        duration=None,
        parent_id=None,
        parent_display_id=None,
        created_at=None,
        updated_at=None,
        author=None,
        category=None,
        schedule_manually=None,
        ignore_non_working_days=None,
        derived_start_date=None,
        derived_due_date=None,
        percentage_done=None,
        derived_percentage_done=None,
        readonly=None,
    )


class _FakeQueryExecutionApi:
    def __init__(self, pages: list[list[dict]]) -> None:
        """`pages` is a list of server pages -- each call to `execute()` with
        an incrementing server offset returns the next page in order, then
        empty lists once exhausted (simulating real pagination)."""
        self._pages = pages
        self.execute_calls: list[tuple[int, int, int]] = []

    async def execute(self, query_id: int, *, offset: int, page_size: int) -> QueryResultPage:
        self.execute_calls.append((query_id, offset, page_size))
        index = offset - 1
        elements = self._pages[index] if index < len(self._pages) else []
        return QueryResultPage(raw_elements=elements)


class _FakeWorkPackageApi:
    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        wp_id = payload["id"]
        return WorkPackageRecord(summary=_summary(wp_id), to_detail=lambda: None, payload=payload)


def _service(
    *,
    api: _FakeQueryExecutionApi,
    settings=None,
) -> QueryExecutionService:
    return QueryExecutionService(
        api=api,
        work_package_api=_FakeWorkPackageApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
    )


@pytest.mark.asyncio
async def test_execute_returns_stamped_summaries_when_scope_allows_all() -> None:
    api = _FakeQueryExecutionApi([[_raw_wp(1), _raw_wp(2)]])
    service = _service(api=api)

    result = await service.execute(7, offset=1, limit=20)

    assert [r.id for r in result.results] == [1, 2]
    assert result.total == 2
    assert result.next_offset is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_execute_denies_when_read_disabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    api = _FakeQueryExecutionApi([[_raw_wp(1)]])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.execute(7)

    assert api.execute_calls == []


# --- allowlist-safe scanning (the security-critical guarantee) ---------------


@pytest.mark.asyncio
async def test_execute_finds_an_allowed_match_beyond_a_single_server_page() -> None:
    """Reproduces the exact bug class documented for WorkPackageService's own
    _list_collection_scanned: a query with many matches server-side, only
    one allowed, landing on a later server page than a single-page filter
    would ever look at. A naive "filter only the first requested page"
    implementation would silently return zero results here."""
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), max_page_size=2)
    # Page 1: 2 disallowed matches (project "secret"). Page 2: 1 allowed match.
    api = _FakeQueryExecutionApi(
        [
            [
                _raw_wp(1, project_href="/api/v3/projects/2", project_title="Secret"),
                _raw_wp(2, project_href="/api/v3/projects/2", project_title="Secret"),
            ],
            [_raw_wp(3, project_href="/api/v3/projects/1", project_title="Demo")],
        ]
    )
    service = _service(api=api, settings=settings)

    result = await service.execute(7, offset=1, limit=20)

    assert [r.id for r in result.results] == [3]
    assert result.total == 1
    # Proves multiple server pages were actually scanned, not just the first.
    assert len(api.execute_calls) >= 2


@pytest.mark.asyncio
async def test_execute_total_reflects_allowlist_filtered_count_not_raw_server_total() -> None:
    """The raw server-reported total (visible to the API token's full
    permissions) must never leak into the response -- total must reflect
    only allowlist-surviving matches on this page, same guarantee as
    list_work_packages under a restricted scope."""
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), max_page_size=50)
    api = _FakeQueryExecutionApi(
        [
            [
                _raw_wp(1, project_href="/api/v3/projects/1", project_title="Demo"),
                _raw_wp(2, project_href="/api/v3/projects/2", project_title="Secret"),
                _raw_wp(3, project_href="/api/v3/projects/2", project_title="Secret"),
            ]
        ]
    )
    service = _service(api=api, settings=settings)

    result = await service.execute(7, offset=1, limit=20)

    assert [r.id for r in result.results] == [1]
    assert result.total == 1


@pytest.mark.asyncio
async def test_execute_denies_disallowed_projects_across_pages_and_stops_at_limit() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), max_page_size=1)
    api = _FakeQueryExecutionApi(
        [
            [_raw_wp(1, project_href="/api/v3/projects/1", project_title="Demo")],
            [_raw_wp(2, project_href="/api/v3/projects/1", project_title="Demo")],
            [_raw_wp(3, project_href="/api/v3/projects/1", project_title="Demo")],
        ]
    )
    service = _service(api=api, settings=settings)

    result = await service.execute(7, offset=1, limit=1)

    assert [r.id for r in result.results] == [1]
    assert result.truncated is True
    assert result.next_offset == 2


# --- hidden-fields ------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_masks_hidden_work_package_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("subject",)})
    api = _FakeQueryExecutionApi([[_raw_wp(1)]])
    service = _service(api=api, settings=settings)

    result = await service.execute(7)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"subject"}
