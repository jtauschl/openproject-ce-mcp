from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.services.watcher_service import WatcherService
from openproject_ce_mcp.models import WatcherSummary


def _summary(user_id: int = 5, *, name: str = "Ada Lovelace", login: str | None = "ada") -> WatcherSummary:
    return WatcherSummary(id=user_id, name=name, login=login, url=f"https://op.example.com/users/{user_id}")


class _FakeWatcherApi:
    def __init__(self, watchers: list[WatcherSummary] | None = None) -> None:
        self._watchers = {w.id: w for w in (watchers or [_summary()])}
        self.list_for_work_package_calls: list[int] = []
        self.get_user_calls: list[int] = []
        self.add_calls: list[tuple[int, int]] = []
        self.remove_calls: list[tuple[int, int]] = []

    async def list_for_work_package(self, work_package_id: int) -> list[WatcherSummary]:
        self.list_for_work_package_calls.append(work_package_id)
        return list(self._watchers.values())

    async def get_user(self, user_id: int) -> WatcherSummary:
        self.get_user_calls.append(user_id)
        if user_id not in self._watchers:
            raise AssertionError(f"no fake watcher for user_id {user_id}")
        return self._watchers[user_id]

    async def add(self, work_package_id: int, user_id: int) -> WatcherSummary:
        self.add_calls.append((work_package_id, user_id))
        if user_id not in self._watchers:
            raise AssertionError(f"no fake watcher for user_id {user_id}")
        return self._watchers[user_id]

    async def remove(self, work_package_id: int, user_id: int) -> None:
        self.remove_calls.append((work_package_id, user_id))


def _resolve_work_package_id_ok(resolved_id: int = 9):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_work_package_id_denied():
    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        raise PermissionDeniedError("OpenProject access to this project is disabled.")

    return resolve


def _service(
    *,
    api: _FakeWatcherApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> WatcherService:
    return WatcherService(
        api=api or _FakeWatcherApi(),
        settings=settings or make_settings(),
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- list_for_work_package ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_summaries() -> None:
    api = _FakeWatcherApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.list_for_work_package(9)

    assert result.count == 1
    assert result.results[0].id == 5
    assert resolver.calls == [(9, False)]  # type: ignore[attr-defined]
    assert api.list_for_work_package_calls == [9]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeWatcherApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.list_for_work_package(9)

    assert api.list_for_work_package_calls == []


@pytest.mark.asyncio
async def test_list_for_work_package_masks_hidden_login() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"watcher": ("login",)})
    service = _service(settings=settings)

    result = await service.list_for_work_package(9)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"login"}


# --- add ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_preview_without_confirm_does_not_call_api_add() -> None:
    api = _FakeWatcherApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.add(9, 5, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.work_package_id == 9
    assert result.result is not None
    assert result.result.id == 5
    assert api.get_user_calls == [5]
    assert api.add_calls == []
    # write=True even on preview -- verbatim behavior of client.py's original,
    # which fetched the work package and checked its write-allowlist
    # unconditionally, even for a confirm=False preview call.
    assert resolver.calls == [(9, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_add_commit_with_confirm_calls_api_add() -> None:
    api = _FakeWatcherApi()
    service = _service(api=api)

    result = await service.add(9, 5, confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.work_package_id == 9
    assert result.result is not None
    assert result.result.id == 5
    assert api.add_calls == [(9, 5)]
    assert api.get_user_calls == []


@pytest.mark.asyncio
async def test_add_masks_hidden_login_in_preview_and_commit() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"watcher": ("login",)})

    preview_service = _service(settings=settings)
    preview_result = await preview_service.add(9, 5, confirm=False)
    assert getattr(preview_result.result, "_hidden_keys", frozenset()) == {"login"}

    commit_service = _service(settings=settings)
    commit_result = await commit_service.add(9, 5, confirm=True)
    assert getattr(commit_result.result, "_hidden_keys", frozenset()) == {"login"}


@pytest.mark.asyncio
async def test_add_denies_write_outside_write_allowlist() -> None:
    api = _FakeWatcherApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.add(9, 5, confirm=True)

    assert api.add_calls == []


@pytest.mark.asyncio
async def test_add_denies_write_even_without_confirm() -> None:
    """The write-allowlist check (via resolve_work_package_id(write=True))
    runs BEFORE the confirm branch, not just as part of the confirm=True
    commit path -- found missing during this migration's step-6 self-audit.
    A confirm=True-only denial test can't distinguish "checked before
    confirm" from "checked only when confirming"; this test isolates it by
    denying on a confirm=False (preview) call, where no api.get_user call
    should happen either."""
    api = _FakeWatcherApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.add(9, 5, confirm=False)

    assert api.get_user_calls == []
    assert api.add_calls == []


# --- remove -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_preview_without_confirm_does_not_call_api_remove() -> None:
    api = _FakeWatcherApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.remove(9, 5, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.work_package_id == 9
    assert result.result is None
    assert api.remove_calls == []
    assert resolver.calls == [(9, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_remove_commit_with_confirm_calls_api_remove() -> None:
    api = _FakeWatcherApi()
    service = _service(api=api)

    result = await service.remove(9, 5, confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.work_package_id == 9
    assert result.result is None
    assert api.remove_calls == [(9, 5)]


@pytest.mark.asyncio
async def test_remove_denies_write_outside_write_allowlist() -> None:
    api = _FakeWatcherApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.remove(9, 5, confirm=True)

    assert api.remove_calls == []


@pytest.mark.asyncio
async def test_remove_denies_write_even_without_confirm() -> None:
    """Mirrors test_add_denies_write_even_without_confirm: the write-allowlist
    check must fire even on a confirm=False preview call, not only as part
    of the confirm=True commit path."""
    api = _FakeWatcherApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.remove(9, 5, confirm=False)

    assert api.remove_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_login_hidden_by_watcher_scope_not_user_scope() -> None:
    """Regression test for the entity="watcher" vs a same-shaped neighbor
    hide-field bug class (same bug class as the Priority/Notification
    findings)."""
    settings_user_hidden = dataclasses.replace(make_settings(), hidden_fields={"user": ("login",)})
    service_user_hidden = _service(settings=settings_user_hidden)
    result_user_hidden = await service_user_hidden.list_for_work_package(9)
    assert getattr(result_user_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_watcher_hidden = dataclasses.replace(make_settings(), hidden_fields={"watcher": ("login",)})
    service_watcher_hidden = _service(settings=settings_watcher_hidden)
    result_watcher_hidden = await service_watcher_hidden.list_for_work_package(9)
    assert getattr(result_watcher_hidden.results[0], "_hidden_keys", frozenset()) == {"login"}
