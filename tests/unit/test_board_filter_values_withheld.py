"""A board filter value names a record only where every user sees the name alike; everywhere else it is withheld.

A saved board is a `queries` record whose record-valued filters render `_links.values`, a list of `{href, title}`.
The title of a version, a project or a work package can name a record in a project outside the read scope, so the
adapter withholds it; the reference the server sent (`/api/v3/versions/4242`) must not stand in for the name either.
The decision is made per collection of the link, never per filter key: an instance-wide collection keeps its title,
every other one reads `<kind> (name withheld)`, a value that is no link reads `record (name withheld)`.

Stated boundary: the board adapter and `link_titles` only (the census does not scan every adapter); a href bound to a
variable first, or read through `getattr`, is not found by the census. The previews and `list` never reach the
normalizer (a preview has no detail, `list` returns summaries), so they are asserted as such, not claimed as covered.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings

import openproject_ce_mcp
from openproject_ce_mcp.app import link_titles
from openproject_ce_mcp.app.adapters import _text
from openproject_ce_mcp.app.adapters.httpx_board_api import HttpxBoardApi
from openproject_ce_mcp.app.services.board_service import BoardService
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.presentation import _to_payload

SRC = Path(openproject_ce_mcp.__file__).parent
BASE_URL = "https://op.example.com"
FOREIGN_ID = 4242
SECRET = "Secret Name"

# The pin of the set that keeps its title: every other collection is withheld.
KEPT_COLLECTIONS = [
    "statuses",
    "types",
    "priorities",
    "roles",
    "users",
    "groups",
    "principals",
    "project_phase_definitions",
]
KEPT_UNNAMED_LABEL = {
    "statuses": "Unnamed status",
    "types": "Unnamed type",
    "priorities": "Unnamed priority",
    "roles": "Unnamed role",
    "users": "Unnamed user",
    "groups": "Unnamed principal",
    "principals": "Unnamed principal",
    "project_phase_definitions": "Unnamed project phase definition",
}
WITHHELD_LABEL = {
    "versions": "version (name withheld)",
    "projects": "project (name withheld)",
    "work_packages": "work package (name withheld)",
    "categories": "category (name withheld)",
    "custom_options": "custom option (name withheld)",
    "budgets": "budget (name withheld)",
    "placeholder_users": "record (name withheld)",
    "sprints": "record (name withheld)",
}


def _filter(key: str, values: list[Any]) -> dict[str, Any]:
    return {
        "_links": {
            "filter": {"href": f"/api/v3/queries/filters/{key}", "title": key.title()},
            "operator": {"href": "/api/v3/queries/operators/=", "title": "is"},
            "values": values,
        }
    }


def _link(href: str, title: str | None = SECRET) -> dict[str, Any]:
    return {"href": href, **({"title": title} if title is not None else {})}


def _board_payload(filters: list[dict[str, Any]], board_id: int = 1) -> dict[str, Any]:
    return {
        "id": board_id,
        "name": "Board",
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "update": {"href": f"/api/v3/queries/{board_id}/form"},
            "delete": {"href": f"/api/v3/queries/{board_id}"},
        },
        "public": True,
        "filters": filters,
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


async def _filter_values(values: list[Any], *, key: str = "version") -> list[str]:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_board_payload([_filter(key, values)]), request=request)

    async with _client(handler) as http_client:
        record = await HttpxBoardApi(HttpxTransport(http_client, redact_server_text=False)).get(1)
    [board_filter] = record.detail.filters
    return board_filter.values


@pytest.mark.asyncio
@pytest.mark.parametrize("collection", KEPT_COLLECTIONS)
async def test_an_instance_wide_collection_keeps_the_title_of_its_value(collection: str) -> None:
    values = await _filter_values([_link(f"/api/v3/{collection}/{FOREIGN_ID}", "Shared Name")], key="assignee")

    assert values == ["Shared Name"]


@pytest.mark.asyncio
@pytest.mark.parametrize("collection", KEPT_COLLECTIONS)
async def test_an_instance_wide_link_without_a_title_reads_its_unnamed_label(collection: str) -> None:
    values = await _filter_values([_link(f"/api/v3/{collection}/{FOREIGN_ID}", None)], key="assignee")

    assert values == [KEPT_UNNAMED_LABEL[collection]]


@pytest.mark.asyncio
@pytest.mark.parametrize(("collection", "label"), sorted(WITHHELD_LABEL.items()))
async def test_every_other_collection_withholds_the_name_and_the_reference(collection: str, label: str) -> None:
    values = await _filter_values([_link(f"/api/v3/{collection}/{FOREIGN_ID}")])

    assert values == [label]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["status", "assignee", "version", "parent", "customField5"])
async def test_the_decision_does_not_depend_on_the_filter_key(key: str) -> None:
    values = await _filter_values(
        [_link(f"/api/v3/versions/{FOREIGN_ID}"), _link(f"/api/v3/statuses/{FOREIGN_ID}", "Open")], key=key
    )

    assert values == ["version (name withheld)", "Open"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "href",
    [
        "/op/api/v3/versions/4242",
        f"{BASE_URL}/api/v3/versions/4242",
        "/api/v3/versions/4242/extra",
        "/api/v3/versions/4242?timestamps=PT0S",
        "/api/v3/versions/4242#frag",
        "not a link",
        "",
    ],
)
async def test_a_reference_of_another_shape_never_names_a_record(href: str) -> None:
    values = await _filter_values([_link(href)])

    assert len(values) == 1
    assert SECRET not in values[0] and str(FOREIGN_ID) not in values[0] and "/api/" not in values[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("href", "label"),
    [
        ("/op/api/v3/versions/4242", "version (name withheld)"),
        ("/op/api/v3/users/me", "Secret Name"),
        ("/api/v3/users/me", "Secret Name"),
        (f"{BASE_URL}/api/v3/users/me", "Secret Name"),
        ("/api/v3/users/4242/", "record (name withheld)"),
        ("/api/v3/versions/4242/api/v3/users/1", "record (name withheld)"),
        ("/api/v3/users/4242/extra", "record (name withheld)"),
        ("/api/v3/users/4242?x=1", "record (name withheld)"),
        ("/api/v3/users/4242#frag", "record (name withheld)"),
    ],
)
async def test_the_collection_is_read_from_the_end_of_the_whole_reference(href: str, label: str) -> None:
    assert await _filter_values([_link(href)]) == [label]


@pytest.mark.asyncio
async def test_no_other_member_of_a_value_names_it() -> None:
    value = {
        "href": f"/api/v3/versions/{FOREIGN_ID}",
        "name": SECRET,
        "title": SECRET,
        "_links": {"self": {"href": f"/api/v3/versions/{FOREIGN_ID}", "title": SECRET}},
    }

    assert await _filter_values([value]) == ["version (name withheld)"]


@pytest.mark.asyncio
async def test_a_value_that_is_no_link_is_withheld_and_the_count_stays() -> None:
    values = await _filter_values(["plain text", {"name": SECRET}, None, _link(f"/api/v3/versions/{FOREIGN_ID}")])

    assert values == ["record (name withheld)"] * 3 + ["version (name withheld)"]


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["   ", None, ""])
async def test_a_kept_link_whose_title_is_no_usable_text_reads_its_unnamed_label(title: Any) -> None:
    value = {"href": f"/api/v3/users/{FOREIGN_ID}", "title": title}

    assert await _filter_values([value], key="assignee") == ["Unnamed user"]


@pytest.mark.asyncio
async def test_values_that_are_no_list_give_no_values() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        board = _board_payload([_filter("version", [])])
        board["filters"][0]["_links"]["values"] = {"href": "/api/v3/versions/4242"}
        return httpx.Response(200, json=board, request=request)

    async with _client(handler) as http_client:
        record = await HttpxBoardApi(HttpxTransport(http_client, redact_server_text=False)).get(1)

    assert record.detail.filters[0].values == []


# --- the same through the service paths over the real adapter ---------------------------------------------------------


def _board_with_foreign_filters(board_id: int = 1) -> dict[str, Any]:
    return _board_payload(
        [
            _filter("version", [_link(f"/api/v3/versions/{FOREIGN_ID}")]),
            _filter("project", [_link(f"/api/v3/projects/{FOREIGN_ID}")]),
            _filter("parent", [_link(f"/api/v3/work_packages/{FOREIGN_ID}")]),
            _filter("status", [_link("/api/v3/statuses/1", "Open")]),
        ],
        board_id,
    )


def _service(handler) -> tuple[BoardService, httpx.AsyncClient]:
    http_client = _client(handler)

    async def resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        return {"id": 6, "identifier": "demo", "name": "Demo", "_links": {}}

    service = BoardService(
        api=HttpxBoardApi(HttpxTransport(http_client, redact_server_text=False)),
        settings=dataclasses.replace(make_settings(), read_projects=("demo",), write_projects=("demo",)),
        project_id_to_identifier={6: "demo"},
        resolve_project_ref=resolve_project_ref,
        api_prefix="/api/v3/",
        origin=BASE_URL,
    )
    return service, http_client


def _router(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    if method == "DELETE":
        return httpx.Response(204, request=request)
    if method == "POST" and path.endswith("/form"):
        return httpx.Response(
            200,
            json={"_embedded": {"payload": json.loads(request.content or b"{}"), "validationErrors": {}}},
            request=request,
        )
    if method == "POST":
        return httpx.Response(201, json=_board_with_foreign_filters(42), request=request)
    if path == "/api/v3/queries":
        return httpx.Response(200, json={"_embedded": {"elements": [_board_with_foreign_filters()]}}, request=request)
    return httpx.Response(200, json=_board_with_foreign_filters(), request=request)


def _shown(detail: Any) -> str:
    return json.dumps(_to_payload(detail, elide_none=True), ensure_ascii=False)


def _assert_withheld(shown: str) -> None:
    assert str(FOREIGN_ID) not in shown and SECRET not in shown
    assert "version (name withheld)" in shown and "Open" in shown


@pytest.mark.asyncio
async def test_get_board_withholds_the_reference_of_a_foreign_value() -> None:
    service, http_client = _service(_router)
    async with http_client:
        _assert_withheld(_shown(await service.get(1)))


@pytest.mark.asyncio
async def test_a_confirmed_create_and_update_return_withheld_values() -> None:
    service, http_client = _service(_router)
    async with http_client:
        created = await service.create(name="Board", project="demo", confirm=True)
        updated = await service.update(board_id=1, name="Renamed", confirm=True)

    _assert_withheld(_shown(created.result))
    _assert_withheld(_shown(updated.result))


@pytest.mark.asyncio
async def test_a_confirmed_delete_returns_withheld_values() -> None:
    service, http_client = _service(_router)
    async with http_client:
        deleted = await service.delete(board_id=1, confirm=True)

    _assert_withheld(_shown(deleted.result))


@pytest.mark.asyncio
async def test_a_preview_and_list_do_not_reach_the_normalizer_of_filter_values() -> None:
    service, http_client = _service(_router)
    async with http_client:
        preview = await service.update(board_id=1, name="Renamed", confirm=False)
        listed = await service.list()

    assert preview.result is None
    assert len(listed.results) == 1
    assert "filters" not in {field.name for field in dataclasses.fields(listed.results[0])}


# --- the tables and the sites ---------------------------------------------------------------------------------------


def test_the_label_table_of_untitled_kept_links_covers_exactly_the_kept_collections() -> None:
    from openproject_ce_mcp.app.adapters import httpx_board_api

    assert set(httpx_board_api._UNNAMED_KEPT_LINK) == set(link_titles.KEPT_TITLE_COLLECTIONS)


@pytest.mark.asyncio
async def test_a_write_preview_still_echoes_the_stored_references_of_the_filters() -> None:
    """The known limit of every write preview (tracked on its own): the form echoes what the board stores."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/form"):
            stored = _board_with_foreign_filters()
            return httpx.Response(200, json={"_embedded": {"payload": stored, "validationErrors": {}}}, request=request)
        return _router(request)

    service, http_client = _service(handler)
    async with http_client:
        preview = await service.update(board_id=1, name="Renamed", confirm=False)

    assert f"/api/v3/versions/{FOREIGN_ID}" in json.dumps(preview.payload)


def test_the_set_of_collections_that_keep_their_title_is_the_pinned_one() -> None:
    assert sorted(link_titles.KEPT_TITLE_COLLECTIONS) == sorted(KEPT_COLLECTIONS)


def test_the_label_of_a_withheld_name_never_carries_the_reference() -> None:
    for collection in [*WITHHELD_LABEL, "unknown_collection", None]:
        label = _text.withheld_label_for(collection)

        assert not any(character.isdigit() for character in label), label


def test_every_kind_the_withheld_table_names_is_a_known_kind() -> None:
    import typing

    assert set(_text.WITHHELD_KIND_BY_COLLECTION.values()) <= set(typing.get_args(_text.WithheldKind))


def _call_sites(names: set[str]) -> list[tuple[str, str, str]]:
    """(file, enclosing function or `<module>`, called name) of every call of one of `names` under `app/`."""
    found: list[tuple[str, str, str]] = []

    def visit(node: ast.AST, path: str, function: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names:
            found.append((path, function, node.func.id))
        for child in ast.iter_child_nodes(node):
            visit(child, path, function)

    for path in sorted((SRC / "app").rglob("*.py")):
        visit(ast.parse(path.read_text()), str(path.relative_to(SRC)), "<module>")
    return found


def test_a_withheld_label_is_built_in_one_place_and_asked_for_in_one_place() -> None:
    assert _call_sites({"withheld", "withheld_label_for"}) == [
        ("app/adapters/_text.py", "withheld_label_for", "withheld"),
        ("app/adapters/httpx_board_api.py", "_filter_value_label", "withheld_label_for"),
    ]


def test_no_module_imports_without_titles_it_is_used_inside_link_titles_only() -> None:
    importers = sorted(
        str(path.relative_to(SRC))
        for path in (SRC / "app").rglob("*.py")
        if any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "without_titles" for alias in node.names)
            for node in ast.walk(ast.parse(path.read_text()))
        )
    )

    assert importers == []


# Every `href` read of the board adapter that flows into a text, with the reason it is no name of a record.
BOARD_ADAPTER_HREF_READS = {
    (
        "_normalize_board_filter",
        4,
    ): "the filter key and the operator are read as slugs of the filter and operator links",
    ("_filter_value_label", 1): "the collection of the link decides the label; the reference is never shown",
    ("_normalize_query_link_label", 2): "a column, group-by or sort label is the slug of a query property, no record",
    ("normalize_board", 2): "the project id member of the project link; the name is its title",
}


def test_every_href_read_of_the_board_adapter_is_a_row_with_a_reason_and_a_count() -> None:
    """A read is the constant `"href"` or a use of `_slug_from_href` / `_id_from_href`; the count per function is
    pinned, so a second read inside a listed function fails too. A href bound to a variable first, or read through
    `getattr`, is not found."""
    tree = ast.parse((SRC / "app/adapters/httpx_board_api.py").read_text())
    reads: dict[str, int] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Constant) and node.value == "href") or (
                isinstance(node, ast.Name) and node.id in {"_slug_from_href", "_id_from_href"}
            ):
                reads[function.name] = reads.get(function.name, 0) + 1

    assert set(reads.items()) == set(BOARD_ADAPTER_HREF_READS)
