"""Which tool parameters take a reference to an OpenProject resource, and what
they accept: a numeric id as a JSON number or a decimal string, never a
boolean or a decimal fraction.

The tables are checked against every registered tool, so a new reference
parameter typed `str` (refusing a JSON number) fails here until it is either
listed in REFERENCE_PARAMETERS and typed `IdOrName`, or listed in NAME_ONLY
with the reason it never takes an id.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from typing import Any

import pytest
from _tools_test_helpers import FakeContext
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from openproject_ce_mcp import tools_runtime
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app

REFERENCE_PARAMETERS: dict[str, tuple[str, ...]] = {
    "copy_project": ("source_project", "parent"),
    "create_board": ("project",),
    "create_meeting": ("project", "participant_user_refs"),
    "create_membership": ("project", "principal", "roles"),
    "create_news": ("project",),
    "create_project": ("parent",),
    "create_recurring_meeting": ("project",),
    "create_subtask": (
        "type",
        "version",
        "target_versions",
        "observed_in_versions",
        "project_phase",
        "assignee",
        "responsible",
        "priority",
        "category",
    ),
    "create_time_entry": ("project", "user", "activity"),
    "create_time_entry_until": ("project", "user", "activity"),
    "create_user_non_working_time": ("user_ref",),
    "create_user_working_hours": ("user_ref",),
    "create_version": ("project",),
    "create_work_package": (
        "project",
        "type",
        "version",
        "target_versions",
        "observed_in_versions",
        "project_phase",
        "assignee",
        "responsible",
        "priority",
        "category",
        "parent",
    ),
    "delete_project": ("project",),
    "delete_user_non_working_time": ("user_ref",),
    "delete_user_working_hours": ("user_ref",),
    "get_category": ("project",),
    "get_my_project_access": ("project",),
    "get_project": ("project",),
    "get_project_admin_context": ("project",),
    "get_project_configuration": ("project",),
    "get_project_work_package_context": ("project", "type"),
    "get_user": ("user",),
    "get_user_working_hours": ("user_ref",),
    "list_available_assignees": ("project",),
    "list_backlog_buckets": ("project",),
    "list_boards": ("project",),
    "list_capabilities": ("project",),
    "list_categories": ("project",),
    "list_documents": ("project",),
    "list_meetings": ("project",),
    "list_news": ("project",),
    "list_project_memberships": ("project",),
    "list_project_storages": ("project",),
    "list_query_filter_instance_schemas": ("project",),
    "list_recurring_meetings": ("project",),
    "list_sprints": ("project",),
    "list_time_entries": ("project", "user"),
    "list_types": ("project",),
    "list_user_non_working_times": ("user_ref",),
    "list_user_working_hours": ("user_ref",),
    "list_versions": ("project",),
    "list_views": ("project",),
    "list_work_packages": ("project", "type", "version", "observed_in_version", "assignee", "status", "priority"),
    "search_work_packages": ("project", "status", "assignee", "priority"),
    "set_project_favorite": ("project",),
    "update_board": ("project",),
    "update_meeting": ("participant_user_refs",),
    "update_membership": ("roles",),
    "update_project": ("project", "parent"),
    "update_time_entry": ("user", "activity"),
    "update_time_entry_until": ("user", "activity"),
    "update_user_non_working_time": ("user_ref",),
    "update_user_working_hours": ("user_ref",),
    "update_work_package": (
        "type",
        "version",
        "target_versions",
        "observed_in_versions",
        "sprint",
        "project_phase",
        "status",
        "assignee",
        "responsible",
        "priority",
        "category",
        "parent",
    ),
}

_PROJECT_STATUS = "a project status code or title such as on_track"
_NEW_IDENTIFIER = "the identifier being set; OpenProject never allows an all-digit one"
_QUERY_METADATA_ID = "OpenProject's string id of a query attribute, operator or sort, such as 'status' or '='"

_EXPECTED_DISPLAY_ID = (
    "a display id such as PROJ-51; a bare number is the internal id and is what the guard compares against"
)

_EXPECTED_PARENT_DISPLAY_ID = "a display id such as PROJ-51 naming the parent; a bare number is the internal id"

_EXPECTED_RELATED_DISPLAY_ID = (
    "a display id such as PROJ-51 naming the related work package; a bare number is the internal id"
)

NAME_ONLY: dict[tuple[str, str], str] = {
    ("update_work_package", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("delete_work_package", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("add_work_package_comment", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_work_package_attachment", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("set_work_package_watcher", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_work_package", "expect_parent_display_id"): _EXPECTED_PARENT_DISPLAY_ID,
    ("create_subtask", "expect_parent_display_id"): _EXPECTED_PARENT_DISPLAY_ID,
    ("update_work_package", "expect_parent_display_id"): _EXPECTED_PARENT_DISPLAY_ID,
    ("create_work_package_relation", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_work_package_reminder", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_work_package_wiki_link", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("delete_work_package_wiki_link", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_time_entry", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_time_entry_until", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_meeting_agenda_item", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("update_meeting_agenda_item", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_meeting_outcome", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("update_meeting_outcome", "expect_display_id"): _EXPECTED_DISPLAY_ID,
    ("create_work_package_relation", "expect_related_display_id"): _EXPECTED_RELATED_DISPLAY_ID,
    ("copy_project", "identifier"): _NEW_IDENTIFIER,
    ("copy_project", "status"): _PROJECT_STATUS,
    ("create_project", "identifier"): _NEW_IDENTIFIER,
    ("create_project", "status"): _PROJECT_STATUS,
    ("update_project", "identifier"): _NEW_IDENTIFIER,
    ("update_project", "status"): _PROJECT_STATUS,
    ("create_version", "status"): "a version status: open, locked or closed",
    ("update_version", "status"): "a version status: open, locked or closed",
    ("create_user", "status"): "a user status such as active or invited",
    ("create_grid", "scope"): "a web path such as /projects/<identifier>",
    ("list_grids", "scope"): "a web path such as /projects/<identifier>",
    ("list_views", "type"): "a view type name, compared case-insensitively",
    ("create_storage", "tenant_id"): "an external Azure tenant id",
    ("create_storage", "drive_id"): "an external Azure drive id",
    ("create_work_package_wiki_link", "identifier"): "a wiki provider's page identifier, sent as a string",
    ("create_work_package_wiki_link", "provider"): "a wiki provider identifier, a UUID or 'internal'",
    ("get_job_status", "job_status_id"): "a background job UUID",
    ("list_capabilities", "capability_id"): "a composite action and context string",
    ("get_query_column", "column_id"): _QUERY_METADATA_ID,
    ("get_query_filter", "filter_id"): _QUERY_METADATA_ID,
    ("get_query_filter_instance_schema", "schema_id"): _QUERY_METADATA_ID,
    ("get_query_operator", "operator_id"): _QUERY_METADATA_ID,
    ("get_query_sort_by", "sort_by_id"): _QUERY_METADATA_ID,
}

_REFERENCE_NAME = re.compile(
    r"project|source_project|parent|type|status|priority|version|target_versions|observed_in_versions?|category"
    r"|project_phase"
    r"|sprint|assignee|responsible|user|principal|roles|activity|identifier|provider|scope"
    r"|.*_(?:id|ids|ref|refs)"
)


def _settings_exposing_every_tool() -> Settings:
    flags = {field.name: True for field in dataclasses.fields(Settings) if field.name.startswith("enable_")}
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
        attachment_root="/tmp/op-attachments",
        **flags,
    )


_TOOLS = {tool.name: tool for tool in create_app(_settings_exposing_every_tool())._tool_manager.list_tools()}

_REFERENCE_ROWS = [(tool, parameter) for tool, parameters in REFERENCE_PARAMETERS.items() for parameter in parameters]


def _branches(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return schema.get("anyOf", [schema])


def _value_schema(tool: str, parameter: str) -> dict[str, Any]:
    """The schema a single reference value is checked against: the item schema
    for a list parameter."""
    schema = _TOOLS[tool].parameters["properties"][parameter]
    arrays = [branch for branch in _branches(schema) if branch.get("type") == "array"]
    return arrays[0]["items"] if arrays else schema


def _is_list_parameter(tool: str, parameter: str) -> bool:
    schema = _TOOLS[tool].parameters["properties"][parameter]
    return any(branch.get("type") == "array" for branch in _branches(schema))


def _types(schema: dict[str, Any]) -> set[str]:
    return {branch["type"] for branch in _branches(schema) if "type" in branch}


_PLACEHOLDER_BY_TYPE: dict[str, Any] = {"string": "x", "integer": 1, "boolean": False, "array": [], "object": {}}


def _arguments(tool: str, parameter: str, value: Any) -> dict[str, Any]:
    """`value` for `parameter`, plus a placeholder for every other required
    parameter, so validation can only fail on `parameter`."""
    properties = _TOOLS[tool].parameters["properties"]
    arguments = {
        name: _PLACEHOLDER_BY_TYPE[sorted(_types(properties[name]) - {"null"})[0]]
        for name in _TOOLS[tool].parameters.get("required", [])
    }
    arguments[parameter] = [value] if _is_list_parameter(tool, parameter) else value
    return arguments


def _validated(tool: str, parameter: str, value: Any) -> Any:
    validated = _TOOLS[tool].fn_metadata.validate_arguments(_arguments(tool, parameter, value))
    result = validated[parameter]
    return result[0] if _is_list_parameter(tool, parameter) else result


def test_every_registered_tool_is_exposed_to_the_guard() -> None:
    assert set(_TOOLS) == set(tools_runtime._TOOL_FUNCTIONS)


def test_every_row_names_an_existing_tool_and_parameter() -> None:
    rows = [*_REFERENCE_ROWS, *NAME_ONLY]
    stale = [
        f"{tool}.{parameter}"
        for tool, parameter in rows
        if tool not in tools_runtime._TOOL_FUNCTIONS
        or parameter not in inspect.signature(tools_runtime._TOOL_FUNCTIONS[tool]).parameters
    ]
    assert stale == []


def test_no_parameter_is_both_a_reference_and_name_only() -> None:
    assert set(_REFERENCE_ROWS) & set(NAME_ONLY) == set()


def test_every_reference_named_string_parameter_is_classified() -> None:
    """A parameter that takes an integer cannot refuse a JSON number, so only
    string-only parameters can carry the defect this guards against."""
    unclassified = []
    for tool, fn in tools_runtime._TOOL_FUNCTIONS.items():
        for parameter in inspect.signature(fn).parameters:
            if parameter == "ctx" or not _REFERENCE_NAME.fullmatch(parameter):
                continue
            if "integer" in _types(_value_schema(tool, parameter)):
                continue
            if (tool, parameter) not in set(_REFERENCE_ROWS) | set(NAME_ONLY):
                unclassified.append(f"{tool}.{parameter}")
    assert unclassified == []


@pytest.mark.parametrize(("tool", "parameter"), sorted(NAME_ONLY))
def test_a_name_only_parameter_stays_string_only(tool: str, parameter: str) -> None:
    assert _types(_value_schema(tool, parameter)) - {"null"} == {"string"}


@pytest.mark.parametrize(("tool", "parameter"), _REFERENCE_ROWS)
def test_a_reference_parameter_schema_allows_an_integer(tool: str, parameter: str) -> None:
    assert {"integer", "string"} <= _types(_value_schema(tool, parameter))


@pytest.mark.parametrize(("tool", "parameter"), _REFERENCE_ROWS)
def test_a_reference_parameter_accepts_a_number_and_a_string_unchanged(tool: str, parameter: str) -> None:
    number = _validated(tool, parameter, 7)
    text = _validated(tool, parameter, "7")

    assert (type(number), number) == (int, 7)
    assert (type(text), text) == (str, "7")


@pytest.mark.parametrize("value", [True, False, 7.0, 7.5])
@pytest.mark.parametrize(("tool", "parameter"), _REFERENCE_ROWS)
def test_a_reference_parameter_rejects_a_boolean_or_a_fraction(tool: str, parameter: str, value: Any) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _TOOLS[tool].fn_metadata.validate_arguments(_arguments(tool, parameter, value))

    assert {error["loc"][0] for error in excinfo.value.errors()} == {parameter}


class _Recorder:
    """Stands in for the client: records each service call the tool makes and
    returns an empty result."""

    def __init__(self, calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]], path: str = "") -> None:
        self.calls = calls
        self._path = path

    def __getattr__(self, name: str) -> _Recorder:
        return _Recorder(self.calls, f"{self._path}.{name}" if self._path else name)

    async def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((self._path, args, kwargs))
        return {}


# One tool per validator that turns an accepted number into the decimal string
# the services expect: (tool, the other arguments it needs, the parameter
# under test, the service call, and the position or keyword carrying it).
_CONVERSION_CASES = [
    ("get_project", {}, "project", "project.get", 0),
    ("list_versions", {}, "project", "version.list", "project"),
    ("update_project", {"project": "demo"}, "parent", "update_project", "parent"),
    ("get_user", {}, "user", "user.get_user", 0),
    ("list_work_packages", {}, "type", "work_package.list", "type"),
    ("update_work_package", {"work_package_id": 42}, "version", "work_package.update", "version"),
    ("update_work_package", {"work_package_id": 42}, "sprint", "work_package.update", "sprint"),
    ("update_work_package", {"work_package_id": 42}, "assignee", "work_package.update", "assignee"),
    ("update_work_package", {"work_package_id": 42}, "parent", "work_package.update", "parent_work_package_id"),
    ("list_time_entries", {}, "user", "time_entry.list_all", "user"),
    ("update_work_package", {"work_package_id": 42}, "target_versions", "work_package.update", "target_versions"),
    ("list_work_packages", {}, "observed_in_version", "work_package.list", "observed_in_version"),
    (
        "update_work_package",
        {"work_package_id": 42},
        "observed_in_versions",
        "work_package.update",
        "observed_in_versions",
    ),
    ("list_available_assignees", {}, "project", "work_package_picker.available_assignees", "project_ref"),
    (
        "create_meeting",
        {"project": "demo", "title": "Sync", "start_time": "2026-12-01T09:00:00Z", "duration": "PT1H"},
        "participant_user_refs",
        "meeting.create",
        "participant_user_refs",
    ),
    ("update_membership", {"membership_id": 3}, "roles", "membership.update", "roles"),
]


async def _run(tool: str, arguments: dict[str, Any]) -> _Recorder:
    client = _Recorder([])
    await _TOOLS[tool].run(arguments, FakeContext(client))  # type: ignore[arg-type]
    return client


@pytest.mark.parametrize(("tool", "arguments", "parameter", "call", "argument"), _CONVERSION_CASES)
async def test_a_numeric_reference_reaches_the_service_as_a_decimal_string(
    tool: str, arguments: dict[str, Any], parameter: str, call: str, argument: int | str
) -> None:
    client = await _run(tool, {**_arguments(tool, parameter, 7), **arguments})

    [(name, args, kwargs)] = client.calls
    sent = args[argument] if isinstance(argument, int) else kwargs[argument]
    assert name == call
    assert sent == (["7"] if _is_list_parameter(tool, parameter) else "7")


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize(("tool", "arguments", "parameter", "call", "argument"), _CONVERSION_CASES)
async def test_a_numeric_reference_below_one_is_rejected_with_the_field_name(
    tool: str, arguments: dict[str, Any], parameter: str, call: str, argument: int | str, value: int
) -> None:
    with pytest.raises(ToolError, match=rf"\[VALIDATION_FAILED\] {re.escape(parameter)}(\[0\])? must be at least 1"):
        await _run(tool, {**_arguments(tool, parameter, value), **arguments})
