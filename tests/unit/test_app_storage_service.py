from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.storage_api import StorageRecord
from openproject_ce_mcp.app.services.storage_service import StorageService
from openproject_ce_mcp.models import StorageDetail, StorageSummary
from openproject_ce_mcp.tools import _to_payload


def _summary(
    storage_id: int = 3,
    *,
    name: str = "Seed Nextcloud Storage",
    provider_type: str = "Nextcloud",
    host: str | None = "http://nextcloud.example.com/",
    configured: bool = False,
    has_application_password: bool | None = False,
    forbidden_file_name_characters: str | None = '<>:"\\/|?*',
    tenant_id: str | None = None,
    drive_id: str | None = None,
) -> StorageSummary:
    return StorageSummary(
        id=storage_id,
        name=name,
        provider_type=provider_type,
        host=host,
        configured=configured,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
        has_application_password=has_application_password,
        forbidden_file_name_characters=forbidden_file_name_characters,
        tenant_id=tenant_id,
        drive_id=drive_id,
    )


def _detail(
    storage_id: int = 3, *, authorization_state: str | None = "not_connected", **kwargs: object
) -> StorageDetail:
    summary = _summary(storage_id, **kwargs)  # type: ignore[arg-type]
    return StorageDetail(
        id=summary.id,
        name=summary.name,
        provider_type=summary.provider_type,
        host=summary.host,
        configured=summary.configured,
        authorization_state=authorization_state,
        authentication_method="two_way_oauth2" if summary.provider_type == "Nextcloud" else None,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        has_application_password=summary.has_application_password,
        forbidden_file_name_characters=summary.forbidden_file_name_characters,
        tenant_id=summary.tenant_id,
        drive_id=summary.drive_id,
    )


def _record(**kwargs: object) -> StorageRecord:
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    return StorageRecord(summary=_summary(**kwargs), to_detail=lambda: detail)  # type: ignore[arg-type]


class _FakeStorageApi:
    def __init__(self, records: list[StorageRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.commit_delete_calls: list[int] = []
        self.create_result: StorageDetail | None = None
        self.create_error: Exception | None = None

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[StorageRecord], int]:
        self.list_all_calls.append((offset, page_size))
        records = list(self._records.values())
        return records, len(records)

    async def get(self, storage_id: int) -> StorageRecord:
        self.get_calls.append(storage_id)
        record = self._records.get(storage_id)
        if record is None:
            raise AssertionError(f"no fake record for storage_id {storage_id}")
        return record

    async def commit_create(self, payload: dict) -> StorageDetail:
        self.commit_create_calls.append(payload)
        if self.create_error is not None:
            raise self.create_error
        return self.create_result or _detail(storage_id=42)

    async def commit_update(self, storage_id: int, payload: dict) -> StorageDetail:
        self.commit_update_calls.append((storage_id, payload))
        return _detail(storage_id=storage_id)

    async def commit_delete(self, storage_id: int) -> None:
        self.commit_delete_calls.append(storage_id)


def _admin_settings(**overrides: object):
    return dataclasses.replace(make_settings(), enable_admin_read=True, **overrides)


def _admin_write_settings(**overrides: object):
    return _admin_settings(enable_admin_write=True, **overrides)


def _service(api: _FakeStorageApi | None = None, *, settings=None) -> StorageService:
    return StorageService(api=api or _FakeStorageApi(), settings=settings or _admin_settings())


# --- list_storages -----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_storages_returns_stamped_summaries() -> None:
    api = _FakeStorageApi()
    service = _service(api)

    result = await service.list_storages()

    assert result.count == 1
    assert result.results[0].id == 3
    assert result.results[0].provider_type == "Nextcloud"
    # Fetches everything (bounded by max_results), not effective_limit --
    # storages is an UnpaginatedCollection server-side.
    assert api.list_all_calls == [(1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_storages_paginates_client_side() -> None:
    records = [_record(storage_id=i, name=f"Storage {i}") for i in range(1, 4)]
    api = _FakeStorageApi(records)
    service = _service(api)

    result = await service.list_storages(limit=1, offset=2)

    assert result.total == 3
    assert result.count == 1
    assert result.results[0].id == 2
    assert result.truncated is True
    assert result.next_offset == 3


@pytest.mark.asyncio
async def test_list_storages_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_storages()

    assert api.list_all_calls == []


@pytest.mark.asyncio
async def test_list_storages_applies_hidden_field_masking() -> None:
    settings = _admin_settings(hidden_fields={"storage": ("host",)})
    api = _FakeStorageApi()
    service = _service(api, settings=settings)

    result = await service.list_storages()
    storage = result.results[0]

    assert storage._hidden_keys == frozenset({"host"})
    serialized = _to_payload(storage)
    assert "host" not in serialized
    assert serialized["id"] == 3


# --- get_storage: provider-polymorphic shape ----------------------------------


@pytest.mark.asyncio
async def test_get_storage_nextcloud_populates_nextcloud_only_fields() -> None:
    api = _FakeStorageApi([_record(provider_type="Nextcloud", has_application_password=True)])
    service = _service(api)

    detail = await service.get_storage(3)

    assert detail.provider_type == "Nextcloud"
    assert detail.has_application_password is True
    assert detail.forbidden_file_name_characters == '<>:"\\/|?*'
    assert detail.tenant_id is None
    assert detail.drive_id is None
    assert detail.authentication_method == "two_way_oauth2"


@pytest.mark.asyncio
async def test_get_storage_one_drive_populates_one_drive_only_fields() -> None:
    api = _FakeStorageApi(
        [
            _record(
                provider_type="OneDrive",
                host=None,
                has_application_password=None,
                forbidden_file_name_characters=None,
                tenant_id="11111111-1111-1111-1111-111111111111",
                drive_id="b!driveid1234567890",
            )
        ]
    )
    service = _service(api)

    detail = await service.get_storage(3)

    assert detail.provider_type == "OneDrive"
    assert detail.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert detail.drive_id == "b!driveid1234567890"
    assert detail.has_application_password is None
    assert detail.forbidden_file_name_characters is None
    # authenticationMethod link is only rendered for Nextcloud.
    assert detail.authentication_method is None


@pytest.mark.asyncio
async def test_get_storage_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_storage(3)

    assert api.get_calls == []


# --- create --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(name="New Storage", provider_type="Nextcloud", host="http://nc.example.com/")

    assert result.state == "preview"
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_nextcloud_when_confirmed() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(
        name="New Storage",
        provider_type="Nextcloud",
        host="http://nc.example.com/",
        authentication_method="two_way_oauth2",
        confirm=True,
    )

    assert result.state == "confirmed"
    # authenticationMethod is a link (link_without_resource on
    # StorageRepresenter, op-sources), never a top-level property -- its
    # setter reads ONLY _links.authenticationMethod.href (a full URN), so it
    # must be nested under _links, not sent as a bare "authentication_method"
    # key (which the real representer silently drops).
    assert api.commit_create_calls == [
        {
            "name": "New Storage",
            "_links": {
                "type": {"href": "urn:openproject-org:api:v3:storages:Nextcloud"},
                "origin": {"href": "http://nc.example.com/"},
                "authenticationMethod": {
                    "href": "urn:openproject-org:api:v3:storages:authenticationMethod:TwoWayOAuth2"
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_create_commits_one_drive_without_host() -> None:
    """OneDriveContract validates :host, absence: true -- no `origin` link
    must be sent when host is not given."""
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(
        name="New OneDrive",
        provider_type="OneDrive",
        tenant_id="11111111-1111-1111-1111-111111111111",
        confirm=True,
    )

    assert result.state == "confirmed"
    sent = api.commit_create_calls[0]
    assert "origin" not in sent["_links"]
    assert sent["tenant_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_create_rejects_unknown_provider_type_before_any_api_call() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    with pytest.raises(InvalidInputError, match="provider_type"):
        await service.create(name="X", provider_type="Dropbox", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_unknown_authentication_method_before_any_api_call() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    with pytest.raises(InvalidInputError, match="authentication_method"):
        await service.create(name="X", provider_type="Nextcloud", authentication_method="password", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_propagates_enterprise_gate_rejection_untouched() -> None:
    """Simulates the 422 Enterprise-gate rejection this MCP relies on
    raise_for_status to translate into a clean InvalidInputError -- this test
    proves the Service does not swallow/rewrap that error."""
    api = _FakeStorageApi()
    api.create_error = InvalidInputError("The request can not be handled due to invalid or missing Enterprise token.")
    service = _service(api, settings=_admin_write_settings())

    with pytest.raises(InvalidInputError, match="Enterprise token"):
        await service.create(
            name="New OneDrive",
            provider_type="OneDrive",
            tenant_id="11111111-1111-1111-1111-111111111111",
            confirm=True,
        )


@pytest.mark.asyncio
async def test_create_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeStorageApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.create(name="X", provider_type="Nextcloud", host="http://nc.example.com/", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_preview_also_denied_without_admin_write_enabled() -> None:
    api = _FakeStorageApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.create(name="X", provider_type="Nextcloud", host="http://nc.example.com/", confirm=False)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"storage": ("name",)})
    api = _FakeStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="X", provider_type="Nextcloud", host="http://nc.example.com/", confirm=True)

    assert api.commit_create_calls == []


# --- update ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(storage_id=3, name="Renamed", confirm=True)

    assert result.state == "confirmed"
    assert result.storage_id == 3
    assert api.commit_update_calls == [(3, {"name": "Renamed"})]
    # The confirmed branch never references the fetched detail (its result
    # comes from commit_update), so no prior GET should happen -- only the
    # preview branch (test_update_preview_shows_current_state) needs one.
    assert api.get_calls == []


@pytest.mark.asyncio
async def test_update_preview_shows_current_state() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(storage_id=3, name="Renamed", confirm=False)

    assert result.state == "preview"
    assert api.get_calls == [3]
    assert api.commit_update_calls == []
    assert result.result is not None
    assert result.result.id == 3


@pytest.mark.asyncio
async def test_update_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeStorageApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.update(storage_id=3, name="Renamed", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_host_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"storage": ("host",)})
    api = _FakeStorageApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(storage_id=3, host="http://other.example.com/", confirm=True)

    assert api.commit_update_calls == []


# --- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_denies_without_admin_write_and_never_calls_commit() -> None:
    api = _FakeStorageApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.delete(3, confirm=True)

    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_preview_shows_current_state_and_does_not_commit() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(3, confirm=False)

    assert result.state == "preview"
    assert api.get_calls == [3]
    assert result.result is not None
    assert result.result.id == 3
    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed_with_no_result() -> None:
    api = _FakeStorageApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(3, confirm=True)

    assert result.state == "confirmed"
    assert result.storage_id == 3
    assert result.result is None
    assert api.commit_delete_calls == [3]
    # The confirmed branch never needs the current detail (commit_delete
    # only needs the id) -- only the preview branch fetches it.
    assert api.get_calls == []
