"""No write-allowlist-denial test exists here: unlike every project-scoped
domain, User Preferences has no project link and no allowlist concept at all
(self-scoped to the token owner) -- there is nothing for an allowlist to
check. This absence is deliberate, not an oversight."""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.user_preferences_api import UserPreferencesRecord
from openproject_ce_mcp.app.services.user_preferences_service import UserPreferencesService
from openproject_ce_mcp.models import UserPreferences


def _preferences(**overrides: object) -> UserPreferences:
    defaults: dict[str, object] = {
        "id": 1,
        "lang": "en",
        "time_zone": "Europe/Berlin",
        "comment_sort_descending": True,
        "warn_on_leaving_unsaved": False,
        "auto_hide_popups": True,
        "notifications_reminder_time": "08:00",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return UserPreferences(**defaults)  # type: ignore[arg-type]


def _settings(**overrides: object) -> object:
    defaults: dict[str, object] = {"enable_personal_read": True, "enable_personal_write": True}
    defaults.update(overrides)
    return dataclasses.replace(make_settings(), **defaults)


class _FakeUserPreferencesApi:
    def __init__(self, *, record: UserPreferencesRecord | None = None) -> None:
        self._record = record or UserPreferencesRecord(detail=_preferences())
        self.get_calls = 0
        self.commit_update_calls: list[dict] = []

    async def get(self) -> UserPreferencesRecord:
        self.get_calls += 1
        return self._record

    async def commit_update(self, payload: dict) -> UserPreferences:
        self.commit_update_calls.append(payload)
        return _preferences(lang=payload.get("lang", self._record.detail.lang))


def _service(api: _FakeUserPreferencesApi | None = None, *, settings=None) -> UserPreferencesService:
    return UserPreferencesService(api=api or _FakeUserPreferencesApi(), settings=settings or _settings())


@pytest.mark.asyncio
async def test_get_returns_stamped_preferences() -> None:
    api = _FakeUserPreferencesApi()
    service = _service(api)

    result = await service.get()

    assert result.id == 1
    assert result.lang == "en"
    assert api.get_calls == 1


@pytest.mark.asyncio
async def test_get_checks_read_enabled_before_any_api_call() -> None:
    settings = _settings(enable_personal_read=False)
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get()

    assert api.get_calls == 0


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = _settings(hidden_fields={"user_preferences": ("lang",)})
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    result = await service.get()

    assert getattr(result, "_hidden_keys", frozenset()) == {"lang"}


@pytest.mark.asyncio
async def test_lang_hidden_by_user_preferences_scope_not_user_or_personal_scope() -> None:
    """Regression test for the entity="user_preferences" vs a same-named
    neighbor mixup. Two different namespaces are at play here: "personal" is
    the access-scope string (read/write gating), "user_preferences" is the
    masking-entity string (hidden_fields) -- a copy-paste bug could easily
    conflate them, or reuse "user"'s entity string since both domains touch
    user-owned data.
    """
    settings_user_hidden = _settings(hidden_fields={"user": ("lang",)})
    result_user_hidden = await _service(settings=settings_user_hidden).get()
    assert getattr(result_user_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_personal_hidden = _settings(hidden_fields={"personal": ("lang",)})
    result_personal_hidden = await _service(settings=settings_personal_hidden).get()
    assert getattr(result_personal_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_correctly_hidden = _settings(hidden_fields={"user_preferences": ("lang",)})
    result_correctly_hidden = await _service(settings=settings_correctly_hidden).get()
    assert getattr(result_correctly_hidden, "_hidden_keys", frozenset()) == {"lang"}


@pytest.mark.asyncio
async def test_update_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeUserPreferencesApi()
    service = _service(api)

    result = await service.update(lang="de", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None
    assert result.payload == {"lang": "de"}
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = _settings(hidden_fields={"user_preferences": ("time_zone",)})
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    result = await service.update(lang="de", confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [{"lang": "de"}]
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"time_zone"}


@pytest.mark.asyncio
async def test_update_checks_write_enabled_even_on_preview_not_only_on_commit() -> None:
    """Verbatim port of client.py:3542's gate placement: the write-scope
    check sits at the TOP of update(), before the confirm branch -- so even
    a preview call (confirm=False) is denied without personal-write, unlike
    DocumentService's ordering (gate only inside the confirmed branch). This
    must not be silently normalized to the Document-style ordering.
    """
    settings = _settings(enable_personal_write=False)
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(lang="de", confirm=False)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_checks_write_enabled_on_commit() -> None:
    settings = _settings(enable_personal_write=False)
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(lang="de", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_hidden_field_is_being_written() -> None:
    settings = _settings(hidden_fields={"user_preferences": ("lang",)})
    api = _FakeUserPreferencesApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(lang="de", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_does_not_perform_a_prerequisite_get() -> None:
    """Verbatim port of client.py's original: update_my_preferences PATCHes
    directly with no fetch-current-resource step first, unlike
    DocumentService.update() which must GET to obtain project_link. There is
    no project link to derive here at all.
    """
    api = _FakeUserPreferencesApi()
    service = _service(api)

    await service.update(lang="de", confirm=True)

    assert api.get_calls == 0
