"""A text that is exactly one wrapped read result loses the `<user-content>` pair on the way in.

A read returns long text wrapped in the delimiter; an agent that feeds a read result back into a
write call sends the marker along, and without the strip it is stored in the ticket for every
other reader. Only a value that is exactly one wrapped text loses the pair: two joined results,
a tag in the middle or a lone tag are stored as written, because the read side escapes them.
"""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _source_scan import ADAPTERS, matching_nodes
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import materialize_case

import openproject_ce_mcp.tools  # noqa: F401  (registers the tools in _TOOL_FUNCTIONS)
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.tool_params import BulkCreateWorkPackageItem, BulkUpdateWorkPackageItem
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS
from openproject_ce_mcp.tools_validation import (
    _validate_optional_custom_fields,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_required_text,
)
from openproject_ce_mcp.user_content import delimit_user_content, strip_user_content_wrapper

OPEN, CLOSE = "<user-content>", "</user-content>"

# (stored read result or hand-written value, expected result). Only the first group fails without the change.
WRAPPED = [
    (f"{OPEN}text{CLOSE}", "text"),
    (f"  {OPEN}text{CLOSE}\n", "text"),
    (f"{OPEN}line one\nline two{CLOSE}", "line one\nline two"),
    (f"{OPEN}{CLOSE}", ""),
    (f"{OPEN}a < b and <p>html</p>{CLOSE}", "a < b and <p>html</p>"),
    (f"{OPEN}&lt;/user-content> escaped inside{CLOSE}", "&lt;/user-content> escaped inside"),
]
AS_WRITTEN = [
    "plain text",
    f"{OPEN}a{CLOSE}\n{OPEN}b{CLOSE}",
    f"{OPEN}a{OPEN}b{CLOSE}{CLOSE}",
    f"{OPEN}a{CLOSE}b{CLOSE}",
    f"{OPEN}a{OPEN}b{CLOSE}",
    f"{OPEN}a{CLOSE} then more",
    f"before {OPEN}a{CLOSE}",
    f"{OPEN}only an opening tag",
    f"only a closing tag{CLOSE}",
    f"{OPEN}",
    f"{CLOSE}",
    f"{OPEN}a</user-content >",
    "<USER-CONTENT>a</USER-CONTENT>",
    "< user-content >a</ user-content >",
    "",
]


@pytest.mark.parametrize(("text", "expected"), WRAPPED, ids=[repr(t) for t, _ in WRAPPED])
def test_exactly_one_wrapped_text_loses_the_pair(text: str, expected: str) -> None:
    assert strip_user_content_wrapper(text) == expected


@pytest.mark.parametrize("text", AS_WRITTEN, ids=[repr(t) for t in AS_WRITTEN])
def test_everything_else_is_returned_unchanged(text: str) -> None:
    assert strip_user_content_wrapper(text) == text


BENIGN = ["plain text", "a < b", "<p>html</p>", "```py\nx = '<'\n```", "5 < 3 and 2 > 1", "&lt;tag&gt;"]
HOSTILE_READ = ["</user-content>", "a </user-content> b", "<user-content>x", f"{OPEN}x{CLOSE}"]


@pytest.mark.parametrize("text", BENIGN)
def test_a_benign_text_survives_the_read_write_round_trip(text: str) -> None:
    assert strip_user_content_wrapper(delimit_user_content(text)) == text
    assert delimit_user_content(strip_user_content_wrapper(delimit_user_content(text))) == delimit_user_content(text)


@pytest.mark.parametrize("text", HOSTILE_READ)
def test_a_hostile_text_keeps_its_escaped_tags_through_the_round_trip(text: str) -> None:
    read = delimit_user_content(text)
    written = strip_user_content_wrapper(read)

    assert OPEN not in written
    assert CLOSE not in written
    assert delimit_user_content(written) == read


WRAPPED_TEXT_VALIDATORS: list[Callable[..., Any]] = [
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_required_text,
]


@pytest.mark.parametrize("validate", WRAPPED_TEXT_VALIDATORS, ids=lambda f: f.__name__)
def test_a_validator_for_a_wrapped_on_read_field_strips_the_pair(validate: Callable[..., Any]) -> None:
    assert validate(f" {OPEN}text{CLOSE} ", field_name="description", max_length=None, wrapped_on_read=True) == "text"


@pytest.mark.parametrize("validate", WRAPPED_TEXT_VALIDATORS, ids=lambda f: f.__name__)
def test_a_validator_keeps_a_wrapped_value_by_default(validate: Callable[..., Any]) -> None:
    """Short fields (titles, locations, file paths) are never wrapped on read and keep the default."""
    assert validate(f"{OPEN}text{CLOSE}", field_name="title", max_length=None) == f"{OPEN}text{CLOSE}"


def test_a_value_that_is_only_a_wrapper_follows_the_empty_value_rule_of_each_validator() -> None:
    empty = f"{OPEN}{CLOSE}"

    assert _validate_optional_text(empty, field_name="d", max_length=None, wrapped_on_read=True) is None
    assert _validate_optional_update_text(empty, field_name="d", max_length=None, wrapped_on_read=True) == ""
    with pytest.raises(ValueError, match="comment is required"):
        _validate_required_text(empty, field_name="comment", max_length=None, wrapped_on_read=True)


def test_the_text_inside_the_pair_is_stripped_again() -> None:
    assert (
        _validate_optional_text(f"{OPEN}  text \n{CLOSE}", field_name="d", max_length=None, wrapped_on_read=True)
        == "text"
    )
    assert _validate_optional_text(f"{OPEN}   {CLOSE}", field_name="d", max_length=None, wrapped_on_read=True) is None
    assert (
        _validate_optional_update_text(f"{OPEN}   {CLOSE}", field_name="d", max_length=None, wrapped_on_read=True) == ""
    )


def test_the_length_limit_applies_to_the_text_without_the_pair() -> None:
    assert _validate_optional_text(f"{OPEN}abc{CLOSE}", field_name="d", max_length=3, wrapped_on_read=True) == "abc"
    with pytest.raises(ValueError, match="at most 3"):
        _validate_optional_text(f"{OPEN}abcd{CLOSE}", field_name="d", max_length=3, wrapped_on_read=True)


def test_short_fields_are_not_stripped() -> None:
    assert _validate_optional_query(f"{OPEN}x{CLOSE}", field_name="name", max_length=255) == f"{OPEN}x{CLOSE}"


def test_custom_fields_strip_a_top_level_string_only() -> None:
    result = _validate_optional_custom_fields(
        {
            "customField1": f"{OPEN}text{CLOSE}",
            "customField2": 5,
            "customField3": [f"{OPEN}item{CLOSE}", "plain"],
            "customField4": f"{OPEN}a{CLOSE}\n{OPEN}b{CLOSE}",
            "customField5": "plain",
        }
    )

    assert result == {
        "customField1": "text",
        "customField2": 5,
        "customField3": [f"{OPEN}item{CLOSE}", "plain"],
        "customField4": f"{OPEN}a{CLOSE}\n{OPEN}b{CLOSE}",
        "customField5": "plain",
    }


# Write tools whose text parameters are wrapped on read: tool -> the parameters that carry the text.
# "items[0].<name>" is a field of the first item of a bulk tool.
INVENTORY: dict[str, tuple[str, ...]] = {
    "create_work_package": ("description",),
    "create_subtask": ("description",),
    "update_work_package": ("description",),
    "bulk_create_work_packages": ("items[0].description",),
    "bulk_update_work_packages": ("items[0].description",),
    "add_work_package_comment": ("comment",),
    "update_work_package_comment": ("comment",),
    "create_project": ("description", "status_explanation"),
    "copy_project": ("description", "status_explanation"),
    "update_project": ("description", "status_explanation"),
    "create_version": ("description",),
    "update_version": ("description",),
    "update_document": ("description",),
    "create_news": ("description",),
    "update_news": ("description",),
    "create_work_package_relation": ("description",),
    "update_relation": ("description",),
    "create_time_entry": ("comment",),
    "update_time_entry": ("comment",),
    "create_time_entry_until": ("comment",),
    "update_time_entry_until": ("comment",),
    "create_work_package_reminder": ("note",),
    "update_reminder": ("note",),
    "create_meeting_agenda_item": ("notes",),
    "update_meeting_agenda_item": ("notes",),
    "create_meeting_outcome": ("notes",),
    "update_meeting_outcome": ("notes",),
    "create_work_package_attachment": ("description",),
    "create_container_attachment": ("description",),
}
INSIDE = "Marker745 inside"


def _with_override(kwargs: dict[str, Any], path: str, value: str) -> dict[str, Any]:
    kwargs = {key: (list(item) if isinstance(item, list) else item) for key, item in kwargs.items()}
    if path.startswith("items[0]."):
        name = path.removeprefix("items[0].")
        items = [dict(item) for item in kwargs["items"]]
        items[0][name] = value
        kwargs["items"] = items
    else:
        kwargs[path] = value
    return kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "path"),
    [(tool, path) for tool, paths in INVENTORY.items() for path in paths],
    ids=[f"{tool}:{path}" for tool, paths in INVENTORY.items() for path in paths],
)
async def test_a_write_tool_sends_the_text_without_the_pair(tool: str, path: str, tmp_path) -> None:
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)
    kwargs = _with_override(dict(materialized.kwargs), path, f"{OPEN}{INSIDE}{CLOSE}")
    # Project writes validate through a form request first and send what the form answers, so the
    # text is searched in every request body that is not a read.
    sent: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            sent.append(request.content)
        result = case.handler(request)
        return await result if inspect.isawaitable(result) else result

    client = OpenProjectClient(materialized.settings, transport=httpx.MockTransport(handler))
    try:
        await _TOOL_FUNCTIONS[tool](FakeContext(client), **kwargs, confirm=True)
    finally:
        await client.aclose()

    assert sent, f"{tool} issued no non-GET request"
    body = b"\n".join(sent)
    assert INSIDE.encode() in body
    assert OPEN.encode() not in body
    assert CLOSE.encode() not in body


def _bare_calls_and_keywords() -> dict[str, list[ast.AST]]:
    def is_wrap_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_delimit_user_content"
        )

    return matching_nodes(
        lambda node: is_wrap_call(node) or (isinstance(node, ast.keyword) and is_wrap_call(node.value)),
        directories=(ADAPTERS,),
    )


def _wrapped_field_names_and_unnamed_sites() -> tuple[set[str], Counter[str]]:
    names: set[str] = set()
    unnamed: Counter[str] = Counter()
    for where, nodes in _bare_calls_and_keywords().items():
        named_calls = {id(node.value) for node in nodes if isinstance(node, ast.keyword)}
        names.update(node.arg for node in nodes if isinstance(node, ast.keyword) and node.arg)
        unnamed.update({where: sum(1 for node in nodes if isinstance(node, ast.Call) and id(node) not in named_calls)})
    return names, +unnamed


# Wrapped on read and never accepted by a write tool.
READ_ONLY_WRAPPED_NAMES = {"help_text", "body", "author_name", "message"}
# Wrapped sites without a keyword name: the activity comment and details, the notification value (a
# conditional expression), and the three work package custom field text sites.
UNNAMED_WRAPPED_SITES = Counter(
    {
        "httpx_activity_api.py:normalize_activity": 2,
        "httpx_notification_api.py:normalize_notification_detail": 1,
        "_custom_fields.py:normalize_custom_field_entry": 2,
        "_custom_fields.py:extract_custom_comments": 1,
    }
)


def test_a_new_wrapped_read_field_without_a_write_counterpart_entry_is_noticed() -> None:
    """Guards the inventory against drift; it cannot fail because of the strip itself."""
    names, unnamed = _wrapped_field_names_and_unnamed_sites()
    write_names = names - READ_ONLY_WRAPPED_NAMES
    inventoried = {name.rsplit(".", 1)[-1] for paths in INVENTORY.values() for name in paths}

    assert unnamed == UNNAMED_WRAPPED_SITES
    assert write_names == inventoried
    assert names & READ_ONLY_WRAPPED_NAMES == READ_ONLY_WRAPPED_NAMES


def test_every_write_tool_with_a_wrapped_parameter_name_is_in_the_inventory() -> None:
    names, _ = _wrapped_field_names_and_unnamed_sites()
    wrapped_names = names - READ_ONLY_WRAPPED_NAMES
    with_wrapped_parameter = {
        tool for tool in WRITE_TOOL_CASES if wrapped_names & set(inspect.signature(_TOOL_FUNCTIONS[tool]).parameters)
    }

    bulk_item_names = set(BulkCreateWorkPackageItem.__annotations__) | set(BulkUpdateWorkPackageItem.__annotations__)
    bulk_tools = {"bulk_create_work_packages", "bulk_update_work_packages"}

    assert with_wrapped_parameter <= set(INVENTORY)
    assert not (wrapped_names & bulk_item_names) or bulk_tools <= set(INVENTORY)
    for read_only in READ_ONLY_WRAPPED_NAMES:
        assert not any(read_only in inspect.signature(_TOOL_FUNCTIONS[tool]).parameters for tool in WRITE_TOOL_CASES)
