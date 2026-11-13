"""Every optional parameter of a write tool reaches a request body, or is listed with the reason it cannot be exercised.

A parameter that the tool accepts and never sends is a write that reports success and changes nothing. Every
optional parameter of every write tool is called on its own, with a value of its own, against a fake server that
echoes what it is sent as the form payload and offers allowed values for the reference fields. The call passes when
the value shows up in a request body (the form call or the commit); it fails when it shows up nowhere. A new write
tool or parameter joins the matrix without an entry.

Limits, stated on purpose: one value per parameter and a fake server that accepts everything it can resolve. It proves
that the value is sent, not that OpenProject keeps it: a field that the server's form schema does not offer, or a
contract that ignores it, needs the schema of the real server and is not reached here. A parameter whose generic
call is refused for a reason of the fake server or by a validation of its own sits in `UNEXERCISED` with the expected
refusal, so the gap is listed and cannot grow unnoticed.
"""

from __future__ import annotations

import inspect
import json
import re
import typing
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import FOREIGN, OVERRIDES, READABLE, arguments, serve
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import TOOL_GROUPS

CONTROL = {
    "ctx",
    "confirm",
    "select",
    "expect_display_id",
    "expect_parent_display_id",
    "expect_related_display_id",
    "text_limit",
}
# Parameters of one tool that the generic call cannot exercise for a reason that is not a client matter, with that
# reason. Keyed by tool and parameter: a reason that holds for one tool must not exempt another that takes the same name.
EXEMPT: dict[tuple[str, str], str] = {
    **dict.fromkeys(
        [
            (tool, "custom_fields")
            for tool in ("copy_project", "create_project", "create_subtask", "create_work_package")
        ]
        + [("update_project", "custom_fields"), ("update_work_package", "custom_fields")],
        "needs the field definitions of a real schema",
    ),
    ("create_meeting", "state"): "refused on create by design",
    ("create_meeting", "notify"): "refused on create by design",
    ("update_work_package_comment", "comment"): "the server's permission decides who may edit a comment",
    ("update_work_package_comment", "comment_append"): "the server's permission decides who may edit a comment",
    ("create_storage", "host"): "storage provider settings need a consistent set",
    ("update_storage", "host"): "storage provider settings need a consistent set",
    ("create_storage", "authentication_method"): "storage provider settings need a consistent set",
    ("update_group", "remove_user_ids"): "a removal leaves the body: the value is absent from it by design",
}
# What a tool needs besides the parameter under test when its generic arguments are not enough.
BASE: dict[str, dict[str, Any]] = {
    "create_time_entry": {"project": "demo", "activity": 5},
    "create_time_entry_until": {"project": "demo", "activity": 5},
}
ISO_DATE_TIME = "2026-03-04T10:00:00Z"
VALUES: dict[str, tuple[Any, str]] = {
    "start_time": (ISO_DATE_TIME, ISO_DATE_TIME),
    "remind_at": (ISO_DATE_TIME, ISO_DATE_TIME),
    "end_time": ("2026-03-04T12:00:00Z", "2026-03-04T12:00:00Z"),
    "valid_from": ("2026-03-04", "2026-03-04"),
    "spent_on": ("2026-03-04", "2026-03-04"),
    "hours": ("PT2H", "PT2H"),
    "duration": ("PT2H", "PT2H"),
    "estimated_time": ("PT3H", "PT3H"),
    "remaining_time": ("PT1H", "PT1H"),
    "kind": ("information", "information"),
    "relation_type": ("relates", "relates"),
    "sharing": ("none", "none"),
    "availability_factor": (50, "50"),
    "percentage_done": (50, "50"),
    "version": (5, "5"),
    "target_versions": ([5], "5"),
    "observed_in_versions": ([6], "6"),
    "type": (5, "5"),
    "priority": (5, "5"),
    "category": (5, "5"),
    "roles": ([5], "5"),
    "scope": ("/x", "/x"),
    "participant_user_refs": ([1007], "1007"),
    "frequency": ("weekly", "weekly"),
    "interval": (2, "2"),
    "end_after": ("iterations", "iterations"),
    "tenant_id": ("tenantx", "tenantx"),
    "drive_id": ("drivex", "drivex"),
    "description_replace": ({"old": "readable", "new": "CANARYR"}, "CANARYR"),
    "status_explanation_replace": ({"old": "readable", "new": "CANARYS"}, "CANARYS"),
    "comment_replace": ({"old": "readable", "new": "CANARYC"}, "CANARYC"),
    "filters": ([{"status": {"operator": "o", "values": []}}], "status"),
}
# A generic call that does not reach a body, with the reason and the refusal it ends in (a part of its text).
UNEXERCISED: dict[tuple[str, str], tuple[str, str]] = {}
for _name in ("description", "public", "active", "status", "status_explanation", "parent"):
    UNEXERCISED[("copy_project", _name)] = ("the fake copy job has no job id", "'id'")
for _name in ("row_count", "column_count"):
    UNEXERCISED[("create_grid", _name)] = ("a grid needs a scope of its own", "grid scope must be")
    UNEXERCISED[("update_grid", _name)] = ("the fake grid has no project scope", "grid has a scope")
UNEXERCISED[("update_grid", "name")] = ("the fake grid has no project scope", "grid has a scope")
UNEXERCISED[("create_membership", "notification_message")] = ("the fake has no such principal", "was not found")
for _tool in ("create_project", "update_project"):
    UNEXERCISED[(_tool, "status")] = ("the fake project form offers no status values", "is not allowed")
for _name in ("tenant_id", "drive_id"):
    UNEXERCISED[("create_storage", _name)] = ("a storage provider needs a consistent set of settings", "provider_type")
for _tool in ("create_subtask", "create_work_package", "update_work_package"):
    for _name in ("project_phase", "responsible"):
        UNEXERCISED[(_tool, _name)] = ("the fake form offers other values for this field", "is not allowed")
for _tool in ("update_time_entry", "update_time_entry_until"):
    UNEXERCISED[(_tool, "activity")] = ("the fake form offers no activity of that name", "was not found")
for _tool in ("update_document", "update_news", "update_version", "update_work_package"):
    UNEXERCISED[(_tool, "description_replace")] = ("the passage to replace is not in the fake text", "was not found")
UNEXERCISED[("update_project", "status_explanation_replace")] = ("the passage is not in the fake text", "was not found")
UNEXERCISED[("update_meeting", "participant_user_refs")] = (
    "refused by design on 17.4 and 17.5",
    "cannot change participants",
)
for _name in ("remind_at", "note"):
    UNEXERCISED[("update_reminder", _name)] = ("the fake reminder belongs to no writable project", "are disabled by")
UNEXERCISED[("update_work_package", "sprint")] = ("the fake has no sprints", "sprint")
UNEXERCISED[("update_work_package_comment", "comment_replace")] = (
    "the fake comment belongs to another user",
    "does not allow the configured user",
)


def _schema() -> dict[str, Any]:
    fields = {
        "priority": "priorities",
        "responsible": "users",
        "assignee": "users",
        "category": "categories",
        "projectPhase": "project_phases",
        "version": "versions",
        "type": "types",
        "status": "statuses",
        "parent": "work_packages",
        "sprint": "sprints",
        "activity": "time_entries/activities",
        "user": "users",
        "project": "projects",
    }
    return {
        key: {
            "type": "Resource",
            "writable": True,
            "_embedded": {
                "allowedValues": [
                    {
                        "id": n,
                        "name": f"opt{n}",
                        "_links": {"self": {"href": f"/api/v3/{path}/{n}", "title": f"opt{n}"}},
                    }
                    for n in (5, 6)
                ]
            },
        }
        for key, path in fields.items()
    }


class _Server:
    def __init__(self) -> None:
        self.bodies: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
            return serve(request)
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content.decode("latin1")
        self.bodies.append((str(request.url.query), body))
        echo = {
            "_type": "Form",
            "id": 5,
            "jobId": "j5",
            "subject": "x",
            "name": "x",
            "title": "x",
            "_embedded": {
                "payload": body if isinstance(body, dict) else {},
                "schema": _schema(),
                "validationErrors": {},
            },
            "_links": {"self": {"href": request.url.path}, "commit": {"href": request.url.path.replace("/form", "")}},
        }
        return httpx.Response(200, json=echo, request=request)


def _value(tool: str, name: str, annotation: Any, index: int) -> tuple[Any, str]:
    """A value of its own for the parameter and the text to look for in the bodies."""
    text = str(annotation)
    if name == "status":
        word = (
            "on_track" if "project" in tool else "open" if "version" in tool else "locked" if "user" in tool else None
        )
        return (word, word) if word else (5, "5")
    if name in VALUES:
        return VALUES[name]
    if name.endswith("_date") or name == "date":
        return "2026-03-04", "2026-03-04"
    if "bool" in text and "int" not in text.replace("bool", ""):
        return True, "true"
    if re.search(r"\blist\b|Sequence", text):
        return ([f"CANARY{index}"], f"CANARY{index}") if "str" in text else ([1000 + index], str(1000 + index))
    if "dict" in text.lower():
        return {"customField1": f"CANARY{index}"}, f"CANARY{index}"
    if "Literal" in text and (match := re.search(r"Literal\[([^\]]+)\]", text)):
        first = match.group(1).split(",")[0].strip().strip("'\"")
        return first, first
    if "int" in text and "str" not in text:
        return 1000 + index, str(1000 + index)
    if "float" in text:
        return 7.5, "7.5"
    if "IdOrName" in text or name.endswith("_id") or name in ("project", "parent", "assignee", "responsible", "user"):
        return 1000 + index, str(1000 + index)
    return f"CANARY{index}", f"CANARY{index}"


def _reached(marker: str, bodies: list[Any]) -> bool:
    text = json.dumps(bodies, default=str)
    if marker.isdigit() or marker == "7.5":
        return re.search(r"(?<![0-9A-Za-z.])" + re.escape(marker) + r"(?![0-9A-Za-z])", text) is not None
    return marker in text


def _cases() -> list[tuple[str, str]]:
    cases = []
    for name in sorted({n for names in tools.WRITE_TOOLS_BY_SCOPE.values() for n in names}):
        function = tools_runtime._TOOL_FUNCTIONS[name]
        for parameter, spec in inspect.signature(function).parameters.items():
            if parameter not in CONTROL and spec.default is not inspect.Parameter.empty:
                cases.append((name, parameter))
    return cases


async def _bodies(tool: str, parameter: str, *, give: bool) -> tuple[list[Any], str]:
    """The bodies the tool sends with the parameter (or, as the baseline, without it) and the text to look for."""
    function = tools_runtime._TOOL_FUNCTIONS[tool]
    signature = inspect.signature(function)
    hints = typing.get_type_hints(function, include_extras=False)
    index = list(signature.parameters).index(parameter)
    value, marker = _value(tool, parameter, hints.get(parameter, ""), index)
    server = _Server()
    enabled = {group.read_attr: True for group in TOOL_GROUPS} | {
        group.write.attr: True for group in TOOL_GROUPS if group.write is not None
    }
    client = OpenProjectClient(
        _base_settings(read_projects=("*",), write_projects=("*",), **enabled),
        transport=httpx.MockTransport(
            serving_projects(server, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        base = {**arguments(function), **OVERRIDES.get(tool, {}), **BASE.get(tool, {})}
        for key in list(base):
            if key == "status" or key in VALUES:
                base[key] = _value(tool, key, hints.get(key, ""), 0)[0]
        base.pop(parameter, None)
        await function(FakeContext(client), **{**base, **({parameter: value} if give else {}), "confirm": True})
    finally:
        await client.aclose()
    return server.bodies, marker


async def _call(tool: str, parameter: str) -> tuple[bool, str]:
    """Whether the parameter changed what the tool sends: its value is in the bodies and the bodies differ from the
    ones of the same call without it (a numeric value can equal an id that the call carries anyway)."""
    given, marker = await _bodies(tool, parameter, give=True)
    try:
        baseline, _ = await _bodies(tool, parameter, give=False)
    except Exception:  # noqa: BLE001
        baseline = []  # a call with nothing to write is refused: nothing is sent without the parameter
    return _reached(marker, given) and given != baseline, marker


_CASES = _cases()


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "parameter"), _CASES, ids=[f"{tool}.{parameter}" for tool, parameter in _CASES])
async def test_a_write_parameter_reaches_a_request_body(tool: str, parameter: str) -> None:
    if (tool, parameter) in EXEMPT:
        pytest.skip(EXEMPT[tool, parameter])
    if (tool, parameter) in UNEXERCISED:
        reason, expected_refusal = UNEXERCISED[tool, parameter]
        with pytest.raises(Exception, match=re.escape(expected_refusal)):
            await _call(tool, parameter)
        pytest.skip(reason)

    reached, marker = await _call(tool, parameter)

    assert reached, f"{tool} accepts {parameter} but sends nothing that carries {marker!r}"


def test_every_write_tool_of_the_registry_is_in_the_matrix() -> None:
    registered = {name for names in tools.WRITE_TOOLS_BY_SCOPE.values() for name in names}

    assert registered <= set(tools_runtime._TOOL_FUNCTIONS)
    assert registered == {tool for tool, _ in _CASES} | {
        name
        for name in registered
        if all(
            spec.default is inspect.Parameter.empty or p in CONTROL
            for p, spec in inspect.signature(tools_runtime._TOOL_FUNCTIONS[name]).parameters.items()
        )
    }


def test_every_entry_of_the_unexercised_list_names_a_real_parameter() -> None:
    assert set(UNEXERCISED) <= set(_CASES)
    assert set(EXEMPT) <= set(_CASES)


def test_the_value_check_tells_a_sent_value_from_a_missing_one() -> None:
    assert _reached("CANARY1", [("", {"a": ["x CANARY1"]})])
    assert not _reached("CANARY1", [("", {"a": "other"})])
    assert _reached("1001", [("", {"_links": {"x": {"href": "/api/v3/y/1001"}}})])
    assert not _reached("100", [("", {"a": 1001})])
