from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.caches import SingletonCache
from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.instance_configuration_api import InstanceConfigurationRecord
from openproject_ce_mcp.app.services.instance_configuration_service import InstanceConfigurationService
from openproject_ce_mcp.models import InstanceConfiguration


def _configuration_summary(*, hours_per_day: int | float | None = 8) -> InstanceConfiguration:
    return InstanceConfiguration(
        host_name="op.example.com",
        maximum_attachment_file_size_bytes=104857600,
        maximum_api_v3_page_size=1000,
        per_page_options=[20, 100],
        duration_format="hours_only",
        hours_per_day=hours_per_day,
        days_per_month=20,
        active_feature_flags=[],
        available_features=[],
        trialling_features=[],
    )


class _FakeInstanceConfigurationApi:
    def __init__(self, record: InstanceConfigurationRecord | None = None) -> None:
        self._record = record or InstanceConfigurationRecord(summary=_configuration_summary())
        self.get_configuration_calls = 0

    async def get_configuration(self) -> InstanceConfigurationRecord:
        self.get_configuration_calls += 1
        return self._record


def _service(
    api: _FakeInstanceConfigurationApi | None = None, *, settings=None, cache: SingletonCache | None = None
) -> InstanceConfigurationService:
    return InstanceConfigurationService(
        api=api or _FakeInstanceConfigurationApi(),
        settings=settings or make_settings(),
        cache=cache if cache is not None else SingletonCache(),
    )


@pytest.mark.asyncio
async def test_get_instance_configuration_returns_the_configuration() -> None:
    service = _service()

    configuration = await service.get_instance_configuration()

    assert configuration.host_name == "op.example.com"
    assert configuration.hours_per_day == 8


@pytest.mark.asyncio
async def test_get_instance_configuration_checks_project_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeInstanceConfigurationApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_instance_configuration()

    assert api.get_configuration_calls == 0


@pytest.mark.asyncio
async def test_get_instance_configuration_masks_hidden_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"instance_configuration": ("host_name",)})
    service = _service(settings=settings)

    configuration = await service.get_instance_configuration()

    assert configuration._hidden_keys == frozenset({"host_name"})  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_instance_configuration_does_not_call_the_api_twice() -> None:
    api = _FakeInstanceConfigurationApi()
    service = _service(api)

    await service.get_instance_configuration()
    await service.get_instance_configuration()

    assert api.get_configuration_calls == 1


@pytest.mark.asyncio
async def test_get_instance_configuration_still_gates_a_read_after_the_cache_is_populated() -> None:
    """A cache hit must not bypass the read-enablement gate -- the gate check
    runs on every call, only the underlying API fetch is skipped."""
    cache: SingletonCache = SingletonCache()
    api = _FakeInstanceConfigurationApi()
    await _service(api, cache=cache).get_instance_configuration()

    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    gated_service = _service(api, settings=settings, cache=cache)

    with pytest.raises(PermissionDeniedError):
        await gated_service.get_instance_configuration()
