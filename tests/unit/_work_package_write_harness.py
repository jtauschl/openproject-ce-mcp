"""A recording server and the tool calls shared by the tests of the writes that take a work package reference.

The bare number `436` and the display reference `PROJ-436` resolve to two different work packages behind the real
client, resolver, adapter and service (`_work_package_target_helpers`). `_Server` answers the requests of one
write and records every work package fetch by the reference it carried and every request it saw. Each call in
`TOOLS` takes `(ctx, reference, confirm)` and passes the context's `expect_display_id` to a tool that has the parameter.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from _client_test_helpers import _write_enabled_settings
from _tools_test_helpers import FakeContext
from _work_package_target_helpers import (
    RECORDS_BY_REFERENCE,
    form_response,
    project_response,
)

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.tools import (
    create_time_entry,
    create_time_entry_until,
    create_work_package_attachment,
    create_work_package_reminder,
    create_work_package_wiki_link,
    delete_work_package_wiki_link,
    set_work_package_watcher,
)
from openproject_ce_mcp.tools_meetings import (
    create_meeting_agenda_item,
    create_meeting_outcome,
    update_meeting_agenda_item,
    update_meeting_outcome,
)

_API = "/api/v3"
_WORK_PACKAGE = re.compile(rf"^{_API}/work_packages/([^/]+)$")
_WORK_PACKAGE_SUB = re.compile(rf"^{_API}/work_packages/([^/]+)/(\w+)(?:/(\d+))?$")
_ITEM = {"id": 21, "title": "Item", "lockVersion": 1, "_links": {"meeting": {"href": f"{_API}/meetings/4"}}}
_OUTCOME = {"id": 31, "kind": "decision", "_links": {"agendaItem": {"href": f"{_API}/meeting_agenda_items/21"}}}
_MEETING = {
    "id": 4,
    "title": "Weekly",
    "_links": {"project": {"href": f"{_API}/projects/1", "title": "Project A"}},
}
_USER = {"_type": "User", "id": 3, "name": "Ada", "_links": {}}


class _Server:
    """Answers the requests of one write; every work package fetch is recorded by the reference it carried."""

    def __init__(self, records: dict[str, dict[str, Any]] | None = None) -> None:
        self.records = RECORDS_BY_REFERENCE if records is None else records
        self.work_package_gets: list[str] = []
        self.requests: list[str] = []

    @property
    def writes(self) -> list[str]:
        """Every request that changes data; the form POSTs only validate."""
        return [
            request for request in self.requests if not request.startswith("GET ") and not request.endswith("/form")
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append(f"{method} {path}")
        wp = _WORK_PACKAGE.match(path)
        if wp is not None and method == "GET":
            self.work_package_gets.append(wp.group(1))
            if wp.group(1) not in self.records:
                return _json(request, {"message": "not found"}, status=404)
            return _json(request, self.records[wp.group(1)])
        sub = _WORK_PACKAGE_SUB.match(path)
        if sub is not None:
            return self._work_package_sub_resource(request, sub.group(2), sub.group(3))
        for response in (self._meeting_routes(request), self._other_routes(request)):
            if response is not None:
                return response
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    @staticmethod
    def _work_package_sub_resource(request: httpx.Request, resource: str, tail: str | None) -> httpx.Response:
        method = request.method
        if resource == "relations" and method == "POST":
            return _json(request, _relation(request), status=201)
        if resource == "reminders" and method == "POST":
            reminder = {"id": 5, "remindAt": "2026-12-01T09:00:00Z", "note": "n", "_links": {}}
            return _json(request, reminder, status=201)
        if resource == "watchers" and method == "POST":
            return _json(request, _USER, status=201)
        if resource == "watchers" and method == "DELETE" and tail is not None:
            return httpx.Response(204, request=request)
        if resource == "attachments" and method == "POST":
            attachment = {"id": 9, "fileName": "note.txt", "_links": {}}
            return _json(request, attachment, status=201)
        if resource == "wiki_page_links" and method == "GET":
            return _json(request, {"total": 1, "_embedded": {"elements": [_wiki_link(12)]}})
        if resource == "wiki_page_links" and method == "POST":
            return _json(request, {"_embedded": {"elements": [_wiki_link(12)]}}, status=201)
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    @staticmethod
    def _meeting_routes(request: httpx.Request) -> httpx.Response | None:
        key = (request.method, request.url.path)
        routes: dict[tuple[str, str], tuple[dict[str, Any], int]] = {
            ("GET", f"{_API}/meetings/4"): (_MEETING, 200),
            ("GET", f"{_API}/meeting_agenda_items/21"): (_ITEM, 200),
            ("POST", f"{_API}/meeting_agenda_items"): (_ITEM, 201),
            ("PATCH", f"{_API}/meeting_agenda_items/21"): (_ITEM, 200),
            ("GET", f"{_API}/meeting_outcomes/31"): (_OUTCOME, 200),
            ("POST", f"{_API}/meeting_outcomes"): (_OUTCOME, 201),
            ("PATCH", f"{_API}/meeting_outcomes/31"): (_OUTCOME, 200),
        }
        if key not in routes:
            return None
        body, status = routes[key]
        return _json(request, body, status=status)

    @staticmethod
    def _other_routes(request: httpx.Request) -> httpx.Response | None:
        key = (request.method, request.url.path)
        if key == ("GET", f"{_API}/projects/1"):
            return project_response(request, 1, "proj-a", "Project A")
        if key == ("GET", f"{_API}/projects/2"):
            return project_response(request, 2, "proj-b", "Project B")
        if key == ("GET", f"{_API}/users/3"):
            return _json(request, _USER)
        if key == ("GET", f"{_API}/users/me"):
            return _json(request, _USER)
        if key == ("GET", f"{_API}/configuration"):
            return _json(request, {"maximumAttachmentFileSize": 5_000_000})
        if key == ("POST", f"{_API}/time_entries/form"):
            return form_response(request)
        if key == ("POST", f"{_API}/time_entries"):
            entry = {
                "id": 55,
                "hours": "PT1H",
                "spentOn": "2026-11-01",
                "_links": {"project": {"href": f"{_API}/projects/1", "title": "Project A"}},
            }
            return _json(request, entry, status=201)
        if key == ("DELETE", f"{_API}/wiki_page_links/12"):
            return httpx.Response(204, request=request)
        return None


def _json(request: httpx.Request, body: dict[str, Any], *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, request=request)


def _relation(request: httpx.Request) -> dict[str, Any]:
    body = json.loads(request.content)
    return {
        "id": 31,
        "type": body["type"],
        "_links": {
            "from": {"href": f"{_API}/work_packages/1", "title": "From"},
            "to": body["_links"]["to"],
        },
    }


def _wiki_link(link_id: int) -> dict[str, Any]:
    return {
        "id": link_id,
        "identifier": "7",
        "wikiPageLinkType": "wikiPageLinks:Relation",
        "_links": {"provider": {"title": "internal"}, "linkable": {"href": f"{_API}/work_packages/436"}},
    }


def _client(server: _Server, settings: Settings) -> OpenProjectClient:
    return OpenProjectClient(settings, transport=httpx.MockTransport(server.handler))


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return dataclasses.replace(
        _write_enabled_settings(), enable_meeting_write=True, attachment_root=str(tmp_path), **overrides
    )


Call = Callable[[Any, str, bool], Awaitable[Any]]


async def _reminder(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_reminder(ctx, ref, "2026-12-01T09:00:00Z", note="n", confirm=confirm)


async def _watcher_add(ctx: Any, ref: str, confirm: bool) -> Any:
    return await set_work_package_watcher(ctx, ref, 3, True, expect_display_id=ctx.expect_display_id, confirm=confirm)


async def _watcher_remove(ctx: Any, ref: str, confirm: bool) -> Any:
    return await set_work_package_watcher(ctx, ref, 3, False, expect_display_id=ctx.expect_display_id, confirm=confirm)


async def _time_entry(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_time_entry(ctx, "1", "PT1H", "2026-11-01", work_package_id=ref, confirm=confirm)


async def _time_entry_until(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_time_entry_until(
        ctx,
        "1",
        "2026-11-01T09:00:00Z",
        "2026-11-01T10:00:00Z",
        "2026-11-01",
        work_package_id=ref,
        confirm=confirm,
    )


async def _wiki_create(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_wiki_link(ctx, ref, "7", "internal", confirm=confirm)


async def _wiki_delete(ctx: Any, ref: str, confirm: bool) -> Any:
    return await delete_work_package_wiki_link(ctx, ref, 12, confirm=confirm)


async def _attachment(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_attachment(
        ctx, ref, ctx.attachment_file, expect_display_id=ctx.expect_display_id, confirm=confirm
    )


async def _agenda_create(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_meeting_agenda_item(ctx, 4, "Item", work_package_id=ref, confirm=confirm)


async def _agenda_update(ctx: Any, ref: str, confirm: bool) -> Any:
    return await update_meeting_agenda_item(ctx, 21, work_package_id=ref, confirm=confirm)


async def _outcome_create(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_meeting_outcome(ctx, 21, "decision", work_package_id=ref, confirm=confirm)


async def _outcome_update(ctx: Any, ref: str, confirm: bool) -> Any:
    return await update_meeting_outcome(ctx, 31, work_package_id=ref, confirm=confirm)


TOOLS: dict[str, Call] = {
    "create_work_package_reminder": _reminder,
    "set_work_package_watcher_add": _watcher_add,
    "set_work_package_watcher_remove": _watcher_remove,
    "create_time_entry": _time_entry,
    "create_time_entry_until": _time_entry_until,
    "create_work_package_wiki_link": _wiki_create,
    "delete_work_package_wiki_link": _wiki_delete,
    "create_work_package_attachment": _attachment,
    "create_meeting_agenda_item": _agenda_create,
    "update_meeting_agenda_item": _agenda_update,
    "create_meeting_outcome": _outcome_create,
    "update_meeting_outcome": _outcome_update,
}


class _Context(FakeContext):
    """A tool context that also names the file the attachment tool uploads and the expectation a guarded tool gets."""

    def __init__(self, client: OpenProjectClient, attachment_file: str, expect_display_id: str | None) -> None:
        super().__init__(client)
        self.attachment_file = attachment_file
        self.expect_display_id = expect_display_id


async def _run(
    call: Call,
    ref: str,
    tmp_path: Path,
    *,
    confirm: bool,
    expect: str | None = None,
    settings: Settings | None = None,
    server: _Server | None = None,
) -> tuple[Any, _Server]:
    upload = tmp_path / "note.txt"
    upload.write_text("hello")
    server = server or _Server()
    client = _client(server, settings or _settings(tmp_path))
    try:
        return await call(_Context(client, str(upload), expect), ref, confirm), server
    finally:
        await client.aclose()
