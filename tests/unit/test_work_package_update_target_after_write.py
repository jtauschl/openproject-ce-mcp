"""A confirmed update names the work package as written, a preview as it was read.

`target` of `update_work_package` and of each `bulk_update_work_packages` item is the work package the
reference resolved to. A preview shows it as read before the write. After the commit the status and the
subject may have changed, so the confirmed result names the record the write answered with. A static
server that answers the PATCH with the record it was read as cannot tell the two apart, so this server
keeps state: a PATCH changes the stored record.

The second half is the class guard: every call of a target builder by its name in `app/services` is listed with the
reason its `target` is right, so a new write path has to decide.
"""

from __future__ import annotations

import ast
import copy
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
from _work_package_target_helpers import R1, form_response, project_response

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tools import bulk_update_work_packages, update_work_package

_WP_PATH = re.compile(r"^/api/v3/work_packages/436(/form)?$")
_STATUSES = {"New": 1, "Closed": 12}

BEFORE = {
    "id": 436,
    "display_id": "A-1",
    "project": "Project A",
    "subject": "Subject of the bare number",
    "status": "New",
}


class _StatefulServer:
    """One work package whose stored record a PATCH changes."""

    def __init__(self) -> None:
        self.record = copy.deepcopy(R1)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        wp = _WP_PATH.match(path)
        if wp is not None and wp.group(1) == "/form" and method == "POST":
            return form_response(request)
        if wp is not None and wp.group(1) is None and method == "GET":
            return httpx.Response(200, json=self.record, request=request)
        if wp is not None and wp.group(1) is None and method == "PATCH":
            self._patch(json.loads(request.content))
            return httpx.Response(200, json=self.record, request=request)
        if path == "/api/v3/statuses" and method == "GET":
            elements = [{"id": i, "name": n, "isClosed": n == "Closed"} for n, i in _STATUSES.items()]
            return httpx.Response(200, json={"_embedded": {"elements": elements}}, request=request)
        status = re.match(r"^/api/v3/statuses/(\d+)$", path)
        if status is not None and method == "GET":
            name = next(n for n, i in _STATUSES.items() if i == int(status.group(1)))
            return httpx.Response(
                200, json={"id": _STATUSES[name], "name": name, "isClosed": name == "Closed"}, request=request
            )
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        raise AssertionError(f"Unexpected request: {method} {request.url}")

    def _patch(self, body: dict[str, Any]) -> None:
        if "subject" in body:
            self.record["subject"] = body["subject"]
        href = body.get("_links", {}).get("status", {}).get("href")
        if href is not None:
            number = int(href.rsplit("/", 1)[1])
            name = next(n for n, i in _STATUSES.items() if i == number)
            self.record["_links"]["status"] = {"href": href, "title": name}


def _client(server: _StatefulServer, settings: Settings | None = None) -> OpenProjectClient:
    return OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))


Call = Callable[..., Awaitable[Any]]


async def _update(ctx: Any, confirm: bool, **fields: Any) -> Any:
    return await update_work_package(ctx, "436", expect_display_id="A-1", confirm=confirm, **fields)


async def _bulk_update(ctx: Any, confirm: bool, **fields: Any) -> Any:
    item = {"work_package_id": "436", "expect_display_id": "A-1", **fields}
    result = await bulk_update_work_packages(ctx, [item], confirm=confirm)
    assert result.failed == 0, result.items[0].error
    return result.items[0].result


tool_param = pytest.mark.parametrize("call", [_update, _bulk_update], ids=["update_work_package", "bulk_update"])


async def _run(call: Call, *, confirm: bool, settings: Settings | None = None, **fields: Any) -> dict[str, Any]:
    client = _client(_StatefulServer(), settings)
    try:
        return _to_payload(await call(FakeContext(client), confirm, **fields))
    finally:
        await client.aclose()


@tool_param
@pytest.mark.asyncio
async def test_a_confirmed_update_names_the_status_and_subject_as_written(call: Call) -> None:
    payload = await _run(call, confirm=True, status="Closed", subject="Renamed")

    assert payload["state"] == "confirmed"
    assert payload["target"] == {**BEFORE, "status": "Closed", "subject": "Renamed"}
    assert payload["result"]["status"] == "Closed"


@tool_param
@pytest.mark.asyncio
async def test_a_preview_names_the_work_package_as_it_was_read(call: Call) -> None:
    payload = await _run(call, confirm=False, status="Closed", subject="Renamed")

    assert payload["state"] == "preview"
    assert payload["target"] == BEFORE


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_subject_stays_absent_from_the_refreshed_target(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("subject",))

    payload = await _run(call, confirm=True, settings=settings, status="Closed")

    assert payload["target"] == {"id": 436, "display_id": "A-1", "project": "Project A", "status": "Closed"}


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_status_stays_absent_from_the_refreshed_target(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("status",))

    payload = await _run(call, confirm=True, settings=settings, subject="Renamed")

    assert payload["target"] == {
        "id": 436,
        "display_id": "A-1",
        "project": "Project A",
        "subject": "Renamed",
    }


@pytest.mark.asyncio
async def test_the_lean_confirmed_bulk_item_shows_the_same_status_in_target_and_beside_it() -> None:
    client = _client(_StatefulServer())
    try:
        result = await bulk_update_work_packages(
            FakeContext(client),
            [{"work_package_id": "436", "expect_display_id": "A-1", "status": "Closed"}],
            confirm=True,
        )
    finally:
        await client.aclose()

    item = _to_payload(result)["items"][0]["result"]
    assert item["target"]["status"] == item["result"]["status"] == "Closed"


# --- the class guard ------------------------------------------------------------------------------------------------

SERVICES = Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp" / "app" / "services"
BUILDERS = frozenset(
    {
        "present_target",
        "_present_target",
        "write_target",
        "_write_target",
        "resolved_target",
        "check_target",
        "_resolved_parent",
    }
)

BEFORE_WRITE = "before-write is right"
REFRESHED = "refreshed after commit"
PLUMBING = "builder plumbing, not a write site"
_OTHER_RESOURCE = f"{BEFORE_WRITE}: the write changes another resource, not the status or subject of this work package"

# (module, function, assignment target, builder, first argument) -> (class, reason)
SITES: dict[tuple[str, str, str, str, str], tuple[str, str]] = {
    ("_work_package_target.py", "check_target", "target", "present_target", "payload"): (
        PLUMBING,
        "the helpers every write site calls to build its target",
    ),
    ("_work_package_target.py", "resolved_target", "target", "check_target", "canonical"): (
        PLUMBING,
        "the helpers every write site calls to build its target",
    ),
    ("_work_package_target.py", "write_target", "target", "check_target", "reference"): (
        PLUMBING,
        "the helpers every write site calls to build its target",
    ),
    ("attachment_service.py", "create", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("meeting_agenda_item_service.py", "create", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("meeting_agenda_item_service.py", "update", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("meeting_outcome_service.py", "create", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("meeting_outcome_service.py", "update", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    (
        "relation_service.py",
        "create",
        "(related_record, related_target)",
        "resolved_target",
        "related_to_work_package_id",
    ): (BEFORE_WRITE, _OTHER_RESOURCE),
    ("relation_service.py", "create", "target", "check_target", "source_ref"): (BEFORE_WRITE, _OTHER_RESOURCE),
    ("reminder_service.py", "create", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    (
        "reminder_service.py",
        "delete",
        "target",
        "present_target",
        "await self._ensure_reminder_project_write_allowed(reminder_id)",
    ): (BEFORE_WRITE, _OTHER_RESOURCE),
    ("time_entry_service.py", "create", "target", "check_target", "work_package_reference"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("watcher_service.py", "add", "(record, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("watcher_service.py", "remove", "(record, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("wiki_page_link_service.py", "create", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("wiki_page_link_service.py", "delete", "(resolved, target)", "resolved_target", "work_package_id"): (
        BEFORE_WRITE,
        _OTHER_RESOURCE,
    ),
    ("work_package_service.py", "_present_target", "<return>", "present_target", "payload"): (
        PLUMBING,
        "a wrapper every write site below calls",
    ),
    ("work_package_service.py", "_resolved_parent", "<return>", "resolved_target", "parent"): (
        PLUMBING,
        "a wrapper every write site below calls",
    ),
    ("work_package_service.py", "_write_target", "<return>", "write_target", "ref"): (
        PLUMBING,
        "a wrapper every write site below calls",
    ),
    ("work_package_service.py", "add_comment", "(_, target)", "_write_target", "ref"): (
        BEFORE_WRITE,
        "a comment changes neither the status nor the subject",
    ),
    ("work_package_service.py", "create", "(parent_record, target)", "_resolved_parent", "parent_work_package_id"): (
        BEFORE_WRITE,
        "names the parent, which the write does not change",
    ),
    (
        "work_package_service.py",
        "create_subtask",
        "(parent_record, target)",
        "_write_target",
        "work_package_ref(parent_work_package_id)",
    ): (BEFORE_WRITE, "names the parent, which the write does not change"),
    ("work_package_service.py", "delete", "(record, target)", "_write_target", "ref"): (
        BEFORE_WRITE,
        "a delete names the work package as it was when it was deleted",
    ),
    ("work_package_service.py", "update", "(current_record, target)", "_write_target", "ref"): (
        BEFORE_WRITE,
        "the preview, and every outcome without a commit, names the work package as it was read",
    ),
    (
        "work_package_service.py",
        "update",
        "(parent_record, parent_target)",
        "_resolved_parent",
        "_narrow_cleared(parent_work_package_id, sentinel=CLEAR_PARENT)",
    ): (BEFORE_WRITE, "names the new parent, which the write does not change"),
    ("work_package_service.py", "update", "target", "_present_target", "outcome.detail.payload"): (
        REFRESHED,
        "after a confirmed update the record the write answered with replaces the one read before it",
    ),
}


def _scan() -> list[tuple[str, str, str, str, str]]:
    """Every call of a target builder, one entry per call (a duplicate stays visible); an aliased import of a builder or a
    direct `ResolvedWorkPackage(...)` construction is a failure, because the scan would not see it."""
    found: list[tuple[str, str, str, str, str]] = []
    for path in sorted(SERVICES.rglob("*.py")):
        tree = ast.parse(path.read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert not (alias.name in BUILDERS and alias.asname), (
                        f"{path.name}: a builder is imported under an alias"
                    )
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            assert name != "ResolvedWorkPackage" or path.name == "_work_package_presentation.py", (
                f"{path.name}:{node.lineno}: a target is built by hand"
            )
            if name not in BUILDERS:
                continue
            up = parents[node]
            while isinstance(up, ast.Await):
                up = parents[up]
            if isinstance(up, ast.Assign):
                target = ast.unparse(up.targets[0])
            elif isinstance(up, ast.Return):
                target = "<return>"
            else:
                raise AssertionError(
                    f"{path.name}:{node.lineno}: a target builder is called in a position the guard cannot key"
                )
            function = up
            while function in parents and not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = parents[function]
            found.append((path.name, function.name, target, name, ast.unparse(node.args[0])))
    return found


def test_every_target_builder_call_is_classified_once_and_no_entry_is_stale() -> None:
    assert sorted(_scan()) == sorted(SITES)
    assert all(kind in {BEFORE_WRITE, REFRESHED, PLUMBING} and reason for kind, reason in SITES.values())
    assert [key for key, (kind, _) in SITES.items() if kind == REFRESHED] == [
        ("work_package_service.py", "update", "target", "_present_target", "outcome.detail.payload")
    ]
