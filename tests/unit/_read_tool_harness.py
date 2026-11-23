"""A fake OpenProject server and generic tool arguments for the registry-driven read matrices.

Everything under the readable project carries the marker `readable`, global lookups `global`, and everything else
belongs to a foreign project and carries `CANARY`. `arguments` builds one call per tool from its own signature (an
id of 5, the readable project `demo`), `OVERRIDES` fixes the few tools whose generic call needs other arguments.
"""

from __future__ import annotations

import datetime
import inspect
import json
import re
import typing
import zlib
from collections.abc import Callable
from typing import Any

import httpx

CANARY = "OUTSIDE-READ-SCOPE-CANARY"
READABLE = 1
FOREIGN = 99

KIND_BY_SEGMENT = {
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

GLOBAL_LOOKUPS = {"statuses", "priorities", "types", "roles", "custom_options", "days", "help_texts", "configuration"}


def item(kind: str, number: int, project_id: int, marker: str) -> dict[str, Any]:
    project = {"href": f"/api/v3/projects/{project_id}", "title": marker}
    return {
        "_type": kind,
        "id": number,
        "subject": marker,
        "name": marker,
        "title": marker,
        "identifier": "foreign" if project_id == FOREIGN else "demo",
        "description": {"raw": marker, "html": marker, "format": "markdown"},
        "startTime": "2026-01-01T00:00:00Z",
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


def serve(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/v3/").strip("/")
    segments = path.split("/")
    if path in (f"projects/{FOREIGN}", "projects/foreign"):
        return httpx.Response(200, json=item("Project", FOREIGN, FOREIGN, CANARY), request=request)
    if path in (f"projects/{READABLE}", "projects/demo"):
        return httpx.Response(200, json=item("Project", READABLE, READABLE, "readable"), request=request)
    # Global lookups name no project: nothing in them can belong to one outside the read scope.
    if segments[0] in GLOBAL_LOOKUPS or segments[:2] == ["time_entries", "activities"] or path == "users/me":
        owner, marker = READABLE, "global"
    # What sits under the readable project is that project's own data, whatever the item links say.
    elif segments[:2] in (["projects", "1"], ["projects", "demo"]):
        owner, marker = READABLE, "readable"
    else:
        owner, marker = FOREIGN, CANARY
    last = segments[-1]
    kind = KIND_BY_SEGMENT.get(last) or KIND_BY_SEGMENT.get(segments[-2] if len(segments) > 1 else "", "Thing")
    if last.isdigit() or last in ("me", "configuration"):
        body = item(kind, int(last) if last.isdigit() else 1, owner, marker)
        return httpx.Response(200, json=body, request=request)
    body = {
        "_type": "Collection",
        "total": 2,
        "count": 2,
        "pageSize": 100,
        "offset": 1,
        "_embedded": {"elements": [item(kind, 5, owner, marker), item(kind, 6, owner, marker)]},
        "_links": {"self": {"href": "/x"}},
    }
    return httpx.Response(200, json=body, request=request)


OVERRIDES: dict[str, dict[str, Any]] = {
    "get_job_status": {"job_status_id": "5"},
    "list_available_assignees": {"work_package_id": 5},
    "list_capabilities": {"project": "foreign"},
    "list_container_attachments": {"container_type": "post", "container_id": 5},
    "get_query_column": {"column_id": "subject"},
    "get_query_filter": {"filter_id": "status"},
    "get_query_filter_instance_schema": {"schema_id": "status"},
    "get_query_operator": {"operator_id": "="},
    "get_query_sort_by": {"sort_by_id": "subject-asc"},
}


def arguments(function: Callable[..., Any]) -> dict[str, Any]:
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


# The sentinel fake of the read-result scans: `serve` with every value rewritten so that each scalar of each resource is
# a string, number or date of its own, and the same resource reads the same wherever it is linked.
SENTINEL_BASE = 7_000_000
_KEEP_KEYS = frozenset(
    {"_type", "format", "identifier", "total", "count", "pageSize", "offset", "lockVersion", "avatar"}
)
_LABEL_KEYS = frozenset({"subject", "name", "title"})
_RESOURCE_HREF = re.compile(r"^(/api/v3/(?!projects/)[a-z_]+/)(\d+)$")


def sentinel_id(kind: str, number: int) -> int:
    """The id a resource carries under the sentinel fake; idempotent, so a request for it is served again."""
    if kind == "Project" or number >= SENTINEL_BASE:
        return number
    return SENTINEL_BASE + (zlib.crc32(kind.encode()) % 900) * 1000 + number


def _kind_of_href(href: str) -> str:
    match = re.match(r"^/api/v3/([a-z_]+)/", href)
    if match is None:
        return "Thing"
    return KIND_BY_SEGMENT.get(match.group(1)) or match.group(1).title().replace("_", "")


def sentinel_tag(kind: str, number: int) -> str:
    """A token of the resource that does not contain its id, so a text never repeats the number by accident."""
    return f"{zlib.crc32(f'{kind}{sentinel_id(kind, number)}'.encode()):08x}"


def sentinel_label(kind: str, number: int) -> str:
    return f"LBL-{kind}-{sentinel_tag(kind, number)}"


def sentinel_display_id(kind: str, number: int) -> str:
    return f"DSP-{sentinel_tag(kind, number)}"


def sentinel_date(seed: str) -> str:
    moment = datetime.datetime(2031, 1, 1) + datetime.timedelta(minutes=zlib.crc32(seed.encode()) % 400_000)
    return moment.strftime("%Y-%m-%dT%H:%M:00Z")


def _rewrite_href(href: str) -> str:
    match = _RESOURCE_HREF.match(href)
    if match is None:
        return href
    return f"{match.group(1)}{sentinel_id(_kind_of_href(href), int(match.group(2)))}"


def _sentinel_value(path: str, key: str, value: Any, kind: str, number: int) -> Any:
    if isinstance(value, bool) or value is None or key in _KEEP_KEYS:
        return value
    if key in _LABEL_KEYS:
        return sentinel_label(kind, number)
    if isinstance(value, int):
        return SENTINEL_BASE + zlib.crc32(f"{kind}{number}{path}".encode()) % 1_000_000
    if isinstance(value, str) and re.match(r"^\d{4}-\d\d-\d\dT", value):
        return sentinel_date(f"{kind}{number}{path}")
    return f"{path}-{kind}-{sentinel_tag(kind, number)}" if isinstance(value, str) else value


def _sentinel_walk(node: Any, path: str, kind: str, number: int, segment: str = "x") -> Any:
    if isinstance(node, list):
        return [_sentinel_walk(entry, path, kind, number, segment) for entry in node]
    if not isinstance(node, dict):
        return node
    if "href" in node and ("title" in node or "displayId" in node or len(node) == 1):
        href = _rewrite_href(str(node["href"]))
        target = re.search(r"/(\d+)$", href)
        rewritten: dict[str, Any] = {"href": href}
        if "title" in node and target:
            rewritten["title"] = sentinel_label(_kind_of_href(href), int(target.group(1)))
        elif "title" in node:
            rewritten["title"] = node["title"]
        if "displayId" in node and target:
            rewritten["displayId"] = sentinel_display_id("WorkPackage", int(target.group(1)))
        return rewritten
    if "_type" in node and "id" in node and isinstance(node["id"], int):
        kind, number = node["_type"], node["id"]
        own = f"/api/v3/{segment}/{sentinel_id(kind, number)}"
        node = {**node, "id": sentinel_id(kind, number), "_links": {**node["_links"], "self": {"href": own}}}
        if kind == "WorkPackage":
            node = {**node, "displayId": sentinel_display_id(kind, number), "_links": _hierarchy(node["_links"])}
        elif kind == "Project":
            node = {**node, "_links": {**node["_links"], **_project_hierarchy()}}
        elif kind == "User":
            node = {**node, "avatar": f"https://op.example.com/users/{sentinel_id(kind, number)}/avatar"}
        elif kind == "Attachment":
            download = {"href": f"/api/v3/attachments/{sentinel_id(kind, number)}/content"}
            node = {**node, "_links": {**node["_links"], "downloadLocation": download}}
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "id" or isinstance(value, (dict, list)):
            out[key] = (
                _sentinel_walk(value, key if not path else f"{path}.{key}", kind, number, segment)
                if key != "id"
                else value
            )
        else:
            out[key] = _sentinel_value(f"{path}.{key}" if path else key, key, value, kind, number)
    return out


def _linked(kind_segment: str, number: int) -> dict[str, Any]:
    return {"href": f"/api/v3/{kind_segment}/{number}", "title": "x", "displayId": "x"}


def _hierarchy(links: dict[str, Any]) -> dict[str, Any]:
    return {
        **links,
        "parent": _linked("work_packages", 8),
        "ancestors": [_linked("work_packages", 7), _linked("work_packages", 8)],
        "children": [_linked("work_packages", 9), _linked("work_packages", 10)],
    }


def _project_hierarchy() -> dict[str, Any]:
    return {
        "parent": {"href": "/api/v3/projects/98", "title": "x"},
        "ancestors": [{"href": "/api/v3/projects/97", "title": "x"}, {"href": "/api/v3/projects/98", "title": "x"}],
    }


def sentinel_serve(request: httpx.Request) -> httpx.Response:
    response = serve(request)
    body = json.loads(response.content)
    segments = request.url.path.removeprefix("/api/v3/").strip("/").split("/")
    segment = segments[-2] if segments[-1].isdigit() and len(segments) > 1 else segments[-1]
    rewritten = _sentinel_walk(body, "", "Thing", 0, segment)
    return httpx.Response(
        response.status_code,
        content=json.dumps(rewritten),
        headers={"content-type": "application/json"},
        request=request,
    )


# The names a nameless record lacks: the adapters fall back to a label for every one of them. A link's title is
# the title of another record, not of this one, so only the record's own members go.
_NAME_KEYS = frozenset({"name", "title", "subject", "fileName"})


def _without_names(node: Any) -> Any:
    if isinstance(node, list):
        return [_without_names(entry) for entry in node]
    if not isinstance(node, dict):
        return node
    own = "_type" in node and "href" not in node
    out = {key: _without_names(value) for key, value in node.items() if not (own and key in _NAME_KEYS)}
    origin = out.get("originData")
    if isinstance(origin, dict):
        out["originData"] = {key: value for key, value in origin.items() if key != "name"}
    return out


def nameless_sentinel_serve(request: httpx.Request) -> httpx.Response:
    """`sentinel_serve` where no record carries a name, title, subject or file name: every adapter falls back."""
    response = sentinel_serve(request)
    if "recurring_meetings" in request.url.path:
        # Their adapter reads `payload["title"]` without a fallback: a server always sends it.
        return response
    return httpx.Response(
        response.status_code,
        content=json.dumps(_without_names(json.loads(response.content))),
        headers={"content-type": "application/json"},
        request=request,
    )
