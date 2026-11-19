"""A value of a field the settings hide appears nowhere in a write result, not only in `payload` and `result`.

The record a write result carries (`result`) is stamped by the hide settings, but the same value comes back in
other places: the identity fields at the top of the result (`project`, `meeting_id`, `grid_id` ...), the work package
`target` and `related_target`, the payload copies of an id, and messages. Reading the code finds some of them; this
scan finds all of them for every write tool of the contract cases.

For each tool and each scalar field of the record in its `result` (taken from the confirmed run, else from the
preview), the field is hidden alone in every entity, the tool runs again (preview and confirmed), and the value must
not occur outside `result` any more, neither as a leaf nor inside a message text. A value that is the same fact as a
field that is not hidden (the title of an attachment is its file name) sits in `COINCIDENCE` with that reason. The
visible baseline (the same value outside `result` in the run without any hide setting) is counted, so a fake that
stops echoing a value cannot turn the scan into a pass without a copy to hide.
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib
import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import materialize_case

from openproject_ce_mcp import tools  # noqa: F401 -- importing the tools registers them in _TOOL_FUNCTIONS
from openproject_ce_mcp.app.policies.identity_fields import IDENTITY_FIELDS, PAYLOAD_COPIES
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS

ENTITIES = sorted(HIDE_FIELD_ENV_BY_ENTITY)
ERRORS: list[tuple[str, bool, str]] = []
MIN_BASELINE_COPIES = 120
# (tool, confirm) -> the contract case fake does not serve that state.
BASELINE_FAILS: set[tuple[str, bool]] = set()
# Tools with no value to look for: the result carries no record and no member that repeats a field.
NO_COPIES: dict[str, str] = {
    "update_my_preferences": "the preview carries only what the caller passed; the confirmed result is the record",
}

# (tool, leaf path, field) -> why the value is the same fact as a field that stays visible.
_OWN_PROJECT = "the work package's own project, owned by the work package settings, not the time entry's"
_TEXT_WITH_NUMBER = "the fake's subject text contains the number as a word of its own"
_OWN_ID = "`id` is a field of its own: hiding the display id hides the display reference only"
COINCIDENCE: dict[tuple[str, str, str], str] = {
    ("create_time_entry", ".target.project", "project"): _OWN_PROJECT,
    ("create_time_entry_until", ".target.project", "project"): _OWN_PROJECT,
    ("delete_relation", ".payload.from_id", "work_package_id"): "the other end of the relation, a field of its own",
    ("delete_work_package", ".payload.id", "work_package_id"): _OWN_ID,
    ("delete_work_package", ".target.id", "work_package_id"): _OWN_ID,
    ("set_work_package_watcher", ".target.id", "work_package_id"): _OWN_ID,
    ("update_work_package", ".target.id", "work_package_id"): _OWN_ID,
    ("add_work_package_comment", ".target.id", "work_package_id"): _OWN_ID,
    ("bulk_update_work_packages", ".target.id", "work_package_id"): _OWN_ID,
    ("bulk_update_work_packages", ".payload.subject", "work_package_id"): _TEXT_WITH_NUMBER,
    ("bulk_update_work_packages", ".target.subject", "work_package_id"): _TEXT_WITH_NUMBER,
    (
        "create_work_package_attachment",
        ".message",
        "status",
    ): "the message says what the tool did, not the stored status",
    ("create_container_attachment", ".message", "status"): "the message says what the tool did, not the stored status",
    ("update_storage", ".message", "provider_type"): "static advice about Nextcloud storages, not the record's value",
}


def _is_id_name(name: str) -> bool:
    return name == "id" or name.endswith(("_id", "Id", ".id", "_ids"))


def _tracked(field: str, value: Any) -> bool:
    if isinstance(value, str) and value.isdigit() and _is_id_name(field):
        value = int(value)
    if value is None or isinstance(value, (bool, dict, list)):
        return False
    if isinstance(value, int):
        return abs(value) >= 10 or (value > 0 and _is_id_name(field))
    return isinstance(value, str) and len(value) >= 3


def _leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item, f"{path}[]")
    else:
        yield path, value


def _outside_result(output: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in output.items() if key != "result"}


def _holds(path: str, leaf: Any, value: Any) -> bool:
    if isinstance(value, int) and not isinstance(value, bool) and isinstance(leaf, str):
        return (abs(value) >= 10 or _is_id_name(path.rsplit(".", 1)[-1])) and bool(
            re.search(rf"(?<![\d]){abs(value)}(?![\d])", leaf)
        )
    if isinstance(value, int) and abs(value) < 10 and not _is_id_name(path.rsplit(".", 1)[-1]):
        return False
    if leaf == value:
        return True
    return isinstance(value, str) and len(value) >= 4 and isinstance(leaf, str) and value in leaf


def _entity_of(record: Any) -> str | None:
    name = re.sub(r"(Summary|Detail|Record)$", "", type(record).__name__)
    entity = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return entity if entity in HIDE_FIELD_ENV_BY_ENTITY else None


async def _run(
    tool: str, hidden: dict[str, tuple[str, ...]] | None, confirm: bool, tmp_path: pathlib.Path
) -> tuple[Any, Any] | None:
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)
    settings = materialized.settings
    if hidden:
        settings = dataclasses.replace(settings, hidden_fields=hidden)

    async def handler(request: httpx.Request) -> httpx.Response:
        result = case.handler(request)
        return await result if inspect.isawaitable(result) else result

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = await _TOOL_FUNCTIONS[tool](FakeContext(client), **materialized.kwargs, confirm=confirm)
        return result, _to_payload(result, elide_none=True)
    except Exception as exc:  # noqa: BLE001 -- a hidden field can stop a write; the run has no output to scan
        if hidden is None:
            ERRORS.append((tool, confirm, f"{type(exc).__name__}: {exc}"[:120]))
        return None
    finally:
        await client.aclose()


def _at(payload: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(payload, dict) or key not in payload:
            return None
        payload = payload[key]
    return payload


def _normal(value: Any) -> Any:
    return int(value) if isinstance(value, str) and value.isdigit() else value


def _targets(raw: Any, plain: dict[str, Any]) -> list[tuple[str, Any, dict[str, tuple[str, ...]], str]]:
    """What to hide and what to look for: (label, value, hide setting, kind). The record fields are hidden in the
    entity of the record; the members and payload copies are hidden through the owner field the table names, so a
    wrong owner leaves the value visible."""
    found: list[tuple[str, Any, dict[str, tuple[str, ...]], str]] = []
    record = getattr(raw, "result", None)
    entity = _entity_of(record) if record is not None else None
    if entity is not None and isinstance(plain.get("result"), dict):
        for field, value in plain["result"].items():
            if _tracked(field, value):
                found.append((field, value, {entity: (field,)}, "record"))
    for member, owners in IDENTITY_FIELDS.get(type(raw).__name__, {}).items():
        value = _normal(plain.get(member))
        if member in ("target", "related_target", "parent_target") or not _tracked(member, value):
            continue
        for owner_entity, owner_field in owners:
            found.append((member, value, {owner_entity: (owner_field,)}, "value"))
    for key, owners in PAYLOAD_COPIES.get(type(raw).__name__, {}).items():
        if _at(plain.get("payload"), key.replace("_links.", "_links.")) is None:
            continue
        for owner_entity, owner_field in owners:
            found.append((f"payload.{key}", key, {owner_entity: (owner_field,)}, "payload"))
    return found


def _units(raw: Any, plain: dict[str, Any]) -> list[tuple[Any, dict[str, Any], tuple[Any, ...]]]:
    """The write results inside one tool result: the result itself, or each item of a batch."""
    items = getattr(raw, "items", None)
    if isinstance(items, list) and isinstance(plain.get("items"), list):
        return [
            (item.result, plain["items"][index]["result"], ("items", index, "result"))
            for index, item in enumerate(items)
            if getattr(item, "result", None) is not None and isinstance(plain["items"][index].get("result"), dict)
        ]
    return [(raw, plain, ())]


def _dig(output: Any, route: tuple[Any, ...]) -> Any:
    for step in route:
        output = output[step]
    return output


async def _scan(
    tool: str, tmp_path: pathlib.Path, used: set[tuple[str, str, str]] | None = None
) -> tuple[int, list[tuple[bool, str, Any, str]]]:
    copies = 0
    leaks: list[tuple[bool, str, Any, str]] = []
    for confirm in (False, True):
        plain_run = await _run(tool, None, confirm, tmp_path)
        if plain_run is None or not isinstance(plain_run[1], dict):
            continue
        for unit_raw, unit_plain, route in _units(*plain_run):
            for label, value, hide, kind in _targets(unit_raw, unit_plain):
                hidden_run = await _run(tool, hide, confirm, tmp_path)
                unit_hidden = None
                if hidden_run is not None and isinstance(hidden_run[1], dict):
                    try:
                        unit_hidden = _dig(hidden_run[1], route)
                    except (KeyError, IndexError):
                        unit_hidden = {}
                if kind == "payload":
                    copies += 1
                    if (
                        isinstance(unit_hidden, dict)
                        and _at(unit_hidden.get("payload"), value) is not None
                        and (tool, label, label) not in COINCIDENCE
                    ):
                        leaks.append((confirm, label, value, "payload key stays"))
                    continue
                copies += sum(1 for path, leaf in _leaves(_outside_result(unit_plain)) if _holds(path, leaf, value))
                if not isinstance(unit_hidden, dict):
                    continue
                shown_record = unit_hidden.get("result")
                if kind == "record" and isinstance(shown_record, dict) and label in shown_record:
                    leaks.append((confirm, label, value, "result keeps the hidden key"))
                for path, leaf in _leaves(_outside_result(unit_hidden)):
                    if not _holds(path, leaf, value):
                        continue
                    if (tool, path, label) in COINCIDENCE:
                        if used is not None:
                            used.add((tool, path, label))
                    else:
                        leaks.append((confirm, label, value, path))
    return copies, leaks


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(WRITE_TOOL_CASES))
async def test_a_hidden_value_appears_nowhere_in_the_result(tool: str, tmp_path: pathlib.Path) -> None:
    _, leaks = await _scan(tool, tmp_path)

    assert leaks == []


@pytest.mark.asyncio
async def test_every_tool_has_a_visible_copy_to_hide_or_says_why_not(tmp_path: pathlib.Path) -> None:
    empty = []
    total = 0
    for tool in sorted(WRITE_TOOL_CASES):
        copies, _ = await _scan(tool, tmp_path)
        total += copies
        if copies == 0:
            empty.append(tool)

    assert set(empty) == set(NO_COPIES), "a tool lost its copies, or a listed tool has some now"
    assert total >= MIN_BASELINE_COPIES


@pytest.mark.asyncio
async def test_no_run_without_a_hide_setting_fails(tmp_path: pathlib.Path) -> None:
    for tool in sorted(WRITE_TOOL_CASES):
        await _scan(tool, tmp_path)

    assert [error for error in ERRORS if (error[0], error[1]) not in BASELINE_FAILS] == []


# (result class, member) -> the owner fields, written down here and not read from the table, for the members the
# record of the result cannot confirm (a result without a record, or a member the record does not carry).
INDEPENDENT_OWNERS: dict[tuple[str, str], set[tuple[str, str]]] = {
    ("NotificationMarkResult", "notification_id"): {("notification", "id")},
    ("FavoriteWriteResult", "project_id"): {("project", "id")},
    ("FavoriteWriteResult", "project"): {("project", "name")},
    ("ProjectCopyResult", "source_project_id"): {("project", "id")},
    ("ProjectCopyResult", "source_project"): {("project", "name")},
    ("ProjectCopyResult", "job_status_id"): {("job_status", "id")},
    ("ContainerAttachmentWriteResult", "container_type"): {("attachment", "container_type")},
    ("QueryStarResult", "query_id"): {("view", "id")},
    ("RecurringMeetingOccurrenceWriteResult", "recurring_meeting_id"): {
        ("recurring_meeting", "id"),
        ("meeting", "recurring_meeting_id"),
    },
    ("RecurringMeetingOccurrenceWriteResult", "start_time"): {
        ("recurring_meeting", "start_time"),
        ("meeting", "start_time"),
    },
    ("ProjectWriteResult", "project"): {("project", "name")},
    ("EmojiReactionWriteResult", "activity_id"): {("activity", "id")},
    ("ActivityWriteResult", "work_package_id"): {("work_package", "id"), ("work_package", "display_id")},
    ("FileLinkWriteResult", "work_package_id"): {("work_package", "id"), ("work_package", "display_id")},
    ("WatcherWriteResult", "work_package_id"): {("work_package", "id"), ("work_package", "display_id")},
    ("EmojiReactionWriteResult", "reaction"): {("emoji_reaction", "reaction")},
}


@pytest.mark.asyncio
async def test_every_owner_is_the_field_whose_value_the_member_repeats(tmp_path: pathlib.Path) -> None:
    unconfirmed: set[tuple[str, str]] = set()
    verified: set[tuple[str, str]] = set()
    wrong: list[tuple[str, str, Any]] = []
    for tool in sorted(WRITE_TOOL_CASES):
        for confirm in (False, True):
            run = await _run(tool, None, confirm, tmp_path)
            if run is None or not isinstance(run[1], dict):
                continue
            for raw, plain, _ in _units(*run):
                record = getattr(raw, "result", None)
                entity = _entity_of(record) if record is not None else None
                for member, owners in IDENTITY_FIELDS.get(type(raw).__name__, {}).items():
                    value = _normal(plain.get(member))
                    if member in ("target", "related_target", "parent_target") or value is None:
                        continue
                    own = [field for owner_entity, field in owners if owner_entity == entity]
                    if not own or (type(raw).__name__, member) in INDEPENDENT_OWNERS:
                        unconfirmed.add((type(raw).__name__, member))
                    elif not any(_normal(getattr(record, field, None)) == value for field in own):
                        wrong.append((tool, member, value))
                    else:
                        verified.add((type(raw).__name__, member))
    assert wrong == []
    for key in sorted(unconfirmed - verified):
        expected = INDEPENDENT_OWNERS.get(key)
        assert expected is not None, f"{key}: no record confirms the owner and none is written down"
        assert set(IDENTITY_FIELDS[key[0]][key[1]]) == expected, key


@pytest.mark.asyncio
async def test_no_coincidence_row_is_stale(tmp_path: pathlib.Path) -> None:
    """A row that exempts nothing any more hides the next leak under its path; it has to go."""
    used: set[tuple[str, str, str]] = set()
    for tool in sorted(WRITE_TOOL_CASES):
        await _scan(tool, tmp_path, used)

    assert set(COINCIDENCE) - used == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("tool", ["bulk_create_work_packages", "bulk_update_work_packages"])
async def test_select_over_a_batch_keeps_the_hidden_members_out(
    tool: str, confirm: bool, tmp_path: pathlib.Path
) -> None:
    """`select` takes its own path through the serializer: a stamped member stays out even when it is asked for,
    in the preview and in the confirmed result."""
    plain = await _run(tool, None, confirm, tmp_path)
    assert plain is not None
    select = frozenset({"project", "work_package_id", "state"})
    shown = _to_payload(plain[0], select=select, elide_none=False)
    state = "confirmed" if confirm else "preview"
    assert shown["items"] and all(item["success"] for item in shown["items"])
    results = [item["result"] for item in shown["items"] if item.get("result")]
    assert results and all(result["state"] == state and "project" in result for result in results), "no baseline"

    hidden = await _run(tool, {"work_package": ("project",)}, confirm, tmp_path)
    assert hidden is not None
    hidden_shown = _to_payload(hidden[0], select=select, elide_none=False)
    assert hidden_shown["items"] and all(item["success"] for item in hidden_shown["items"])
    hidden_results = [item["result"] for item in hidden_shown["items"] if item.get("result")]
    assert hidden_results and all(result["state"] == state for result in hidden_results)
    assert all("project" not in result for result in hidden_results)
