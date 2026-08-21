from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.caches import SingletonCache
from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.current_user_api import CurrentUserRecord
from openproject_ce_mcp.app.services.current_user_service import CurrentUserService
from openproject_ce_mcp.models import CurrentUser


class _FakeCurrentUserApi:
    def __init__(self, record: CurrentUserRecord | None = None) -> None:
        self._record = record or CurrentUserRecord(summary=CurrentUser(id=99, name="Alice", login="alice"))
        self.get_current_user_calls = 0

    async def get_current_user(self) -> CurrentUserRecord:
        self.get_current_user_calls += 1
        return self._record


def _service(
    api: _FakeCurrentUserApi | None = None, *, settings=None, cache: SingletonCache | None = None
) -> CurrentUserService:
    return CurrentUserService(
        api=api or _FakeCurrentUserApi(),
        settings=settings or make_settings(),
        cache=cache if cache is not None else SingletonCache(),
    )


@pytest.mark.asyncio
async def test_get_current_user_returns_the_current_user() -> None:
    service = _service()

    current_user = await service.get_current_user()

    assert current_user.id == 99
    assert current_user.name == "Alice"


@pytest.mark.asyncio
async def test_get_current_user_checks_principal_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeCurrentUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_current_user()

    assert api.get_current_user_calls == 0


@pytest.mark.asyncio
async def test_get_current_user_masks_hidden_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"current_user": ("login",)})
    service = _service(settings=settings)

    current_user = await service.get_current_user()

    assert current_user._hidden_keys == frozenset({"login"})  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_current_user_does_not_call_the_api_twice() -> None:
    api = _FakeCurrentUserApi()
    service = _service(api)

    await service.get_current_user()
    await service.get_current_user()

    assert api.get_current_user_calls == 1


@pytest.mark.asyncio
async def test_get_current_user_still_gates_a_read_after_the_cache_is_populated() -> None:
    """A cache hit must not bypass the read-enablement gate -- the gate check
    runs on every call, only the underlying API fetch is skipped."""
    cache: SingletonCache = SingletonCache()
    api = _FakeCurrentUserApi()
    await _service(api, cache=cache).get_current_user()

    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    gated_service = _service(api, settings=settings, cache=cache)

    with pytest.raises(PermissionDeniedError):
        await gated_service.get_current_user()


@pytest.mark.asyncio
async def test_get_current_user_shares_its_cache_with_the_resolver() -> None:
    """cache is the SAME instance client.py also gives CurrentUserResolver --
    a fetch via the Service must be visible to the Resolver without a
    second API call."""
    from openproject_ce_mcp.app.resolvers.current_user_resolver import CurrentUserResolver

    api = _FakeCurrentUserApi()
    cache: SingletonCache = SingletonCache()
    service = _service(api, cache=cache)
    resolver = CurrentUserResolver(api=api, settings=make_settings(), cache=cache)

    await service.get_current_user()
    await resolver()

    assert api.get_current_user_calls == 1
