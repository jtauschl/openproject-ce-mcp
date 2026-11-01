"""A work package write names the work package its reference resolved to, in `target`.

The same two requests are sent through every tool of this group with a recording server behind the
real client, resolver, adapter and service: the bare number `436` resolves to one work package, the
display reference `PROJ-436` to another. A preview that only echoed the reference could not tell the
two apart; `target` must name the record each reference actually resolved to.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from _client_test_helpers import _write_enabled_settings, make_settings
from _tools_test_helpers import FakeContext
from _work_package_target_helpers import (
    EXPECTED_R1,
    EXPECTED_R2,
    R1,
    R2,
    RECORDS_BY_REFERENCE,
    REFERENCES,
    form_response,
    project_response,
    work_package_record,
)

from openproject_ce_mcp.app.policies import hidden_fields
from openproject_ce_mcp.app.services._work_package_presentation import present_target
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.models import ResolvedWorkPackage
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError
from openproject_ce_mcp.tools import (
    add_work_package_comment,
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_subtask,
    create_work_package,
    delete_work_package,
    update_work_package,
)

_WP_PATH = re.compile(r"^/api/v3/work_packages/([^/]+)(/form|/activities)?$")
_PROJECT_FORM_PATH = re.compile(r"^/api/v3/projects/(\d+)/work_packages/form$")


class _Server:
    """Answers the requests of one write; every work package fetch is recorded by reference."""

    def __init__(self) -> None:
        self.work_package_gets: list[str] = []
        self.requests: list[str] = []
        self.records = RECORDS_BY_REFERENCE

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append(f"{method} {path}")
        wp = _WP_PATH.match(path)
        if wp is not None:
            return self._work_package(request, wp.group(1), wp.group(2))
        if path == "/api/v3/work_packages" and method == "POST":
            body = json.loads(request.content)
            created = {**work_package_record(777, "A-777", body["subject"], "New", 1, "Project A")}
            return httpx.Response(201, json=created, request=request)
        form = _PROJECT_FORM_PATH.match(path)
        if form is not None and method == "POST":
            return form_response(request)
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        if path == "/api/v3/projects/2":
            return project_response(request, 2, "proj", "Project B")
        if re.match(r"^/api/v3/projects/\d+/types$", path):
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 8, "name": "Task"}]}}, request=request)
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    def _work_package(self, request: httpx.Request, ref: str, suffix: str | None) -> httpx.Response:
        method = request.method
        if suffix == "/form" and method == "POST":
            return form_response(request)
        if suffix == "/activities" and method == "POST":
            activity = {"id": 77, "_type": "Activity", "version": 3, "comment": {"raw": "hello"}, "_links": {}}
            return httpx.Response(201, json=activity, request=request)
        if suffix is None and method == "GET":
            self.work_package_gets.append(ref)
            return httpx.Response(200, json=self.records[ref], request=request)
        if suffix is None and method == "PATCH":
            return httpx.Response(200, json=self.records[ref], request=request)
        if suffix is None and method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {method} {request.url}")


def _client(server: _Server, settings: Settings | None = None) -> OpenProjectClient:
    return OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))


async def _comment(ctx: Any, ref: str, confirm: bool) -> Any:
    return await add_work_package_comment(ctx, ref, "hello", confirm=confirm)


async def _update(ctx: Any, ref: str, confirm: bool) -> Any:
    return await update_work_package(ctx, ref, subject="Renamed", confirm=confirm)


async def _delete(ctx: Any, ref: str, confirm: bool) -> Any:
    return await delete_work_package(ctx, ref, confirm=confirm)


async def _subtask(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_subtask(ctx, ref, "Task", "Child", confirm=confirm)


async def _create_under_parent(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package(ctx, "demo", "Task", "Child", parent=ref, confirm=confirm)


async def _bulk_update(ctx: Any, ref: str, confirm: bool) -> Any:
    result = await bulk_update_work_packages(ctx, [{"work_package_id": ref, "subject": "Renamed"}], confirm=confirm)
    assert result.failed == 0, result.items[0].error
    return result.items[0].result


async def _bulk_create_under_parent(ctx: Any, ref: str, confirm: bool) -> Any:
    item = {"project": "demo", "type": "Task", "subject": "Child", "parent": ref}
    result = await bulk_create_work_packages(ctx, [item], confirm=confirm)
    assert result.failed == 0, result.items[0].error
    return result.items[0].result


Call = Callable[[Any, str, bool], Awaitable[Any]]

TOOLS: dict[str, Call] = {
    "add_work_package_comment": _comment,
    "update_work_package": _update,
    "delete_work_package": _delete,
    "bulk_update_work_packages": _bulk_update,
    "create_subtask": _subtask,
    "create_work_package": _create_under_parent,
    "bulk_create_work_packages": _bulk_create_under_parent,
}
tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
reference_param = pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])


async def _run(call: Call, ref: str, *, confirm: bool, settings: Settings | None = None) -> tuple[Any, _Server]:
    server = _Server()
    client = _client(server, settings)
    try:
        return await call(FakeContext(client), ref, confirm), server
    finally:
        await client.aclose()


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_preview_names_the_work_package_the_reference_resolved_to(call: Call, ref: str, expected: dict) -> None:
    result, server = await _run(call, ref, confirm=False)

    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_confirmed_result_names_the_same_work_package(call: Call, ref: str, expected: dict) -> None:
    result, server = await _run(call, ref, confirm=True)

    assert result.state == "confirmed"
    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@pytest.mark.asyncio
async def test_hidden_fields_are_absent_from_the_serialized_target(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("status", "display_id"))

    result, _ = await _run(call, "PROJ-436", confirm=False, settings=settings)

    assert _to_payload(result)["target"] == {
        "id": 9001,
        "project": "Project B",
        "subject": "Subject of the display reference",
    }


@pytest.mark.parametrize("call", [_comment, _delete], ids=["add_work_package_comment", "delete_work_package"])
@pytest.mark.asyncio
async def test_a_hidden_subject_is_absent_from_the_serialized_target(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("subject",))

    result, _ = await _run(call, "PROJ-436", confirm=False, settings=settings)

    assert _to_payload(result)["target"] == {
        "id": 9001,
        "display_id": "PROJ-436",
        "project": "Project B",
        "status": "In progress",
    }


@pytest.mark.asyncio
async def test_create_work_package_without_a_parent_has_no_target() -> None:
    async def create(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await create_work_package(ctx, "demo", "Task", "Child", confirm=confirm)

    result, server = await _run(create, "", confirm=False)

    assert result.target is None
    assert "target" not in _to_payload(result)
    assert server.work_package_gets == []


@pytest.mark.asyncio
async def test_bulk_create_item_without_a_parent_has_no_target() -> None:
    async def create(ctx: Any, _ref: str, confirm: bool) -> Any:
        item = {"project": "demo", "type": "Task", "subject": "Child"}
        return (await bulk_create_work_packages(ctx, [item], confirm=confirm)).items[0].result

    result, server = await _run(create, "", confirm=False)

    assert result.target is None
    assert "target" not in _to_payload(result)
    assert server.work_package_gets == []


@pytest.mark.asyncio
async def test_bulk_update_names_each_item_by_its_own_reference() -> None:
    server = _Server()
    client = _client(server)
    items = [
        {"work_package_id": "436", "subject": "One"},
        {"work_package_id": "PROJ-436", "subject": "Two"},
    ]

    result = await bulk_update_work_packages(FakeContext(client), items, confirm=False)
    await client.aclose()

    assert [_to_payload(item.result)["target"] for item in result.items] == [EXPECTED_R1, EXPECTED_R2]
    assert server.work_package_gets == ["436", "PROJ-436"]


@pytest.mark.asyncio
async def test_a_bulk_item_that_fails_has_no_target() -> None:
    server = _Server()
    settings = dataclasses.replace(_write_enabled_settings(), write_projects=("2",), read_projects=("*",))
    client = _client(server, settings)

    result = await bulk_update_work_packages(
        FakeContext(client), [{"work_package_id": "436", "subject": "One"}], confirm=False
    )
    await client.aclose()

    assert result.failed == 1
    assert result.items[0].result is None
    assert "disabled by OPENPROJECT_WRITE_PROJECTS" in (result.items[0].error or "")


@pytest.mark.asyncio
async def test_a_target_can_be_selected_in_a_bulk_result() -> None:
    server = _Server()
    client = _client(server)

    result = await bulk_update_work_packages(
        FakeContext(client), [{"work_package_id": "PROJ-436", "subject": "One"}], select=["target"], confirm=False
    )
    await client.aclose()

    assert _to_payload(result, select=frozenset({"target"}))["items"][0]["result"] == {"target": EXPECTED_R2}


class TestPresentTarget:
    """`present_target` is the one place that decides what of a fetched work package a result may show."""

    @staticmethod
    def _settings(**overrides: Any) -> Settings:
        return dataclasses.replace(make_settings(), **overrides)

    def test_a_fetched_work_package_is_fully_named(self) -> None:
        target = present_target(R2, settings=make_settings())

        assert dataclasses.asdict(target) == EXPECTED_R2

    def test_a_missing_title_is_none(self) -> None:
        payload = {"id": 5, "_links": {"project": {"href": "/api/v3/projects/1"}}}

        target = present_target(payload, settings=make_settings())

        assert dataclasses.asdict(target) == {
            "id": 5,
            "display_id": None,
            "project": None,
            "subject": None,
            "status": None,
        }

    def test_the_subject_is_trimmed_like_a_work_package_detail_and_not_delimited(self) -> None:
        payload = {**R1, "subject": "  Spaced \n out  " + "x" * 300}

        target = present_target(payload, settings=make_settings())

        assert target.subject is not None
        assert target.subject.startswith("Spaced out xxx")
        assert len(target.subject) == 255
        assert target.subject.endswith("…")
        assert "<user-content>" not in target.subject

    def test_a_hidden_field_is_stamped_for_the_serializer(self) -> None:
        settings = self._settings(hide_work_package_fields=("subject",))

        target = present_target(R1, settings=settings)

        assert isinstance(target, ResolvedWorkPackage)
        assert target._hidden_keys == frozenset({"subject"})  # type: ignore[attr-defined]
        assert hidden_fields.field_hidden("work_package", "subject", settings=settings)
        assert "subject" not in _to_payload(target)


OUT_OF_READ_SCOPE = dataclasses.replace(_write_enabled_settings(), read_projects=("1",), write_projects=("*",))


@pytest.mark.parametrize(
    "call",
    [_comment, _update, _delete, _subtask, _create_under_parent],
    ids=[
        "add_work_package_comment",
        "update_work_package",
        "delete_work_package",
        "create_subtask",
        "create_work_package",
    ],
)
@pytest.mark.asyncio
async def test_a_write_to_a_work_package_outside_the_read_scope_is_denied_before_any_target_exists(call: Call) -> None:
    with pytest.raises(ToolCallError, match=r"\[PROJECT_SCOPE_DENIED\].*OPENPROJECT_READ_PROJECTS"):
        await _run(call, "PROJ-436", confirm=False, settings=OUT_OF_READ_SCOPE)


@pytest.mark.asyncio
async def test_a_bulk_item_outside_the_read_scope_fails_without_a_result() -> None:
    server = _Server()
    client = _client(server, OUT_OF_READ_SCOPE)
    items = [{"work_package_id": "PROJ-436", "subject": "One"}]

    result = await bulk_update_work_packages(FakeContext(client), items, confirm=False)
    await client.aclose()

    assert result.items[0].result is None
    assert "OPENPROJECT_READ_PROJECTS" in (result.items[0].error or "")
