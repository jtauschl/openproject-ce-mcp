from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.user_api import UserFormResult, UserRecord
from openproject_ce_mcp.app.services.user_service import UserService
from openproject_ce_mcp.models import UserDetail, UserSummary
from openproject_ce_mcp.tools import _to_payload

BASE_URL = "https://op.example.com"


def _summary(user_id: int = 5, *, login: str = "ada", name: str = "Ada Lovelace") -> UserSummary:
    return UserSummary(
        id=user_id,
        name=name,
        login=login,
        email=f"{login}@example.com",
        status="active",
        admin=False,
        locked=False,
        avatar_url=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
        url=f"{BASE_URL}/users/{user_id}",
        firstname="Ada",
        lastname="Lovelace",
    )


def _detail(user_id: int = 5, **kwargs: object) -> UserDetail:
    summary = _summary(user_id, **kwargs)  # type: ignore[arg-type]
    return UserDetail(
        id=summary.id,
        name=summary.name,
        login=summary.login,
        email=summary.email,
        status=summary.status,
        admin=summary.admin,
        locked=summary.locked,
        avatar_url=summary.avatar_url,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        language="en",
        identity_url=None,
        auth_source=None,
        groups=[],
        url=summary.url,
        firstname=summary.firstname,
        lastname=summary.lastname,
    )


def _record(**kwargs: object) -> UserRecord:
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    return UserRecord(summary=_summary(**kwargs), to_detail=lambda: detail)  # type: ignore[arg-type]


class _FakeUserApi:
    def __init__(self, records: list[UserRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_users_calls: list[tuple[int, int]] = []
        self.list_users_search_calls: list[int] = []
        self.get_user_calls: list[str] = []
        self.create_form_calls: list[dict] = []
        self.update_form_calls: list[tuple[int, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.commit_delete_calls: list[int] = []
        self.commit_lock_calls: list[int] = []
        self.commit_unlock_calls: list[int] = []
        self.validation_errors: dict[str, str] = {}

    async def list_users(self, *, offset: int, page_size: int) -> tuple[list[UserRecord], int]:
        self.list_users_calls.append((offset, page_size))
        records = list(self._records.values())
        return records, len(records)

    async def list_users_search(self, *, page_size: int) -> list[UserRecord]:
        self.list_users_search_calls.append(page_size)
        return list(self._records.values())

    async def get_user(self, user_ref: str) -> UserRecord:
        self.get_user_calls.append(user_ref)
        for record in self._records.values():
            if str(record.summary.id) == user_ref or record.summary.login == user_ref:
                return record
        raise AssertionError(f"no fake record for user_ref {user_ref}")

    async def create_form(self, payload: dict) -> UserFormResult:
        self.create_form_calls.append(payload)
        # Real OpenProject never echoes `password` back in the form response
        # (a security precaution) -- mirroring that here is what makes
        # test_create_restores_password_into_the_commit_payload below able to
        # actually catch a regression of the commit_payload_override fix; a
        # fake that echoed password back verbatim would pass even if
        # UserService.create() went back to committing form.payload as-is.
        echoed = {k: v for k, v in payload.items() if k != "password"}
        return UserFormResult(payload=echoed, validation_errors=self.validation_errors)

    async def update_form(self, user_id: int, payload: dict) -> UserFormResult:
        self.update_form_calls.append((user_id, payload))
        return UserFormResult(payload=payload, validation_errors=self.validation_errors)

    async def commit_create(self, payload: dict) -> UserDetail:
        self.commit_create_calls.append(payload)
        return _detail(user_id=42)

    async def commit_update(self, user_id: int, payload: dict) -> UserDetail:
        self.commit_update_calls.append((user_id, payload))
        return _detail(user_id=user_id)

    async def commit_delete(self, user_id: int) -> None:
        self.commit_delete_calls.append(user_id)

    async def commit_lock(self, user_id: int) -> UserDetail:
        self.commit_lock_calls.append(user_id)
        return _detail(user_id=user_id)

    async def commit_unlock(self, user_id: int) -> UserDetail:
        self.commit_unlock_calls.append(user_id)
        return _detail(user_id=user_id)


def _admin_settings(**overrides: object):
    # admin read/write both default False (config.py) -- unlike most other
    # scopes, so every positive-path test needs enable_admin_read=True
    # explicitly, not just make_settings()'s permissive project scope.
    return dataclasses.replace(make_settings(), enable_admin_read=True, **overrides)


def _service(api: _FakeUserApi | None = None, *, settings=None) -> UserService:
    return UserService(api=api or _FakeUserApi(), settings=settings or _admin_settings())


def _admin_write_settings(**overrides: object):
    return _admin_settings(enable_admin_write=True, **overrides)


# --- list_users --------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_returns_stamped_summaries() -> None:
    api = _FakeUserApi()
    service = _service(api)

    result = await service.list_users()

    assert result.count == 1
    assert result.results[0].id == 5
    assert result.results[0].login == "ada"
    assert api.list_users_calls == [(1, make_settings().default_page_size)]
    assert api.list_users_search_calls == []


@pytest.mark.asyncio
async def test_list_users_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_users()

    assert api.list_users_calls == []
    assert api.list_users_search_calls == []


@pytest.mark.asyncio
async def test_list_users_applies_hidden_field_masking() -> None:
    settings = _admin_settings(hidden_fields={"user": ("email",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    result = await service.list_users()
    user = result.results[0]

    assert user._hidden_keys == frozenset({"email"})
    serialized = _to_payload(user)
    assert "email" not in serialized
    assert serialized["id"] == 5


@pytest.mark.asyncio
async def test_list_users_hidden_by_user_scope_not_group_or_user_preferences_scope() -> None:
    """Regression test for the entity="user" vs a same-named neighbor
    hide-field bug class (this project's lessons log records this recurring
    across Role/Document/News/Actions & Capabilities' pre-migration or
    pre-audit code) -- found missing for User specifically during the 18th
    domain's (User Preferences) step-6 self-audit, which widened scope to
    every already-migrated domain rather than just the newest. "group" and
    "user_preferences" are the two most plausible same-named-neighbor mixups
    for "user" -- both touch user-owned data, and "user_preferences" is a
    brand new entity string as of this same migration.
    """
    settings_group_hidden = _admin_settings(hidden_fields={"group": ("login",)})
    result_group_hidden = await _service(settings=settings_group_hidden).list_users()
    assert getattr(result_group_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_user_preferences_hidden = _admin_settings(hidden_fields={"user_preferences": ("login",)})
    result_user_preferences_hidden = await _service(settings=settings_user_preferences_hidden).list_users()
    assert getattr(result_user_preferences_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_user_hidden = _admin_settings(hidden_fields={"user": ("login",)})
    result_user_hidden = await _service(settings=settings_user_hidden).list_users()
    assert getattr(result_user_hidden.results[0], "_hidden_keys", frozenset()) == {"login"}


@pytest.mark.asyncio
async def test_list_users_search_overfetches_and_filters_then_paginates() -> None:
    records = [
        _record(user_id=1, login="alice", name="Alice"),
        _record(user_id=2, login="bob", name="Bob"),
        _record(user_id=3, login="alison", name="Alison"),
    ]
    api = _FakeUserApi(records)
    service = _service(api)

    result = await service.list_users(search="ali", limit=1, offset=2)

    # 2 survivors match "ali" (alice, alison); page 2 with limit=1 is the 2nd survivor.
    assert result.total == 2
    assert result.count == 1
    assert result.results[0].login == "alison"
    assert api.list_users_search_calls == [make_settings().max_results]
    assert api.list_users_calls == []


@pytest.mark.asyncio
async def test_list_users_search_matches_login_and_email_case_insensitively() -> None:
    records = [_record(user_id=1, login="ADA", name="Someone Else")]
    api = _FakeUserApi(records)
    service = _service(api)

    result = await service.list_users(search="ada")

    assert result.count == 1


# --- get_user ------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_returns_stamped_detail() -> None:
    api = _FakeUserApi()
    service = _service(api)

    detail = await service.get_user("5")

    assert detail.id == 5
    assert detail.login == "ada"
    assert api.get_user_calls == ["5"]


@pytest.mark.asyncio
async def test_get_user_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_user("5")

    assert api.get_user_calls == []


# --- create ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    api = _FakeUserApi()
    service = _service(api)

    result = await service.create(login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace")

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_validation_errors_present() -> None:
    api = _FakeUserApi()
    api.validation_errors = {"email": "is invalid"}
    service = _service(api)

    result = await service.create(login="ada", email="bad", firstname="Ada", lastname="Lovelace")

    assert result.ready is False
    assert result.validation_errors == {"email": "is invalid"}
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_when_confirmed_and_admin_write_enabled() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(
        login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True
    )

    assert result.confirmed is True
    assert result.user_id == 42
    assert api.commit_create_calls == [
        {
            "login": "ada",
            "email": "ada@example.com",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "admin": False,
            "status": "active",
        }
    ]


@pytest.mark.asyncio
async def test_create_restores_password_into_the_commit_payload() -> None:
    # Regression: OpenProject's users/form response never echoes `password`
    # back (see _FakeUserApi.create_form's own comment on this). An earlier
    # version of create() committed form.payload verbatim, silently dropping
    # password even though the original request (including it) had passed
    # validation -- the real write then failed server-side with "Password
    # can't be blank." despite the preview reporting ready=True. This test
    # would NOT catch that regression without create_form's fake also
    # dropping password from its echoed payload, same as the real server.
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(
        login="ada",
        email="ada@example.com",
        firstname="Ada",
        lastname="Lovelace",
        password="Aa1!secret",
        confirm=True,
    )

    assert result.confirmed is True
    assert api.commit_create_calls == [
        {
            "login": "ada",
            "email": "ada@example.com",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "admin": False,
            "status": "active",
            "password": "Aa1!secret",
        }
    ]


@pytest.mark.asyncio
async def test_create_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeUserApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.create(login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_a_written_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("email",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True)

    assert api.create_form_calls == []
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_optional_language_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("language",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(
            login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", language="en", confirm=True
        )

    assert api.commit_create_calls == []


# --- update ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(user_id=5, login="ada2", confirm=True)

    assert result.confirmed is True
    assert result.user_id == 5
    assert api.commit_update_calls == [(5, {"login": "ada2"})]


@pytest.mark.asyncio
async def test_update_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeUserApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.update(user_id=5, login="ada2", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_the_only_field_being_written_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("login",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(user_id=5, login="ada2", confirm=True)

    assert api.update_form_calls == []
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_does_not_check_fields_the_caller_did_not_set() -> None:
    # A field hidden in config but NOT part of this update call must not
    # block it -- only fields actually present in the call are checked.
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("email",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    result = await service.update(user_id=5, login="ada2", confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [(5, {"login": "ada2"})]


# --- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_denies_target_outside_admin_write_and_never_calls_commit() -> None:
    api = _FakeUserApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.delete(5, confirm=True)

    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_preview_does_not_call_commit() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(5, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(5, confirm=True)

    assert result.confirmed is True
    assert result.user_id == 5
    assert api.commit_delete_calls == [5]


# --- lock/unlock ---------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_denies_without_admin_write_and_never_calls_commit() -> None:
    api = _FakeUserApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.lock(5, confirm=True)

    assert api.commit_lock_calls == []


@pytest.mark.asyncio
async def test_lock_preview_does_not_call_commit() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.lock(5, confirm=False)

    assert result.action == "lock"
    assert result.confirmed is False
    assert result.result is None
    assert api.commit_lock_calls == []


@pytest.mark.asyncio
async def test_lock_commits_when_confirmed() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.lock(5, confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert api.commit_lock_calls == [5]


@pytest.mark.asyncio
async def test_lock_rejects_when_locked_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("locked",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.lock(5, confirm=True)

    assert api.commit_lock_calls == []


@pytest.mark.asyncio
async def test_unlock_rejects_when_locked_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"user": ("locked",)})
    api = _FakeUserApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.unlock(5, confirm=True)

    assert api.commit_unlock_calls == []


@pytest.mark.asyncio
async def test_unlock_denies_without_admin_write_and_never_calls_commit() -> None:
    api = _FakeUserApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.unlock(5, confirm=True)

    assert api.commit_unlock_calls == []


@pytest.mark.asyncio
async def test_unlock_commits_when_confirmed() -> None:
    api = _FakeUserApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.unlock(5, confirm=True)

    assert result.action == "unlock"
    assert result.confirmed is True
    assert api.commit_unlock_calls == [5]
