"""Every write tool that takes a work package reference lets the caller name the ticket it means.

The scan finds the reference parameters of the registered write tools and of the bulk item types by what they
are typed as (`WorkPackageRef`/`OptionalWorkPackageRef`, compared by the identity of their `Field` metadata),
plus the `parent` of the work package tools and items, which is typed `IdOrName`. The pairs found must equal the
table below in both directions, and each owner must expose the sibling `expect_*` parameter of the pair's role.
A tool added later with a reference and no way to name the ticket fails here.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable, Mapping
from typing import Annotated, Any, NotRequired, Required, get_args, get_origin, get_type_hints

import pytest
from typing_extensions import is_typeddict

from openproject_ce_mcp import tool_params, tools, tools_runtime
from openproject_ce_mcp.tool_params import OptionalWorkPackageRef, WorkPackageRef

_REFERENCE_FIELDS = {id(meta) for alias in (WorkPackageRef, OptionalWorkPackageRef) for meta in alias.__metadata__}
_WORK_PACKAGE_TOOLS_MODULE = "openproject_ce_mcp.tools_work_packages"

SIBLING_BY_PARAMETER = {
    "work_package_id": "expect_display_id",
    "related_to_work_package_id": "expect_related_display_id",
    "parent": "expect_parent_display_id",
    "parent_work_package_id": "expect_parent_display_id",
}

EXPECTED_PAIRS: dict[tuple[str, str], str] = {
    ("add_work_package_comment", "work_package_id"): "expect_display_id",
    ("delete_work_package", "work_package_id"): "expect_display_id",
    ("update_work_package", "work_package_id"): "expect_display_id",
    ("update_work_package", "parent"): "expect_parent_display_id",
    ("create_work_package", "parent"): "expect_parent_display_id",
    ("create_subtask", "parent_work_package_id"): "expect_parent_display_id",
    ("BulkCreateWorkPackageItem", "parent"): "expect_parent_display_id",
    ("BulkCreateWorkPackageItem", "parent_work_package_id"): "expect_parent_display_id",
    ("BulkUpdateWorkPackageItem", "work_package_id"): "expect_display_id",
    ("BulkUpdateWorkPackageItem", "parent"): "expect_parent_display_id",
    ("BulkUpdateWorkPackageItem", "parent_work_package_id"): "expect_parent_display_id",
    ("set_work_package_watcher", "work_package_id"): "expect_display_id",
    ("create_work_package_attachment", "work_package_id"): "expect_display_id",
    ("create_work_package_relation", "work_package_id"): "expect_display_id",
    ("create_work_package_relation", "related_to_work_package_id"): "expect_related_display_id",
    ("create_work_package_reminder", "work_package_id"): "expect_display_id",
    ("create_work_package_wiki_link", "work_package_id"): "expect_display_id",
    ("delete_work_package_wiki_link", "work_package_id"): "expect_display_id",
    ("create_time_entry", "work_package_id"): "expect_display_id",
    ("create_time_entry_until", "work_package_id"): "expect_display_id",
    ("create_meeting_agenda_item", "work_package_id"): "expect_display_id",
    ("update_meeting_agenda_item", "work_package_id"): "expect_display_id",
    ("create_meeting_outcome", "work_package_id"): "expect_display_id",
    ("update_meeting_outcome", "work_package_id"): "expect_display_id",
}

Inventory = dict[tuple[str, str], frozenset[str]]


def _carries_reference_field(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Annotated:
        return any(id(meta) in _REFERENCE_FIELDS for meta in annotation.__metadata__) or _carries_reference_field(
            get_args(annotation)[0]
        )
    if origin in (Required, NotRequired):
        return _carries_reference_field(get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return any(_carries_reference_field(member) for member in get_args(annotation))
    return False


def _bulk_item_types() -> list[type]:
    return [
        value
        for value in vars(tool_params).values()
        if inspect.isclass(value) and is_typeddict(value) and value.__module__ == tool_params.__name__
    ]


def _inventory(functions: Mapping[str, Callable[..., Any]], *, is_write: Callable[[str], bool]) -> Inventory:
    """(owner, reference parameter) -> every parameter the owner has, for each write tool and each item type."""
    found: Inventory = {}
    for name, function in functions.items():
        if not is_write(name):
            continue
        parameters = inspect.signature(function, eval_str=True).parameters
        in_work_package_tools = function.__module__ == _WORK_PACKAGE_TOOLS_MODULE
        for parameter, spec in parameters.items():
            if _carries_reference_field(spec.annotation) or (in_work_package_tools and parameter == "parent"):
                found[(name, parameter)] = frozenset(parameters)
    for item in _bulk_item_types():
        hints = get_type_hints(item, include_extras=True)
        for parameter, annotation in hints.items():
            if _carries_reference_field(annotation) or parameter == "parent":
                found[(item.__name__, parameter)] = frozenset(hints)
    return found


def _live_inventory() -> Inventory:
    annotations = tools.TOOL_ANNOTATIONS
    return _inventory(tools_runtime._TOOL_FUNCTIONS, is_write=lambda name: not annotations[name].read_only_hint)


def _problems(found: Inventory) -> list[str]:
    problems = [f"found but not listed: {pair}" for pair in sorted(found.keys() - EXPECTED_PAIRS.keys())]
    problems += [f"listed but not found: {pair}" for pair in sorted(EXPECTED_PAIRS.keys() - found.keys())]
    for (owner, parameter), parameters in sorted(found.items()):
        sibling = SIBLING_BY_PARAMETER.get(parameter)
        if sibling is None:
            problems.append(f"{owner}.{parameter} has no role in SIBLING_BY_PARAMETER")
        elif sibling not in parameters:
            problems.append(f"{owner}.{parameter} lacks its sibling {sibling}")
        elif EXPECTED_PAIRS.get((owner, parameter), sibling) != sibling:
            problems.append(f"{owner}.{parameter} is listed with a sibling other than {sibling}")
    return problems


def test_every_write_reference_has_the_sibling_that_names_the_ticket() -> None:
    assert _problems(_live_inventory()) == []


def test_the_scan_finds_the_listed_pairs_and_so_cannot_match_nothing() -> None:
    assert set(_live_inventory()) == set(EXPECTED_PAIRS)
    assert len(EXPECTED_PAIRS) == 24


def test_the_listed_sibling_of_each_pair_is_the_one_its_role_names() -> None:
    assert {pair: SIBLING_BY_PARAMETER[pair[1]] for pair in EXPECTED_PAIRS} == EXPECTED_PAIRS


def test_a_read_tool_with_a_reference_is_not_in_the_inventory() -> None:
    owners = {owner for owner, _ in _live_inventory()}

    assert "get_work_package" not in owners
    assert "list_work_package_attachments" not in owners


def test_a_project_parent_is_not_a_work_package_reference() -> None:
    owners = {owner for owner, _ in _live_inventory()}

    assert "update_project" not in owners
    assert "create_project" not in owners


async def _planted_without_a_sibling(ctx: Any, work_package_id: WorkPackageRef, confirm: bool = False) -> None: ...


async def _planted_with_a_sibling(
    ctx: Any, work_package_id: WorkPackageRef, expect_display_id: str | None = None, confirm: bool = False
) -> None: ...


async def _planted_with_an_unrelated_parameter(ctx: Any, project: str, confirm: bool = False) -> None: ...


async def _reminder_without_its_sibling(
    ctx: Any, work_package_id: WorkPackageRef, remind_at: str, confirm: bool = False
) -> None: ...


def _planted(name: str, function: Callable[..., Any]) -> Inventory:
    functions = {**tools_runtime._TOOL_FUNCTIONS, name: function}
    annotations = tools.TOOL_ANNOTATIONS
    return _inventory(functions, is_write=lambda tool: tool == name or not annotations[tool].read_only_hint)


def test_a_planted_write_tool_with_a_reference_and_no_sibling_fails() -> None:
    problems = _problems(_planted("planted_write", _planted_without_a_sibling))

    assert "found but not listed: ('planted_write', 'work_package_id')" in problems
    assert "planted_write.work_package_id lacks its sibling expect_display_id" in problems


def test_a_planted_write_tool_with_a_sibling_fails_only_for_being_unlisted() -> None:
    assert _problems(_planted("planted_write", _planted_with_a_sibling)) == [
        "found but not listed: ('planted_write', 'work_package_id')"
    ]


def test_a_planted_write_tool_with_an_unrelated_parameter_passes() -> None:
    assert _problems(_planted("planted_write", _planted_with_an_unrelated_parameter)) == []


def test_removing_the_sibling_of_an_existing_tool_fails() -> None:
    functions = {**tools_runtime._TOOL_FUNCTIONS, "create_work_package_reminder": _reminder_without_its_sibling}
    annotations = tools.TOOL_ANNOTATIONS
    found = _inventory(functions, is_write=lambda name: not annotations[name].read_only_hint)

    assert _problems(found) == ["create_work_package_reminder.work_package_id lacks its sibling expect_display_id"]


@pytest.mark.parametrize(
    ("owner", "parameter"),
    [("create_work_package_relation", "related_to_work_package_id"), ("update_work_package", "parent")],
)
def test_a_wrongly_named_sibling_is_not_accepted(owner: str, parameter: str) -> None:
    found = _live_inventory()
    parameters = found[(owner, parameter)] - {SIBLING_BY_PARAMETER[parameter]} | {"expect_display_id_typo"}

    assert _problems({**found, (owner, parameter): parameters}) == [
        f"{owner}.{parameter} lacks its sibling {SIBLING_BY_PARAMETER[parameter]}"
    ]
