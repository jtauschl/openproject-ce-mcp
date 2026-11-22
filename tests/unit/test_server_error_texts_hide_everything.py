"""A server error names no field the settings hide, and still says what else is wrong.

Counterpart of the write and read result scans, for the text OpenProject sends when it rejects a write: the
`validationErrors` of a form, and a 4xx at the commit or the delete. Each error object names an attribute
(`_embedded.details.attribute`) and carries a localized message that names that attribute or quotes a value, so
only the attribute can be judged. For every write tool of the contract cases whose result is a record of an entity
with an error table, the fake answers the form (or the commit) with one error per attribute of the entity, plus
`base`, an attribute no table knows, a custom field and an error without attribute; each message carries a
sentinel of its own. A setting hides one field (or a custom field by key, or by a name pattern, or an unrelated
entity); three things are asserted:

1. leak: the sentinel of every error the hidden field owns is nowhere in the result or the error text;
2. precision: the sentinel of every other error that a table or a fixed rule leaves visible is still there, so a
   text that is generic everywhere (the transport alone) fails;
3. reached: the rejecting request was served (a write the policy refuses before any request proves nothing).

With no hide setting every sentinel appears, the baseline.

`INDEPENDENT` is this file's own table of which attribute is about which field; it is compared with the policy's
`ERROR_KEYS`, so a wrong or a missing owner fails in either direction. Stated boundary: one generic call per
tool; the attributes listed here; bulk items are read from the serialized result; the free text of a failed copy
job (`get_job_status`) is a named limit and not part of the scan.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import pathlib
import re
from typing import Any

import httpx
import pytest
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import materialize_case

from openproject_ce_mcp import tools  # noqa: F401 -- importing the tools registers them in _TOOL_FUNCTIONS
from openproject_ce_mcp.app.policies.error_fields import BASE_FIELDS, ERROR_KEYS, QUOTES
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS

# entity -> API attribute -> the model fields it is about, written down here and not read from the policy.
INDEPENDENT: dict[str, dict[str, tuple[str, ...]]] = {
    "work_package": {
        "subject": ("subject",),
        "status": ("status",),
        "startDate": ("start_date",),
        "dueDate": ("due_date",),
    },
    "project": {"name": ("name",), "identifier": ("identifier",), "description": ("description",)},
    "user": {"login": ("login",), "email": ("email",)},
    "version": {"name": ("name",), "startDate": ("start_date",), "effectiveDate": ("end_date",)},
    "time_entry": {"comments": ("comment",)},
    "board": {"name": ("name",)},
    "meeting": {"title": ("title",)},
    "membership": {"user": ("principal_id", "principal_name")},
    "grid": {"rowCount": ("row_count",)},
    "relation": {"type": ("type",)},
}
# Tools that return no single record: the entity their service judges by.
DELETE_ENTITY = {
    "delete_work_package": "work_package",
    "delete_version": "version",
    "delete_project": "project",
    "delete_user": "user",
    "delete_board": "board",
    "delete_time_entry": "time_entry",
    # The items of a bulk result carry the text of a rejected item.
    "bulk_create_work_packages": "work_package",
    "bulk_update_work_packages": "work_package",
    # The result of an occurrence is a meeting record, but the recurring meeting service judges its errors.
    "init_recurring_meeting_occurrence": "recurring_meeting",
    "cancel_recurring_meeting_occurrence": "recurring_meeting",
}
# The work package form hands its schema over, so a custom field is judged by its name there.
SCHEMA_NAME = "Public Field"
# entity -> the fields (of the ones the scan hides) a `base` error of the entity can describe; an entity without a row
# has its `base` judged as an unknown attribute. Written here, not read from the policy.
BASE_OWNERS: dict[str, set[str]] = {"work_package": {"status"}}
# (entity, attribute) -> the fields, beside its own, whose value the message can quote: the start date error of a work
# package, on `startDate` and on `dueDate`, quote the soonest start the relations allow: the finish of a predecessor, or
# its start when it has no finish.
QUOTED: dict[tuple[str, str], set[str]] = {
    ("work_package", "startDate"): {"start_date", "due_date"},
    ("work_package", "dueDate"): {"start_date", "due_date"},
}
CUSTOM_ATTRIBUTE = "customField5"
UNKNOWN_ATTRIBUTE = "zzForeign"
PRECISION_FLOOR = 25


def test_the_independent_table_is_the_policy_table_where_it_speaks() -> None:
    for entity, attributes in INDEPENDENT.items():
        for attribute, fields in attributes.items():
            assert ERROR_KEYS[entity][attribute] == fields, (entity, attribute)
    for entity, owners in BASE_OWNERS.items():
        assert owners <= BASE_FIELDS[entity], entity
    assert {key: set(fields) for key, fields in QUOTES.items()} == QUOTED


def _error_object(attribute: str | None, sentinel: str, code: str = "PropertyConstraintViolation") -> dict[str, Any]:
    error: dict[str, Any] = {
        "_type": "Error",
        "errorIdentifier": f"urn:openproject-org:api:v3:errors:{code}",
        "message": f"{sentinel} {attribute or 'request'} is invalid",
    }
    if attribute is not None:
        error["_embedded"] = {"details": {"attribute": attribute}}
    return error


def _attributes(entity: str) -> list[str]:
    return [*INDEPENDENT[entity], "base", UNKNOWN_ATTRIBUTE, CUSTOM_ATTRIBUTE]


def _sentinels(entity: str, mode: str) -> dict[str | None, str]:
    """attribute (None: no attribute, only a commit error can lack one) -> its sentinel."""
    attributes: list[str | None] = [*_attributes(entity), *([None] if mode == "commit" else [])]
    return {attribute: f"ZQ{index:03d}" for index, attribute in enumerate(attributes)}


@dataclasses.dataclass(frozen=True)
class Hide:
    label: str
    fields: dict[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)
    custom: tuple[str, ...] = ()


def _hides(entity: str) -> list[Hide]:
    owners = sorted({field for fields in INDEPENDENT[entity].values() for field in fields})
    hides = [Hide(f"{entity}.{field}", {entity: (field,)}) for field in owners]
    hides += [
        Hide("custom raw key", custom=(CUSTOM_ATTRIBUTE,)),
        Hide("custom name pattern, other name", custom=("Secret*",)),
        Hide("custom name pattern, this name", custom=("Public*",)),
        Hide("unrelated entity", {"attachment": ("title",)}),
    ]
    return hides


def _expected_hidden(entity: str, hide: Hide, *, schema_in_hand: bool) -> set[str | None]:
    """The attributes whose sentinel must be gone: the ones a hidden field owns, a custom field the settings hide
    by key or (no name is known here) by a name pattern, and, while any hide is active, every attribute no table
    knows, an error without attribute and a `base` the entity has no row for."""
    hidden: set[str | None] = {UNKNOWN_ATTRIBUTE, None}
    hidden_names = set(hide.fields.get(entity, ()))
    for attribute, fields in INDEPENDENT[entity].items():
        if (set(fields) | QUOTED.get((entity, attribute), set())) & hidden_names:
            hidden.add(attribute)
    knows_the_name = entity == "work_package" and schema_in_hand
    if CUSTOM_ATTRIBUTE in hide.custom or any(
        pattern.startswith("Public") or (not knows_the_name and pattern.endswith("*")) for pattern in hide.custom
    ):
        hidden.add(CUSTOM_ATTRIBUTE)
    base_owners = BASE_OWNERS.get(entity)
    if base_owners is None or base_owners & hidden_names:
        hidden.add("base")
    return hidden


def _entity_of(record: Any) -> str | None:
    name = re.sub(r"(Summary|Detail|Record)$", "", type(record).__name__)
    entity = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return entity if entity in HIDE_FIELD_ENV_BY_ENTITY else None


class _Injected:
    def __init__(self, case: Any, mode: str, entity: str) -> None:
        self.case = case
        self.mode = mode
        self.served = 0
        self.sentinels = _sentinels(entity, mode)

    def _errors(self) -> list[dict[str, Any]]:
        return [_error_object(attribute, sentinel) for attribute, sentinel in self.sentinels.items()]

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        result = self.case.handler(request)
        response = await result if inspect.isawaitable(result) else result
        if request.url.path.endswith("/form") and request.method == "POST":
            body = json.loads(response.content)
            body.setdefault("_embedded", {}).setdefault("schema", {})[CUSTOM_ATTRIBUTE] = {"name": SCHEMA_NAME}
            response = httpx.Response(200, json=body, request=request)
        if self.mode == "form" and request.url.path.endswith("/form") and request.method == "POST":
            body = json.loads(response.content)
            errors = {
                attribute: _error_object(attribute, sentinel, "PropertyConstraintViolation")
                for attribute, sentinel in self.sentinels.items()
                if attribute is not None
            }
            body.setdefault("_embedded", {})["validationErrors"] = errors
            self.served += 1
            return httpx.Response(200, json=body, request=request)
        if self.mode == "commit" and (request.method, request.url.path) == tuple(self.case.write_request):
            self.served += 1
            body = {
                "_type": "Error",
                "errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors",
                "message": "Multiple field constraints have been violated.",
                "_embedded": {"errors": self._errors()},
            }
            return httpx.Response(422, json=body, request=request)
        return response


async def _run(
    tool: str, entity: str, mode: str, hide: Hide | None, tmp_path: pathlib.Path
) -> tuple[str, int, Any] | None:
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)
    settings = materialized.settings
    if hide is not None:
        settings = dataclasses.replace(settings, hidden_fields=hide.fields, hide_custom_fields=hide.custom)
    injected = _Injected(case, mode, entity)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(injected))
    try:
        try:
            result = await _TOOL_FUNCTIONS[tool](FakeContext(client), **materialized.kwargs, confirm=True)
            text = json.dumps(_to_payload(result, elide_none=True), default=str)
        except Exception as exc:  # noqa: BLE001 -- a rejected commit is an exception, its text is the output
            text = f"{type(exc).__name__}: {exc}"
        return text, injected.served, None
    finally:
        await client.aclose()


async def _entity_for(tool: str, tmp_path: pathlib.Path) -> str | None:
    if tool in DELETE_ENTITY:
        return DELETE_ENTITY[tool]
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        result = case.handler(request)
        return await result if inspect.isawaitable(result) else result

    client = OpenProjectClient(materialized.settings, transport=httpx.MockTransport(handler))
    try:
        result = await _TOOL_FUNCTIONS[tool](FakeContext(client), **materialized.kwargs, confirm=True)
    except Exception:  # noqa: BLE001
        return None
    finally:
        await client.aclose()
    record = getattr(result, "result", None)
    return _entity_of(record) if record is not None else None


MODES = ("form", "commit")
SCANNED = sorted(WRITE_TOOL_CASES)
RESULTS: dict[str, Any] = {"precision": 0, "unreached": set(), "reached": set()}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", SCANNED)
async def test_a_server_error_names_no_hidden_field_and_keeps_the_rest(tool: str, tmp_path: pathlib.Path) -> None:
    entity = await _entity_for(tool, tmp_path)
    if entity not in INDEPENDENT:
        pytest.skip(f"no error table row in this scan for the entity of {tool}: {entity}")
    for mode in MODES:
        sentinels = _sentinels(entity, mode)
        baseline = await _run(tool, entity, mode, None, tmp_path)
        assert baseline is not None
        text, served, _ = baseline
        if served == 0:
            RESULTS["unreached"].add((tool, mode))
            continue
        RESULTS["reached"].add((tool, mode))
        missing = [attribute for attribute, sentinel in sentinels.items() if sentinel not in text]
        assert missing == [], f"{tool} {mode}: the visible run does not show {missing}"
        reached_with_a_hide = 0
        for hide in _hides(entity):
            hidden_text, hidden_served, _ = await _run(tool, entity, mode, hide, tmp_path) or ("", 0, None)
            if hidden_served == 0 or "is hidden by" in hidden_text and "cannot be written" in hidden_text:
                continue  # the write names a hidden field and the policy refuses it: nothing to judge
            reached_with_a_hide += 1
            gone = _expected_hidden(entity, hide, schema_in_hand=not tool.startswith("delete_")) & set(sentinels)
            leaked = [a for a in gone if sentinels[a] in hidden_text]
            assert leaked == [], f"{tool} {mode} {hide.label}: leaks {leaked}"
            lost = [a for a in sentinels if a not in gone and sentinels[a] not in hidden_text]
            assert lost == [], f"{tool} {mode} {hide.label}: lost {lost}"
            RESULTS["precision"] += len(sentinels) - len(gone)
        assert reached_with_a_hide, f"{tool} {mode}: no hide setting reached the rejecting request"


def test_the_scan_judged_enough_visible_errors() -> None:
    assert RESULTS["precision"] >= PRECISION_FLOOR


def test_the_scan_reached_the_rejecting_request_of_every_tool_it_judges() -> None:
    """Form errors only where a form exists (a delete has none); a commit error everywhere."""
    commit = {tool for tool, mode in RESULTS["reached"] if mode == "commit"}
    form = {tool for tool, mode in RESULTS["reached"] if mode == "form"}

    assert {"create_work_package", "update_work_package", "bulk_update_work_packages", "delete_work_package"} <= commit
    assert {"create_work_package", "update_project", "create_user", "update_version"} <= form
    assert not any(tool.startswith("delete_") for tool in form)
    assert len(commit) >= 20 and len(form) >= 15


# The read side: a 400 on any GET carries a sentinel in its text. With nothing hidden it reaches the caller; with
# any hide setting active (an unrelated one, or a custom field pattern alone) it must not, on any read tool: a read
# has no write form to render, so the transport's generic text is the whole protection (and the flat client's).
READ_SENTINEL = "ZQREAD"
READ_FLOOR = 25


def _read_tools() -> list[str]:
    from openproject_ce_mcp import tools as tools_module

    return sorted({name for names in tools_module.READ_TOOLS_BY_SCOPE.values() for name in names})


async def _read_run(name: str, hide: Hide | None) -> str | None:
    from _client_test_helpers import _base_settings, serving_projects
    from _read_tool_harness import FOREIGN, OVERRIDES, READABLE, arguments

    from openproject_ce_mcp.config import TOOL_GROUPS
    from openproject_ce_mcp.presentation import ContentBundle  # noqa: F401

    function = _TOOL_FUNCTIONS[name]
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    settings = _base_settings(read_projects=("*",), write_projects=(), **enabled)
    if hide is not None:
        settings = dataclasses.replace(settings, hidden_fields=hide.fields, hide_custom_fields=hide.custom)

    def rejecting(request: httpx.Request) -> httpx.Response:
        body = {
            "_type": "Error",
            "errorIdentifier": "urn:openproject-org:api:v3:errors:MultipleErrors",
            "message": "Multiple field constraints have been violated.",
            "_embedded": {
                "errors": [_error_object(UNKNOWN_ATTRIBUTE, READ_SENTINEL), _error_object(None, READ_SENTINEL)]
            },
        }
        return httpx.Response(400, json=body, request=request)

    client = OpenProjectClient(
        settings,
        transport=httpx.MockTransport(
            serving_projects(rejecting, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    try:
        await client.initialize()
        await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {})})
    except Exception as exc:  # noqa: BLE001 -- the text of the rejection is the output
        return f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()
    return None


@pytest.mark.asyncio
async def test_a_rejected_read_names_nothing_while_a_hide_is_active() -> None:
    shown = 0
    for name in _read_tools():
        if name not in _TOOL_FUNCTIONS:
            continue
        baseline = await _read_run(name, None)
        if baseline is None or READ_SENTINEL not in baseline:
            continue  # the call did not reach a rejection (refused earlier, or the text is the tool's own)
        shown += 1
        for hide in (
            Hide("unrelated entity", {"attachment": ("title",)}),
            Hide("custom pattern alone", custom=("Secret*",)),
        ):
            hidden = await _read_run(name, hide)
            assert hidden is not None and READ_SENTINEL not in hidden, (name, hide.label, hidden)
    assert shown >= READ_FLOOR
