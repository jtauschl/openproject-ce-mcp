"""No read tool hands back data that belongs to a project outside OPENPROJECT_READ_PROJECTS.

Every tool of `_PROJECT_SCOPED_READ_TOOLS` runs against a server whose every resource that is not under the
readable project belongs to a project outside the read scope and carries a canary string in each of its texts.
A tool passes when it refuses the read (a scope error), or answers without the canary. The arguments come from
the tool's own signature (an id of `5`, the readable project `demo`), so a new read tool joins the matrix without
an entry; a tool whose generic call fails for another reason sits in `UNEXERCISED` with the reason, so the gap is
listed and cannot grow unnoticed.

Limits, stated on purpose: one synthetic argument set per tool and a fake server that assigns ownership by URL
path. It proves the id, link and list paths of that call, not alternate ids, project or filter values, pagination,
optional flags or each endpoint's real response shape. It does not reach a gate that depends on a particular
parameter value, a filter parameter, or a foreign link inside an allowed resource; those have their own tests
(`test_app_policies_scope.py`, the domain service tests). The global lookups (`_GLOBAL_LOOKUPS`) rest on a reading of
the OpenProject 17.9 representers: statuses, priorities, roles and types carry no project link; the others
(`custom_options`, `days`, `help_texts`, `configuration`, `time_entries/activities`, `users/me`) are instance-wide
by their endpoint and tool signature.
"""

from __future__ import annotations

import inspect
import json
import typing
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import TOOL_GROUPS

CANARY = "OUTSIDE-READ-SCOPE-CANARY"
READABLE = 1
FOREIGN = 99

_KIND_BY_SEGMENT = {
    "work_packages": "WorkPackage",
    "projects": "Project",
    "versions": "Version",
    "news": "News",
    "documents": "Document",
    "wiki_pages": "WikiPage",
    "categories": "Category",
    "memberships": "Membership",
    "queries": "Query",
    "views": "View",
    "grids": "Grid",
    "sprints": "Sprint",
    "meetings": "Meeting",
    "time_entries": "TimeEntry",
    "relations": "Relation",
    "attachments": "Attachment",
    "users": "User",
    "groups": "Group",
    "roles": "Role",
    "boards": "Query",
    "reminders": "Reminder",
    "notifications": "Notification",
    "activities": "Activity::Comment",
    "watchers": "User",
    "storages": "Storage",
    "project_storages": "ProjectStorage",
    "file_links": "FileLink",
    "agenda_items": "MeetingAgendaItem",
    "outcomes": "MeetingOutcome",
    "sections": "MeetingSection",
    "backlog_buckets": "BacklogBucket",
    "posts": "Post",
}

_GLOBAL_LOOKUPS = {"statuses", "priorities", "types", "roles", "custom_options", "days", "help_texts", "configuration"}

# A generic call that does not reach a gate, with the reason; each entry is a gap of this matrix, not a pass.
UNEXERCISED: dict[str, str] = {}


def _item(kind: str, number: int, project_id: int, marker: str) -> dict[str, Any]:
    project = {"href": f"/api/v3/projects/{project_id}", "title": marker}
    return {
        "_type": kind,
        "id": number,
        "subject": marker,
        "name": marker,
        "title": marker,
        "identifier": "foreign" if project_id == FOREIGN else "demo",
        "description": {"raw": marker, "html": marker, "format": "markdown"},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "active": True,
        "_links": {
            "self": {"href": f"/api/v3/x/{number}"},
            "project": project,
            "definingProject": project,
            "context": project,
            "container": ({"href": "/api/v3/work_packages/5", "title": marker} if kind == "Attachment" else project),
            "meeting": {"href": f"/api/v3/meetings/{number}"},
            "agendaItem": {"href": f"/api/v3/meeting_agenda_items/{number}"},
            "workPackage": {"href": "/api/v3/work_packages/5", "title": marker},
            "from": {"href": "/api/v3/work_packages/5"},
            "to": {"href": "/api/v3/work_packages/6"},
            "user": {"href": "/api/v3/users/7", "title": marker},
            "type": {"href": "/api/v3/types/1", "title": marker},
            "status": {"href": "/api/v3/statuses/1", "title": marker},
        },
    }


def _server(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/v3/").strip("/")
    segments = path.split("/")
    if path in (f"projects/{FOREIGN}", "projects/foreign"):
        return httpx.Response(200, json=_item("Project", FOREIGN, FOREIGN, CANARY), request=request)
    if path in (f"projects/{READABLE}", "projects/demo"):
        return httpx.Response(200, json=_item("Project", READABLE, READABLE, "readable"), request=request)
    # Global lookups name no project: nothing in them can belong to one outside the read scope.
    if segments[0] in _GLOBAL_LOOKUPS or segments[:2] == ["time_entries", "activities"] or path == "users/me":
        owner, marker = READABLE, "global"
    # What sits under the readable project is that project's own data, whatever the item links say.
    elif segments[:2] in (["projects", "1"], ["projects", "demo"]):
        owner, marker = READABLE, "readable"
    else:
        owner, marker = FOREIGN, CANARY
    last = segments[-1]
    kind = _KIND_BY_SEGMENT.get(last) or _KIND_BY_SEGMENT.get(segments[-2] if len(segments) > 1 else "", "Thing")
    if last.isdigit() or last in ("me", "configuration"):
        body = _item(kind, int(last) if last.isdigit() else 1, owner, marker)
        return httpx.Response(200, json=body, request=request)
    body = {
        "_type": "Collection",
        "total": 2,
        "count": 2,
        "pageSize": 100,
        "offset": 1,
        "_embedded": {"elements": [_item(kind, 5, owner, marker), _item(kind, 6, owner, marker)]},
        "_links": {"self": {"href": "/x"}},
    }
    return httpx.Response(200, json=body, request=request)


_OVERRIDES: dict[str, dict[str, Any]] = {
    "get_job_status": {"job_status_id": "5"},
    "list_available_assignees": {"work_package_id": 5},
    "list_capabilities": {"project": "foreign"},
    "list_container_attachments": {"container_type": "post", "container_id": 5},
}


def _arguments(function: Callable[..., Any]) -> dict[str, Any]:
    hints = typing.get_type_hints(function, include_extras=False)
    arguments: dict[str, Any] = {}
    for name, parameter in inspect.signature(function).parameters.items():
        if name == "ctx" or parameter.default is not inspect.Parameter.empty:
            continue
        annotation = str(hints.get(name, ""))
        if name.endswith("_ids") or name == "ids":
            arguments[name] = [5]
        elif name == "project":
            arguments[name] = "demo"
        elif name in ("user_ref", "user"):
            arguments[name] = "7"
        elif "int" in annotation and "str" not in annotation:
            arguments[name] = 5
        elif name.endswith("_id") or "WorkPackageRef" in annotation or "IdOrName" in annotation:
            arguments[name] = 5
        else:
            arguments[name] = "x"
    return arguments


def _settings() -> Any:
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    return _base_settings(read_projects=("demo",), write_projects=(), **enabled)


async def _call(name: str) -> tuple[str, str]:
    function = tools_runtime._TOOL_FUNCTIONS[name]
    client = OpenProjectClient(
        _settings(),
        transport=httpx.MockTransport(
            serving_projects(_server, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**_arguments(function), **_OVERRIDES.get(name, {})})
    except Exception as error:  # noqa: BLE001
        text = f"{type(error).__name__}: {error}"
        return (
            "canary" if CANARY in text else "refused" if "SCOPE_DENIED" in text or "PERMISSION" in text else "other"
        ), text
    finally:
        await client.aclose()
    text = json.dumps(result, default=lambda value: getattr(value, "__dict__", str(value)))
    return ("canary" if CANARY in text else "answered"), text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(tools._PROJECT_SCOPED_READ_TOOLS))
async def test_a_read_tool_never_returns_data_of_a_project_outside_the_read_scope(name: str) -> None:
    outcome, detail = await _call(name)

    assert outcome != "canary", (name, detail[:300])
    if name in UNEXERCISED:
        pytest.skip(UNEXERCISED[name])
    assert outcome in ("refused", "answered"), (name, detail[:300])


def test_the_matrix_covers_every_project_scoped_read_tool_that_is_registered() -> None:
    registered = set(tools_runtime._TOOL_FUNCTIONS)

    assert set(tools._PROJECT_SCOPED_READ_TOOLS) <= registered
    assert set(UNEXERCISED) <= set(tools._PROJECT_SCOPED_READ_TOOLS)
