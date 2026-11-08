"""Project attributes through the project adapter: every community format, the scoped link titles, the
schema options and the list query. The shared normalization has its own tests with the work package adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
from openproject_ce_mcp.app.errors import OpenProjectServerError
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference, VisibleReferences
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.models import SortCriterion

BASE_URL = "https://op.example.com"
SECRET_VERSION = ScopedReference("version", 7)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _api(http_client: httpx.AsyncClient) -> HttpxProjectApi:
    return HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)


def _payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": 6,
        "_type": "Project",
        "name": "Demo",
        "identifier": "demo",
        "active": True,
        "description": {"raw": "d"},
        "_links": {"self": {"href": "/api/v3/projects/6"}},
        # every community format: string, text, link, int, float, date, bool
        "customField1": "plain",
        "customField2": {"format": "markdown", "raw": "a long text", "html": "<p>a long text</p>"},
        "customField3": "https://example.com",
        "customField4": 7,
        "customField5": 1.5,
        "customField6": "2026-11-06",
        "customField7": True,
    }
    payload["_links"].update(
        {
            "customField8": {"href": "/api/v3/custom_options/3", "title": "High"},
            "customField9": [
                {"href": "/api/v3/custom_options/4", "title": "Red"},
                {"href": "/api/v3/custom_options/5", "title": "Blue"},
            ],
            "customField10": {"href": "/api/v3/users/5", "title": "Jane Doe"},
            "customField11": {"href": "/api/v3/versions/8", "title": "Own release"},
        }
    )
    payload.update(extra)
    return payload


async def _get(payload: dict[str, Any]):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        return await _api(http_client).get("demo", text_limit=None)


@pytest.mark.asyncio
async def test_every_community_format_is_read_into_the_detail_by_its_raw_key() -> None:
    record = await _get(_payload())

    detail = record.scoped_detail(visible=VisibleReferences.everything())

    assert detail.custom_fields == {
        "customField1": "<user-content>plain</user-content>",
        "customField2": "<user-content>a long text</user-content>",
        "customField3": "<user-content>https://example.com</user-content>",
        "customField4": 7,
        "customField5": 1.5,
        "customField6": "<user-content>2026-11-06</user-content>",
        "customField7": True,
        "customField8": "High",
        "customField9": ["Red", "Blue"],
        "customField10": "Jane Doe",
        "customField11": "Own release",
    }
    assert detail.custom_fields_truncated is False


@pytest.mark.asyncio
async def test_the_summary_and_the_detail_show_the_same_values() -> None:
    record = await _get(_payload())
    everything = VisibleReferences.everything()

    assert (
        record.scoped_summary(visible=everything).custom_fields
        == record.scoped_detail(visible=everything).custom_fields
    )


@pytest.mark.asyncio
async def test_the_identity_summary_of_a_record_carries_no_value_whose_title_was_not_judged() -> None:
    record = await _get(_payload())

    assert record.summary.custom_fields is None
    assert record.summary.custom_comments is None


@pytest.mark.asyncio
async def test_a_version_the_result_may_not_name_reads_null_and_other_values_stay() -> None:
    payload = _payload()
    payload["_links"]["customField11"] = {"href": "/api/v3/versions/7", "title": "Secret release"}
    record = await _get(payload)

    assert record.references == {"customField11": frozenset({SECRET_VERSION})}
    detail = record.scoped_detail(visible=VisibleReferences.only([]))

    assert detail.custom_fields is not None
    assert detail.custom_fields["customField11"] is None
    assert "Secret release" not in json.dumps(detail.custom_fields)
    assert detail.custom_fields["customField8"] == "High"


@pytest.mark.asyncio
async def test_a_multi_value_version_field_keeps_only_the_visible_versions() -> None:
    payload = _payload()
    payload["_links"]["customField12"] = [
        {"href": "/api/v3/versions/7", "title": "Secret release"},
        {"href": "/api/v3/versions/8", "title": "Own release"},
    ]
    record = await _get(payload)

    detail = record.scoped_detail(visible=VisibleReferences.only([ScopedReference("version", 8)]))

    assert detail.custom_fields is not None
    assert detail.custom_fields["customField12"] == ["Own release"]


@pytest.mark.asyncio
async def test_comments_come_from_17_2_and_are_read_by_the_raw_key() -> None:
    record = await _get(_payload(customComment1="why"))

    detail = record.scoped_detail(visible=VisibleReferences.everything())

    assert detail.custom_comments == {"customComment1": "<user-content>why</user-content>"}


@pytest.mark.asyncio
async def test_a_payload_before_17_2_has_no_comments() -> None:
    record = await _get(_payload())

    assert record.scoped_detail(visible=VisibleReferences.everything()).custom_comments is None


@pytest.mark.asyncio
async def test_a_project_without_attributes_has_none() -> None:
    record = await _get({"id": 6, "_type": "Project", "name": "Demo", "identifier": "demo", "_links": {}})

    detail = record.scoped_detail(visible=VisibleReferences.everything())

    assert detail.custom_fields is None
    assert record.references == {}


@pytest.mark.asyncio
async def test_a_list_row_carries_the_values_of_the_page_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_payload()]}}, request=request)

    async with _client(handler) as http_client:
        page = await _api(http_client).list(server_offset=1, server_page_size=10, search=None)

    row = page.records[0].scoped_summary(visible=VisibleReferences.everything())
    assert row.custom_fields is not None
    assert row.custom_fields["customField8"] == "High"


@pytest.mark.asyncio
async def test_a_write_result_is_a_record_with_the_values_of_the_committed_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(customField1="after"), request=request)

    async with _client(handler) as http_client:
        record = await _api(http_client).commit_update(6, {"customField1": "after"})

    detail = record.scoped_detail(visible=VisibleReferences.everything())
    assert detail.custom_fields is not None
    assert detail.custom_fields["customField1"] == "<user-content>after</user-content>"


@pytest.mark.asyncio
async def test_the_list_sends_custom_field_filters_and_the_sort_order_to_the_server() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        await _api(http_client).list(
            server_offset=1,
            server_page_size=10,
            search="demo",
            custom_field_filters=[{"cf_12": {"operator": "=", "values": ["x"]}}],
            sort_by=[SortCriterion(field="cf_12", direction="desc"), SortCriterion(field="name", direction="asc")],
        )

    assert json.loads(seen["filters"]) == [
        {"name_and_identifier": {"operator": "~", "values": ["demo"]}},
        {"cf_12": {"operator": "=", "values": ["x"]}},
    ]
    assert json.loads(seen["sortBy"]) == [["cf_12", "desc"], ["name", "asc"]]


@pytest.mark.asyncio
async def test_the_list_sends_no_sort_order_when_none_is_asked_for() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        await _api(http_client).list(server_offset=1, server_page_size=10, search=None)

    assert "sortBy" not in seen


def _form(schema: dict[str, Any]) -> dict[str, Any]:
    return {"_embedded": {"schema": schema, "payload": {}, "validationErrors": {}}}


@pytest.mark.asyncio
async def test_a_user_field_reads_its_linked_members_so_a_name_can_be_resolved() -> None:
    requested: list[str] = []
    schema = {
        "customField10": {
            "name": "Owner",
            "type": "User",
            "location": "_links",
            "_links": {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}},
        },
        "parent": {"_links": {"allowedValues": {"href": "/api/v3/projects/available_parent_projects?of=6"}}},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.raw_path.decode())
        if request.method == "POST":
            return httpx.Response(200, json=_form(schema), request=request)
        return httpx.Response(
            200,
            json={
                "total": 1,
                "_embedded": {"elements": [{"name": "Jane Doe", "_links": {"self": {"href": "/api/v3/users/5"}}}]},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        result = await _api(http_client).get_schema(project_id=6, draft_payload={}, custom_field_options=True)

    assert result.schema["customField10"]["_embedded"]["allowedValues"][0]["name"] == "Jane Doe"
    assert "_embedded" not in result.schema["parent"]
    assert requested == ["/api/v3/projects/6/form", "/api/v3/principals?filters=%5B%5D&offset=1&pageSize=100"]


@pytest.mark.asyncio
async def test_a_member_past_the_first_page_of_a_user_field_is_among_the_options() -> None:
    schema = {
        "customField10": {
            "name": "Owner",
            "type": "User",
            "location": "_links",
            "_links": {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}},
        }
    }
    members = [{"name": f"Member {n}", "_links": {"self": {"href": f"/api/v3/users/{n}"}}} for n in range(1, 251)]
    pages: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_form(schema), request=request)
        query = dict(request.url.params)
        pages.append(query)
        offset, size = int(query["offset"]), int(query["pageSize"])
        elements = members[(offset - 1) * size : offset * size]
        return httpx.Response(200, json={"total": len(members), "_embedded": {"elements": elements}}, request=request)

    async with _client(handler) as http_client:
        result = await _api(http_client).get_schema(project_id=6, draft_payload={}, custom_field_options=True)

    options = result.schema["customField10"]["_embedded"]["allowedValues"]
    assert [option["name"] for option in options] == [f"Member {n}" for n in range(1, 251)]
    assert [page["offset"] for page in pages] == ["1", "2", "3"]
    assert {page["filters"] for page in pages} == {"[]"}


@pytest.mark.asyncio
async def test_a_linked_option_collection_without_a_total_is_an_error_not_a_short_list() -> None:
    schema = {
        "customField10": {
            "type": "User",
            "location": "_links",
            "_links": {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}},
        }
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_form(schema), request=request)
        return httpx.Response(200, json={"_embedded": {"elements": [{"name": "Jane"}]}}, request=request)

    async with _client(handler) as http_client:
        with pytest.raises(OpenProjectServerError, match="without a total"):
            await _api(http_client).get_schema(project_id=6, draft_payload={}, custom_field_options=True)


@pytest.mark.asyncio
async def test_user_attributes_that_link_the_same_members_read_them_once() -> None:
    link = {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}}
    schema = {
        "customField10": {"name": "Owner", "type": "User", "location": "_links", "_links": link},
        "customField11": {"name": "Reviewer", "type": "User", "location": "_links", "_links": link},
    }
    reads: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_form(schema), request=request)
        reads.append(request.url.path)
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [{"name": "Jane"}]}}, request=request)

    async with _client(handler) as http_client:
        result = await _api(http_client).get_schema(project_id=6, draft_payload={}, custom_field_options=True)

    assert len(reads) == 1
    assert result.schema["customField10"]["_embedded"]["allowedValues"] == [{"name": "Jane"}]
    assert result.schema["customField11"]["_embedded"]["allowedValues"] == [{"name": "Jane"}]


@pytest.mark.asyncio
async def test_the_members_behind_a_user_field_are_read_only_when_a_value_is_written() -> None:
    schema = {
        "customField10": {
            "name": "Owner",
            "type": "User",
            "location": "_links",
            "_links": {"allowedValues": {"href": "/api/v3/principals?filters=%5B%5D"}},
        }
    }
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.raw_path.decode()}")
        return httpx.Response(200, json=_form(schema), request=request)

    async with _client(handler) as http_client:
        result = await _api(http_client).get_schema(project_id=6, draft_payload={})

    assert calls == ["POST /api/v3/projects/6/form"]
    assert "_embedded" not in result.schema["customField10"]


@pytest.mark.asyncio
async def test_embedded_options_are_not_read_again() -> None:
    schema = {
        "customField8": {
            "type": "CustomOption",
            "location": "_links",
            "_embedded": {
                "allowedValues": [{"name": "High", "_links": {"self": {"href": "/api/v3/custom_options/3"}}}]
            },
            "_links": {"allowedValues": {"href": "/api/v3/custom_fields/8/custom_options"}},
        }
    }
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json=_form(schema), request=request)

    async with _client(handler) as http_client:
        await _api(http_client).get_schema(project_id=None, draft_payload={}, custom_field_options=True)

    assert calls == ["POST"]


@pytest.mark.asyncio
async def test_a_linked_option_list_on_another_host_is_never_contacted() -> None:
    schema = {"customField10": {"type": "User", "_links": {"allowedValues": {"href": "https://evil.example/api/v3/x"}}}}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "op.example.com"
        return httpx.Response(200, json=_form(schema), request=request)

    async with _client(handler) as http_client:
        with pytest.raises(OpenProjectServerError, match="unexpected link host"):
            await _api(http_client).get_schema(project_id=6, draft_payload={}, custom_field_options=True)


@pytest.mark.asyncio
async def test_the_copy_schema_is_the_schema_of_the_copy_form() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_form({"customField1": {"name": "Effort", "type": "String"}}), request=request)

    async with _client(handler) as http_client:
        result = await _api(http_client).get_copy_schema(6, draft_payload={"name": "Copy"})

    assert paths == ["/api/v3/projects/6/copy/form"]
    assert [field.key for field in result.fields] == ["customField1"]
