from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings
from _work_package_target_helpers import resolved_record

from openproject_ce_mcp.app.errors import (
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
)
from openproject_ce_mcp.app.ports.wiki_page_link_api import WikiPageLinkRecord
from openproject_ce_mcp.app.ports.work_package_ref import ResolvedRecord
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


def _resolve_work_package_record_ok(resolved_id: int = 42):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> ResolvedRecord:
        calls.append((work_package_ref, write))
        return resolved_record(resolved_id)

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_work_package_record_denied():
    async def resolve(work_package_ref: int | str, *, write: bool = False) -> ResolvedRecord:
        raise PermissionDeniedError("OpenProject access to this project is disabled.")

    return resolve


def _service(
    *,
    api: _FakeWikiPageLinkApi | None = None,
    settings=None,
    resolve_work_package_record=None,
    current_user=None,
) -> WikiPageLinkService:
    return WikiPageLinkService(
        api=api or _FakeWikiPageLinkApi(),
        settings=settings or make_settings(),
        resolve_work_package_record=resolve_work_package_record or _resolve_work_package_record_ok(),
        current_user=current_user or _current_user_ok,
    )


# --- list_for_work_package ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_results() -> None:
    api = _FakeWikiPageLinkApi()
    resolver = _resolve_work_package_record_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_record=resolver)

    result = await service.list_for_work_package(42)

    assert result.count == 1
    assert result.results[0].identifier == "Home"
    assert resolver.calls == [(42, False)]  # type: ignore[attr-defined]
    assert api.list_calls == [(42, 1, 50)]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_record=_resolve_work_package_record_denied())

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
    resolver = _resolve_work_package_record_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_record=resolver)

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
async def test_create_rejects_hidden_identifier_field() -> None:
    api = _FakeWikiPageLinkApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"wiki_page_link": ("identifier",)})
    service = _service(api=api, settings=settings)

    with pytest.raises(InvalidInputError, match="identifier"):
        await service.create(42, identifier="Home", provider="internal", confirm=False)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_hidden_provider_field() -> None:
    api = _FakeWikiPageLinkApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"wiki_page_link": ("provider",)})
    service = _service(api=api, settings=settings)

    with pytest.raises(InvalidInputError, match="provider"):
        await service.create(42, identifier="Home", provider="internal", confirm=False)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_outside_write_allowlist() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_record=_resolve_work_package_record_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(42, identifier="Home", provider="internal", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    """The write-allowlist check (via resolve_work_package_record(..., write=True))
    runs before the confirm branch -- must fire on a preview call too, not
    just on confirm=True."""
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_record=_resolve_work_package_record_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(42, identifier="Home", provider="internal", confirm=False)

    assert api.create_calls == []


# --- delete -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeWikiPageLinkApi()
    resolver = _resolve_work_package_record_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_record=resolver)

    result = await service.delete(42, 9, confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.delete_calls == []
    assert resolver.calls == [(42, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_delete_rejects_link_id_not_belonging_to_the_resolved_work_package() -> None:
    """Security regression: resolving work_package_id's write-allowlist alone
    is NOT sufficient authorization to delete an arbitrary link_id.
    OpenProject's own DELETE enforces manage_wiki_page_links against the
    LINK's actual project, not whatever work_package_id this MCP was told to
    check -- without this verification, a caller with write access to an
    allowed work package could pass a link_id belonging to a disallowed
    project's link and have it deleted."""
    api = _FakeWikiPageLinkApi([WikiPageLinkRecord(summary=_summary(link_id=9))])
    service = _service(api=api)

    with pytest.raises(NotFoundError):
        await service.delete(42, 999, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_rejects_foreign_link_id_even_without_confirm() -> None:
    api = _FakeWikiPageLinkApi([WikiPageLinkRecord(summary=_summary(link_id=9))])
    service = _service(api=api)

    with pytest.raises(NotFoundError):
        await service.delete(42, 999, confirm=False)

    assert api.delete_calls == []


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
    service = _service(api=api, resolve_work_package_record=_resolve_work_package_record_denied())

    with pytest.raises(PermissionDeniedError):
        await service.delete(42, 9, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    api = _FakeWikiPageLinkApi()
    service = _service(api=api, resolve_work_package_record=_resolve_work_package_record_denied())

    with pytest.raises(PermissionDeniedError):
        await service.delete(42, 9, confirm=False)

    assert api.delete_calls == []


_INLINE_LINK_MESSAGE = (
    "Wiki page link 9 on work package 42 is an inline link: OpenProject derives it from a wiki link in "
    "the work package's description or from a wiki page that mentions the work package, and offers no "
    "API to delete it. Remove the link from that text instead."
)


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [True, False])
async def test_delete_rejects_an_inline_link_before_the_request(confirm: bool) -> None:
    api = _FakeWikiPageLinkApi([WikiPageLinkRecord(summary=_summary(link_id=9, link_type="inline"))])
    service = _service(api=api)

    with pytest.raises(InvalidInputError) as exc_info:
        await service.delete(42, 9, confirm=confirm)

    assert str(exc_info.value) == _INLINE_LINK_MESSAGE
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_judges_the_requested_link_not_another_inline_link_of_the_work_package() -> None:
    api = _FakeWikiPageLinkApi(
        [
            WikiPageLinkRecord(summary=_summary(link_id=8, link_type="inline")),
            WikiPageLinkRecord(summary=_summary(link_id=9, link_type="relation")),
        ]
    )
    service = _service(api=api)

    result = await service.delete(42, 9, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [9]


class _ForbiddenDeleteApi(_FakeWikiPageLinkApi):
    """OpenProject 17.6+ for a user without manage_wiki_page_links: the DELETE answers 403."""

    async def delete(self, link_id: int) -> None:
        raise PermissionDeniedError(
            "OpenProject denied access to this resource. (You are not authorized to access this resource.)"
        )


@pytest.mark.asyncio
async def test_delete_without_the_manage_permission_reports_permission_denied_not_a_version() -> None:
    service = _service(api=_ForbiddenDeleteApi())

    with pytest.raises(PermissionDeniedError) as exc_info:
        await service.delete(42, 9, confirm=True)

    assert str(exc_info.value) == (
        "OpenProject denied access to this resource. (You are not authorized to access this resource.)"
    )


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


# --- version floors -------------------------------------------------------------


class _MissingRouteApi(_FakeWikiPageLinkApi):
    """Answers like an OpenProject release that lacks the named routes: 404."""

    def __init__(self, *missing: str) -> None:
        super().__init__()
        self._missing = set(missing)

    def _route(self, name: str) -> None:
        if name in self._missing:
            raise NotFoundError("The requested resource could not be found.")

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WikiPageLinkRecord], int]:
        self._route("list")
        return await super().list_for_work_package(work_package_id, offset=offset, page_size=page_size)

    async def create(
        self, work_package_id: int, *, identifier: str, provider: str, author_id: int
    ) -> WikiPageLinkRecord:
        self._route("create")
        return await super().create(work_package_id, identifier=identifier, provider=provider, author_id=author_id)

    async def delete(self, link_id: int) -> None:
        self._route("delete")
        await super().delete(link_id)


@pytest.mark.asyncio
async def test_list_on_a_server_without_the_route_names_17_5() -> None:
    service = _service(api=_MissingRouteApi("list", "create", "delete"))

    with pytest.raises(NotFoundError) as exc_info:
        await service.list_for_work_package(42)

    assert str(exc_info.value) == (
        "Listing wiki page links: not found, or not available on this instance (it requires OpenProject 17.5 or newer)."
    )


@pytest.mark.asyncio
async def test_create_on_a_server_with_list_and_delete_only_names_17_7() -> None:
    service = _service(api=_MissingRouteApi("create"))

    with pytest.raises(NotFoundError) as exc_info:
        await service.create(42, identifier="Home", provider="internal", confirm=True)

    assert str(exc_info.value) == (
        "Creating wiki page links: not found, or not available on this instance (it requires OpenProject 17.7 or newer)."
    )


@pytest.mark.asyncio
async def test_delete_on_a_server_with_list_only_names_17_6() -> None:
    api = _MissingRouteApi("create", "delete")
    service = _service(api=api)

    with pytest.raises(NotFoundError) as exc_info:
        await service.delete(42, 9, confirm=True)

    assert str(exc_info.value) == (
        "Deleting wiki page links: not found, or not available on this instance (it requires OpenProject 17.6 or newer)."
    )
    assert api.list_calls == [(42, 1, 50)]


@pytest.mark.asyncio
async def test_delete_preview_on_a_server_without_any_route_names_17_6() -> None:
    service = _service(api=_MissingRouteApi("list", "create", "delete"))

    with pytest.raises(NotFoundError) as exc_info:
        await service.delete(42, 9, confirm=False)

    assert str(exc_info.value) == (
        "Deleting wiki page links: not found, or not available on this instance (it requires OpenProject 17.6 or newer)."
    )


@pytest.mark.asyncio
async def test_delete_of_an_untyped_link_on_a_server_with_list_only_names_17_6() -> None:
    """OpenProject 17.5 renders no link type for a reverse inline link, and has no DELETE route."""
    api = _MissingRouteApi("create", "delete")
    api._records = [WikiPageLinkRecord(summary=_summary(link_id=9, link_type=None))]
    service = _service(api=api)

    with pytest.raises(NotFoundError) as exc_info:
        await service.delete(42, 9, confirm=True)

    assert str(exc_info.value) == (
        "Deleting wiki page links: not found, or not available on this instance (it requires OpenProject 17.6 or newer)."
    )


class _BrokenListApi(_MissingRouteApi):
    """OpenProject 17.5: GET 500s on a work package whose links do not resolve, DELETE is missing."""

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WikiPageLinkRecord], int]:
        raise OpenProjectServerError("OpenProject returned a server error.")


@pytest.mark.asyncio
async def test_delete_on_a_server_whose_list_fails_reports_the_server_error() -> None:
    api = _BrokenListApi("create", "delete")
    service = _service(api=api)

    with pytest.raises(OpenProjectServerError, match=r"^OpenProject returned a server error\.$"):
        await service.delete(42, 9, confirm=True)

    assert api.delete_calls == []
