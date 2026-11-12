"""A fake OpenProject server and generic tool arguments for the registry-driven read matrices.

Everything under the readable project carries the marker `readable`, global lookups `global`, and everything else
belongs to a foreign project and carries `CANARY`. `arguments` builds one call per tool from its own signature (an
id of 5, the readable project `demo`), `OVERRIDES` fixes the few tools whose generic call needs other arguments.
"""

from __future__ import annotations

import inspect
import typing
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
