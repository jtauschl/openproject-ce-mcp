"""A value of a field the settings hide appears nowhere in a read result, not only in the record that carries it.

Instrument A, the record scan (counterpart of `test_write_results_hide_values_everywhere.py`). Every read tool runs
against the sentinel fake of `_read_tool_harness`, where each scalar of each resource is a string, number or date of its
own and a resource reads the same wherever it is linked. For every scalar field of a record in the result (found by
walking the result dataclasses and their lists) that holds a sentinel, the field is hidden in every entity, the tool
runs again through the serializer a caller sees, and the sentinel must be nowhere in the output: not as the member of
a wrapper, not in a row of another class, not inside a URL or a text, not in a nested row. The visible run counts
the places that hold the value, so a fake that stops echoing it cannot turn the scan into a pass.

Stated boundary: one generic call per tool; the first and the second row of a list plus the wrapper; values the fake
gives a sentinel (strings, numbers, dates; booleans and enums are not searchable); the project ids stay 1, 97 to 99
because the scope checks need them, so a copy of a project id is not found here. The scan finds copies the fake can
show; it does not prove that no other representation of a value exists (a value inside a free text of the server, a
hash). A tool whose generic call is refused, or refused once a field is hidden, is listed with its reason.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import typing
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import (
    FOREIGN,
    OVERRIDES,
    READABLE,
    SENTINEL_BASE,
    arguments,
    nameless_sentinel_serve,
    sentinel_serve,
)
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.app.adapters._text import NamelessKind
from openproject_ce_mcp.app.policies import filter_policy
from openproject_ce_mcp.app.policies.identity_fields import READ_IDENTITY_FIELDS
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY, TOOL_GROUPS
from openproject_ce_mcp.presentation import ContentBundle, _to_payload

ENTITIES = sorted(HIDE_FIELD_ENV_BY_ENTITY)
READ_TOOLS = sorted({name for names in tools.READ_TOOLS_BY_SCOPE.values() for name in names})

# tool -> why the generic call of the visible run gives no record to scan.
NO_RECORD: dict[str, str] = {
    "get_grid": "the fake grid names no project scope, so the read is refused before any record is built",
}
# (tool, class, field) -> why the value that stays is the same fact as a field of its own that is not hidden.
_TWO_FIELDS = "the same project name is a field of two entities; hiding one leaves the other"
COINCIDENCE: dict[tuple[str, str, str], str] = {
    ("list_work_package_relations", "QueriedRelationPerspective", "queried_work_package_id"): (
        "`from_id` of the relation is a field of its own that carries the same work package"
    ),
    ("get_project_work_package_context", "ProjectWorkPackageContext", "project_name"): _TWO_FIELDS,
    ("get_project_work_package_context", "VersionSummary", "defining_project"): _TWO_FIELDS,
}
# class -> why no entity owns its fields: the rows are the option lists of a context, governed by its `available_*`.
ROW_CLASSES_OF_THEIR_PARENT: dict[str, str] = {
    "OptionValue": "a row of an `available_*` list of the work package context; hiding a type's id is not hiding it",
}
# Tools whose run shows no record field with a tracked value: the scan checks nothing for them, so they are listed.
_STRING_IDS = "its ids are strings, which the fake gives no sentinel: the `url` copies are judged by the table scan"
_NO_RECORD = "the fake gives no record with a tracked value, so the scan checks nothing (a stated boundary)"
NO_TRACKED_VALUE: dict[str, str] = {
    "execute_query": _NO_RECORD,
    "get_instance_configuration": _NO_RECORD,
    "get_job_status": _NO_RECORD,
    "get_my_preferences": _NO_RECORD,
    "get_query_column": _STRING_IDS,
    "get_query_filter": _STRING_IDS,
    "get_query_filter_instance_schema": _STRING_IDS,
    "get_query_operator": _STRING_IDS,
    "get_query_sort_by": _STRING_IDS,
    "list_actions": _STRING_IDS,
    "list_container_attachments": _NO_RECORD,
    "list_work_package_available_projects": _NO_RECORD,
    "list_grids": _NO_RECORD,
    "list_project_memberships": _NO_RECORD,
    "list_project_phase_definitions": _NO_RECORD,
    "list_projects": _NO_RECORD,
    "list_query_filter_instance_schemas": _STRING_IDS,
    "list_work_package_meeting_agenda_items": _NO_RECORD,
    "list_work_package_reactions": _NO_RECORD,
}
MIN_TRACKED_PAIRS = 480
_SENTINEL_TEXT = re.compile(r"(LBL-|DSP-|-[0-9a-f]{8}$|^2031-)")


def _settings(hidden: dict[str, tuple[str, ...]] | None = None):
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    settings = _base_settings(read_projects=("*",), write_projects=(), **enabled)
    return dataclasses.replace(settings, hidden_fields=hidden or {})


async def _run(
    name: str, hidden: dict[str, tuple[str, ...]] | None, *, nameless: bool = False
) -> tuple[Any, str] | str:
    """The result object and the text a caller sees, or the refusal as a string."""
    function = tools_runtime._TOOL_FUNCTIONS[name]
    client = OpenProjectClient(
        _settings(hidden),
        transport=httpx.MockTransport(
            serving_projects(
                nameless_sentinel_serve if nameless else sentinel_serve,
                [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")],
            )
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {})})
    except Exception as error:  # noqa: BLE001 -- a hidden field can stop a read; the run has no output to scan
        return f"{type(error).__name__}: {error}"[:160]
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    elide_none = "select" in inspect.signature(function).parameters
    text = json.dumps(_to_payload(body, select=None, elide_none=elide_none), default=str)
    if elide_none:
        # `select` takes its own path through the serializer: ask for every field of every class of the result.
        found: dict[str, type] = {}
        _classes(body, found)
        every = frozenset(field.name for cls in found.values() for field in dataclasses.fields(cls))
        text += json.dumps(_to_payload(body, select=every, elide_none=False), default=str)
    return body, text


def _tracked(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= SENTINEL_BASE
    return isinstance(value, str) and bool(_SENTINEL_TEXT.search(value))


def _present(text: str, value: Any) -> bool:
    if isinstance(value, int):
        return re.search(rf"(?<!\d){value}(?!\d)", text) is not None
    return value in text


def _fields(node: Any) -> Iterator[tuple[str, str, Any]]:
    """(class name, field, value) of every tracked scalar of every dataclass below `node`."""
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if _tracked(value):
                yield type(node).__name__, field.name, value
            else:
                yield from _fields(value)
    elif isinstance(node, (list, tuple)):
        for entry in node:
            yield from _fields(entry)
    elif isinstance(node, dict):
        for entry in node.values():
            yield from _fields(entry)


def _hiding(cls: str, field: str) -> dict[str, tuple[str, ...]]:
    """The field hidden in every entity, and the owners the table names for it when it is a member of a wrapper."""
    hiding = dict.fromkeys(ENTITIES, (field,))
    for entity, owner_field in READ_IDENTITY_FIELDS.get(cls, {}).get(field, ()):
        hiding[entity] = (*hiding[entity], owner_field)
    return hiding


async def _scan(
    name: str, used: set[tuple[str, str, str]] | None = None, *, nameless: bool = False
) -> tuple[int, list[tuple[str, str, Any]], str | None]:
    """(tracked pairs, leaks, the refusal of the visible run)."""
    baseline = await _run(name, None, nameless=nameless)
    if isinstance(baseline, str):
        return 0, [], baseline
    body, _ = baseline
    pairs = sorted({(cls, field, value) for cls, field, value in _fields(body)}, key=repr)
    leaks: list[tuple[str, str, Any]] = []
    for cls, field, value in pairs:
        hidden = await _run(name, _hiding(cls, field), nameless=nameless)
        if isinstance(hidden, str) or not _present(hidden[1], value):
            continue
        key = (name, cls, field)
        if cls in ROW_CLASSES_OF_THEIR_PARENT or key in COINCIDENCE:
            if used is not None:
                used.add(key)
        else:
            leaks.append((cls, field, value))
    return len(pairs), leaks, None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", READ_TOOLS)
async def test_a_hidden_value_appears_nowhere_in_the_read_result(name: str) -> None:
    if name not in tools_runtime._TOOL_FUNCTIONS:
        pytest.skip("not registered")
    pairs, leaks, refusal = await _scan(name)
    if name in NO_RECORD:
        assert refusal is not None and pairs == 0, "a listed tool runs now: remove its row"
        pytest.skip(NO_RECORD[name])

    assert refusal is None, refusal
    assert leaks == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", READ_TOOLS)
async def test_a_hidden_value_appears_nowhere_in_the_read_result_of_nameless_records(name: str) -> None:
    """The same scan where the server names no record: the adapters build a label, which must not repeat an id."""
    if name not in tools_runtime._TOOL_FUNCTIONS:
        pytest.skip("not registered")
    pairs, leaks, refusal = await _scan(name, nameless=True)
    if name in NO_RECORD:
        pytest.skip(NO_RECORD[name])

    assert refusal is None, refusal
    assert leaks == []


@pytest.mark.asyncio
async def test_every_label_of_a_nameless_record_is_shown_by_some_tool() -> None:
    """The nameless scan proves nothing about a kind whose label no tool shows: a kind has to be reached.

    Stated boundary: a project label is shown, but the fake's project ids stay below `SENTINEL_BASE`, so the
    id of a project is judged by `test_nameless_labels.py`, not here."""
    shown: set[str] = set()
    for name in READ_TOOLS:
        if name in tools_runtime._TOOL_FUNCTIONS:
            baseline = await _run(name, None, nameless=True)
            if not isinstance(baseline, str):
                shown |= {kind for kind in typing.get_args(NamelessKind) if f'"Unnamed {kind}"' in baseline[1]}

    assert set(typing.get_args(NamelessKind)) - shown == set()


@pytest.mark.asyncio
async def test_no_exemption_is_stale() -> None:
    """A row that exempts nothing any more hides the next leak under its key; it has to go."""
    used: set[tuple[str, str, str]] = set()
    for name in READ_TOOLS:
        if name in tools_runtime._TOOL_FUNCTIONS and name not in NO_RECORD:
            await _scan(name, used)

    assert set(COINCIDENCE) - used == set()
    assert {cls for _, cls, _ in used} >= set(ROW_CLASSES_OF_THEIR_PARENT)


# Instrument B, the table scan. The owner tables name which field owns each member that sits outside its record;
# Scan A cannot judge them, because an echo of what the caller typed is no sentinel and the owner record is often not
# in the result at all (the costs of a work package, an occurrence list). Each row of the tables runs the tool that
# returns its class with a sentinel argument (a display id `DEMO-92` that resolves to another id, a 7-digit number),
# hides every owner alone, record or no record, and the member must be gone while it is there without any hiding.
DISPLAY_ID = "DEMO-92"
ARGUMENT_ID = 7_000_123
PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "ActionSummary": ("list_actions", {}),
    "CapabilitySummary": ("list_capabilities", {}),
    "ProjectAccessSummary": ("get_my_project_access", {"project": "demo"}),
    "ProjectConfiguration": ("get_project_configuration", {"project": "demo"}),
    "ProjectWorkPackageContext": ("get_project_work_package_context", {"project": "demo"}),
    "UserDetail": ("get_user", {}),
    "UserSummary": ("list_users", {}),
    "QueryColumnSummary": ("get_query_column", {"column_id": "subject"}),
    "QueryFilterInstanceSchemaSummary": ("get_query_filter_instance_schema", {"schema_id": "status"}),
    "QueryFilterSummary": ("get_query_filter", {"filter_id": "status"}),
    "QueryOperatorSummary": ("get_query_operator", {"operator_id": "="}),
    "QuerySortBySummary": ("get_query_sort_by", {"sort_by_id": "subject-asc"}),
    "AttachmentContentResult": ("get_attachment_content", {"attachment_id": ARGUMENT_ID}),
    "AttachmentSummary": ("get_attachment", {"attachment_id": ARGUMENT_ID}),
    "BatchWorkPackageReadItemResult": ("get_work_packages", {"work_package_ids": [DISPLAY_ID, "DEMO-93", DISPLAY_ID]}),
    "RecurringMeetingOccurrenceListResult": (
        "list_recurring_meeting_occurrences",
        {"recurring_meeting_id": ARGUMENT_ID},
    ),
    "RecurringMeetingOccurrenceSummary": ("list_recurring_meeting_occurrences", {"recurring_meeting_id": ARGUMENT_ID}),
    "WorkPackageCostsByTypeResult": ("get_work_package_costs_by_type", {"work_package_id": DISPLAY_ID}),
    "WorkPackageDetail": ("get_work_package", {"work_package_id": ARGUMENT_ID}),
    "ProjectDetail": ("get_project", {"project": "demo"}),
}
MIN_TABLE_COPIES = 10


def _resolving_server(request: httpx.Request) -> httpx.Response:
    """`DEMO-92` resolves to work package 532, `DEMO-93` to 533, as a server with display ids does."""
    path = re.sub(
        r"/work_packages/DEMO-(\d+)$", lambda match: f"/work_packages/{int(match.group(1)) + 440}", request.url.path
    )
    return sentinel_serve(httpx.Request(request.method, request.url.copy_with(path=path), headers=request.headers))


async def _run_probe(
    tool: str,
    arguments_: dict[str, Any],
    hidden: dict[str, tuple[str, ...]] | None,
    refusals: list[Exception] | None = None,
) -> tuple[Any, Any] | None:
    function = tools_runtime._TOOL_FUNCTIONS[tool]
    client = OpenProjectClient(
        _settings(hidden),
        transport=httpx.MockTransport(
            serving_projects(_resolving_server, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(tool, {}), **arguments_})
    except Exception as error:  # noqa: BLE001 -- a hidden owner can stop a read; the run has no output to scan
        if refusals is not None:
            refusals.append(error)
        return None
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    elide_none = "select" in inspect.signature(function).parameters
    return body, _to_payload(body, select=None, elide_none=elide_none)


def _instances(node: Any, cls: str) -> Iterator[Any]:
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        if type(node).__name__ == cls:
            yield node
        for child in vars(node).values():
            yield from _instances(child, cls)
    elif isinstance(node, (list, tuple)):
        for entry in node:
            yield from _instances(entry, cls)


def _member_rows() -> list[tuple[str, str, str, str]]:
    return [
        (cls, member, entity, field)
        for cls, members in sorted(READ_IDENTITY_FIELDS.items())
        for member, owners in sorted(members.items())
        for entity, field in owners
    ]


# (class, member) -> the other field that carries the same value: the member is judged by its key leaving, because
# the value stays in that field of its own.
SAME_FACT: dict[tuple[str, str], str] = {
    ("ProjectWorkPackageContext", "project_name"): "`available_versions[].defining_project` is a field of the version",
}


def _has_member(node: Any, member: str) -> bool:
    if isinstance(node, dict):
        return member in node or any(_has_member(child, member) for child in node.values())
    return isinstance(node, list) and any(_has_member(child, member) for child in node)


def _selects_by(tool: str, entity: str, field: str) -> bool:
    return any(
        row_tool == tool and row.always and (entity, field) in row.owners
        for (row_tool, _), row in filter_policy.FILTER_FIELDS.items()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("cls", "member", "entity", "field"), _member_rows())
async def test_a_member_leaves_with_each_of_its_owners(cls: str, member: str, entity: str, field: str) -> None:
    tool, arguments_ = PROBES[cls]
    plain = await _run_probe(tool, arguments_, None)
    assert plain is not None, "the probe call is refused"
    values = [getattr(item, member) for item in _instances(plain[0], cls) if getattr(item, member) is not None]
    assert values, f"{cls}.{member} has no value to hide under this probe"
    refusals: list[Exception] = []
    hidden = await _run_probe(tool, arguments_, {entity: (field,)}, refusals)
    if _selects_by(tool, entity, field):
        # The tool selects its rows by this owner and is refused while it is hidden: nothing is shown at all.
        assert hidden is None
        assert len(refusals) == 1, refusals
        assert "cannot be used to filter" in str(refusals[0])
        assert f"field '{field}' is hidden by {HIDE_FIELD_ENV_BY_ENTITY[entity]}" in str(refusals[0])
        return
    assert hidden is not None
    if all(isinstance(value, int) and value < SENTINEL_BASE for value in values) or (cls, member) in SAME_FACT:
        # A small number (the project ids stay 1 and 97 to 99 in the fake) is not searchable, and a value that stays in
        # a field of its own is no proof of a leak: the key must go.
        assert _has_member(plain[1], member), "the visible run does not show the member"
        assert not _has_member(hidden[1], member)
        return
    plain_text = json.dumps(plain[1], default=str)
    assert all(_present(plain_text, value) for value in values), "the visible run does not show the value"
    hidden_text = json.dumps(hidden[1], default=str)
    assert [value for value in values if _present(hidden_text, value)] == []


# (class, member) -> the owner fields, written down here and not read from the table, so a missing owner and an extra
# one both fail. An owner too many hides a value for a field that does not carry it.
INDEPENDENT_OWNERS: dict[tuple[str, str], set[tuple[str, str]]] = {
    ("ActionSummary", "url"): {("action", "id")},
    ("AttachmentContentResult", "attachment_id"): {("attachment", "id")},
    ("AttachmentSummary", "download_url"): {("attachment", "id")},
    ("BatchWorkPackageReadItemResult", "id"): {("work_package", "id"), ("work_package", "display_id")},
    ("CapabilitySummary", "url"): {("capability", "id")},
    ("ProjectAccessSummary", "current_user_id"): {("current_user", "id")},
    ("ProjectAccessSummary", "current_user_name"): {("current_user", "name")},
    ("ProjectAccessSummary", "project_id"): {("project", "id")},
    ("ProjectAccessSummary", "project_identifier"): {("project", "identifier")},
    ("ProjectAccessSummary", "project_name"): {("project", "name")},
    ("ProjectConfiguration", "project_id"): {("project", "id")},
    ("ProjectConfiguration", "project_name"): {("project", "name")},
    ("ProjectWorkPackageContext", "project_id"): {("project", "id")},
    ("ProjectWorkPackageContext", "project_identifier"): {("project", "identifier")},
    ("ProjectWorkPackageContext", "project_name"): {("project", "name")},
    ("QueryColumnSummary", "url"): {("query_column", "id")},
    ("QueryFilterInstanceSchemaSummary", "url"): {("query_filter_instance_schema", "id")},
    ("QueryFilterSummary", "url"): {("query_filter", "id")},
    ("QueryOperatorSummary", "url"): {("query_operator", "id")},
    ("QuerySortBySummary", "url"): {("query_sort_by", "id")},
    ("RecurringMeetingOccurrenceListResult", "recurring_meeting_id"): {
        ("recurring_meeting", "id"),
        ("meeting", "recurring_meeting_id"),
    },
    ("RecurringMeetingOccurrenceSummary", "meeting_id"): {("meeting", "id")},
    ("RecurringMeetingOccurrenceSummary", "start_time"): {
        ("recurring_meeting", "start_time"),
        ("meeting", "start_time"),
    },
    ("UserDetail", "avatar_url"): {("user", "id")},
    ("UserSummary", "avatar_url"): {("user", "id")},
    ("WorkPackageCostsByTypeResult", "work_package_id"): {("work_package", "id"), ("work_package", "display_id")},
}


def test_every_owner_is_the_field_whose_value_the_member_repeats() -> None:
    tabled = {
        (cls, member): set(owners)
        for cls, members in READ_IDENTITY_FIELDS.items()
        for member, owners in members.items()
    }
    assert tabled == INDEPENDENT_OWNERS


def _row_rules() -> list[tuple[str, str, str, str, str, bool]]:
    from openproject_ce_mcp.app.policies.identity_fields import PARENT_ROW_KEYS, ROW_KEYS

    rows = [
        (cls, member, key, entity, field, False)
        for (cls, member), keys in sorted(ROW_KEYS.items())
        for key, owners in sorted(keys.items())
        for entity, field in owners
    ]
    rows += [
        (cls, member, key, entity, field, True)
        for (cls, member), keys in sorted(PARENT_ROW_KEYS.items())
        for key, owners in sorted(keys.items())
        for entity, field in owners
    ]
    return rows


def _row_values(payload: Any, member: str, key: str, *, parent_only: bool, parent_id: Any) -> list[Any]:
    rows = payload.get(member) or []
    return [
        row.get(key)
        for row in rows
        if row.get(key) is not None and (not parent_only or str(row.get("href")).rsplit("/", 1)[-1] == str(parent_id))
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("cls", "member", "key", "entity", "field", "parent_only"), _row_rules())
async def test_a_row_key_leaves_with_each_of_its_owners(
    cls: str, member: str, key: str, entity: str, field: str, parent_only: bool
) -> None:
    tool, arguments_ = PROBES[cls]
    plain = await _run_probe(tool, arguments_, None)
    assert plain is not None
    parent_id = next(iter(_instances(plain[0], cls))).parent_id
    shown = _row_values(plain[1], member, key, parent_only=parent_only, parent_id=parent_id)
    assert shown, f"no row of {cls}.{member} carries {key} to hide"

    hidden = await _run_probe(tool, arguments_, {entity: (field,)})
    assert hidden is not None
    left = _row_values(hidden[1], member, key, parent_only=False, parent_id=None)
    assert [value for value in shown if value in left] == []


@pytest.mark.asyncio
async def test_every_table_row_has_a_probe_and_the_tables_show_enough_copies() -> None:
    from openproject_ce_mcp.app.policies.identity_fields import ROW_KEYS

    needed = set(READ_IDENTITY_FIELDS) | {cls for cls, _ in ROW_KEYS}
    assert needed - set(PROBES) == set(), "a table class without a probe"
    copies = 0
    for cls in needed:
        tool, arguments_ = PROBES[cls]
        plain = await _run_probe(tool, arguments_, None)
        assert plain is not None
        copies += sum(
            1
            for item in _instances(plain[0], cls)
            for member in READ_IDENTITY_FIELDS.get(cls, {})
            if getattr(item, member) is not None
        )
    assert copies >= MIN_TABLE_COPIES


# Static completeness. A class a read tool returns is an entity record (its fields are judged by that entity's own
# settings), a wrapper whose members are tabled, or a class whose other members are listed here with the reason no
# owner field exists. A member added later fails until it is classified.
_PAGE_MEMBERS = frozenset({"results", "count", "truncated", "next_offset", "offset", "limit", "total"})
NOT_AN_IDENTITY_READ: dict[str, dict[str, str]] = {
    "AttachmentContentResult": {
        "file_name": "stamped by hand in `AttachmentService._content_metadata` (the title is its alias)",
        "size_bytes": "nulled by hand in `AttachmentService._content_metadata` with `file_size_bytes`",
        "outcome": "what the server did with the content, no field of the attachment",
        "content_type": "no value of a field the settings can hide here",
        "truncated": "a flag of the content",
        "reason": "text of the decision, names no field value",
    },
    "AttachmentListResult": {
        "total_size_bytes": "nulled by hand with `file_size_bytes` (`_sum_attachment_sizes`)",
        "images": "a list of `AttachmentContentResult`; the stamp descends into it",
    },
    "BatchWorkPackageReadItemResult": {
        "index": "the position in the caller's own list; it is how an item is told apart when `id` is hidden",
        "success": "a flag",
        "work_package": "a record the stamp descends into",
        "error": "the server error text of a failed item: judged with the other server error texts",
    },
    "BatchWorkPackageReadResult": {
        "action": "constant",
        "succeeded": "a count",
        "failed": "a count",
        "message": "a count in words",
    },
    "QueriedRelationPerspective": {
        "queried_work_package_id": "a field of its own of the relation answer; `from_id` and `to_id` carry the same id",
        "direction": "no id",
        "effective_type": "no id",
        "predecessor_id": "not built by `RelationService._stamp` while `from_id` or `to_id` is hidden",
        "successor_id": "not built by `RelationService._stamp` while `from_id` or `to_id` is hidden",
    },
    "RecurringMeetingOccurrenceListResult": {"filter": "the caller's own filter word"},
    "RecurringMeetingOccurrenceSummary": {"state": "stamped by `RecurringMeetingService._stamp_occurrence` by name"},
    "TimeEntryListResult": {
        "total_hours": "an aggregate of the list, not a copy of one record's field",
        "total_hours_truncated": "a flag",
    },
    "WorkPackageListResult": {
        "groups": "judged by `work_package_query_policy` against the hidden fields",
        "total_sums": "judged by `work_package_query_policy.sums_without_hidden_fields`",
        "exact_match": "a work package record the stamp descends into",
    },
}


# class -> the entity its records are stamped with, where the name does not say it.
ENTITY_OF_CLASS: dict[str, str] = {"RelationCandidateSummary": "work_package"}


def _entity_of(name: str) -> str | None:
    if name in ENTITY_OF_CLASS:
        return ENTITY_OF_CLASS[name]
    entity = re.sub(r"(?<!^)(?=[A-Z])", "_", re.sub(r"(Summary|Detail|Record)$", "", name)).lower()
    return entity if entity in HIDE_FIELD_ENV_BY_ENTITY else None


def _classes(node: Any, found: dict[str, type]) -> None:
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        found.setdefault(type(node).__name__, type(node))
        for child in vars(node).values():
            _classes(child, found)
    elif isinstance(node, (list, tuple)):
        for entry in node:
            _classes(entry, found)


@pytest.mark.asyncio
async def test_every_member_of_a_class_without_an_entity_is_classified() -> None:
    found: dict[str, type] = {}
    for name in READ_TOOLS:
        if name in tools_runtime._TOOL_FUNCTIONS and name not in NO_RECORD:
            run = await _run(name, None)
            if not isinstance(run, str):
                _classes(run[0], found)
    unclassified: list[str] = []
    for cls_name, cls in sorted(found.items()):
        if _entity_of(cls_name) is not None or cls_name in ROW_CLASSES_OF_THEIR_PARENT:
            continue
        members = {field.name for field in dataclasses.fields(cls)} - _PAGE_MEMBERS
        tabled = set(READ_IDENTITY_FIELDS.get(cls_name, {})) | set(NOT_AN_IDENTITY_READ.get(cls_name, {}))
        unclassified += [f"{cls_name}.{member}" for member in sorted(members - tabled)]
    assert unclassified == []
    assert all(NOT_AN_IDENTITY_READ[cls].values() for cls in NOT_AN_IDENTITY_READ)
    assert set(NOT_AN_IDENTITY_READ) <= set(found), "a row for a class no read tool returns"


def test_no_class_of_the_tables_is_frozen() -> None:
    """A frozen class cannot take the `_hidden_keys` stamp: it would be skipped, not hidden."""
    from openproject_ce_mcp import models
    from openproject_ce_mcp.app.policies.identity_fields import ROW_KEYS

    for cls_name in set(READ_IDENTITY_FIELDS) | {cls for cls, _ in ROW_KEYS}:
        assert not getattr(models, cls_name).__dataclass_params__.frozen, cls_name


def _entity_fields(entity: str) -> set[str]:
    from openproject_ce_mcp import models

    camel = "".join(part.capitalize() for part in entity.split("_"))
    names: set[str] = set()
    for suffix in ("Summary", "Detail", ""):
        model = getattr(models, camel + suffix, None)
        if model is not None:
            names |= {field.name for field in dataclasses.fields(model)}
    return names


def test_every_owner_is_a_real_field_of_a_hide_entity() -> None:
    from openproject_ce_mcp import models
    from openproject_ce_mcp.app.policies.identity_fields import PARENT_ROW_KEYS, ROW_KEYS

    owners = [
        owner
        for table in (*READ_IDENTITY_FIELDS.values(), *ROW_KEYS.values(), *PARENT_ROW_KEYS.values())
        for pairs in table.values()
        for owner in pairs
    ]
    assert owners
    for entity, field in owners:
        assert entity in HIDE_FIELD_ENV_BY_ENTITY, entity
        assert field in _entity_fields(entity), f"{entity} has no field {field}"
    for cls_name, members in READ_IDENTITY_FIELDS.items():
        assert set(members) <= {f.name for f in dataclasses.fields(getattr(models, cls_name))}, cls_name
    for cls_name, member in ROW_KEYS:
        assert member in {f.name for f in dataclasses.fields(getattr(models, cls_name))}, (cls_name, member)


def test_every_service_that_returns_a_tabled_class_stamps_it() -> None:
    """A public async method whose return annotation names a class of the tables puts its service under
    `stamped_results`; otherwise the row of that class is dead."""
    import ast
    from pathlib import Path

    import openproject_ce_mcp
    from openproject_ce_mcp.app.policies.identity_fields import ROW_KEYS

    tabled = set(READ_IDENTITY_FIELDS) | {cls for cls, _ in ROW_KEYS}
    undecorated: list[str] = []
    for path in sorted((Path(openproject_ce_mcp.__file__).parent / "app" / "services").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            decorated = any(isinstance(item, ast.Name) and item.id == "stamped_results" for item in node.decorator_list)
            for method in node.body:
                if (
                    not isinstance(method, ast.AsyncFunctionDef)
                    or method.name.startswith("_")
                    or method.returns is None
                ):
                    continue
                if set(re.findall(r"[A-Za-z_]+", ast.unparse(method.returns))) & tabled and not decorated:
                    undecorated.append(f"{path.name}:{node.name}.{method.name}")
    assert undecorated == []


# (class, member, key) -> why a key of a dict row has no owner field.
ROW_KEYS_WITHOUT_OWNER: dict[tuple[str, str, str], str] = {
    ("ProjectDetail", "ancestors", "display_id"): "a project has no display id: the key is always null",
}


@pytest.mark.asyncio
async def test_every_key_of_a_dict_row_has_an_owner_or_says_why_not() -> None:
    from openproject_ce_mcp.app.policies.identity_fields import ROW_KEYS

    seen: set[tuple[str, str, str]] = set()
    for (cls, member), keys in ROW_KEYS.items():
        tool, arguments_ = PROBES[cls]
        plain = await _run_probe(tool, arguments_, None)
        assert plain is not None
        rows = getattr(next(iter(_instances(plain[0], cls))), member)
        assert rows, f"the probe shows no row of {cls}.{member}"
        seen |= {(cls, member, key) for row in rows for key in row} - {(cls, member, key) for key in keys}
    assert seen == set(ROW_KEYS_WITHOUT_OWNER)


@pytest.mark.asyncio
async def test_the_scan_has_values_to_hide_and_lists_the_tools_without_any() -> None:
    """A fake that stops giving a record a tracked value would turn its tool into a pass with nothing checked."""
    total = 0
    empty: set[str] = set()
    for name in READ_TOOLS:
        if name in tools_runtime._TOOL_FUNCTIONS and name not in NO_RECORD:
            pairs, _, _ = await _scan(name)
            total += pairs
            if pairs == 0:
                empty.add(name)

    assert empty == set(NO_TRACKED_VALUE)
    assert total >= MIN_TRACKED_PAIRS


_WORK_PACKAGE_REF = {("work_package", "id"), ("work_package", "display_id")}
INDEPENDENT_ROW_OWNERS: dict[tuple[str, str, str], set[tuple[str, str]]] = {
    ("WorkPackageDetail", "children", "href"): _WORK_PACKAGE_REF,
    ("WorkPackageDetail", "children", "title"): {("work_package", "subject")},
    ("WorkPackageDetail", "children", "display_id"): {("work_package", "display_id")},
    ("WorkPackageDetail", "ancestors", "href"): _WORK_PACKAGE_REF,
    ("WorkPackageDetail", "ancestors", "title"): {("work_package", "subject")},
    ("WorkPackageDetail", "ancestors", "display_id"): {("work_package", "display_id")},
    ("ProjectDetail", "ancestors", "href"): {("project", "id")},
    ("ProjectDetail", "ancestors", "title"): {("project", "name")},
}
INDEPENDENT_PARENT_ROW_OWNERS: dict[tuple[str, str, str], set[tuple[str, str]]] = {
    ("WorkPackageDetail", "ancestors", "href"): {("work_package", "parent_id")},
    ("WorkPackageDetail", "ancestors", "display_id"): {("work_package", "parent_display_id")},
    ("ProjectDetail", "ancestors", "href"): {("project", "parent_id")},
    ("ProjectDetail", "ancestors", "title"): {("project", "parent_name")},
}


def test_every_row_owner_is_the_field_whose_value_the_key_repeats() -> None:
    from openproject_ce_mcp.app.policies.identity_fields import PARENT_ROW_KEYS, ROW_KEYS

    def flat(table: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str, str], set[tuple[str, str]]]:
        return {
            (cls, member, key): set(owners) for (cls, member), keys in table.items() for key, owners in keys.items()
        }

    assert flat(ROW_KEYS) == INDEPENDENT_ROW_OWNERS
    assert flat(PARENT_ROW_KEYS) == INDEPENDENT_PARENT_ROW_OWNERS
