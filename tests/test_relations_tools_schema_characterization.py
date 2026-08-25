"""Characterization test: freezes the 5 Relations MCP tool schemas.

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


def test_create_work_package_relation_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_work_package_relation"]
    assert (
        tool.description
        == "Prepare or create a relation between work packages.\n\nBoth work_package_id and related_to_work_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nrelation_type: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required.\nwork_package_id becomes from_id and related_to_work_package_id becomes to_id — but OpenProject stores\nonly one canonical type per pair and silently rewrites the other: creating with relation_type='precedes'\n(or 'blocked', 'duplicated', 'partof', 'required') is stored as the paired canonical type ('follows',\n'blocks', 'duplicates', 'includes', 'requires' respectively) with from_id/to_id SWAPPED relative to\nwork_package_id/related_to_work_package_id. The canonical types themselves ('follows', 'blocks',\n'duplicates', 'includes', 'requires', and non-directional 'relates') are stored exactly as given, with\nfrom_id/to_id unswapped. This happens once at creation and does not depend on which work package's\nrelations you later query — always read the actual type/from_id/to_id from the response rather than\nassuming they match what you requested.\n"
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
            "related_to_work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Related To Work Package Id",
            },
            "relation_type": {
                "title": "Relation Type",
                "type": "string",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "lag": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Lag",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "related_to_work_package_id", "relation_type"],
        "title": "create_work_package_relationArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "work_package_id",
        "related_to_work_package_id",
        "relation_type",
        "description",
        "lag",
        "confirm",
    ]


def test_delete_relation_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_relation"]
    assert tool.description == "Prepare or delete a relation between work packages."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "relation_id": {
                "title": "Relation Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["relation_id"],
        "title": "delete_relationArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["relation_id", "confirm"]


def test_get_work_package_relations_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_work_package_relations"]
    assert (
        tool.description
        == 'Get all relations for a work package (blocks, relates to, duplicates, etc.).\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\ntype/from_id/to_id reflect how OpenProject actually stored the relation, which does not depend on\nwhich work package\'s relations you query — but can differ from how it was originally requested, since\nOpenProject canonicalizes some relation types at creation time (e.g. a relation requested as \'precedes\'\nis stored as \'follows\' with from_id/to_id swapped; see create_work_package_relation). Use from_id/to_id\ntogether with type, not the request you expect to have made, to determine the actual direction.\n\nEach result additionally carries queried_perspective, a caller-relative reading of the same relation\nfrom work_package_id\'s own side — never a replacement for type/from_id/to_id, which stay unchanged.\nqueried_perspective.direction is "from" or "to" (which raw id equals work_package_id);\nqueried_perspective.effective_type is the type as read FROM work_package_id\'s side (e.g. a stored\n"blocks" relation reads as effective_type="blocked" when work_package_id is the to_id side, "blocks"\nwhen it\'s the from_id side). queried_perspective.predecessor_id/successor_id are populated only for\nthe precedes/follows type pair (OpenProject\'s own scheduling-relevant relation types); both stay null\nfor every other type, since no other type has an equivalent first/second concept.\n\nselect fields: id, type, to_id (see server instructions for select\'s general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call\'s offset to page past the cap. total is only\nthe count of allowed relations returned on THIS page, not a full count\nof all matches — the search stops as soon as it has enough, so an exact\ntotal would need an extra full walk. Page until next_offset is null.\n'
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
        "required": ["work_package_id"],
        "title": "get_work_package_relationsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "offset", "limit", "select"]


def test_list_relations_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_relations"]
    assert (
        tool.description
        == "List all relations across the instance, optionally filtered by type (e.g. 'blocks', 'follows').\n\ntype/from_id/to_id reflect how OpenProject actually stored the relation (it does not change depending\non which work package's relations you're viewing), which can differ from how it was originally\nrequested — OpenProject canonicalizes some relation types at creation time (e.g. a relation requested\nas 'precedes' is stored as 'follows' with from_id/to_id swapped; see create_work_package_relation).\nFiltering by relation_type matches the stored (canonical) type, not necessarily the type a caller\noriginally requested when creating it.\n\nEach result's queried_perspective field is always null here — a caller-relative reading needs one\nanchor work package to read the relation FROM, and this instance-wide listing has none. Use\nget_work_package_relations instead when you need queried_perspective populated.\n\nselect fields: id, type, to_id (see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed relations returned on THIS page, not a full count\nof all matches — the search stops as soon as it has enough, so an exact\ntotal would need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "relation_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Relation Type",
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
        "title": "list_relationsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["relation_type", "offset", "limit", "select"]


def test_update_relation_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_relation"]
    assert (
        tool.description
        == 'Prepare or update the type or description of a relation. Set confirm=true to write.\n\nrelation_type is subject to the same write-time canonicalization as create_work_package_relation:\nsetting it to a "reverse" pair member (precedes, blocked, duplicated, partof, required) rewrites the\nstored relation to the paired canonical type (follows, blocks, duplicates, includes, requires) with\nfrom_id/to_id swapped relative to the relation\'s existing from/to. Read the actual type/from_id/to_id\nback afterward rather than assuming they match what was requested.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "relation_id": {
                "title": "Relation Id",
                "type": "integer",
            },
            "relation_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Relation Type",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["relation_id"],
        "title": "update_relationArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["relation_id", "relation_type", "description", "confirm"]
