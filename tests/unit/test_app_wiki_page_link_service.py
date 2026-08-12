from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.wiki_page_link_api import WikiPageLinkRecord
from openproject_ce_mcp.app.services.wiki_page_link_service import WikiPageLinkService
from openproject_ce_mcp.models import CurrentUser, WikiPageLinkSummary


def _summary(link_id: int = 9, **extra) -> WikiPageLinkSummary:
    defaults = {
        "id": link_id,
        "identifier": "Home",
        "link_type": "relation",
        "provider": "Internal Wiki",
        "work_package_id": 42,
        "author": "Alice",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(extra)
    return WikiPageLinkSummary(**defaults)


class _FakeWikiPageLinkApi:
    def __init__(self, records: list[WikiPageLinkRecord] | None = None) -> None:
        self._records = records or [WikiPageLinkRecord(summary=_summary())]
        self.list_calls: list[tuple[int, int, int]] = []
        self.create_calls: list[tuple[int, str, str, int]] = []
        self.delete_calls: list[int] = []

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WikiPageLinkRecord], int]:
        self.list_calls.append((work_package_id, offset, page_size))
        return list(self._records), len(self._records)

    async def create(
        self, work_package_id: int, *, identifier: str, provider: str, author_id: int
    ) -> WikiPageLinkRecord:
        self.create_calls.append((work_package_id, identifier, provider, author_id))
        return WikiPageLinkRecord(summary=_summary(identifier=identifier, provider=provider))

    async def delete(self, link_id: int) -> None:
        self.delete_calls.append(link_id)


async def _current_user_ok() -> CurrentUser:
    return CurrentUser(id=7, name="Alice", login="alice")


def _resolve_work_package_id_ok(resolved_id: int = 42):
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
    api: _FakeWikiPageLinkApi | None = None,
    settings=None,
    resolve_work_package_id=None,
    current_user=None,
) -> WikiPageLinkService:
    return WikiPageLinkService(
        api=api or _FakeWikiPageLinkApi(),
        settings=settings or make_settings(),
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
        current_user=current_user or _current_user_ok,
    )


# --- list_for_work_package ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_results() -> None:
    api = _FakeWikiPageLinkApi()
    resolver = _resolve_work_package_id_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.list_for_work_package(42)

    assert result.count == 1
    assert result.results[0].identifier == "Home"
    assert resolver.calls == [(42, False)]  # type: ignore[attr-defined]
    assert api.list_calls == [(42, 1, 50)]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.list_for_work_package(42)

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_work_package_masks_hidden_identifier() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"wiki_page_link": ("identifier",)})
    service = _service(settings=settings)

    result = await service.list_for_work_package(42)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"identifier"}


# --- create ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeWikiPageLinkApi()
    resolver = _resolve_work_package_id_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.create(42, identifier="Home", provider="internal", confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.create_calls == []
    assert resolver.calls == [(42, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api)

    result = await service.create(42, identifier="Home", provider="internal", confirm=True)

    assert result.state == "confirmed"
    assert result.result is not None
    assert result.result.identifier == "Home"
    assert api.create_calls == [(42, "Home", "internal", 7)]


@pytest.mark.asyncio
async def test_create_masks_hidden_identifier_in_commit_result() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"wiki_page_link": ("identifier",)})
    service = _service(settings=settings)

    result = await service.create(42, identifier="Home", provider="internal", confirm=True)

    assert getattr(result.result, "_hidden_keys", frozenset()) == {"identifier"}


@pytest.mark.asyncio
async def test_create_denies_write_outside_write_allowlist() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(42, identifier="Home", provider="internal", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    """The write-allowlist check (via resolve_work_package_id(..., write=True))
    runs before the confirm branch -- must fire on a preview call too, not
    just on confirm=True."""
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(42, identifier="Home", provider="internal", confirm=False)

    assert api.create_calls == []


# --- delete -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeWikiPageLinkApi()
    resolver = _resolve_work_package_id_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.delete(42, 9, confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.delete_calls == []
    assert resolver.calls == [(42, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api)

    result = await service.delete(42, 9, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [9]


@pytest.mark.asyncio
async def test_delete_denies_write_outside_write_allowlist() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.delete(42, 9, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.delete(42, 9, confirm=False)

    assert api.delete_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_identifier_hidden_by_wiki_page_link_scope_not_wiki_page_scope() -> None:
    """Regression test for the entity="wiki_page_link" vs a same-shaped
    neighbor hide-field bug class (same bug class as the Priority/Notification
    findings documented in this project's history)."""
    settings_wiki_page_hidden = dataclasses.replace(make_settings(), hidden_fields={"wiki_page": ("identifier",)})
    service_wiki_page_hidden = _service(settings=settings_wiki_page_hidden)
    result_wiki_page_hidden = await service_wiki_page_hidden.list_for_work_package(42)
    assert getattr(result_wiki_page_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_link_hidden = dataclasses.replace(make_settings(), hidden_fields={"wiki_page_link": ("identifier",)})
    service_link_hidden = _service(settings=settings_link_hidden)
    result_link_hidden = await service_link_hidden.list_for_work_package(42)
    assert getattr(result_link_hidden.results[0], "_hidden_keys", frozenset()) == {"identifier"}
