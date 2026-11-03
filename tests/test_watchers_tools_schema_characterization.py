"""Characterization test: freezes the 2 Watchers MCP tool schemas.

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


def test_list_work_package_watchers_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_watchers"]
    assert tool.description == "List watchers of a work package."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: id, login, name.",
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_watchersArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


def test_set_work_package_watcher_schema() -> None:
    tool = _tools(create_app(_make_settings()))["set_work_package_watcher"]
    assert (
        tool.description
        == "Add/remove a watcher on a work package.\n\nwatching=true adds the watcher; watching=false removes it. The two\npreviews are NOT symmetric: watching=true's preview looks up and returns\nthe user's summary (result is populated; whether the user already watches\nis not checked); watching=false's preview makes no extra lookup and always\nreturns result=null.\nexpect_display_id names the ticket you mean and makes a mismatch an error; see the server instructions.\nThe result names the work package the reference resolved to in `target`.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "user_id": {"title": "User Id", "type": "integer"},
            "watching": {"title": "Watching", "type": "boolean"},
            "expect_display_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Display id of the work package you mean, e.g. "PROJ-51"; see the server instructions.',
                "title": "Expect Display Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "user_id", "watching"],
        "title": "set_work_package_watcherArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "work_package_id",
        "user_id",
        "watching",
        "expect_display_id",
        "confirm",
    ]
