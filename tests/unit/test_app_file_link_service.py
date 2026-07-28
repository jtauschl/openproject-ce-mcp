from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.file_link_api import FileLinkRecord
from openproject_ce_mcp.app.services.file_link_service import FileLinkService
from openproject_ce_mcp.models import FileLinkSummary

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "secret"}


def _summary(file_link_id: int = 5) -> FileLinkSummary:
    return FileLinkSummary(
        id=file_link_id,
        title="spec.pdf",
        storage_id=3,
        storage_name="Nextcloud",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        url=f"/api/v3/file_links/{file_link_id}",
    )


def _record(file_link_id: int = 5, *, has_container_link: bool = True) -> FileLinkRecord:
    container_link = {"href": "/api/v3/work_packages/9"} if has_container_link else None
    return FileLinkRecord(summary=_summary(file_link_id), container_link=container_link)


class _FakeFileLinkApi:
    def __init__(self, records: list[FileLinkRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_for_work_package_calls: list[int] = []
        self.get_calls: list[int] = []
        self.delete_calls: list[int] = []

    async def list_for_work_package(self, work_package_id: int) -> list[FileLinkRecord]:
        self.list_for_work_package_calls.append(work_package_id)
        return list(self._records.values())

    async def get(self, file_link_id: int) -> FileLinkRecord:
        self.get_calls.append(file_link_id)
        if file_link_id not in self._records:
            raise AssertionError(f"no fake record for file_link_id {file_link_id}")
        return self._records[file_link_id]

    async def delete(self, file_link_id: int) -> None:
        self.delete_calls.append(file_link_id)


_DEFAULT_PROJECT_LINK = {"href": "/api/v3/projects/6"}


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = _DEFAULT_PROJECT_LINK) -> None:
        self._project_link = project_link
        self.get_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        return {"id": int(work_package_ref), "_links": {"project": self._project_link}}

    async def get_by_href(self, href: str) -> dict:
        raise AssertionError("get_by_href should not be used by FileLinkService")


def _resolve_work_package_id_ok(resolved_id: int = 9):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_work_package_id_denied():
    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")

    return resolve


def _service(
    *,
    api: _FakeFileLinkApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> FileLinkService:
    return FileLinkService(
        api=api or _FakeFileLinkApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- list_for_work_package ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_summaries() -> None:
    api = _FakeFileLinkApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.list_for_work_package(9)

    assert result.count == 1
    assert result.results[0].id == 5
    assert resolver.calls == [(9, False)]  # type: ignore[attr-defined]
    assert api.list_for_work_package_calls == [9]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeFileLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.list_for_work_package(9)

    # The resolver's own denial must short-circuit before the sub-fetch happens.
    assert api.list_for_work_package_calls == []


@pytest.mark.asyncio
async def test_list_for_work_package_masks_hidden_storage_name() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"file_link": ("storage_name",)})
    service = _service(settings=settings)

    result = await service.list_for_work_package(9)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"storage_name"}


# --- delete -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeFileLinkApi()
    service = _service(api=api)

    result = await service.delete(5, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.work_package_id == 9
    assert result.result is not None
    assert result.result.id == 5
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeFileLinkApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api)

    result = await service.delete(5, confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.work_package_id == 9
    assert result.result is None
    assert api.delete_calls == [5]
    # The derived work_package_id (from the file link's own container link,
    # not any caller-supplied value) must be what's actually looked up --
    # a wrong id here would silently check the wrong project's write
    # allowlist. Found missing during this migration's step-6 self-audit.
    assert work_package_lookup_api.get_calls == ["9"]


@pytest.mark.asyncio
async def test_delete_preview_masks_hidden_storage_name() -> None:
    """The delete() preview returns the same normalized summary shape as
    list_for_work_package() -- it must be stamped too, not just list()'s
    results, or hidden fields would leak from delete previews."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"file_link": ("storage_name",)})
    service = _service(settings=settings)

    result = await service.delete(5, confirm=False)

    assert getattr(result.result, "_hidden_keys", frozenset()) == {"storage_name"}


@pytest.mark.asyncio
async def test_delete_denies_write_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    api = _FakeFileLinkApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/6"})
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(5, confirm=True)

    assert api.delete_calls == []
    assert work_package_lookup_api.get_calls == ["9"]


@pytest.mark.asyncio
async def test_delete_reports_none_work_package_id_when_container_unresolvable() -> None:
    api = _FakeFileLinkApi(records=[_record(has_container_link=False)])
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    settings = dataclasses.replace(make_settings(), write_projects=("*",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    result = await service.delete(5, confirm=True)

    assert result.work_package_id is None
    assert result.confirmed is True
    # Fail-closed: no work package to fetch a project link from.
    assert work_package_lookup_api.get_calls == []


@pytest.mark.asyncio
async def test_delete_fails_closed_when_container_unresolvable_and_write_scope_restricted() -> None:
    api = _FakeFileLinkApi(records=[_record(has_container_link=False)])
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(5, confirm=True)

    assert api.delete_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_storage_name_hidden_by_file_link_scope_not_grid_scope() -> None:
    """Regression test for the entity="file_link" vs a same-shaped neighbor
    hide-field bug class (same bug class as OPM-1627's Priority/Notification
    findings)."""
    settings_grid_hidden = dataclasses.replace(make_settings(), hidden_fields={"grid": ("storage_name",)})
    service_grid_hidden = _service(settings=settings_grid_hidden)
    result_grid_hidden = await service_grid_hidden.list_for_work_package(9)
    assert getattr(result_grid_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_file_link_hidden = dataclasses.replace(make_settings(), hidden_fields={"file_link": ("storage_name",)})
    service_file_link_hidden = _service(settings=settings_file_link_hidden)
    result_file_link_hidden = await service_file_link_hidden.list_for_work_package(9)
    assert getattr(result_file_link_hidden.results[0], "_hidden_keys", frozenset()) == {"storage_name"}
