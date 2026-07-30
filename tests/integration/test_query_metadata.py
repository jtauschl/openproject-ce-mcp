"""Integration tests for query metadata and capability endpoints.

get_query_filter/get_query_column/get_query_operator/get_query_sort_by have
no collection endpoint to list from -- their ids are well-known, stable
OpenProject constants (e.g. "assignee", "subject", "=", "subject:asc"), not
something discoverable via a list call. list_query_filter_instance_schemas
is the only one of the five with a real collection endpoint.
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_query_filter(client: OpenProjectClient) -> None:
    filter_ = await client.get_query_filter("assignee")
    assert filter_.id == "assignee"
    assert filter_.name


async def test_get_query_column(client: OpenProjectClient) -> None:
    column = await client.get_query_column("subject")
    assert column.id == "subject"
    assert column.name


async def test_get_query_operator(client: OpenProjectClient) -> None:
    operator = await client.get_query_operator("=")
    assert operator.id == "="


async def test_get_query_sort_by_resolves_colon_form_id(client: OpenProjectClient) -> None:
    """OpenProject's sort_bys route is queries/sort_bys/:id-:direction
    (hyphen-joined), not a bare id segment. A request built from the
    caller-facing colon-separated id ("subject:asc") must resolve against a
    real instance, and the public id contract must stay the caller's
    colon-form regardless of the server's own hyphen-form self-link."""
    result = await client.get_query_sort_by("subject:asc")
    assert result.id == "subject:asc"
    assert result.direction is not None


async def test_list_query_filter_instance_schemas(client: OpenProjectClient) -> None:
    result = await client.list_query_filter_instance_schemas()
    assert result.count > 0


async def test_get_query_filter_instance_schema(client: OpenProjectClient) -> None:
    listed = await client.list_query_filter_instance_schemas()
    schema_id = listed.results[0].id

    schema = await client.get_query_filter_instance_schema(schema_id)

    assert schema.id == schema_id


async def test_list_capabilities_context_filter_accepted(client: OpenProjectClient, test_project: str) -> None:
    """Regression: an earlier fix switched the context filter's project-scoping
    value from the project-prefixed form (p{id}) to the workspace-prefixed
    form (w{id}), which OpenProject 16.x rejects outright ("Filters Context
    malformed value"). Confirm the request succeeds (no exception) against
    whatever version this instance actually is."""
    result = await client.list_capabilities(project=test_project)
    assert result.count >= 0


async def test_list_capabilities_by_id_denies_record_outside_read_allowlist(
    client: OpenProjectClient, test_project: str
) -> None:
    """Regression: capability_id-only lookups fetched the single capability
    record directly (GET capabilities/{id}) without ever checking whether its
    own context (the project it belongs to) is in OPENPROJECT_READ_PROJECTS
    -- unlike the project-filtered collection query, which resolves the
    project first and thus already enforces the allowlist. A caller with no
    read access to test_project could still read any of its capability
    records by id."""
    listed = await client.list_capabilities(project=test_project)
    if listed.count == 0:
        pytest.skip("No capability records in test project")
    capability_id = listed.results[0].id

    denied_settings = dataclasses.replace(client.settings, read_projects=("no-such-project-for-integration-tests",))
    denied_client = OpenProjectClient(denied_settings)
    await denied_client.initialize()

    denied_result = await denied_client.list_capabilities(capability_id=capability_id)
    assert denied_result.count == 0
