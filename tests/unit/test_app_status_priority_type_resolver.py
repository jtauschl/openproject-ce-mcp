from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.status_priority_type_api import PriorityRecord, StatusRecord
from openproject_ce_mcp.app.resolvers.status_priority_type_resolver import StatusPriorityTypeResolver
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.models import PrioritySummary, StatusSummary

BASE_URL = "https://op.example.com"


def _status(status_id: int, name: str, *, lookup_name: str | None = None) -> StatusRecord:
    return StatusRecord(
        summary=StatusSummary(
            id=status_id,
            name=name,
            is_default=False,
            is_closed=False,
            color=None,
            position=1,
            url=f"/api/v3/statuses/{status_id}",
            is_readonly=False,
            default_done_ratio=None,
            excluded_from_totals=False,
        ),
        lookup_name=name if lookup_name is None else lookup_name,
    )


def _priority(priority_id: int, name: str, *, lookup_name: str | None = None) -> PriorityRecord:
    return PriorityRecord(
        summary=PrioritySummary(id=priority_id, name=name, is_default=False, is_active=True, color=None, position=1),
        lookup_name=name if lookup_name is None else lookup_name,
    )


class _FakeApi:
    def __init__(
        self, *, statuses: list[StatusRecord] | None = None, priorities: list[PriorityRecord] | None = None
    ) -> None:
        self._statuses = statuses or []
        self._priorities = priorities or []

    async def list_statuses(self) -> list[StatusRecord]:
        return self._statuses

    async def list_priorities(self) -> list[PriorityRecord]:
        return self._priorities


@pytest.mark.asyncio
async def test_resolve_status_id_numeric_passthrough_never_calls_the_api() -> None:
    resolver = StatusPriorityTypeResolver(api=_FakeApi())
    assert await resolver.resolve_status_id("7") == "7"


@pytest.mark.asyncio
async def test_resolve_status_id_matches_by_case_insensitive_name() -> None:
    api = _FakeApi(statuses=[_status(1, "New"), _status(2, "In Progress")])
    resolver = StatusPriorityTypeResolver(api=api)
    assert await resolver.resolve_status_id("in progress") == "2"


@pytest.mark.asyncio
async def test_resolve_status_id_returns_first_match_on_duplicate_names() -> None:
    """The flat original silently returns the first match on an ambiguous
    name -- no ambiguity error, unlike TypeResolver/SprintResolver. This
    asymmetry is pre-existing and must be preserved exactly."""
    api = _FakeApi(statuses=[_status(1, "New"), _status(2, "New")])
    resolver = StatusPriorityTypeResolver(api=api)
    assert await resolver.resolve_status_id("New") == "1"


@pytest.mark.asyncio
async def test_resolve_status_id_raises_when_not_found() -> None:
    resolver = StatusPriorityTypeResolver(api=_FakeApi())
    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_status_id("Ghost")


@pytest.mark.asyncio
async def test_resolve_priority_id_numeric_passthrough_never_calls_the_api() -> None:
    resolver = StatusPriorityTypeResolver(api=_FakeApi())
    assert await resolver.resolve_priority_id("3") == "3"


@pytest.mark.asyncio
async def test_resolve_priority_id_matches_by_case_insensitive_name() -> None:
    api = _FakeApi(priorities=[_priority(1, "Low"), _priority(2, "High")])
    resolver = StatusPriorityTypeResolver(api=api)
    assert await resolver.resolve_priority_id("HIGH") == "2"


@pytest.mark.asyncio
async def test_resolve_priority_id_returns_first_match_on_duplicate_names() -> None:
    api = _FakeApi(priorities=[_priority(1, "High"), _priority(2, "High")])
    resolver = StatusPriorityTypeResolver(api=api)
    assert await resolver.resolve_priority_id("High") == "1"


@pytest.mark.asyncio
async def test_resolve_priority_id_raises_when_not_found() -> None:
    resolver = StatusPriorityTypeResolver(api=_FakeApi())
    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_priority_id("Ghost")


@pytest.mark.asyncio
async def test_resolve_status_id_matches_the_raw_name_exactly_via_real_port() -> None:
    """Against the REAL adapter (not the fake used elsewhere in this file):
    resolution compares StatusRecord.lookup_name, the RAW (never trimmed,
    never synthesized) name -- byte-for-byte identical matching semantics to
    the flat original's `str(item.get("name","")).casefold()`. A name with
    irregular internal whitespace, as actually returned by the server, must
    be matched with that same irregular whitespace, not a normalized form
    (an earlier draft of this resolver compared against the DISPLAY name,
    `summary.name`, which trims/collapses whitespace -- see
    status_priority_type_api.py's port module docstring for the full
    rationale)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/statuses"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": 1, "name": "In   Progress\t"}]}},
            request=request,
        )

    http = httpx.AsyncClient(base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler))
    api = HttpxStatusPriorityTypeApi(HttpxTransport(http), base_url=BASE_URL, api_prefix="/api/v3/")
    resolver = StatusPriorityTypeResolver(api=api)

    assert await resolver.resolve_status_id("In   Progress\t") == "1"
    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_status_id("In Progress")
    await http.aclose()


@pytest.mark.asyncio
async def test_resolve_status_id_does_not_match_a_blank_name_against_the_synthetic_display_fallback() -> None:
    """Regression test:
    normalize_status falls back to a synthetic display name ("Status 7")
    when the raw name is blank -- correct DISPLAY behavior, but resolution
    must use lookup_name (the raw, un-synthesized name, "" here) so a
    caller's literal search for "Status 7" never accidentally matches a
    status whose real name was blank, matching the flat original's raw
    comparison against "" exactly."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": ""}]}}, request=request)

    http = httpx.AsyncClient(base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler))
    api = HttpxStatusPriorityTypeApi(HttpxTransport(http), base_url=BASE_URL, api_prefix="/api/v3/")
    resolver = StatusPriorityTypeResolver(api=api)

    with pytest.raises(InvalidInputError, match="was not found"):
        await resolver.resolve_status_id("Status 7")
    await http.aclose()
