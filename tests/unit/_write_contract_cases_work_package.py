"""Behavioral-contract fixture cases for the "work_package"-scope write/delete MCP
tools (OPM-209 / Phase D). Split out per scope so no single file grows unwieldy;
this one covers every tool in `WRITE_TOOLS_BY_SCOPE["work_package"]`
(src/openproject_ce_mcp/tools.py) -- the largest scope group.

Sibling test files import from this module as `from
_write_contract_cases_work_package import ...` (no package prefix), matching the
rootless import convention documented in `_client_test_helpers.py`/
`_tools_test_helpers.py`.
"""

from __future__ import annotations

import json

import httpx
from _client_test_helpers import make_settings
from _write_contract_cases_types import WriteToolCase

_SETTINGS = make_settings()


# --- create_work_package / create_subtask / bulk_create_work_packages share the
# same underlying create flow: resolve the project, resolve the type, probe the
# work_packages/form endpoint, then (once confirmed) POST /api/v3/work_packages. ---


def _create_work_package_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
        return httpx.Response(
            200,
            json={
                "_type": "Project",
                "id": 1,
                "name": "Demo",
                "identifier": "demo",
                "_links": {"versions": {"href": "/api/v3/projects/1/versions"}},
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/projects/1/types":
        return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
    if request.method == "POST" and request.url.path == "/api/v3/projects/1/work_packages/form":
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages":
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": 501,
                "subject": body.get("subject", ""),
                "lockVersion": 1,
                "_links": {
                    "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                    "status": {"title": "New"},
                    "type": {"title": "Task"},
                    "activities": {"href": "/api/v3/work_packages/501/activities"},
                    "relations": {"href": "/api/v3/work_packages/501/relations"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _create_subtask_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={
                "id": 42,
                "subject": "Parent feature",
                "_links": {
                    "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                    "status": {"title": "New"},
                    "type": {"title": "Feature"},
                    "activities": {"href": "/api/v3/work_packages/42/activities"},
                    "relations": {"href": "/api/v3/work_packages/42/relations"},
                },
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/projects/1":
        return httpx.Response(
            200,
            json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo"},
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/projects/1/types":
        return httpx.Response(200, json={"_embedded": {"elements": [{"id": 8, "name": "Task"}]}}, request=request)
    if request.method == "POST" and request.url.path == "/api/v3/projects/1/work_packages/form":
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages":
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": 502,
                "subject": body.get("subject", ""),
                "lockVersion": 1,
                "_links": {
                    "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                    "status": {"title": "New"},
                    "type": {"title": "Task"},
                    "activities": {"href": "/api/v3/work_packages/502/activities"},
                    "relations": {"href": "/api/v3/work_packages/502/relations"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _update_work_package_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={
                "id": 42,
                "subject": "Old title",
                "lockVersion": 4,
                "_links": {
                    "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                    "status": {"title": "New"},
                    "type": {"title": "Feature"},
                    "activities": {"href": "/api/v3/work_packages/42/activities"},
                    "relations": {"href": "/api/v3/work_packages/42/relations"},
                },
            },
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/42/form":
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={
                "id": 42,
                "subject": "Updated title",
                "lockVersion": 5,
                "_links": {
                    "project": {"title": "Demo"},
                    "status": {"title": "New"},
                    "type": {"title": "Feature"},
                    "activities": {"href": "/api/v3/work_packages/42/activities"},
                    "relations": {"href": "/api/v3/work_packages/42/relations"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _bulk_update_work_packages_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/10":
        return httpx.Response(
            200,
            json={
                "id": 10,
                "subject": "Old 10",
                "lockVersion": 1,
                "_links": {
                    "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                    "status": {"title": "New"},
                    "type": {"title": "Task"},
                    "activities": {"href": "/api/v3/work_packages/10/activities"},
                    "relations": {"href": "/api/v3/work_packages/10/relations"},
                },
            },
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/10/form":
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/work_packages/10":
        return httpx.Response(
            200,
            json={
                "id": 10,
                "subject": "New 10",
                "lockVersion": 2,
                "_links": {
                    "project": {"title": "Demo"},
                    "status": {"title": "New"},
                    "type": {"title": "Task"},
                    "activities": {"href": "/api/v3/work_packages/10/activities"},
                    "relations": {"href": "/api/v3/work_packages/10/relations"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_work_package_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={
                "id": 42,
                "subject": "Delete me",
                "lockVersion": 4,
                "_links": {
                    "project": {"title": "Demo"},
                    "status": {"title": "New"},
                    "type": {"title": "Task"},
                    "activities": {"href": "/api/v3/work_packages/42/activities"},
                    "relations": {"href": "/api/v3/work_packages/42/relations"},
                },
            },
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _add_work_package_comment_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/42/activities":
        return httpx.Response(
            201,
            json={
                "id": 77,
                "_type": "Activity",
                "version": 3,
                "comment": {"raw": "Looks good to me."},
                "_links": {"user": {"title": "OpenProject Bot"}},
                "createdAt": "2026-03-20T11:00:00Z",
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _toggle_activity_emoji_reaction_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/activities/1988":
        return httpx.Response(
            200,
            json={"id": 1988, "_links": {"workPackage": {"href": "/api/v3/work_packages/42"}}},
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/activities/1988/emoji_reactions":
        return httpx.Response(
            200,
            json={
                "_type": "Collection",
                "_embedded": {
                    "elements": [
                        {
                            "_type": "EmojiReaction",
                            "reaction": "heart",
                            "emoji": "❤️",
                            "reactionsCount": 1,
                            "_links": {"reactingUsers": [{"title": "Alice"}]},
                        }
                    ]
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _create_work_package_reminder_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/42/reminders":
        return httpx.Response(
            201,
            json={
                "id": 5,
                "remindAt": "2026-12-01T09:00:00Z",
                "_links": {"remindable": {"href": "/api/v3/work_packages/42"}},
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _update_reminder_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/reminders/5":
        return httpx.Response(
            200,
            json={
                "id": 5,
                "remindAt": "2026-12-01T09:00:00Z",
                "_links": {"remindable": {"href": "/api/v3/work_packages/42"}},
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/reminders/5":
        return httpx.Response(
            200,
            json={
                "id": 5,
                "remindAt": "2026-12-01T09:00:00Z",
                "note": "Updated note",
                "_links": {"remindable": {"href": "/api/v3/work_packages/42"}},
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_reminder_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/reminders/5":
        return httpx.Response(
            200,
            json={
                "id": 5,
                "remindAt": "2026-12-01T09:00:00Z",
                "_links": {"remindable": {"href": "/api/v3/work_packages/42"}},
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/reminders/5":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _create_work_package_relation_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/43":
        return httpx.Response(
            200,
            json={"id": 43, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/42/relations":
        return httpx.Response(
            201,
            json={
                "id": 99,
                "type": "relates",
                "_links": {
                    "from": {"href": "/api/v3/work_packages/42"},
                    "to": {"href": "/api/v3/work_packages/43"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_relation_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/relations/99":
        return httpx.Response(
            200,
            json={
                "id": 99,
                "type": "relates",
                "_links": {
                    "from": {"href": "/api/v3/work_packages/42"},
                    "to": {"href": "/api/v3/work_packages/43"},
                },
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/relations/99":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _update_relation_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/relations/99":
        return httpx.Response(
            200,
            json={
                "id": 99,
                "type": "relates",
                "_links": {
                    "from": {"href": "/api/v3/work_packages/42"},
                    "to": {"href": "/api/v3/work_packages/43"},
                },
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/relations/99":
        return httpx.Response(
            200,
            json={
                "id": 99,
                "type": "relates",
                "description": "Updated description",
                "_links": {
                    "from": {"href": "/api/v3/work_packages/42"},
                    "to": {"href": "/api/v3/work_packages/43"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_attachment_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/attachments/7":
        return httpx.Response(
            200,
            json={
                "id": 7,
                "fileName": "notes.txt",
                "fileSize": 12,
                "_links": {"container": {"href": "/api/v3/work_packages/42"}},
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/attachments/7":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _add_work_package_watcher_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/users/5":
        return httpx.Response(200, json={"id": 5, "name": "Alice", "login": "alice"}, request=request)
    if request.method == "POST" and request.url.path == "/api/v3/work_packages/42/watchers":
        return httpx.Response(200, json={"id": 5, "name": "Alice", "login": "alice"}, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _remove_work_package_watcher_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/work_packages/42/watchers/5":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _create_time_entry_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
        return httpx.Response(
            200,
            json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "POST" and request.url.path == "/api/v3/time_entries":
        return httpx.Response(
            201,
            json={
                "id": 8,
                "hours": "PT1H",
                "spentOn": "2026-01-01",
                "_links": {
                    "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                    "entity": {"href": "/api/v3/work_packages/42"},
                    "activity": {"href": "/api/v3/time_entries/activities/1", "title": "Development"},
                },
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _update_time_entry_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/time_entries/8":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "hours": "PT1H",
                "spentOn": "2026-01-01",
                "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
            },
            request=request,
        )
    if request.method == "PATCH" and request.url.path == "/api/v3/time_entries/8":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "hours": "PT1H",
                "spentOn": "2026-01-01",
                "comment": {"raw": "Updated comment"},
                "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
            },
            request=request,
        )
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_time_entry_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/time_entries/8":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "hours": "PT1H",
                "spentOn": "2026-01-01",
                "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
            },
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/time_entries/8":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _delete_file_link_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/file_links/5":
        return httpx.Response(
            200,
            json={
                "id": 5,
                "_links": {
                    "self": {"href": "/api/v3/file_links/5"},
                    "container": {"href": "/api/v3/work_packages/9"},
                },
            },
            request=request,
        )
    if request.method == "GET" and request.url.path == "/api/v3/work_packages/9":
        return httpx.Response(
            200,
            json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
            request=request,
        )
    if request.method == "DELETE" and request.url.path == "/api/v3/file_links/5":
        return httpx.Response(204, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


WORK_PACKAGE_CASES: dict[str, WriteToolCase] = {
    "create_work_package": WriteToolCase(
        tool="create_work_package",
        kwargs={"project": "demo", "type": "Task", "subject": "New work package"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_work_package_handler,
        write_request=("POST", "/api/v3/work_packages"),
    ),
    "create_subtask": WriteToolCase(
        tool="create_subtask",
        kwargs={"parent_work_package_id": 42, "type": "Task", "subject": "New subtask"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_subtask_handler,
        write_request=("POST", "/api/v3/work_packages"),
    ),
    "update_work_package": WriteToolCase(
        tool="update_work_package",
        kwargs={"work_package_id": 42, "subject": "Updated title"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_update_work_package_handler,
        write_request=("PATCH", "/api/v3/work_packages/42"),
    ),
    "bulk_create_work_packages": WriteToolCase(
        tool="bulk_create_work_packages",
        kwargs={"items": [{"project": "demo", "type": "Task", "subject": "WP 1"}]},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_work_package_handler,
        write_request=("POST", "/api/v3/work_packages"),
        denial_mode="bulk_result",
    ),
    "bulk_update_work_packages": WriteToolCase(
        tool="bulk_update_work_packages",
        kwargs={"items": [{"work_package_id": 10, "subject": "New 10"}]},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_bulk_update_work_packages_handler,
        write_request=("PATCH", "/api/v3/work_packages/10"),
        denial_mode="bulk_result",
    ),
    "delete_work_package": WriteToolCase(
        tool="delete_work_package",
        kwargs={"work_package_id": 42},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_work_package_handler,
        write_request=("DELETE", "/api/v3/work_packages/42"),
    ),
    "add_work_package_comment": WriteToolCase(
        tool="add_work_package_comment",
        kwargs={"work_package_id": 42, "comment": "Looks good to me."},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_add_work_package_comment_handler,
        write_request=("POST", "/api/v3/work_packages/42/activities"),
    ),
    "toggle_activity_emoji_reaction": WriteToolCase(
        tool="toggle_activity_emoji_reaction",
        kwargs={"activity_id": 1988, "reaction": "heart"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_toggle_activity_emoji_reaction_handler,
        write_request=("PATCH", "/api/v3/activities/1988/emoji_reactions"),
    ),
    "create_work_package_reminder": WriteToolCase(
        tool="create_work_package_reminder",
        kwargs={"work_package_id": 42, "remind_at": "2026-12-01T09:00:00Z"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_work_package_reminder_handler,
        write_request=("POST", "/api/v3/work_packages/42/reminders"),
    ),
    "update_reminder": WriteToolCase(
        tool="update_reminder",
        kwargs={"reminder_id": 5, "note": "Updated note"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_update_reminder_handler,
        write_request=("PATCH", "/api/v3/reminders/5"),
    ),
    "delete_reminder": WriteToolCase(
        tool="delete_reminder",
        kwargs={"reminder_id": 5},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_reminder_handler,
        write_request=("DELETE", "/api/v3/reminders/5"),
    ),
    "create_work_package_relation": WriteToolCase(
        tool="create_work_package_relation",
        kwargs={"work_package_id": 42, "related_to_work_package_id": 43, "relation_type": "relates"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_work_package_relation_handler,
        write_request=("POST", "/api/v3/work_packages/42/relations"),
    ),
    "delete_relation": WriteToolCase(
        tool="delete_relation",
        kwargs={"relation_id": 99},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_relation_handler,
        write_request=("DELETE", "/api/v3/relations/99"),
    ),
    "delete_attachment": WriteToolCase(
        tool="delete_attachment",
        kwargs={"attachment_id": 7},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_attachment_handler,
        write_request=("DELETE", "/api/v3/attachments/7"),
    ),
    "add_work_package_watcher": WriteToolCase(
        tool="add_work_package_watcher",
        kwargs={"work_package_id": 42, "user_id": 5},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_add_work_package_watcher_handler,
        write_request=("POST", "/api/v3/work_packages/42/watchers"),
    ),
    "remove_work_package_watcher": WriteToolCase(
        tool="remove_work_package_watcher",
        kwargs={"work_package_id": 42, "user_id": 5},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_remove_work_package_watcher_handler,
        write_request=("DELETE", "/api/v3/work_packages/42/watchers/5"),
    ),
    "create_time_entry": WriteToolCase(
        tool="create_time_entry",
        kwargs={"work_package_id": 42, "activity": "1", "hours": "PT1H", "spent_on": "2026-01-01"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_create_time_entry_handler,
        write_request=("POST", "/api/v3/time_entries"),
    ),
    "update_time_entry": WriteToolCase(
        tool="update_time_entry",
        kwargs={"time_entry_id": 8, "comment": "Updated comment"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_update_time_entry_handler,
        write_request=("PATCH", "/api/v3/time_entries/8"),
    ),
    "delete_time_entry": WriteToolCase(
        tool="delete_time_entry",
        kwargs={"time_entry_id": 8},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_time_entry_handler,
        write_request=("DELETE", "/api/v3/time_entries/8"),
    ),
    "update_relation": WriteToolCase(
        tool="update_relation",
        kwargs={"relation_id": 99, "description": "Updated description"},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_update_relation_handler,
        write_request=("PATCH", "/api/v3/relations/99"),
    ),
    "delete_file_link": WriteToolCase(
        tool="delete_file_link",
        kwargs={"file_link_id": 5},
        settings=_SETTINGS,
        write_scope="work_package",
        handler=_delete_file_link_handler,
        write_request=("DELETE", "/api/v3/file_links/5"),
    ),
}
