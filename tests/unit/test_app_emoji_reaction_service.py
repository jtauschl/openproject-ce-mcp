from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, OpenProjectServerError, PermissionDeniedError
from openproject_ce_mcp.app.services.emoji_reaction_service import EmojiReactionService
from openproject_ce_mcp.models import EmojiReactionSummary

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "secret"}


def _summary(reaction: str = "thumbs_up", *, count: int = 2) -> EmojiReactionSummary:
    return EmojiReactionSummary(reaction=reaction, emoji="\U0001f44d", count=count, users=["Ada Lovelace"])


class _FakeEmojiReactionApi:
    def __init__(self, reactions: list[EmojiReactionSummary] | None = None) -> None:
        self._reactions = reactions or [_summary()]
        self.list_for_work_package_calls: list[int] = []
        self.get_activity_calls: list[int] = []
        self.toggle_calls: list[tuple[int, str]] = []
        self.activity_work_package_href: str | None = "/api/v3/work_packages/42"

    async def list_for_work_package(self, work_package_id: int) -> list[EmojiReactionSummary]:
        self.list_for_work_package_calls.append(work_package_id)
        return list(self._reactions)

    async def get_activity(self, activity_id: int) -> dict:
        self.get_activity_calls.append(activity_id)
        links = {}
        if self.activity_work_package_href is not None:
            links["workPackage"] = {"href": self.activity_work_package_href}
        return {"id": activity_id, "_links": links}

    async def toggle(self, activity_id: int, reaction: str) -> list[EmojiReactionSummary]:
        self.toggle_calls.append((activity_id, reaction))
        return list(self._reactions)


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = None) -> None:
        self._project_link = project_link or {"href": "/api/v3/projects/6"}
        self.get_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        return {"id": int(work_package_ref), "_links": {"project": self._project_link}}

    async def get_by_href(self, href: str) -> dict:
        raise AssertionError("get_by_href should not be used by EmojiReactionService")


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
    api: _FakeEmojiReactionApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> EmojiReactionService:
    return EmojiReactionService(
        api=api or _FakeEmojiReactionApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- list_for_work_package ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_summaries() -> None:
    api = _FakeEmojiReactionApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.list_for_work_package(9)

    assert result.count == 1
    assert result.results[0].reaction == "thumbs_up"
    assert resolver.calls == [(9, False)]  # type: ignore[attr-defined]
    assert api.list_for_work_package_calls == [9]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeEmojiReactionApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.list_for_work_package(9)

    assert api.list_for_work_package_calls == []


@pytest.mark.asyncio
async def test_list_for_work_package_masks_hidden_users() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"emoji_reaction": ("users",)})
    service = _service(settings=settings)

    result = await service.list_for_work_package(9)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"users"}


# --- toggle -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_rejects_invalid_reaction() -> None:
    service = _service()

    with pytest.raises(InvalidInputError, match="reaction must be one of"):
        await service.toggle(1988, "banana", confirm=False)


@pytest.mark.asyncio
async def test_toggle_fails_closed_without_work_package_link() -> None:
    api = _FakeEmojiReactionApi()
    api.activity_work_package_href = None
    service = _service(api=api)

    with pytest.raises(OpenProjectServerError, match="missing a work package link"):
        await service.toggle(1988, "thumbs_up", confirm=True)

    assert api.toggle_calls == []


@pytest.mark.asyncio
async def test_toggle_preview_without_confirm_does_not_call_api_toggle() -> None:
    api = _FakeEmojiReactionApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api)

    result = await service.toggle(1988, "thumbs_up", confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.activity_id == 1988
    assert result.reaction == "thumbs_up"
    assert result.result is None
    assert api.toggle_calls == []
    # The allowlist check runs even on preview -- verbatim behavior of
    # client.py's original.
    assert work_package_lookup_api.get_calls == ["42"]


@pytest.mark.asyncio
async def test_toggle_commit_with_confirm_calls_api_toggle() -> None:
    api = _FakeEmojiReactionApi()
    service = _service(api=api)

    result = await service.toggle(1988, "thumbs_up", confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.result is not None
    assert result.result.count == 1
    assert result.result.results[0].reaction == "thumbs_up"
    assert api.toggle_calls == [(1988, "thumbs_up")]


@pytest.mark.asyncio
async def test_toggle_masks_hidden_users_in_commit_result() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"emoji_reaction": ("users",)})
    service = _service(settings=settings)

    result = await service.toggle(1988, "thumbs_up", confirm=True)

    assert getattr(result.result.results[0], "_hidden_keys", frozenset()) == {"users"}


@pytest.mark.asyncio
async def test_toggle_denies_write_outside_write_allowlist() -> None:
    api = _FakeEmojiReactionApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.toggle(1988, "thumbs_up", confirm=True)

    assert api.toggle_calls == []


@pytest.mark.asyncio
async def test_toggle_denies_write_even_without_confirm() -> None:
    """The write-allowlist check runs BEFORE the confirm branch, not just as
    part of the confirm=True commit path -- must fire on a preview call too."""
    api = _FakeEmojiReactionApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.toggle(1988, "thumbs_up", confirm=False)

    assert api.toggle_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_users_hidden_by_emoji_reaction_scope_not_watcher_scope() -> None:
    """Regression test for the entity="emoji_reaction" vs a same-shaped
    neighbor hide-field bug class (same bug class as OPM-1627's
    Priority/Notification findings)."""
    settings_watcher_hidden = dataclasses.replace(make_settings(), hidden_fields={"watcher": ("users",)})
    service_watcher_hidden = _service(settings=settings_watcher_hidden)
    result_watcher_hidden = await service_watcher_hidden.list_for_work_package(9)
    assert getattr(result_watcher_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_emoji_hidden = dataclasses.replace(make_settings(), hidden_fields={"emoji_reaction": ("users",)})
    service_emoji_hidden = _service(settings=settings_emoji_hidden)
    result_emoji_hidden = await service_emoji_hidden.list_for_work_package(9)
    assert getattr(result_emoji_hidden.results[0], "_hidden_keys", frozenset()) == {"users"}
