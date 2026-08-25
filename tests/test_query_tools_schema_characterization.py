"""Characterization test: freezes the 1 Query Execution MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (trimmed tools register with structured_output=False and have
none, see test_trimming.py). A future relocation of any of these functions to
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


def test_execute_query_schema() -> None:
    tool = _tools(create_app(_make_settings()))["execute_query"]
    assert (
        tool.description
        == "Execute a saved OpenProject query by id and return its resolved work packages.\n\nquery_id: the query's own numeric id — obtain it from get_view/list_views's\nquery_id field, or from list_boards/get_board (a board's id IS its\nunderlying query id, since OpenProject Boards are Query resources).\n\nRuns the query server-side (OpenProject resolves its stored filters/sort/\ngroup_by and returns real work packages, not just the query's\ndefinition) — no client-side filter translation happens here. Results are\nstill filtered against this MCP's own OPENPROJECT_READ_PROJECTS allowlist\nbefore being returned, since the query itself executes with the API\ntoken's full server-side permissions.\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "query_id": {
                "title": "Query Id",
                "type": "integer",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
        },
        "required": ["query_id"],
        "title": "execute_queryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["query_id", "offset", "limit"]
