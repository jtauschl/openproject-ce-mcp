from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.role_api import RoleRecord
from openproject_ce_mcp.app.services.role_service import RoleService
from openproject_ce_mcp.models import RoleSummary
from openproject_ce_mcp.tools import _to_payload


def _role_summary(role_id: int = 8, name: str = "Project admin") -> RoleSummary:
    return RoleSummary(id=role_id, name=name, url=f"https://op.example.com/roles/{role_id}")


class _FakeRoleApi:
    def __init__(self, *, records: list[RoleRecord] | None = None, total: int | None = None) -> None:
        self._records = records if records is not None else [RoleRecord(summary=_role_summary())]
        self._total = total if total is not None else len(self._records)
        self.list_roles_calls: list[tuple[int, int]] = []

    async def list_roles(self, *, offset: int, page_size: int) -> tuple[list[RoleRecord], int]:
        self.list_roles_calls.append((offset, page_size))
        return list(self._records), self._total


def _service(api: _FakeRoleApi | None = None, *, settings=None) -> RoleService:
    return RoleService(api=api or _FakeRoleApi(), settings=settings or make_settings())


@pytest.mark.asyncio
async def test_list_roles_returns_stamped_summaries() -> None:
    api = _FakeRoleApi()
    service = _service(api)

    result = await service.list_roles()

    assert result.count == 1
    assert result.results[0].id == 8
    assert result.results[0].name == "Project admin"
    # The server ignores offset/pageSize for /api/v3/roles and always
    # returns the full collection, so the Service always fetches with
    # max_results (not the caller's effective_limit) and slices client-side.
    assert api.list_roles_calls == [(1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_roles_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeRoleApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_roles()

    assert api.list_roles_calls == []


@pytest.mark.asyncio
async def test_list_roles_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"role": ("url",)})
    api = _FakeRoleApi()
    service = _service(api, settings=settings)

    result = await service.list_roles()
    role = result.results[0]

    assert role._hidden_keys == frozenset({"url"})
    serialized = _to_payload(role)
    assert "url" not in serialized
    assert serialized["id"] == 8


@pytest.mark.asyncio
async def test_role_hidden_by_role_scope_not_membership_scope() -> None:
    """Regression test for the entity="role" vs a same-named neighbor
    ("membership") hide-field bug class (same bug class the runbook flags as
    having independently hit News/Documents/Actions & Capabilities'
    pre-migration or pre-audit code)."""
    settings_membership_hidden = dataclasses.replace(make_settings(), hidden_fields={"membership": ("name",)})
    service_membership_hidden = _service(settings=settings_membership_hidden)
    result_membership_hidden = await service_membership_hidden.list_roles()
    assert getattr(result_membership_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_role_hidden = dataclasses.replace(make_settings(), hidden_fields={"role": ("name",)})
    service_role_hidden = _service(settings=settings_role_hidden)
    result_role_hidden = await service_role_hidden.list_roles()
    assert getattr(result_role_hidden.results[0], "_hidden_keys", frozenset()) == {"name"}


@pytest.mark.asyncio
async def test_list_roles_paginates_client_side_when_server_ignores_pagination() -> None:
    """Regression found via a live Docker integration run against
    real OpenProject 16.6.10/17.4.1/17.5.1: /api/v3/roles ignores offset/pageSize
    server-side and always returns the full collection (verified against
    op-sources/17.6 -- RoleCollectionRepresenter subclasses UnpaginatedCollection,
    not OffsetPaginatedCollection). This fake models exactly that: it always
    returns every configured record regardless of what offset/page_size it's
    called with, and its own `total` matches the full record count (never a
    larger, server-claimed total the client can't actually retrieve) -- the bug
    was trusting a `total` figure disconnected from what was actually fetched.
    """
    records = [RoleRecord(summary=_role_summary(role_id=i, name=f"Role {i}")) for i in range(12)]
    api = _FakeRoleApi(records=records, total=12)
    service = _service(api)

    result = await service.list_roles(offset=1, limit=1)

    assert result.count == 1
    assert result.total == 12
    assert result.next_offset == 2
    assert result.truncated is True
    # The fetch always requests the full collection (max_results), not the
    # caller's limit=1 -- the server would ignore a smaller page_size anyway.
    assert api.list_roles_calls == [(1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_roles_not_truncated_on_last_page() -> None:
    records = [RoleRecord(summary=_role_summary())]
    api = _FakeRoleApi(records=records, total=1)
    service = _service(api)

    result = await service.list_roles(offset=1, limit=20)

    assert result.next_offset is None
    assert result.truncated is False
