from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_query_metadata_api import (
    HttpxQueryMetadataApi,
    normalize_query_column,
    normalize_query_filter,
    normalize_query_filter_instance_schema,
    normalize_query_operator,
    normalize_query_sort_by,
)
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def test_normalize_query_filter_builds_web_url_from_self_link() -> None:
    filter_ = normalize_query_filter(
        {
            "name": "Assignee",
            "_links": {"self": {"href": "/api/v3/queries/filters/assignee", "title": "Assignee"}},
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert filter_.id == "assignee"
    assert filter_.name == "Assignee"
    assert filter_.url == f"{BASE_URL}/api/v3/queries/filters/assignee"


def test_normalize_query_column_extracts_type_and_relation_type() -> None:
    column = normalize_query_column(
        {
            "name": "Subject",
            "_type": "Query::Column::Property",
            "relationType": None,
            "_links": {"self": {"href": "/api/v3/queries/columns/subject"}},
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert column.id == "subject"
    assert column.type == "Query::Column::Property"


def test_normalize_query_operator_falls_back_to_self_link_title() -> None:
    operator = normalize_query_operator(
        {"_links": {"self": {"href": "/api/v3/queries/operators/%3D", "title": "is (OR)"}}},
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert operator.id == "="
    assert operator.name == "is (OR)"


def test_normalize_query_sort_by_falls_back_to_direction_link_title() -> None:
    # No requested_id passed -- id is derived from the self-link, which carries
    # OpenProject's real hyphen-joined form ("subject-asc"), not the client's
    # colon-separated public id ("subject:asc"). See get_sort_by for the
    # colon-form preservation via requested_id.
    sort_by = normalize_query_sort_by(
        {
            "name": "Subject asc",
            "_links": {
                "self": {"href": "/api/v3/queries/sort_bys/subject-asc"},
                "column": {"title": "Subject"},
                "direction": {"title": "ascending"},
            },
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert sort_by.id == "subject-asc"
    assert sort_by.column == "Subject"
    assert sort_by.direction == "ascending"


def test_normalize_query_filter_instance_schema_counts_dependencies() -> None:
    schema = normalize_query_filter_instance_schema(
        {
            "name": {"name": "Assignee schema"},
            "_links": {
                "self": {"href": "/api/v3/queries/filter_instance_schemas/assignee"},
                "filter": {"title": "Assignee"},
            },
            "_dependencies": [{"dependencies": {"=": {}, "!": {}}}],
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert schema.id == "assignee"
    assert schema.name == "Assignee schema"
    assert schema.filter == "Assignee"
    assert schema.operator_count == 2


@pytest.mark.asyncio
async def test_get_filter_percent_encodes_the_id_in_the_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/filters/subject_or_id"
        return httpx.Response(
            200,
            json={"_links": {"self": {"href": "/api/v3/queries/filters/subject_or_id"}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get_filter("subject_or_id")

    assert record.summary.id == "subject_or_id"


@pytest.mark.asyncio
async def test_get_sort_by_translates_colon_to_hyphen_and_preserves_requested_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # OpenProject's sort_bys route is "queries/sort_bys/:id-:direction"
        # (hyphen-joined, verified against OpenProject's own API
        # implementation), not a bare id segment like
        # filters/columns/operators. The client must request the hyphen form,
        # not the caller-facing colon form ("subject:asc" -> "subject-asc").
        assert request.url.raw_path == b"/api/v3/queries/sort_bys/subject-asc"
        return httpx.Response(
            200,
            json={"_links": {"self": {"href": "/api/v3/queries/sort_bys/subject-asc"}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get_sort_by("subject:asc")

    # The public id stays in the colon form the caller passed in, even though
    # the server's own self-link href uses the hyphen form.
    assert record.summary.id == "subject:asc"


@pytest.mark.asyncio
async def test_get_operator_percent_encodes_special_characters_in_the_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == b"/api/v3/queries/operators/%3D"
        return httpx.Response(
            200,
            json={"_links": {"self": {"href": "/api/v3/queries/operators/%3D", "title": "is (OR)"}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get_operator("=")

    assert record.summary.id == "="


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_without_project_id_requests_global_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/filter_instance_schemas"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "elements": [
                        {
                            "_links": {
                                "self": {"href": "/api/v3/queries/filter_instance_schemas/assignee"},
                                "filter": {"title": "Assignee"},
                            },
                            "_dependencies": [],
                        }
                    ]
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        records = await api.list_filter_instance_schemas(project_id=None)

    assert len(records) == 1
    assert records[0].summary.id == "assignee"


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_with_project_id_requests_project_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6/queries/filter_instance_schemas"
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        records = await api.list_filter_instance_schemas(project_id=6)

    assert records == []


@pytest.mark.asyncio
async def test_get_filter_instance_schema_percent_encodes_the_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/filter_instance_schemas/assignee"
        return httpx.Response(
            200,
            json={"_links": {"self": {"href": "/api/v3/queries/filter_instance_schemas/assignee"}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get_filter_instance_schema("assignee")

    assert record.summary.id == "assignee"


async def _no_request_client() -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    return _client(handler)


@pytest.mark.asyncio
async def test_get_filter_rejects_path_traversal_id() -> None:
    """Regression: filter_id was interpolated into
    the URL path with no validation -- a value like "../projects/42" quotes
    to itself unchanged (quote() never escapes ".") and httpx then normalizes
    ".." away when building the request, redirecting to an unrelated endpoint."""
    async with await _no_request_client() as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="filter_id"):
            await api.get_filter("../projects/42")


@pytest.mark.asyncio
async def test_get_column_rejects_path_traversal_id() -> None:
    async with await _no_request_client() as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="column_id"):
            await api.get_column("../projects/42")


@pytest.mark.asyncio
async def test_get_operator_rejects_path_traversal_id() -> None:
    async with await _no_request_client() as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="operator_id"):
            await api.get_operator("../projects/42")


@pytest.mark.asyncio
async def test_get_sort_by_rejects_path_traversal_id() -> None:
    async with await _no_request_client() as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="sort_by_id"):
            await api.get_sort_by("../projects/42")


@pytest.mark.asyncio
async def test_get_filter_instance_schema_rejects_path_traversal_id() -> None:
    async with await _no_request_client() as http_client:
        api = HttpxQueryMetadataApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="schema_id"):
            await api.get_filter_instance_schema("../projects/42")
