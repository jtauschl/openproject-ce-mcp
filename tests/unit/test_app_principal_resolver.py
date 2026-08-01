from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.principal_api import PrincipalRecord
from openproject_ce_mcp.app.resolvers.principal_resolver import PrincipalResolver
from openproject_ce_mcp.models import CurrentUser, PrincipalSummary


def _principal(principal_id: int, name: str) -> PrincipalRecord:
    return PrincipalRecord(
        summary=PrincipalSummary(
            id=principal_id,
            type="User",
            name=name,
            login=name.lower(),
            email=None,
            status=None,
            url=f"https://op.example.com/users/{principal_id}",
        )
    )


class _FakePrincipalApi:
    def __init__(self, records: list[PrincipalRecord]) -> None:
        self._records = records
        self.last_search: str | None = None
        self.last_offset: int | None = None
        self.last_page_size: int | None = None

    async def list_principals(
        self, *, search: str | None, offset: int, page_size: int
    ) -> tuple[list[PrincipalRecord], int]:
        self.last_search = search
        self.last_offset = offset
        self.last_page_size = page_size
        return self._records, len(self._records)


async def _current_user() -> CurrentUser:
    return CurrentUser(id=99, name="Me", login="me", url="https://op.example.com/users/99")


@pytest.mark.asyncio
async def test_resolve_id_me_uses_current_user_lookup() -> None:
    api = _FakePrincipalApi([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())
    assert await resolver.resolve_id("me") == "99"


@pytest.mark.asyncio
async def test_resolve_id_numeric_passthrough_never_calls_the_api() -> None:
    api = _FakePrincipalApi([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())
    assert await resolver.resolve_id("42") == "42"
    assert api.last_search is None


@pytest.mark.asyncio
async def test_resolve_id_name_search_bypasses_admin_read_gate() -> None:
    """The single most important regression test for this migration: the
    resolver must succeed with enable_admin_read left at its default (off) --
    proving PrincipalApi is genuinely ungated here, unlike PrincipalService's
    public list_principals method."""
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakePrincipalApi([_principal(7, "Alice")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=settings)
    assert await resolver.resolve_id("Alice") == "7"
    assert api.last_search == "Alice"


@pytest.mark.asyncio
async def test_resolve_id_name_search_page_size_is_capped_by_max_page_size() -> None:
    """Regression test (Codex review finding): the original
    _resolve_principal_id passed max_results through _resolve_limit, which
    clamps by min(max_page_size, max_results) -- passing max_results
    unclamped would silently request a larger page than the configured
    per-request maximum allows."""
    settings = dataclasses.replace(make_settings(), max_page_size=50, max_results=100)
    api = _FakePrincipalApi([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=settings)
    with pytest.raises(InvalidInputError):
        await resolver.resolve_id("Nobody")
    assert api.last_offset == 1
    assert api.last_page_size == 50


@pytest.mark.asyncio
async def test_resolve_id_raises_when_no_match() -> None:
    api = _FakePrincipalApi([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())
    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_id("Ghost")


@pytest.mark.asyncio
async def test_resolve_id_raises_when_ambiguous() -> None:
    api = _FakePrincipalApi([_principal(1, "Alice"), _principal(2, "Alice")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("Alice")
