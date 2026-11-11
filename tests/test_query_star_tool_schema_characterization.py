"""Characterization test: freezes the saved query star MCP tool schema.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (no tool carries one, see test_compact_result_seam.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from pydantic import SecretStr

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": SecretStr("token"),
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "enable_work_package_write": True,
        "enable_project_write": True,
        "enable_membership_write": True,
        "enable_version_write": True,
        "enable_board_write": True,
        "enable_admin_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_set_query_starred_schema() -> None:
    tool = _tools(create_app(_make_settings()))["set_query_starred"]
    assert tool.description == (
        "Star or unstar a saved query.\n\n"
        "The star belongs to the query, not to you: starring a public query changes it for everyone, and a query of a\n"
        "project needs that project in OPENPROJECT_WRITE_PROJECTS. A public query without a project needs the write scope\n"
        "`*`. A private query can be starred only by its owner. Only a caller OpenProject allows to star or unstar the "
        "query\ncan do it; a query already in the wanted state is left unchanged.\n"
    )
    assert tool.output_schema is None
    assert list(tool.parameters["properties"]) == ["query_id", "starred", "confirm"]
    assert tool.parameters["required"] == ["query_id", "starred"]
    assert tool.parameters["properties"]["starred"]["type"] == "boolean"
    assert tool.parameters["properties"]["confirm"]["default"] is False
    assert tool.parameters["additionalProperties"] is False
