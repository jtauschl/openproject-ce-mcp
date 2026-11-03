"""Characterization test: freezes the 4 Sprints MCP tool schemas.

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


def test_list_sprints_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_sprints"]
    assert (
        tool.description
        == "List Backlogs sprints, optionally filtered by name search.\n\nOmit project to list every sprint visible to the current token across all\nprojects; pass it to list only sprints for that project.\n\nRequires the OpenProject Backlogs module and OpenProject 17.3 or newer;\nunavailable instances return a clear not-found message.\n\ntotal is only the count of allowed sprints returned on THIS page, not a full count of all matches; the search\nstops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, defining_workspace, defining_workspace_id, finish_date, id, name, start_date, status, updated_at.",
                "title": "Select",
            },
        },
        "title": "list_sprintsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select"]


def test_get_sprint_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_sprint"]
    assert tool.description == "Get a Backlogs sprint by id. Requires OpenProject 17.3 or newer."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "sprint_id": {
                "title": "Sprint Id",
                "type": "integer",
            },
        },
        "required": ["sprint_id"],
        "title": "get_sprintArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["sprint_id"]


def test_list_backlog_buckets_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_backlog_buckets"]
    assert (
        tool.description
        == "List Backlogs backlog buckets, optionally filtered by name search.\n\nOmit project to list every backlog bucket visible to the current token\nacross all projects; pass it to list only backlog buckets for that project.\n\nRequires the OpenProject Backlogs module and OpenProject 17.6 or newer;\nunavailable instances return a clear not-found message.\n\ntotal is only the count of allowed backlog buckets returned on THIS page, not a full count of all matches; the\nsearch stops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset\nis null."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, defining_workspace, defining_workspace_id, id, name, updated_at.",
                "title": "Select",
            },
        },
        "title": "list_backlog_bucketsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select"]


def test_get_backlog_bucket_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_backlog_bucket"]
    assert tool.description == "Get a Backlogs backlog bucket by id. Requires OpenProject 17.6 or newer."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "backlog_bucket_id": {
                "title": "Backlog Bucket Id",
                "type": "integer",
            },
        },
        "required": ["backlog_bucket_id"],
        "title": "get_backlog_bucketArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["backlog_bucket_id"]
