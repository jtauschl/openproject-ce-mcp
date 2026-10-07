"""The bulk work-package tools as an MCP client sees them.

The other integration tests call the client or the tool functions directly,
which skips the SDK layer that decides what an error looks like to the agent.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from mcp import types
from mcp.client import Client

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

pytestmark = pytest.mark.integration


# A server, not an open session: the SDK's task groups must be entered and left
# in one task, and pytest-asyncio tears fixtures down in another.
@pytest.fixture
def mcp_server(client: OpenProjectClient) -> StrictMCPServer:
    return create_app(client.settings)


def _connect(server: StrictMCPServer) -> Client:
    # "legacy": the initialize handshake today's stdio clients use.
    return Client(server, mode="legacy")


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def _call_ok(mcp: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(name, arguments)
    assert result.is_error is False, _text(result)
    return json.loads(_text(result))


async def _ids_matching(client: OpenProjectClient, project: str, marker: str) -> list[int]:
    found = await client.work_package.search(search=marker, project=project)
    return [row.id for row in found.results]


async def test_confirmed_bulk_create_and_update_with_select(
    mcp_server: StrictMCPServer, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    marker = f"[integration-test] bulk over mcp {uuid.uuid4().hex[:8]}"
    async with _connect(mcp_server) as mcp:
        created = await _call_ok(
            mcp,
            "bulk_create_work_packages",
            {
                "items": [{"project": test_project, "type": "Task", "subject": f"{marker} {n}"} for n in (1, 2)],
                "select": ["work_package_id"],
                "confirm": True,
            },
        )
        wp_ids.extend(item["result"]["work_package_id"] for item in created["items"])
        updated = await _call_ok(
            mcp,
            "bulk_update_work_packages",
            {
                "items": [{"work_package_id": wp_id, "subject": f"{marker} renamed"} for wp_id in wp_ids],
                "select": ["work_package_id", "state"],
                "confirm": True,
            },
        )

    assert (created["confirmed"], created["succeeded"], created["failed"]) == (True, 2, 0)
    assert [item["index"] for item in created["items"]] == [0, 1]
    assert all(item.keys() == {"index", "success", "result"} for item in created["items"])
    assert all(item["result"].keys() == {"work_package_id"} for item in created["items"])
    assert (updated["confirmed"], updated["succeeded"], updated["failed"]) == (True, 2, 0)
    assert [item["result"] for item in updated["items"]] == [
        {"work_package_id": wp_id, "state": "confirmed"} for wp_id in wp_ids
    ]
    for wp_id in wp_ids:
        assert (await client.work_package.get(wp_id)).subject == f"{marker} renamed"


async def test_bulk_create_with_a_work_package_field_in_select_reports_why_and_writes_nothing(
    mcp_server: StrictMCPServer, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    marker = f"[integration-test] bulk bad select {uuid.uuid4().hex[:8]}"
    async with _connect(mcp_server) as mcp:
        result = await mcp.call_tool(
            "bulk_create_work_packages",
            {
                "items": [{"project": test_project, "type": "Task", "subject": marker}],
                "select": ["work_package_id", "subject"],
                "confirm": True,
            },
        )

    assert result.is_error is True
    assert "[validation_error] select field 'subject' is not a valid WorkPackageWriteResult field" in _text(result)
    assert "work_package_id" in _text(result).split("Allowed:")[1]
    written = await _ids_matching(client, test_project, marker)
    wp_ids.extend(written)
    assert written == []


async def test_bulk_update_with_a_work_package_field_in_select_reports_why_and_writes_nothing(
    mcp_server: StrictMCPServer, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    subject = "[integration-test] bulk bad select update"
    created = await client.work_package.create(project=test_project, type="Task", subject=subject, confirm=True)
    wp_ids.append(created.work_package_id)

    async with _connect(mcp_server) as mcp:
        result = await mcp.call_tool(
            "bulk_update_work_packages",
            {
                "items": [{"work_package_id": created.work_package_id, "subject": f"{subject} renamed"}],
                "select": ["work_package_id", "status"],
                "confirm": True,
            },
        )

    assert result.is_error is True
    assert "[validation_error] select field 'status' is not a valid WorkPackageWriteResult field" in _text(result)
    assert (await client.work_package.get(created.work_package_id)).subject == subject
