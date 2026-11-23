"""The label of a record the server sent without a name never contains the record's id.

Every place that builds such a label (`unnamed(kind)`, `app/adapters/_text.py`) has a row here: a payload with a
7-digit id and no name-like member, and the assertion is the label itself. A label that equals the constant cannot
carry an id, so a site that goes back to an `f"X {id}"` fails here wherever the read-result scan cannot see it (the
fake's project ids stay small there). The table is keyed by call site, `(file, function, kind)`, and is compared with
the sites found in the source, so a new site without a row, or a row whose site is gone, fails.
"""

from __future__ import annotations

import ast
import dataclasses
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import nameless_sentinel_serve

import openproject_ce_mcp
from openproject_ce_mcp.app.adapters import (
    httpx_attachment_api,
    httpx_backlog_bucket_api,
    httpx_board_api,
    httpx_category_api,
    httpx_document_api,
    httpx_file_link_api,
    httpx_news_api,
    httpx_notification_api,
    httpx_post_api,
    httpx_principal_api,
    httpx_project_api,
    httpx_role_api,
    httpx_sprint_api,
    httpx_status_priority_type_api,
    httpx_storage_api,
    httpx_time_entry_api,
    httpx_version_api,
    httpx_view_api,
    httpx_watcher_api,
    httpx_wiki_page_api,
    httpx_work_package_api,
)
from openproject_ce_mcp.app.adapters._text import NamelessKind, unnamed
from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
from openproject_ce_mcp.app.ports.scoped_reference import VisibleReferences
from openproject_ce_mcp.app.resource_href import ResourceLinks
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.client import OpenProjectClient

SRC = Path(openproject_ce_mcp.__file__).parent
ID = 7_000_123
BASE_URL = "https://op.example.com"


def _work_package_summary(payload: dict[str, Any]) -> Any:
    return httpx_work_package_api.normalize_work_package_summary(
        payload,
        text_limit=None,
        visible=VisibleReferences.everything(),
        resource_links=ResourceLinks(BASE_URL),
    )


# (file, function, kind) -> (the call on a payload that has the id only, the member that holds the label).
NORMALIZERS: dict[tuple[str, str, NamelessKind], tuple[Callable[[dict[str, Any]], Any], str]] = {
    ("app/adapters/httpx_attachment_api.py", "normalize_attachment", "attachment"): (
        lambda payload: httpx_attachment_api.normalize_attachment(payload, base_url=BASE_URL, origin=BASE_URL),
        "title",
    ),
    ("app/adapters/httpx_backlog_bucket_api.py", "normalize_backlog_bucket", "backlog bucket"): (
        httpx_backlog_bucket_api.normalize_backlog_bucket,
        "name",
    ),
    ("app/adapters/httpx_board_api.py", "normalize_board", "board"): (httpx_board_api.normalize_board, "name"),
    ("app/adapters/httpx_category_api.py", "normalize_category", "category"): (
        lambda payload: httpx_category_api.normalize_category(payload, project_id=None, project_name=None),
        "name",
    ),
    ("app/adapters/httpx_document_api.py", "normalize_document", "document"): (
        httpx_document_api.normalize_document,
        "title",
    ),
    ("app/adapters/httpx_file_link_api.py", "normalize_file_link", "file link"): (
        httpx_file_link_api.normalize_file_link,
        "title",
    ),
    ("app/adapters/httpx_news_api.py", "normalize_news", "news"): (httpx_news_api.normalize_news, "title"),
    ("app/adapters/httpx_notification_api.py", "normalize_notification", "notification"): (
        httpx_notification_api.normalize_notification,
        "subject",
    ),
    ("app/adapters/httpx_post_api.py", "normalize_post", "post"): (httpx_post_api.normalize_post, "subject"),
    ("app/adapters/httpx_principal_api.py", "normalize_principal", "principal"): (
        httpx_principal_api.normalize_principal,
        "name",
    ),
    ("app/adapters/httpx_project_api.py", "normalize_project", "project"): (
        httpx_project_api.normalize_project,
        "name",
    ),
    ("app/adapters/httpx_project_api.py", "normalize_project_phase_definition", "project phase definition"): (
        httpx_project_api.normalize_project_phase_definition,
        "name",
    ),
    ("app/adapters/httpx_project_api.py", "normalize_project_phase", "project phase"): (
        httpx_project_api.normalize_project_phase,
        "name",
    ),
    ("app/adapters/httpx_role_api.py", "normalize_role", "role"): (httpx_role_api.normalize_role, "name"),
    ("app/adapters/httpx_sprint_api.py", "normalize_sprint", "sprint"): (httpx_sprint_api.normalize_sprint, "name"),
    ("app/adapters/httpx_status_priority_type_api.py", "normalize_status", "status"): (
        httpx_status_priority_type_api.normalize_status,
        "name",
    ),
    ("app/adapters/httpx_status_priority_type_api.py", "normalize_priority", "priority"): (
        httpx_status_priority_type_api.normalize_priority,
        "name",
    ),
    ("app/adapters/httpx_status_priority_type_api.py", "normalize_type", "type"): (
        httpx_status_priority_type_api.normalize_type,
        "name",
    ),
    ("app/adapters/httpx_storage_api.py", "normalize_storage", "storage"): (
        httpx_storage_api.normalize_storage,
        "name",
    ),
    ("app/adapters/httpx_time_entry_api.py", "normalize_time_entry_activity_raw", "time entry activity"): (
        httpx_time_entry_api.normalize_time_entry_activity_raw,
        "name",
    ),
    ("app/adapters/httpx_version_api.py", "normalize_version", "version"): (
        httpx_version_api.normalize_version,
        "name",
    ),
    ("app/adapters/httpx_view_api.py", "normalize_view", "view"): (httpx_view_api.normalize_view, "name"),
    ("app/adapters/httpx_watcher_api.py", "normalize_watcher", "user"): (httpx_watcher_api.normalize_watcher, "name"),
    ("app/adapters/httpx_wiki_page_api.py", "normalize_wiki_page", "wiki page"): (
        httpx_wiki_page_api.normalize_wiki_page,
        "title",
    ),
    ("app/adapters/httpx_work_package_api.py", "normalize_work_package_summary", "work package"): (
        _work_package_summary,
        "subject",
    ),
}
# Sites that sit inside a method and are driven through the real method on a fake transport: site -> its test.
INLINE: dict[tuple[str, str, NamelessKind], str] = {
    (
        "app/adapters/httpx_project_api.py",
        "list_available_parent_projects",
        "project",
    ): "test_a_nameless_parent_candidate_is_labelled_without_its_id_and_keeps_no_name_for_the_scope",
    (
        "client.py",
        "get_project_work_package_context",
        "project",
    ): "test_the_project_context_of_a_nameless_project_is_labelled_without_its_id",
}


def _label_sites() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted([*(SRC / "app").rglob("*.py"), *SRC.glob("*.py")]):
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "unnamed":
                    found.add((str(path.relative_to(SRC)), function.name, ast.literal_eval(node.args[0])))
    return found


def _strings(node: Any) -> list[str]:
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return [text for field in dataclasses.fields(node) for text in _strings(getattr(node, field.name))]
    if isinstance(node, (list, tuple)):
        return [text for entry in node for text in _strings(entry)]
    if isinstance(node, dict):
        return [text for entry in node.values() for text in _strings(entry)]
    return [node] if isinstance(node, str) else []


def test_every_site_that_builds_a_label_has_a_row_and_every_row_has_a_site() -> None:
    assert _label_sites() == set(NORMALIZERS) | set(INLINE)


def test_every_inline_site_names_a_test_that_exists() -> None:
    assert all(callable(globals().get(test)) for test in INLINE.values())


def test_every_kind_has_a_site() -> None:
    assert {kind for _, _, kind in _label_sites()} == set(typing.get_args(NamelessKind))


@pytest.mark.parametrize(("site", "row"), sorted(NORMALIZERS.items()), ids=[f"{k[1]}" for k in sorted(NORMALIZERS)])
def test_a_nameless_record_is_shown_under_the_constant_label(
    site: tuple[str, str, NamelessKind], row: tuple[Callable[[dict[str, Any]], Any], str]
) -> None:
    call, member = row
    record = call({"id": ID})
    label = getattr(record, member)

    assert label == unnamed(site[2])
    assert [text for text in _strings(record) if str(ID) in text] == []


@pytest.mark.parametrize("kind", typing.get_args(NamelessKind))
def test_a_label_names_its_kind_and_nothing_else(kind: str) -> None:
    assert unnamed(kind) == f"Unnamed {kind}"  # type: ignore[arg-type]


async def test_a_nameless_parent_candidate_is_labelled_without_its_id_and_keeps_no_name_for_the_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"_embedded": {"elements": [{"id": ID, "identifier": "p"}]}, "total": 1}, request=request
        )

    async with httpx.AsyncClient(base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler)) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client, redact_server_text=False), base_url=BASE_URL)
        [candidate] = await api.list_available_parent_projects(6, schema={"parent": {"_links": {}}})

    assert candidate.ref.name == "Unnamed project"
    assert candidate.scope_name is None


async def test_the_project_context_of_a_nameless_project_is_labelled_without_its_id() -> None:
    client = OpenProjectClient(
        _base_settings(read_projects=("*",)),
        transport=httpx.MockTransport(serving_projects(nameless_sentinel_serve, [(1, "demo", "Demo")])),
    )
    await client.initialize()
    try:
        context = await client.get_project_work_package_context(project="demo")
    finally:
        await client.aclose()

    assert context.project_name == "Unnamed project"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({"name": "Dev"}, "Dev"), ({}, ""), ({"name": None}, ""), ({"name": 5}, "")],
    ids=["a name", "no name", "a JSON null", "not a text"],
)
def test_the_raw_name_of_a_resolver_is_never_a_label_or_the_text_none(payload: dict[str, Any], expected: str) -> None:
    from openproject_ce_mcp.app.adapters._text import lookup_name

    assert lookup_name(payload) == expected
