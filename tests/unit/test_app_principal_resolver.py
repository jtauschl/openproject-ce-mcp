from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.principal_api import PrincipalRecord
from openproject_ce_mcp.app.resolvers.principal_resolver import PrincipalResolver
from openproject_ce_mcp.models import CurrentUser, PrincipalSummary


def _principal(principal_id: int, name: str, *, lookup_name: str | None = None) -> PrincipalRecord:
    return PrincipalRecord(
        summary=PrincipalSummary(
            id=principal_id,
            type="User",
            name=name,
            email=None,
        ),
        lookup_name=name if lookup_name is None else lookup_name,
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
    return CurrentUser(id=99, name="Me", login="me")


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
    """Regression test: the original
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


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["²", "٣"])
async def test_resolve_id_reads_non_ascii_digits_as_a_name(name: str) -> None:
    api = _FakePrincipalApi([_principal(7, name)])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())
    assert await resolver.resolve_id(name) == "7"
    assert api.last_search == name


class _PagedPrincipalApi:
    """A server that honors the requested page size."""

    def __init__(self, records: list[PrincipalRecord]) -> None:
        self._records = records
        self.offsets: list[int] = []

    async def list_principals(
        self, *, search: str | None, offset: int, page_size: int
    ) -> tuple[list[PrincipalRecord], int]:
        self.offsets.append(offset)
        start = (offset - 1) * page_size
        return self._records[start : start + page_size], len(self._records)


def _three_per_page():
    return dataclasses.replace(make_settings(), max_page_size=3, max_results=3)


def _fillers(count: int) -> list[PrincipalRecord]:
    return [_principal(100 + i, f"Jane Doe {i}") for i in range(count)]


@pytest.mark.asyncio
async def test_resolve_id_finds_the_exact_name_on_a_later_page() -> None:
    api = _PagedPrincipalApi([*_fillers(5), _principal(7, "Jane Doe")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    assert await resolver.resolve_id("Jane Doe") == "7"
    assert api.offsets == [1, 2]


@pytest.mark.asyncio
async def test_resolve_id_reports_a_second_exact_match_on_a_later_page_as_ambiguous() -> None:
    api = _PagedPrincipalApi([_principal(7, "Jane Doe"), *_fillers(4), _principal(8, "Jane Doe")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("Jane Doe")


@pytest.mark.asyncio
async def test_resolve_id_stops_after_the_last_page() -> None:
    api = _PagedPrincipalApi([_principal(7, "Jane Doe"), *_fillers(2)])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    await resolver.resolve_id("Jane Doe")

    assert api.offsets == [1]


@pytest.mark.asyncio
async def test_resolve_id_stops_on_an_empty_page_whatever_the_server_total_says() -> None:
    class _Lying(_PagedPrincipalApi):
        async def list_principals(self, *, search, offset, page_size):
            self.offsets.append(offset)
            return [], 999

    api = _Lying([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_id("Nobody")

    assert api.offsets == [1]


@pytest.mark.asyncio
async def test_resolve_id_reads_on_when_the_server_cuts_the_page_size() -> None:
    class _Cutting(_PagedPrincipalApi):
        async def list_principals(self, *, search, offset, page_size):
            return await super().list_principals(search=search, offset=offset, page_size=2)

    api = _Cutting([*_fillers(5), _principal(7, "Jane Doe")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    assert await resolver.resolve_id("Jane Doe") == "7"
    assert api.offsets == [1, 2, 3]


@pytest.mark.asyncio
async def test_resolve_id_gives_up_on_a_name_that_matches_pages_without_end() -> None:
    class _Endless(_PagedPrincipalApi):
        async def list_principals(self, *, search, offset, page_size):
            self.offsets.append(offset)
            return [_principal(offset, f"Jane Doe {offset}")], 10**9

    api = _Endless([])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=_three_per_page())

    with pytest.raises(InvalidInputError, match="too many names"):
        await resolver.resolve_id("Jane")

    assert len(api.offsets) == 20


@pytest.mark.asyncio
async def test_an_ambiguous_principal_names_its_candidates_and_an_unknown_one_offers_nothing() -> None:
    api = _FakePrincipalApi([_principal(1, "Alice"), _principal(2, "Alice")])
    resolver = PrincipalResolver(api=api, current_user=_current_user, settings=make_settings())

    with pytest.raises(InvalidInputError) as ambiguous:
        await resolver.resolve_id("Alice")
    with pytest.raises(InvalidInputError) as unknown:
        await resolver.resolve_id("Bob")

    assert str(ambiguous.value).endswith("Pass a numeric user or group id. Matches: 1 (Alice), 2 (Alice).")
    assert str(unknown.value) == "OpenProject principal 'Bob' was not found."
