"""Characterization test: freezes the 2 Watchers MCP tool schemas.

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


def test_list_work_package_watchers_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_watchers"]
    assert (
        tool.description
        == 'List watchers of a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\n\nselect fields: id, name (see server instructions for select\'s general semantics).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
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
        "required": ["work_package_id"],
        "title": "list_work_package_watchersArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


def test_list_work_package_available_watchers_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_available_watchers"]
    assert (
        tool.description
        == 'List the users OpenProject accepts as a new watcher of a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\nPass a returned id to set_work_package_watcher.\n\nselect fields: id, type, name, email (see server instructions for\nselect\'s general semantics).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Work Package Id"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_available_watchersArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


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


def test_list_work_package_available_projects_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_available_projects"]
    assert (
        tool.description
        == "List the projects a work package can be moved to.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nOnly projects inside OPENPROJECT_READ_PROJECTS are listed; moving still\nneeds the target in OPENPROJECT_WRITE_PROJECTS (update_work_package's\nproject field).\n\nselect fields: id, name, identifier (see server instructions for\nselect's general semantics).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Work Package Id"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_available_projectsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


def test_list_work_package_relation_candidates_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_relation_candidates"]
    assert (
        tool.description
        == "List work packages that can be the other end of a new relation.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nquery: text to match against the candidates' subject or id.\nrelation_type: only candidates valid for this relation (relates,\nduplicates, duplicated, blocks, blocked, precedes, follows, includes,\npartof, requires, required) -- OpenProject leaves out e.g. a work package\nthat would create a cycle. Candidates in projects outside\nOPENPROJECT_READ_PROJECTS are left out. limit is capped at\nOPENPROJECT_MAX_PAGE_SIZE (default 50).\n\nselect fields: id, display_id, subject, type, status, project (see server\ninstructions for select's general semantics).\n"
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
        "title": "list_work_package_relation_candidatesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "query", "relation_type", "limit", "select"]


def test_list_work_package_revisions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_revisions"]
    assert (
        tool.description
        == 'List the repository revisions (commits) linked to a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\nOpenProject links a commit when its message references the work package.\nEmpty when the project has no repository configured.\n\nselect fields: id, formatted_identifier, author_name, message, created_at\n(see server instructions for select\'s general semantics).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Work Package Id"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_revisionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "select"]


def test_get_revision_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_revision"]
    assert tool.description == "Return one repository revision (commit) by its OpenProject id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "identifier": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Identifier"},
            "formatted_identifier": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Formatted Identifier"},
            "author_name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Author Name"},
            "author": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Author"},
            "message": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Message"},
            "project": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Project"},
            "created_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Created At"},
            "message_truncated": {"default": False, "title": "Message Truncated", "type": "boolean"},
        },
        "required": [
            "id",
            "identifier",
            "formatted_identifier",
            "author_name",
            "author",
            "message",
            "project",
            "created_at",
        ],
        "title": "RevisionSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"revision_id": {"title": "Revision Id", "type": "integer"}},
        "required": ["revision_id"],
        "title": "get_revisionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["revision_id"]


def test_set_work_package_watcher_schema() -> None:
    tool = _tools(create_app(_make_settings()))["set_work_package_watcher"]
    assert (
        tool.description
        == "Prepare or add/remove a watcher on a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nwatching=true adds the watcher; watching=false removes it. The two\npreviews are NOT symmetric: watching=true's preview looks up and returns\nthe real watcher's summary (result is populated); watching=false's\npreview makes no extra lookup and always returns result=null.\n"
    )
    assert tool.output_schema == {
        "$defs": {
            "WatcherSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                    "login": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Login",
                    },
                },
                "required": ["id", "name", "login"],
                "title": "WatcherSummary",
                "type": "object",
            },
        },
        "properties": {
            "action": {
                "title": "Action",
                "type": "string",
            },
            "state": {
                "enum": ["rejected", "invalid", "preview", "confirmed"],
                "title": "State",
                "type": "string",
            },
            "ready": {
                "title": "Ready",
                "type": "boolean",
            },
            "message": {
                "title": "Message",
                "type": "string",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "watcher_user_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Watcher User Id",
            },
            "validation_errors": {
                "additionalProperties": True,
                "title": "Validation Errors",
                "type": "object",
            },
            "result": {
                "anyOf": [
                    {
                        "$ref": "#/$defs/WatcherSummary",
                    },
                    {
                        "type": "null",
                    },
                ],
            },
        },
        "required": [
            "action",
            "state",
            "ready",
            "message",
            "work_package_id",
            "watcher_user_id",
            "validation_errors",
            "result",
        ],
        "title": "WatcherWriteResult",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "user_id": {
                "title": "User Id",
                "type": "integer",
            },
            "watching": {
                "title": "Watching",
                "type": "boolean",
            },
            "confirm": {
                "default": False,
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
    assert list(tool.parameters["properties"]) == ["work_package_id", "user_id", "watching", "confirm"]
