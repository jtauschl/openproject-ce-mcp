from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.action_capability_api import ActionRecord, CapabilityRecord
from openproject_ce_mcp.app.services.action_capability_service import ActionCapabilityService
from openproject_ce_mcp.models import ActionSummary, CapabilitySummary
from openproject_ce_mcp.tools import _to_payload


def _action_summary(action_id: str = "update") -> ActionSummary:
    return ActionSummary(id=action_id, url=f"https://op.example.com/actions/{action_id}")


def _capability_summary(
    capability_id: str = "update-project",
    *,
    action_id: str | None = "update",
    principal_id: int | None = 5,
    principal_name: str | None = "Alice",
    context: str | None = "Demo",
) -> CapabilitySummary:
    return CapabilitySummary(
        id=capability_id,
        action_id=action_id,
        principal_id=principal_id,
        principal_name=principal_name,
        context=context,
        url=f"https://op.example.com/capabilities/{capability_id}",
    )


class _FakeActionCapabilityApi:
    def __init__(
        self,
        *,
        action_records: list[ActionRecord] | None = None,
        action_total: int | None = None,
        capability_records: list[CapabilityRecord] | None = None,
        capability_total: int | None = None,
    ) -> None:
        self._action_records = (
            action_records if action_records is not None else [ActionRecord(summary=_action_summary())]
        )
        self._action_total = action_total if action_total is not None else len(self._action_records)
        self._capability_records = (
            capability_records if capability_records is not None else [CapabilityRecord(summary=_capability_summary())]
        )
        self._capability_total = capability_total if capability_total is not None else len(self._capability_records)
        self.list_actions_calls: list[tuple[int, int]] = []
        self.list_capabilities_calls: list[tuple[list[dict[str, object]], int, int]] = []

    async def list_actions(self, *, offset: int, page_size: int) -> tuple[list[ActionRecord], int]:
        self.list_actions_calls.append((offset, page_size))
        return list(self._action_records), self._action_total

    async def list_capabilities(
        self, *, filters: list[dict[str, object]], offset: int, page_size: int
    ) -> tuple[list[CapabilityRecord], int]:
        self.list_capabilities_calls.append((filters, offset, page_size))
        return list(self._capability_records), self._capability_total


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _denying_resolve_project_ref(message: str):
    async def _resolve(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError(message)

    return _resolve


def _service(
    api: _FakeActionCapabilityApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> ActionCapabilityService:
    api = api or _FakeActionCapabilityApi()
    return ActionCapabilityService(
        api=api,
        settings=settings or make_settings(),
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_actions_returns_stamped_summaries() -> None:
    api = _FakeActionCapabilityApi()
    service = _service(api)

    result = await service.list_actions()

    assert result.count == 1
    assert result.results[0].id == "update"
    assert api.list_actions_calls == [(1, make_settings().default_page_size)]


@pytest.mark.asyncio
async def test_list_actions_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeActionCapabilityApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_actions()

    assert api.list_actions_calls == []


@pytest.mark.asyncio
async def test_list_actions_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"action": ("url",)})
    api = _FakeActionCapabilityApi()
    service = _service(api, settings=settings)

    result = await service.list_actions()
    action = result.results[0]

    assert action._hidden_keys == frozenset({"url"})
    serialized = _to_payload(action)
    assert "url" not in serialized
    assert serialized["id"] == "update"


@pytest.mark.asyncio
async def test_list_actions_paginates_using_server_total() -> None:
    api = _FakeActionCapabilityApi(action_total=50)
    service = _service(api)

    result = await service.list_actions(offset=1, limit=10)

    assert result.total == 50
    assert result.truncated is True
    assert result.next_offset == 2


@pytest.mark.asyncio
async def test_list_capabilities_requires_project_or_capability_id() -> None:
    service = _service()

    with pytest.raises(InvalidInputError, match="project or capability_id"):
        await service.list_capabilities()


@pytest.mark.asyncio
async def test_list_capabilities_filters_by_capability_id_without_project_resolution() -> None:
    api = _FakeActionCapabilityApi()
    calls: list[bool] = []

    async def resolve_project_ref_tracking(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    service = _service(api, resolve_project_ref=resolve_project_ref_tracking)

    result = await service.list_capabilities(capability_id="update-project")

    assert result.count == 1
    assert calls == []  # no project given -- resolve_project_ref must not be called
    assert api.list_capabilities_calls[0][0] == [{"id": {"operator": "=", "values": ["update-project"]}}]


@pytest.mark.asyncio
async def test_list_capabilities_filters_by_project_context() -> None:
    api = _FakeActionCapabilityApi()
    service = _service(api)

    result = await service.list_capabilities(project="demo")

    assert result.count == 1
    assert result.results[0].principal_name == "Alice"
    assert api.list_capabilities_calls[0][0] == [{"context": {"operator": "=", "values": ["p6"]}}]


@pytest.mark.asyncio
async def test_list_capabilities_combines_project_and_capability_id_filters() -> None:
    api = _FakeActionCapabilityApi()
    service = _service(api)

    await service.list_capabilities(project="demo", capability_id="update-project")

    filters = api.list_capabilities_calls[0][0]
    assert {"id": {"operator": "=", "values": ["update-project"]}} in filters
    assert {"context": {"operator": "=", "values": ["p6"]}} in filters


@pytest.mark.asyncio
async def test_list_capabilities_passes_write_false_to_resolve_project_ref() -> None:
    calls: list[bool] = []

    async def resolve_project_ref_tracking(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeActionCapabilityApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking)

    await service.list_capabilities(project="demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_capabilities_propagates_project_read_allowlist_denial() -> None:
    api = _FakeActionCapabilityApi()
    service = _service(api, resolve_project_ref=_denying_resolve_project_ref("OPENPROJECT_READ_PROJECTS"))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.list_capabilities(project="demo")

    assert api.list_capabilities_calls == []


@pytest.mark.asyncio
async def test_list_capabilities_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeActionCapabilityApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_capabilities(capability_id="update-project")

    assert api.list_capabilities_calls == []


@pytest.mark.asyncio
async def test_capability_hidden_by_capability_scope_not_action_scope() -> None:
    """Regression test for the entity="capability" vs a same-named neighbor
    ("action") hide-field bug class (same bug class the runbook flags as
    having independently hit News and Documents' pre-migration code)."""
    settings_action_hidden = dataclasses.replace(make_settings(), hidden_fields={"action": ("principal_name",)})
    service_action_hidden = _service(settings=settings_action_hidden)
    result_action_hidden = await service_action_hidden.list_capabilities(capability_id="update-project")
    assert getattr(result_action_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_capability_hidden = dataclasses.replace(make_settings(), hidden_fields={"capability": ("principal_name",)})
    service_capability_hidden = _service(settings=settings_capability_hidden)
    result_capability_hidden = await service_capability_hidden.list_capabilities(capability_id="update-project")
    assert getattr(result_capability_hidden.results[0], "_hidden_keys", frozenset()) == {"principal_name"}
