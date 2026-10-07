"""Characterization test: freezes the 2 Work Package Pickers MCP tool schemas.

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


def test_list_available_assignees_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_available_assignees"]
    assert (
        tool.description
        == 'List the users and groups OpenProject accepts as assignee.\n\nPass work_package_id for an existing work package, or project (id or\nidentifier) for one not created yet -- exactly one of the two.\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\nThe same principals are valid as responsible (accountable).\n\nselect fields: id, type, name, email (see server instructions for\nselect\'s general semantics).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Work Package Id",
            },
            "project": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Project"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "title": "list_available_assigneesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "project", "select"]


def test_list_work_package_available_relation_candidates_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_available_relation_candidates"]
    assert (
        tool.description
        == 'List work packages that can be the other end of a new relation.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\nquery: text matching subject, project, type, status or display identifier.\nBare digits match the internal id on older/classic-identifier instances,\nbut the project sequence number on 17.8+ with semantic identifiers;\nuse a subject substring for a version-independent search.\nrelation_type: only candidates valid for this relation (relates,\nduplicates, duplicated, blocks, blocked, precedes, follows, includes,\npartof, requires, required, parent, child) -- OpenProject leaves out e.g. a work package\nthat would create a cycle. Candidates in projects outside\nOPENPROJECT_READ_PROJECTS are left out. limit is capped at\nOPENPROJECT_MAX_PAGE_SIZE (default 50).\n\nselect fields: id, display_id, subject, type, status, project (see server\ninstructions for select\'s general semantics).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Work Package Id"},
            "query": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Query"},
            "relation_type": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Relation Type",
            },
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_available_relation_candidatesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "query", "relation_type", "limit", "select"]
