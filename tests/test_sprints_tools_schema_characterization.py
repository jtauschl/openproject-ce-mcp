"""Characterization test: freezes the 4 Sprints MCP tool schemas.

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


def test_list_sprints_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_sprints"]
    assert (
        tool.description
        == "List Backlogs sprints, optionally filtered by name search.\n\nproject: numeric id (e.g., 7) or identifier (e.g., \"my-project\"), not display\nname. Omit it to list every sprint visible to the current token across all\nprojects; pass it to list only sprints for that project.\n\nRequires the OpenProject Backlogs module; unavailable instances return a clear not-found message.\n\nselect fields: id, name (see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed sprints returned on THIS page, not a full count of\nall matches — the search stops as soon as it has enough, so an exact\ntotal would need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "search": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Search",
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
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
    assert tool.description == "Get a Backlogs sprint by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Status",
            },
            "start_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Start Date",
            },
            "finish_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Finish Date",
            },
            "defining_workspace_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Defining Workspace Id",
            },
            "defining_workspace": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Defining Workspace",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "name",
            "status",
            "start_date",
            "finish_date",
            "defining_workspace_id",
            "defining_workspace",
            "created_at",
            "updated_at",
        ],
        "title": "SprintDetail",
        "type": "object",
    }
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
        == "List Backlogs backlog buckets, optionally filtered by name search.\n\nproject: numeric id (e.g., 7), identifier (e.g., \"my-project\"), or display\nname. Omit it to list every backlog bucket visible to the current token\nacross all projects; pass it to list only backlog buckets for that project.\n\nRequires the OpenProject Backlogs module and OpenProject 17.6 or newer;\nunavailable instances return a clear not-found message.\n\nselect fields: id, name, defining_workspace_id, defining_workspace,\ncreated_at, updated_at (see server instructions for select's general\nsemantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed backlog buckets returned on THIS page, not a full count\nof all matches — the search stops as soon as it has enough, so an exact\ntotal would need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "search": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Search",
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
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "defining_workspace_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Defining Workspace Id",
            },
            "defining_workspace": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Defining Workspace",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": ["id", "name", "defining_workspace_id", "defining_workspace", "created_at", "updated_at"],
        "title": "BacklogBucketDetail",
        "type": "object",
    }
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
