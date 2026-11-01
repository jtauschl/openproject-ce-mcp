"""Every write that takes a caller-typed work package reference names the record it resolved to, in `target`.

Same method as `test_work_package_write_target.py`, for the writes outside the work package domain: the bare
number `436` and the display reference `PROJ-436` resolve to two different work packages behind the real
client, resolver, adapter and service, and each preview and confirmed result must name the record its own
reference resolved to. A tool that takes the work package as an option has no `target` without it.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from _client_test_helpers import _write_enabled_settings
from _tools_test_helpers import FakeContext
from _work_package_target_helpers import (
    EXPECTED_R1,
    EXPECTED_R2,
    RECORDS_BY_REFERENCE,
    REFERENCES,
    form_response,
    project_response,
)

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError
from openproject_ce_mcp.tools import (
    create_time_entry,
    create_time_entry_until,
    create_work_package_attachment,
    create_work_package_relation,
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

    def __init__(self) -> None:
        self.work_package_gets: list[str] = []
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append(f"{method} {path}")
        wp = _WORK_PACKAGE.match(path)
        if wp is not None and method == "GET":
            self.work_package_gets.append(wp.group(1))
            return _json(request, RECORDS_BY_REFERENCE[wp.group(1)])
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
    return await set_work_package_watcher(ctx, ref, 3, True, confirm=confirm)


async def _watcher_remove(ctx: Any, ref: str, confirm: bool) -> Any:
    return await set_work_package_watcher(ctx, ref, 3, False, confirm=confirm)


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
    return await create_work_package_attachment(ctx, ref, ctx.attachment_file, confirm=confirm)


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
tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
reference_param = pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])


class _Context(FakeContext):
    """A tool context that also names the file the attachment tool uploads."""

    def __init__(self, client: OpenProjectClient, attachment_file: str) -> None:
        super().__init__(client)
        self.attachment_file = attachment_file


async def _run(
    call: Call, ref: str, tmp_path: Path, *, confirm: bool, settings: Settings | None = None
) -> tuple[Any, _Server]:
    upload = tmp_path / "note.txt"
    upload.write_text("hello")
    server = _Server()
    client = _client(server, settings or _settings(tmp_path))
    try:
        return await call(_Context(client, str(upload)), ref, confirm), server
    finally:
        await client.aclose()


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_preview_names_the_work_package_the_reference_resolved_to(
    call: Call, ref: str, expected: dict, tmp_path: Path
) -> None:
    result, server = await _run(call, ref, tmp_path, confirm=False)

    assert result.state == "preview"
    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_confirmed_result_names_the_same_work_package(
    call: Call, ref: str, expected: dict, tmp_path: Path
) -> None:
    result, server = await _run(call, ref, tmp_path, confirm=True)

    assert result.state == "confirmed"
    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@pytest.mark.asyncio
async def test_hidden_fields_are_absent_from_the_serialized_target(call: Call, tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("status", "display_id", "subject"))

    result, _ = await _run(call, "PROJ-436", tmp_path, confirm=False, settings=settings)

    assert _to_payload(result)["target"] == {"id": 9001, "project": "Project B"}


async def _time_entry_in_project(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry(ctx, "1", "PT1H", "2026-11-01", project="1", confirm=confirm)


async def _time_entry_until_in_project(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry_until(
        ctx, "1", "2026-11-01T09:00:00Z", "2026-11-01T10:00:00Z", "2026-11-01", project="1", confirm=confirm
    )


async def _agenda_create_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_agenda_item(ctx, 4, "Item", confirm=confirm)


async def _agenda_update_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_agenda_item(ctx, 21, title="Renamed", confirm=confirm)


async def _outcome_create_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_outcome(ctx, 21, "decision", notes="n", confirm=confirm)


async def _outcome_update_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_outcome(ctx, 31, notes="n", confirm=confirm)


WITHOUT_WORK_PACKAGE: dict[str, Call] = {
    "create_time_entry": _time_entry_in_project,
    "create_time_entry_until": _time_entry_until_in_project,
    "create_meeting_agenda_item": _agenda_create_unlinked,
    "update_meeting_agenda_item": _agenda_update_unlinked,
    "create_meeting_outcome": _outcome_create_unlinked,
    "update_meeting_outcome": _outcome_update_unlinked,
}


@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])
@pytest.mark.parametrize("call", list(WITHOUT_WORK_PACKAGE.values()), ids=list(WITHOUT_WORK_PACKAGE))
@pytest.mark.asyncio
async def test_a_write_without_a_work_package_has_no_target(call: Call, confirm: bool, tmp_path: Path) -> None:
    result, server = await _run(call, "", tmp_path, confirm=confirm)

    assert result.target is None
    assert "target" not in _to_payload(result)
    assert server.work_package_gets == []


RELATION_ENDS = [
    ("436", "PROJ-436", EXPECTED_R1, EXPECTED_R2),
    ("PROJ-436", "436", EXPECTED_R2, EXPECTED_R1),
]
relation_ends_param = pytest.mark.parametrize(
    ("source", "related", "expected_target", "expected_related_target"),
    RELATION_ENDS,
    ids=["bare-number-source", "display-reference-source"],
)


@relation_ends_param
@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])
@pytest.mark.asyncio
async def test_a_relation_names_both_ends(
    source: str, related: str, expected_target: dict, expected_related_target: dict, confirm: bool, tmp_path: Path
) -> None:
    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await create_work_package_relation(ctx, source, related, "relates", confirm=confirm)

    result, server = await _run(relate, "", tmp_path, confirm=confirm)

    payload = _to_payload(result)
    assert payload["target"] == expected_target
    assert payload["related_target"] == expected_related_target
    assert sorted(server.work_package_gets) == sorted([source, related])


@pytest.mark.asyncio
async def test_a_hidden_field_is_absent_from_both_ends_of_a_relation(tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("subject",))

    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await create_work_package_relation(ctx, "436", "PROJ-436", "relates", confirm=confirm)

    result, _ = await _run(relate, "", tmp_path, confirm=False, settings=settings)

    payload = _to_payload(result)
    assert "subject" not in payload["target"]
    assert "subject" not in payload["related_target"]
    assert payload["target"]["display_id"] == "A-1"
    assert payload["related_target"]["display_id"] == "PROJ-436"


OUT_OF_READ_SCOPE = dataclasses.replace(_write_enabled_settings(), read_projects=("1",), write_projects=("*",))


async def _relate_outside_scope(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_relation(ctx, "436", ref, "relates", confirm=confirm)


async def _relate_source_outside_scope(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_relation(ctx, ref, "436", "relates", confirm=confirm)


@pytest.mark.parametrize(
    "call",
    [*TOOLS.values(), _relate_outside_scope, _relate_source_outside_scope],
    ids=[*TOOLS, "create_work_package_relation_related", "create_work_package_relation_source"],
)
@pytest.mark.asyncio
async def test_a_write_to_a_work_package_outside_the_read_scope_is_denied_before_any_target_exists(
    call: Call, tmp_path: Path
) -> None:
    settings = dataclasses.replace(
        OUT_OF_READ_SCOPE, enable_meeting_write=True, attachment_root=str(tmp_path), read_projects=("1",)
    )

    with pytest.raises(ToolCallError, match=r"\[PROJECT_SCOPE_DENIED\].*OPENPROJECT_READ_PROJECTS"):
        await _run(call, "PROJ-436", tmp_path, confirm=False, settings=settings)
