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
stops echoing a value cannot turn the scan into a pass without a copy to hide; the floor is per (tool, state).

Stated boundary: ids below 10 are tracked at id-named paths and in hrefs, not in free text; `_tracked` follows no
booleans, dicts or lists and no string shorter than 3 characters; results are serialized without `select` (the
`select` path is tested for one field on two tools); a confirmed bulk item is lean, so only `display_id` and `status`
are hide-tested in that state; a record class whose name maps to no hide entity yields no record target; a field whose
hide setting refuses the tool is a named skip, not a pass (`SKIPPED_RUNS`); a fake that never echoes a value gives no
probe (`NO_COPIES`). A record built by a model constructor, or a stamp lost in a helper, is outside this scan and
covered by the payload scan and the delete matrix.
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
# (tool, field, confirm) of every hidden run that gave nothing to compare: the hide refused the tool, or the hidden
# run lacks the unit the plain run had. A skip is a blind spot, so each one is listed in `SKIPPED_RUNS`.
SKIPS: dict[tuple[str, str, bool], str] = {}
# (tool, field, confirm) -> the hide setting of that skipped run.
SKIPPED_HIDES: dict[tuple[str, str, bool], dict[str, tuple[str, ...]]] = {}
LACKS_UNIT = "the hidden run lacks the unit the plain run had"
# The refusal a tool raises when the hide setting hides a field the call needs.
REFUSAL = re.compile(
    r"ToolInputError: \[VALIDATION_FAILED\] OpenProject field '(?P<field>[^']+)' is hidden by "
    r"OPENPROJECT_HIDE_[A-Z_]+ and cannot be written\."
)
# (tool, confirm, hide) -> the failure of a hidden run, for the kind of a skip
HIDDEN_FAILURES: dict[tuple[str, bool, str], str] = {}
MIN_BASELINE_COPIES = 120
# (tool, confirm) -> the contract case fake does not serve that state.
BASELINE_FAILS: set[tuple[str, bool]] = set()
# (tool, confirm) -> why that state has no value to look for. A tool may have copies in one state and none in the other,
# so the floor is per state. The reasons are structural: these create previews have no record and no id yet (their payload
# is the caller's own input), and the preferences are one record without members that repeat a field.
_CREATE_PREVIEW = "the preview has no record and no id yet, and its payload holds only the caller's own input"
NO_COPIES: dict[tuple[str, bool], str] = {
    ("create_board", False): _CREATE_PREVIEW,
    ("create_group", False): _CREATE_PREVIEW,
    ("create_project", False): _CREATE_PREVIEW,
    ("create_storage", False): _CREATE_PREVIEW,
    ("create_user", False): _CREATE_PREVIEW,
    ("create_user_non_working_time", False): _CREATE_PREVIEW,
    ("create_user_working_hours", False): _CREATE_PREVIEW,
    ("create_work_package_reminder", False): _CREATE_PREVIEW,
    ("update_my_preferences", False): "the preferences are one record: the preview carries only what the caller passed",
    ("update_my_preferences", True): "the result is the record itself: no member repeats a field outside it",
}

# (tool, confirm) -> the fields whose hidden run gave nothing to compare. Every row is a refusal by the hide setting: the
# hidden field is an input of the call, or the write policy needs it, so the tool stops before any request. That is a
# blind spot of the scan for that field in that state, not a leak; the test requires every skip to be that refusal for
# the field that was hidden, and a new skip or one that goes away fails the table. A skip of the other kind (the hidden
# run answers but lacks the unit the plain run had, `LACKS_UNIT`) fails the test until it has a kind of its own.
SKIPPED_RUNS: dict[tuple[str, bool], tuple[str, ...]] = {
    ("add_work_package_comment", True): ("comment",),
    ("copy_project", False): ("source_project",),
    ("copy_project", True): ("source_project",),
    ("create_board", True): ("name", "project"),
    ("create_container_attachment", False): ("payload.fileName",),
    ("create_container_attachment", True): ("file_name", "title"),
    ("create_grid", False): ("scope",),
    ("create_grid", True): ("scope",),
    ("create_group", True): ("name",),
    ("create_meeting", False): ("project",),
    ("create_meeting", True): ("project", "title"),
    ("create_meeting_agenda_item", True): ("title",),
    ("create_meeting_outcome", True): ("kind",),
    ("create_meeting_section", True): ("title",),
    ("create_membership", False): ("project",),
    ("create_membership", True): ("principal_name", "project", "project_name"),
    ("create_news", True): ("title",),
    ("create_project", True): ("identifier", "name", "project"),
    ("create_recurring_meeting", False): ("payload._links.project", "project"),
    ("create_recurring_meeting", True): ("frequency", "project", "start_time", "title"),
    ("create_storage", True): ("host", "name", "provider_type"),
    ("create_subtask", True): ("subject", "type"),
    ("create_time_entry", True): ("activity", "hours", "spent_on"),
    ("create_time_entry_until", True): ("activity", "hours", "spent_on"),
    ("create_user", True): ("login",),
    ("create_user_non_working_time", True): ("end_date", "start_date"),
    ("create_user_working_hours", True): ("valid_from",),
    ("create_version", False): ("project",),
    ("create_version", True): ("defining_project", "name", "project"),
    ("create_work_package", True): ("subject", "type"),
    ("create_work_package_attachment", False): ("payload.description", "payload.fileName"),
    ("create_work_package_attachment", True): ("file_name", "title"),
    ("create_work_package_relation", True): ("type",),
    ("create_work_package_reminder", True): ("remind_at",),
    ("create_work_package_wiki_link", True): ("identifier", "provider"),
    ("update_board", True): ("name",),
    ("update_document", True): ("title",),
    ("update_group", True): ("name",),
    ("update_meeting", True): ("title",),
    ("update_meeting_agenda_item", True): ("title",),
    ("update_meeting_outcome", True): ("kind",),
    ("update_meeting_section", True): ("title",),
    ("update_my_preferences", True): ("time_zone",),
    ("update_news", True): ("title",),
    ("update_project", False): ("project",),
    ("update_project", True): ("name", "project"),
    ("update_recurring_meeting", True): ("title",),
    ("update_relation", True): ("description",),
    ("update_reminder", True): ("note",),
    ("update_storage", False): ("name",),
    ("update_storage", True): ("name",),
    ("update_time_entry", True): ("comment",),
    ("update_time_entry_until", True): ("hours",),
    ("update_user", True): ("email",),
    ("update_user_non_working_time", True): ("end_date",),
    ("update_version", True): ("name",),
    ("update_work_package", True): ("subject",),
    ("update_work_package_comment", True): ("comment",),
}

# (tool, leaf path, field) -> why the value is the same fact as a field that stays visible.
_OWN_PROJECT = "the work package's own project, owned by the work package settings, not the time entry's"
_TEXT_WITH_NUMBER = "the fake's subject text contains the number as a word of its own"
_OWN_ID = "`id` is a field of its own: hiding the display id hides the display reference only"
_MESSAGE = "the message says what the tool did, not the stored status"
# A row exempts one path for one field and one set of leaf values: another text at that path is a leak again.
COINCIDENCE: dict[tuple[str, str, str], tuple[str, frozenset[Any]]] = {
    ("create_time_entry", ".target.project", "project"): (_OWN_PROJECT, frozenset({"Demo"})),
    ("create_time_entry_until", ".target.project", "project"): (_OWN_PROJECT, frozenset({"Demo"})),
    ("delete_relation", ".payload.from_id", "work_package_id"): (
        "the other end of the relation, a field of its own",
        frozenset({42}),
    ),
    ("delete_work_package", ".payload.id", "work_package_id"): (_OWN_ID, frozenset({42})),
    ("delete_work_package", ".target.id", "work_package_id"): (_OWN_ID, frozenset({42})),
    ("set_work_package_watcher", ".target.id", "work_package_id"): (_OWN_ID, frozenset({42})),
    ("update_work_package", ".target.id", "work_package_id"): (_OWN_ID, frozenset({42})),
    ("add_work_package_comment", ".target.id", "work_package_id"): (_OWN_ID, frozenset({42})),
    ("bulk_update_work_packages", ".target.id", "work_package_id"): (_OWN_ID, frozenset({10})),
    ("bulk_update_work_packages", ".payload.subject", "work_package_id"): (_TEXT_WITH_NUMBER, frozenset({"New 10"})),
    ("bulk_update_work_packages", ".target.subject", "work_package_id"): (
        _TEXT_WITH_NUMBER,
        frozenset({"New 10", "Old 10"}),
    ),
    ("create_work_package_attachment", ".message", "status"): (
        _MESSAGE,
        frozenset({"Attachment uploaded successfully."}),
    ),
    ("create_container_attachment", ".message", "status"): (_MESSAGE, frozenset({"Attachment uploaded successfully."})),
    ("update_storage", ".message", "provider_type"): (
        "static advice about Nextcloud storages, not the record's value",
        frozenset(
            {
                "OpenProject is ready to attempt updating the storage. Changing `host` on a Nextcloud storage re-runs "
                "OpenProject's live host-reachability/setup-completeness probe at confirm=true (no pre-validation endpoint "
                "exists to check this earlier). Ask for confirmation, then call again with confirm=true."
            }
        ),
    ),
}


def _is_id_name(name: str) -> bool:
    name = name.removesuffix("[]")
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
        number = abs(value)
        if number >= 10 or _is_id_name(path.rsplit(".", 1)[-1]):
            # An id may come back zero-padded (`00077`); a digit on either side is another number.
            return re.search(rf"(?<!\d)0*{number}(?!\d)", leaf) is not None
        # A small number at a path that is no id is a count or a flag; in a text only a path segment (`/7`, `/7/`, `/7?`)
        # counts as an id. A text like `3/7` matches too: a false positive costs a listed row, a miss costs a leak.
        return re.search(rf"/0*{number}(?:$|[/?#])", leaf) is not None
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
        else:
            HIDDEN_FAILURES[(tool, confirm, repr(sorted(hidden.items())))] = f"{type(exc).__name__}: {exc}"
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
) -> tuple[dict[bool, int], list[tuple[bool, str, Any, str]]]:
    copies = {False: 0, True: 0}
    leaks: list[tuple[bool, str, Any, str]] = []
    for confirm in (False, True):
        plain_run = await _run(tool, None, confirm, tmp_path)
        if plain_run is None or not isinstance(plain_run[1], dict):
            continue
        for unit_raw, unit_plain, route in _units(*plain_run):
            for label, value, hide, kind in _targets(unit_raw, unit_plain):
                hidden_run = await _run(tool, hide, confirm, tmp_path)
                unit_hidden = None
                if hidden_run is None or not isinstance(hidden_run[1], dict):
                    failure = HIDDEN_FAILURES.get((tool, confirm, repr(sorted(hide.items()))), "no output")
                    SKIPS[(tool, label, confirm)] = failure
                    SKIPPED_HIDES[(tool, label, confirm)] = hide
                else:
                    try:
                        unit_hidden = _dig(hidden_run[1], route)
                    except (KeyError, IndexError):
                        unit_hidden = {}
                        SKIPS[(tool, label, confirm)] = LACKS_UNIT
                        SKIPPED_HIDES[(tool, label, confirm)] = hide
                if kind == "payload":
                    copies[confirm] += 1
                    if (
                        isinstance(unit_hidden, dict)
                        and _at(unit_hidden.get("payload"), value) is not None
                        and (tool, label, label) not in COINCIDENCE
                    ):
                        leaks.append((confirm, label, value, "payload key stays"))
                    continue
                copies[confirm] += sum(
                    1 for path, leaf in _leaves(_outside_result(unit_plain)) if _holds(path, leaf, value)
                )
                if not isinstance(unit_hidden, dict):
                    continue
                shown_record = unit_hidden.get("result")
                if kind == "record" and isinstance(shown_record, dict) and label in shown_record:
                    leaks.append((confirm, label, value, "result keeps the hidden key"))
                for path, leaf in _leaves(_outside_result(unit_hidden)):
                    if not _holds(path, leaf, value):
                        continue
                    if (tool, path, label) in COINCIDENCE and leaf in COINCIDENCE[(tool, path, label)][1]:
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
async def test_every_tool_has_a_visible_copy_to_hide_in_each_state_or_says_why_not(tmp_path: pathlib.Path) -> None:
    empty: set[tuple[str, bool]] = set()
    total = 0
    for tool in sorted(WRITE_TOOL_CASES):
        copies, _ = await _scan(tool, tmp_path)
        total += sum(copies.values())
        empty |= {(tool, confirm) for confirm, count in copies.items() if count == 0}

    assert empty == set(NO_COPIES), "a state lost its copies, or a listed state has some now"
    assert all(NO_COPIES.values())
    assert total >= MIN_BASELINE_COPIES


@pytest.mark.asyncio
async def test_every_skipped_run_is_a_refusal_by_the_hide_setting_and_listed(tmp_path: pathlib.Path) -> None:
    """A hidden run that gave nothing to compare is a blind spot of the scan. Each one must be the tool refusing the
    hidden field (its message names that field and the hide setting), and the (tool, state) -> fields table must match
    what the runs skip."""
    SKIPS.clear()
    SKIPPED_HIDES.clear()
    for tool in sorted(WRITE_TOOL_CASES):
        await _scan(tool, tmp_path)

    not_refusals = []
    for key, why in SKIPS.items():
        refusal = REFUSAL.fullmatch(why)
        hidden_fields = {field for fields in SKIPPED_HIDES[key].values() for field in fields}
        if refusal is None or refusal["field"] not in hidden_fields:
            not_refusals.append((key, why))
    assert not_refusals == []
    grouped: dict[tuple[str, bool], set[str]] = {}
    for tool, label, confirm in SKIPS:
        grouped.setdefault((tool, confirm), set()).add(label)
    assert {key: tuple(sorted(labels)) for key, labels in grouped.items()} == SKIPPED_RUNS


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


@pytest.mark.parametrize(
    ("path", "leaf", "value", "found"),
    [
        (".payload._links.version.href", "/api/v3/versions/7", 7, True),
        (".payload._links.version.href", "/api/v3/versions/7/", 7, True),
        (".payload._links.version.href", "/api/v3/versions/7?x=1", 7, True),
        (".payload._links.version.href", "/api/v3/versions/70", 7, False),
        (".message", "Updated 7 items", 7, False),
        (".work_package_id", "00077", 77, True),
        (".work_package_id", "0077 and more", 77, True),
        (".work_package_id", "770", 77, False),
        (".work_package_id", "177", 77, False),
        (".payload.subject", "Task 12", 12, True),
    ],
    ids=[
        "small id at the end of a link",
        "small id before a slash",
        "small id before a query",
        "a longer number is another id",
        "a small number in a text is no id",
        "zero-padded id",
        "zero-padded id in a text",
        "an id followed by a digit",
        "an id preceded by a digit",
        "a two-digit number in a text",
    ],
)
def test_a_value_is_found_where_an_id_can_come_back(path: str, leaf: str, value: int, found: bool) -> None:
    assert _holds(path, leaf, value) is found


@pytest.mark.parametrize("name", ["work_package_ids[]", "work_package_ids", "id", "meeting_id", "x.id"])
def test_a_list_of_ids_is_an_id_path_with_or_without_the_list_suffix(name: str) -> None:
    assert _is_id_name(name)


def test_a_name_that_is_no_id_stays_no_id_path() -> None:
    assert not _is_id_name("subject[]")
