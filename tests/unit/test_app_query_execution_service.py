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
        target_versions=[],
        observed_in_versions=[],
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
    )


def _record(summary: WorkPackageSummary, payload: dict) -> WorkPackageRecord:
    return WorkPackageRecord(
        id=summary.id,
        project=summary.project,
        references={},
        payload=payload,
        summary_factory=lambda _visible: summary,
        detail_factory=lambda _visible: None,  # type: ignore[arg-type,return-value]
    )


async def _all_references_allowed(references):
    return dict.fromkeys(references, True)


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
        return QueryResultPage(raw_elements=elements, server_total=sum(len(page) for page in self._pages))


class _FakeWorkPackageApi:
    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        wp_id = payload["id"]
        return _record(_summary(wp_id), payload)


def _service(
    *,
    api: _FakeQueryExecutionApi,
    settings=None,
    work_package_api=None,
    bulk=None,
) -> QueryExecutionService:
    async def nothing_allowed(hrefs, *, context):
        return dict.fromkeys(hrefs, False)

    return QueryExecutionService(
        api=api,
        work_package_api=work_package_api or _FakeWorkPackageApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        work_package_project_allowed_bulk=bulk or nothing_allowed,
        references_allowed=_all_references_allowed,
        api_prefix="/api/v3/",
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


class _CustomFieldWorkPackageApi:
    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        summary = dataclasses.replace(
            _summary(payload["id"]),
            description="body",
            has_description=True,
            description_truncated=True,
            description_length=900,
            custom_fields={"customField1": "secret", "customField2": "kept"},
            custom_fields_truncated=True,
            custom_comments={"customComment1": "secret note", "customComment2": "kept note"},
        )
        return _record(summary, payload)


@pytest.mark.asyncio
async def test_execute_masks_hidden_custom_fields_and_their_comments_like_every_other_work_package_read() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField1",))
    service = _service(
        api=_FakeQueryExecutionApi([[_raw_wp(1)]]), settings=settings, work_package_api=_CustomFieldWorkPackageApi()
    )

    (row,) = (await service.execute(7)).results

    assert row.custom_fields == {"customField2": "kept"}
    assert row.custom_comments == {"customComment2": "kept note"}


@pytest.mark.asyncio
async def test_execute_resets_the_metadata_of_a_hidden_description_and_hidden_custom_fields() -> None:
    settings = dataclasses.replace(make_settings(), hide_work_package_fields=("description", "custom_fields"))
    service = _service(
        api=_FakeQueryExecutionApi([[_raw_wp(1)]]), settings=settings, work_package_api=_CustomFieldWorkPackageApi()
    )

    (row,) = (await service.execute(7)).results

    assert (row.has_description, row.description_truncated, row.description_length) == (False, False, None)
    assert row.custom_fields_truncated is False


@pytest.mark.asyncio
async def test_execute_denies_when_read_disabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    api = _FakeQueryExecutionApi([[_raw_wp(1)]])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.execute(7)

    assert api.execute_calls == []


@pytest.mark.asyncio
async def test_execute_skips_the_round_trip_with_an_empty_read_allowlist() -> None:
    """Matches WorkPackageService.list()'s own fast path: an empty
    read_projects allowlist can never allow anything, so there is no reason
    to call the server at all."""
    settings = dataclasses.replace(make_settings(), read_projects=())
    api = _FakeQueryExecutionApi([[_raw_wp(1)]])
    service = _service(api=api, settings=settings)

    result = await service.execute(7)

    assert result.results == []
    assert result.total == 0
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
async def test_execute_stops_at_the_server_total_without_fetching_an_empty_page() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",), max_page_size=2)
    api = _FakeQueryExecutionApi([[_raw_wp(1), _raw_wp(2)]])
    service = _service(api=api, settings=settings)

    result = await service.execute(7, offset=1, limit=2)

    assert [r.id for r in result.results] == [1, 2]
    assert [call[1] for call in api.execute_calls] == [1]


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


class _ParentedWorkPackageApi(_FakeWorkPackageApi):
    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        wp_id = payload["id"]
        summary = dataclasses.replace(_summary(wp_id), parent_id=payload.get("parent"), parent_display_id="OTHER-1")
        return _record(summary, payload)


@pytest.mark.asyncio
async def test_execute_leaves_out_a_parent_the_read_scope_does_not_cover() -> None:
    checked: list[list[str]] = []

    async def bulk(hrefs, *, context):
        checked.append(list(hrefs))
        return {href: href.endswith("/21") for href in hrefs}

    api = _FakeQueryExecutionApi([[{**_raw_wp(1), "parent": 20}, {**_raw_wp(2), "parent": 21}, _raw_wp(3)]])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api=api, settings=settings, work_package_api=_ParentedWorkPackageApi(), bulk=bulk)

    result = await service.execute(7)

    assert {row.id: (row.parent_id, row.parent_display_id) for row in result.results} == {
        1: (None, None),
        2: (21, "OTHER-1"),
        3: (None, "OTHER-1"),
    }
    assert checked == [["/api/v3/work_packages/20", "/api/v3/work_packages/21"]]


@pytest.mark.asyncio
async def test_execute_keeps_the_hidden_field_stamp_after_the_parent_is_left_out() -> None:
    api = _FakeQueryExecutionApi([[{**_raw_wp(1), "parent": 20}]])
    settings = dataclasses.replace(
        make_settings(), read_projects=("demo",), hidden_fields={"work_package": ("subject",)}
    )
    service = _service(api=api, settings=settings, work_package_api=_ParentedWorkPackageApi())

    result = await service.execute(7)

    assert result.results[0].parent_id is None
    assert result.results[0]._hidden_keys == frozenset({"subject"})
