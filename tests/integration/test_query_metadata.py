"""Integration tests for Query Metadata reads (17th migrated domain,
OPM-1611).

get_query_filter/get_query_column/get_query_operator/get_query_sort_by have
no collection endpoint to list from -- their ids are well-known, stable
OpenProject constants (e.g. "assignee", "subject", "=", "subject:asc"), not
something discoverable via a list call, matching the runbook's guidance for
a get-only domain with stable slugs (Wiki Pages). list_query_filter_instance_schemas
is the only one of the five with a real collection endpoint.
"""

from __future__ import annotations

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


async def test_get_query_sort_by(client: OpenProjectClient) -> None:
    sort_by = await client.get_query_sort_by("subject:asc")
    assert sort_by.id == "subject:asc"
    assert sort_by.direction


async def test_list_query_filter_instance_schemas(client: OpenProjectClient) -> None:
    result = await client.list_query_filter_instance_schemas()
    assert result.count > 0


async def test_get_query_filter_instance_schema(client: OpenProjectClient) -> None:
    listed = await client.list_query_filter_instance_schemas()
    schema_id = listed.results[0].id

    schema = await client.get_query_filter_instance_schema(schema_id)

    assert schema.id == schema_id
