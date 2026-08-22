"""Characterization test: freezes the 6 Query Schema Extended MCP tool schemas
(get_query_filter, get_query_column, get_query_operator, get_query_sort_by,
list_query_filter_instance_schemas, get_query_filter_instance_schema).

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema. A future relocation of any of these functions to a different
module must leave this file completely unmodified; a diff to it would mean the
move changed the public tool contract, not just its location.
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
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_get_query_filter_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_query_filter"]
    assert tool.description == "Get a single query filter by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "string"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Url"},
        },
        "required": ["id", "name", "url"],
        "title": "QueryFilterSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"filter_id": {"title": "Filter Id", "type": "string"}},
        "required": ["filter_id"],
        "title": "get_query_filterArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["filter_id"]


def test_get_query_column_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_query_column"]
    assert tool.description == "Get a single query column by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "string"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "type": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Type"},
            "relation_type": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Relation Type"},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Url"},
        },
        "required": ["id", "name", "type", "relation_type", "url"],
        "title": "QueryColumnSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"column_id": {"title": "Column Id", "type": "string"}},
        "required": ["column_id"],
        "title": "get_query_columnArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["column_id"]


def test_get_query_operator_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_query_operator"]
    assert tool.description == "Get a single query operator by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "string"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Url"},
        },
        "required": ["id", "name", "url"],
        "title": "QueryOperatorSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"operator_id": {"title": "Operator Id", "type": "string"}},
        "required": ["operator_id"],
        "title": "get_query_operatorArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["operator_id"]


def test_get_query_sort_by_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_query_sort_by"]
    assert tool.description == "Get a single query sort-by definition by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "string"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "column": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Column"},
            "direction": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Direction"},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Url"},
        },
        "required": ["id", "name", "column", "direction", "url"],
        "title": "QuerySortBySummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"sort_by_id": {"title": "Sort By Id", "type": "string"}},
        "required": ["sort_by_id"],
        "title": "get_query_sort_byArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["sort_by_id"]


def test_list_query_filter_instance_schemas_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_query_filter_instance_schemas"]
    assert tool.description == "List query filter instance schemas globally or for a project."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Project"},
        },
        "title": "list_query_filter_instance_schemasArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project"]


def test_get_query_filter_instance_schema_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_query_filter_instance_schema"]
    assert tool.description == "Get a single query filter instance schema by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "string"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "filter": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Filter"},
            "operator_count": {"title": "Operator Count", "type": "integer"},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Url"},
        },
        "required": ["id", "name", "filter", "operator_count", "url"],
        "title": "QueryFilterInstanceSchemaSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"schema_id": {"title": "Schema Id", "type": "string"}},
        "required": ["schema_id"],
        "title": "get_query_filter_instance_schemaArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["schema_id"]
