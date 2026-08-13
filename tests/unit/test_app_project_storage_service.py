from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.project_storage_api import ProjectStorageRecord
from openproject_ce_mcp.app.services.project_storage_service import ProjectStorageService
from openproject_ce_mcp.models import ProjectStorageDetail, ProjectStorageSummary


def _summary(
    project_storage_id: int = 1,
    *,
    project_id: int = 3,
    project: str = "TST Test",
    storage_id: int = 1,
    storage_name: str = "Seed Nextcloud Storage",
    project_folder_mode: str = "inactive",
) -> ProjectStorageSummary:
    return ProjectStorageSummary(
        id=project_storage_id,
        project_id=project_id,
        project=project,
        storage_id=storage_id,
        storage_name=storage_name,
        project_folder_mode=project_folder_mode,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )


def _detail(**kwargs: object) -> ProjectStorageDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return ProjectStorageDetail(
        id=summary.id,
        project_id=summary.project_id,
        project=summary.project,
        storage_id=summary.storage_id,
        storage_name=summary.storage_name,
        project_folder_mode=summary.project_folder_mode,
        creator_id=4,
        creator="OpenProject Admin",
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _record(**kwargs: object) -> ProjectStorageRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return ProjectStorageRecord(
        summary=summary,
        to_detail=lambda: _detail(**kwargs),  # type: ignore[arg-type]
        project_link={"href": f"/api/v3/projects/{summary.project_id}", "title": summary.project},
    )


class _FakeProjectStorageApi:
    def __init__(self, records: list[ProjectStorageRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ProjectStorageRecord], int]:
        self.list_all_calls.append((offset, page_size))
        records = list(self._records.values())
        return records, len(records)

    async def get(self, project_storage_id: int) -> ProjectStorageRecord:
        self.get_calls.append(project_storage_id)
        record = self._records.get(project_storage_id)
        if record is None:
            raise AssertionError(f"no fake record for project_storage_id {project_storage_id}")
        return record


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 3, "identifier": project_ref, "name": "TST Test", "_links": {}}


def _service(
    api: _FakeProjectStorageApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> ProjectStorageService:
    return ProjectStorageService(
        api=api or _FakeProjectStorageApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
    )


# --- list_project_storages -----------------------------------------------


@pytest.mark.asyncio
async def test_list_project_storages_returns_summaries() -> None:
    api = _FakeProjectStorageApi()
    service = _service(api)

    result = await service.list_project_storages()

    assert result.count == 1
    assert result.results[0].project == "TST Test"
    assert result.results[0].storage_name == "Seed Nextcloud Storage"
    # Fetches everything (bounded by max_results) -- project_storages is an
    # UnpaginatedCollection server-side.
    assert api.list_all_calls == [(1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_project_storages_filters_by_project() -> None:
    records = [
        _record(project_storage_id=1, project_id=3, project="TST Test"),
        _record(project_storage_id=2, project_id=9, project="Other Project"),
    ]
    api = _FakeProjectStorageApi(records)
    service = _service(api)

    result = await service.list_project_storages(project="tst")

    assert result.count == 1
    assert result.results[0].project == "TST Test"


@pytest.mark.asyncio
async def test_list_project_storages_drops_rows_outside_read_allowlist() -> None:
    records = [
        _record(project_storage_id=1, project_id=3, project="TST Test"),
        _record(project_storage_id=2, project_id=9, project="Other Project"),
    ]
    api = _FakeProjectStorageApi(records)
    settings = dataclasses.replace(make_settings(), read_projects=("3",))
    service = _service(api, settings=settings)

    result = await service.list_project_storages()

    # Denied rows are silently dropped from the list, not raised -- matches
    # Documents' _record_allowed pattern.
    assert result.count == 1
    assert result.results[0].project == "TST Test"


@pytest.mark.asyncio
async def test_list_project_storages_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeProjectStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_project_storages()

    assert api.list_all_calls == []


# --- get_project_storage --------------------------------------------------


@pytest.mark.asyncio
async def test_get_project_storage_returns_detail_with_creator() -> None:
    api = _FakeProjectStorageApi()
    service = _service(api)

    detail = await service.get_project_storage(1)

    assert detail.project == "TST Test"
    assert detail.creator == "OpenProject Admin"
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_project_storage_denies_project_outside_allowlist() -> None:
    api = _FakeProjectStorageApi([_record(project_id=9, project="Other Project")])
    settings = dataclasses.replace(make_settings(), read_projects=("tst",))
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_project_storage(1)


@pytest.mark.asyncio
async def test_get_project_storage_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeProjectStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_project_storage(1)

    assert api.get_calls == []
