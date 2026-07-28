from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, OpenProjectServerError, PermissionDeniedError
from openproject_ce_mcp.app.ports.work_package_resolution import WorkPackageAllowedContext
from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver


def _wp_payload(wp_id: int, *, project_href: str | None = "/api/v3/projects/6") -> dict:
    links: dict = {}
    if project_href is not None:
        links["project"] = {"href": project_href, "title": "Demo"}
    return {"id": wp_id, "_type": "WorkPackage", "subject": f"WP {wp_id}", "_links": links}


class _FakeWorkPackageLookupApi:
    """No I/O -- an in-memory WorkPackageLookupApi double."""

    def __init__(self, records: dict[str, dict], *, not_found: set[str] | None = None) -> None:
        self._records = records
        self._not_found = not_found or set()
        self.get_calls: list[str] = []
        self.get_by_href_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        if work_package_ref in self._not_found or work_package_ref not in self._records:
            raise NotFoundError(f"no fake work package for ref {work_package_ref}")
        return self._records[work_package_ref]

    async def get_by_href(self, href: str) -> dict:
        self.get_by_href_calls.append(href)
        if href in self._not_found or href not in self._records:
            raise NotFoundError(f"no fake work package for href {href}")
        return self._records[href]


def _resolver(
    records: dict[str, dict], *, settings=None, not_found=None
) -> tuple[WorkPackageResolver, _FakeWorkPackageLookupApi]:
    api = _FakeWorkPackageLookupApi(records, not_found=not_found)
    resolver = WorkPackageResolver(api=api, settings=settings or make_settings(), project_id_to_identifier={})
    return resolver, api


# --- resolve_id ---


@pytest.mark.asyncio
async def test_resolve_id_numeric_ref() -> None:
    resolver, api = _resolver({"42": _wp_payload(42)})

    result = await resolver.resolve_id(42)

    assert result == 42
    assert api.get_calls == ["42"]


@pytest.mark.asyncio
async def test_resolve_id_semantic_project_prefixed_ref() -> None:
    resolver, _api = _resolver({"PROJ-123": _wp_payload(7)})

    result = await resolver.resolve_id("PROJ-123")

    assert result == 7


@pytest.mark.asyncio
async def test_resolve_id_numeric_ref_not_found_reraises_plain_not_found() -> None:
    resolver, _api = _resolver({}, not_found={"42"})

    with pytest.raises(NotFoundError) as exc_info:
        await resolver.resolve_id(42)

    assert "17.5" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_id_semantic_ref_not_found_gets_175_hint_message() -> None:
    resolver, _api = _resolver({}, not_found={"PROJ-999"})

    with pytest.raises(
        NotFoundError,
        match=r"Work package 'PROJ-999' was not found.*OpenProject 17\.5\+.*exact project identifier",
    ):
        await resolver.resolve_id("PROJ-999")


@pytest.mark.asyncio
async def test_resolve_id_write_false_uses_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    # Read is wide open, write is restricted -- write=False must not trigger the
    # write check, so this must succeed.
    result = await resolver.resolve_id(42, write=False)

    assert result == 42


@pytest.mark.asyncio
async def test_resolve_id_write_true_uses_write_allowlist_and_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await resolver.resolve_id(42, write=True)


@pytest.mark.asyncio
async def test_resolve_id_read_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await resolver.resolve_id(42)


# --- project_link_allowed ---


@pytest.mark.asyncio
async def test_project_link_allowed_true_when_project_in_scope() -> None:
    href = "/api/v3/work_packages/42"
    resolver, _api = _resolver({href: _wp_payload(42)})

    assert await resolver.project_link_allowed(href) is True


@pytest.mark.asyncio
async def test_project_link_allowed_false_when_project_out_of_scope() -> None:
    href = "/api/v3/work_packages/42"
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, _api = _resolver({href: _wp_payload(42)}, settings=settings)

    assert await resolver.project_link_allowed(href) is False


@pytest.mark.asyncio
async def test_project_link_allowed_false_when_work_package_not_found() -> None:
    href = "/api/v3/work_packages/999"
    resolver, _api = _resolver({}, not_found={href})

    assert await resolver.project_link_allowed(href) is False


@pytest.mark.asyncio
async def test_project_link_allowed_does_not_swallow_non_not_found_errors() -> None:
    """A transient server/transport error must not be silently treated as
    "not allowed" -- only NotFoundError maps to False; anything else (e.g. a
    5xx) must propagate unchanged, matching the original method's explicit
    "do NOT swallow" contract."""

    class _RaisingApi:
        async def get_by_href(self, href: str) -> dict:
            raise OpenProjectServerError("boom")

    resolver = WorkPackageResolver(api=_RaisingApi(), settings=make_settings(), project_id_to_identifier={})

    with pytest.raises(OpenProjectServerError, match="boom"):
        await resolver.project_link_allowed("/api/v3/work_packages/999")


@pytest.mark.asyncio
async def test_project_link_allowed_without_context_always_fetches_fresh() -> None:
    href = "/api/v3/work_packages/42"
    resolver, api = _resolver({href: _wp_payload(42)})

    await resolver.project_link_allowed(href)
    await resolver.project_link_allowed(href)

    assert api.get_by_href_calls == [href, href]


@pytest.mark.asyncio
async def test_project_link_allowed_with_context_caches_on_second_call() -> None:
    href = "/api/v3/work_packages/42"
    resolver, api = _resolver({href: _wp_payload(42)})
    context = WorkPackageAllowedContext()

    first = await resolver.project_link_allowed(href, context=context)
    second = await resolver.project_link_allowed(href, context=context)

    assert first is True
    assert second is True
    assert api.get_by_href_calls == [href]  # only fetched once


@pytest.mark.asyncio
async def test_project_link_allowed_with_context_caches_denied_result_too() -> None:
    href = "/api/v3/work_packages/42"
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, api = _resolver({href: _wp_payload(42)}, settings=settings)
    context = WorkPackageAllowedContext()

    first = await resolver.project_link_allowed(href, context=context)
    second = await resolver.project_link_allowed(href, context=context)

    assert first is False
    assert second is False
    assert api.get_by_href_calls == [href]


@pytest.mark.asyncio
async def test_project_link_allowed_different_hrefs_are_cached_independently() -> None:
    href_a = "/api/v3/work_packages/1"
    href_b = "/api/v3/work_packages/2"
    resolver, api = _resolver({href_a: _wp_payload(1), href_b: _wp_payload(2)})
    context = WorkPackageAllowedContext()

    await resolver.project_link_allowed(href_a, context=context)
    await resolver.project_link_allowed(href_b, context=context)
    await resolver.project_link_allowed(href_a, context=context)

    assert api.get_by_href_calls == [href_a, href_b]
