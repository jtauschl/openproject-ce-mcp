from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.current_user_api import CurrentUserRecord
from openproject_ce_mcp.app.resolvers.current_user_resolver import CurrentUserResolver
from openproject_ce_mcp.models import CurrentUser


class _FakeCurrentUserApi:
    def __init__(self, record: CurrentUserRecord | None = None) -> None:
        self._record = record or CurrentUserRecord(summary=CurrentUser(id=99, name="Alice", login="alice"))
        self.get_current_user_calls = 0

    async def get_current_user(self) -> CurrentUserRecord:
        self.get_current_user_calls += 1
        return self._record


@pytest.mark.asyncio
async def test_call_returns_the_current_user() -> None:
    api = _FakeCurrentUserApi()
    resolver = CurrentUserResolver(api=api, settings=make_settings())

    current_user = await resolver()

    assert current_user.id == 99
    assert current_user.name == "Alice"
    assert current_user.login == "alice"
    assert api.get_current_user_calls == 1


@pytest.mark.asyncio
async def test_call_checks_principal_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeCurrentUserApi()
    resolver = CurrentUserResolver(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await resolver()

    assert api.get_current_user_calls == 0


@pytest.mark.asyncio
async def test_call_masks_hidden_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"current_user": ("login",)})
    api = _FakeCurrentUserApi()
    resolver = CurrentUserResolver(api=api, settings=settings)

    current_user = await resolver()

    assert current_user._hidden_keys == frozenset({"login"})  # type: ignore[attr-defined]
