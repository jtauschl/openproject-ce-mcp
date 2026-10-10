from __future__ import annotations

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.services.project_scoped_list import (
    record_in_project,
    resolve_project_filter_id,
    trim_text,
)


def test_trim_text_short_text_passes_through() -> None:
    assert trim_text("hello", limit=10) == "hello"


def test_trim_text_none_returns_none() -> None:
    assert trim_text(None, limit=10) is None


def test_trim_text_truncates_and_appends_ellipsis() -> None:
    result = trim_text("x" * 20, limit=10)
    assert result is not None
    assert len(result) == 10
    assert result.endswith("…")


@pytest.mark.asyncio
async def test_resolve_project_filter_id_returns_none_when_no_project() -> None:
    async def resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise AssertionError("must not be called when project is None")

    result = await resolve_project_filter_id(None, resolve_project_ref=resolve_project_ref)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_project_filter_id_returns_the_resolved_projects_id() -> None:
    async def resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        assert write is False
        return {"id": 6, "identifier": "demo", "name": "Demo Project"}

    result = await resolve_project_filter_id("demo", resolve_project_ref=resolve_project_ref)

    assert result == 6


@pytest.mark.parametrize(
    ("project_link", "expected"),
    [
        ({"href": "/api/v3/projects/6", "title": "Demo"}, True),
        ({"href": "/api/v3/projects/99", "title": "Demo"}, False),
        ({"href": "https://evil.example.com/api/v3/projects/6"}, False),
        ({"href": "urn:openproject-org:api:v3:undisclosed"}, False),
        ({"href": None}, False),
        (None, False),
    ],
)
def test_record_in_project_compares_the_strictly_parsed_link_id(project_link, expected: bool) -> None:
    assert record_in_project(project_link, 6, settings=make_settings()) is expected
