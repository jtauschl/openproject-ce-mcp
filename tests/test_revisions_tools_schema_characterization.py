"""Characterization test: freezes the Revisions MCP tool schema.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (no tool carries one, see test_compact_result_seam.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
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


def test_list_work_package_revisions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_revisions"]
    assert tool.description == (
        "List the repository revisions linked to a work package, limited to projects the read scope covers.\n\n"
        "An empty list also means the repository module is off or the caller may not view changesets; the author "
        "name\nand message come from the repository and are delimited as untrusted content."
    )
    assert tool.output_schema is None
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]
    assert tool.parameters["required"] == ["work_package_id"]
    assert tool.parameters["additionalProperties"] is False
