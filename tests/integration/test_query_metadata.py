"""Integration tests for query metadata and capability endpoints."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_query_sort_by_resolves_colon_form_id(client: OpenProjectClient) -> None:
    """Regression (OPM-322): OpenProject's sort_bys route is
    queries/sort_bys/:id-:direction (hyphen-joined), not a bare id segment.
    A request built from the caller-facing colon-separated id
    ("subject:asc") used to hit a 404 on every version -- confirm it now
    resolves against a real instance, and that the public id contract stays
    the caller's colon-form regardless of the server's own hyphen-form
    self-link."""
    result = await client.get_query_sort_by("subject:asc")
    assert result.id == "subject:asc"
    assert result.direction is not None


async def test_list_capabilities_context_filter_accepted(client: OpenProjectClient, test_project: str) -> None:
    """Regression: an earlier fix switched the context filter's project-scoping
    value from the project-prefixed form (p{id}) to the workspace-prefixed
    form (w{id}), which OpenProject 16.x rejects outright ("Filters Context
    malformed value"). Confirm the request succeeds (no exception) against
    whatever version this instance actually is."""
    result = await client.list_capabilities(project=test_project)
    assert result.count >= 0
