from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.version_api import VersionFormResult, VersionPage, VersionRecord
from openproject_ce_mcp.app.services.version_service import VersionService
from openproject_ce_mcp.models import VersionDetail, VersionSummary


def _summary(version_id: int = 8, name: str = "Release 1") -> VersionSummary:
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


def _detail(version_id: int = 8, name: str = "Release 1") -> VersionDetail:
    s = _summary(version_id, name)
    return VersionDetail(
        id=s.id,
        name=s.name,
        status=s.status,
        sharing=s.sharing,
        start_date=s.start_date,
        end_date=s.end_date,
        defining_project=s.defining_project,
        description=s.description,
        url=s.url,
    )


class _FakeVersionApi:
    def __init__(self, records: list[VersionRecord] | None = None) -> None:
        self._records = records or []
        self.validation_errors: dict[str, str] = {}
        self.commit_calls: list[dict] = []
        self.delete_calls: list[int] = []

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> VersionPage:
        return VersionPage(records=self._records, server_total=len(self._records))

    async def list_global(self, *, offset: int, page_size: int, text_limit: int | None = None) -> VersionPage:
        return VersionPage(records=self._records, server_total=None)

    async def get(self, version_id: int, *, text_limit: int | None = None) -> VersionRecord:
        link = {"href": "/api/v3/projects/6", "title": "Demo"}
        return VersionRecord(summary=_summary(version_id), defining_project_link=link)

    async def create_form(self, payload: dict) -> VersionFormResult:
        return VersionFormResult(payload=payload, validation_errors=self.validation_errors)

    async def update_form(self, version_id: int, payload: dict) -> VersionFormResult:
        return VersionFormResult(payload=payload, validation_errors=self.validation_errors)

    async def commit_create(self, payload: dict) -> VersionDetail:
        self.commit_calls.append(payload)
        return _detail(name=payload.get("name", "Release 1"))

    async def commit_update(self, version_id: int, payload: dict) -> VersionDetail:
        self.commit_calls.append(payload)
        return _detail(version_id, name=payload.get("name", "Release 1"))

    async def delete(self, version_id: int) -> None:
        self.delete_calls.append(version_id)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": "demo", "name": "Demo"}


def _service(
    api: _FakeVersionApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> VersionService:
    return VersionService(
        api=api or _FakeVersionApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        resolve_project_ref=resolve_project_ref,
        api_prefix="api/v3/",
    )


@pytest.mark.asyncio
async def test_list_masks_hidden_fields_and_reports_clamped_limit() -> None:
    # The limit must be clamped to max_page_size/max_results in the RETURNED
    # envelope, not just for the actual pagination math -- a caller passing
    # limit=10_000 against a small max_page_size must not see limit=10_000 back.
    records = [VersionRecord(summary=_summary(), defining_project_link=None)]
    settings = dataclasses.replace(
        make_settings(), hidden_fields={"version": ("updated_at",)}, max_page_size=100, max_results=100
    )
    service = _service(_FakeVersionApi(records), settings=settings)

    result = await service.list(project="demo", limit=10_000)

    assert result.limit == 100
    assert result.results[0]._hidden_keys == frozenset({"updated_at"})


@pytest.mark.asyncio
async def test_get_masks_hidden_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"version": ("status",)})
    service = _service(settings=settings)

    detail = await service.get(8)

    assert detail._hidden_keys == frozenset({"status"})


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(8)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(8)


@pytest.mark.asyncio
async def test_get_status_hidden_by_version_scope_not_project_scope() -> None:
    """Regression test for the entity-scope class of bug found via News'
    hotfix and Documents' equivalent: a field must only be masked by
    its OWN domain's OPENPROJECT_HIDE_<ENTITY>_FIELDS scope, never by a
    same-named field under a different (e.g. project) scope.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("status",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(8)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_version_hidden = dataclasses.replace(make_settings(), hidden_fields={"version": ("status",)})
    service_version_hidden = _service(settings=settings_version_hidden)
    result_version_hidden = await service_version_hidden.get(8)
    assert getattr(result_version_hidden, "_hidden_keys", frozenset()) == {"status"}


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    api = _FakeVersionApi()
    service = _service(api)

    result = await service.create(project="demo", name="Release 1", confirm=False)

    assert result.ready is True
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_passes_write_true_to_resolve_project_ref() -> None:
    """create() must ask its injected resolve_project_ref for a WRITE-checked
    resolution (write=True), not a read-only one -- the actual write-
    allowlist enforcement for create() lives inside the real
    _get_project_payload/ProjectResolver.resolve_record (see
    project_resolver.py's `if write: ensure_project_write_allowed(...)`),
    not inside VersionService itself, so this only pins the contract at the
    seam; the enforcement itself is covered by test_project_resolution.py's
    "version-write_denied" policy-matrix case against the real client.
    """
    write_flags: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        write_flags.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    api = _FakeVersionApi()
    service = _service(api, settings=settings, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.create(project="demo", name="Release 1", confirm=True)

    assert write_flags == [True]


@pytest.mark.asyncio
async def test_create_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    result = await service.create(project="demo", name="Release 1", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.name == "Release 1"
    assert len(api.commit_calls) == 1


@pytest.mark.asyncio
async def test_create_rejects_when_validation_errors_present() -> None:
    api = _FakeVersionApi()
    api.validation_errors = {"name": "too short"}
    service = _service(api)

    result = await service.create(project="demo", name="x", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert result.validation_errors == {"name": "too short"}
    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True, hidden_fields={"version": ("name",)})
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_defining_project_field_is_hidden() -> None:
    # project_id is always passed to _build_write_payload from create() (the
    # `project` kwarg is required), so this check fires unconditionally.
    settings = dataclasses.replace(
        make_settings(), enable_version_write=True, hidden_fields={"version": ("defining_project",)}
    )
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_description_field_is_hidden() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_version_write=True, hidden_fields={"version": ("description",)}
    )
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", description="notes", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_start_date_field_is_hidden() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_version_write=True, hidden_fields={"version": ("start_date",)}
    )
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", start_date="2026-01-01", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_end_date_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True, hidden_fields={"version": ("end_date",)})
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", end_date="2026-06-01", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_status_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True, hidden_fields={"version": ("status",)})
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", status="locked", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_sharing_field_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True, hidden_fields={"version": ("sharing",)})
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", name="Release 1", sharing="tree", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_a_written_field_is_hidden() -> None:
    # _build_write_payload is shared between create()/update() -- one
    # representative field is enough here since create()'s tests above
    # already exercise every field through the same shared helper.
    settings = dataclasses.replace(make_settings(), enable_version_write=True, hidden_fields={"version": ("name",)})
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(version_id=8, name="Release 1.1", confirm=True)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    result = await service.update(version_id=8, name="Release 1.1", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.name == "Release 1.1"


@pytest.mark.asyncio
async def test_update_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(version_id=8, name="Release 1.1", confirm=False)

    assert api.commit_calls == []


@pytest.mark.asyncio
async def test_delete_returns_preview_then_commits() -> None:
    settings = dataclasses.replace(make_settings(), enable_version_write=True)
    service = _service(settings=settings)

    preview = await service.delete(version_id=8, confirm=False)
    assert preview.ready is True
    assert preview.requires_confirmation is True
    assert preview.confirmed is False

    committed = await service.delete(version_id=8, confirm=True)
    assert committed.confirmed is True
    assert committed.result is not None
    assert committed.result.id == 8


@pytest.mark.asyncio
async def test_delete_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeVersionApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(version_id=8, confirm=False)

    assert api.delete_calls == []
