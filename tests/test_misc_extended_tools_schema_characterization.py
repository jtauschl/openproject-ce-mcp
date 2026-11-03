"""Characterization test: freezes the 6 Misc Extended MCP tool schemas
(render_text, list_help_texts, get_help_text, list_working_days,
list_non_working_days, get_custom_option).

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema. A future relocation of any of these functions to a different
module must leave this file completely unmodified; a diff to it would mean
the move changed the public tool contract, not just its location.
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
        "enable_metadata_tools": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_render_text_schema() -> None:
    tool = _tools(create_app(_make_settings()))["render_text"]
    assert tool.description == (
        "Render markdown or plain text to HTML using the OpenProject API. format: 'markdown' or 'plain'.\n\n"
        "Refused unless OPENPROJECT_READ_PROJECTS is `*` and no field of work packages, projects, versions,\n"
        "documents, meetings, posts, users, groups, principals or views is hidden: OpenProject expands macros such as\n"
        "#123 or version#4 into the name or display id of any record, whatever its project."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "text": {"title": "Text", "type": "string"},
            "format": {"default": "markdown", "title": "Format", "type": "string"},
        },
        "required": ["text"],
        "title": "render_textArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["text", "format"]


def test_list_help_texts_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_help_texts"]
    assert tool.description == "List all help texts configured for work-package and project attributes."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_help_textsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_get_help_text_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_help_text"]
    assert tool.description == "Get a single help text by id."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "help_text_id": {"title": "Help Text Id", "type": "integer"},
        },
        "required": ["help_text_id"],
        "title": "get_help_textArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["help_text_id"]


def test_list_working_days_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_working_days"]
    assert tool.description == (
        "List the Mon–Sun working-day configuration (7 entries showing which weekdays are working days)."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_working_daysArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_list_non_working_days_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_non_working_days"]
    assert (
        tool.description == "List non-working days (public holidays / closures) for a given year, or the current year."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "year": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Year",
            }
        },
        "title": "list_non_working_daysArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["year"]


def test_get_custom_option_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_custom_option"]
    assert tool.description == "Fetch the label/value of a single custom field option by id."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "custom_option_id": {"title": "Custom Option Id", "type": "integer"},
        },
        "required": ["custom_option_id"],
        "title": "get_custom_optionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["custom_option_id"]
