from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_project_api import HttpxProjectApi
from openproject_ce_mcp.app.errors import OpenProjectServerError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _project_payload(project_id: int = 6, name: str = "Demo Project", identifier: str = "demo") -> dict:
    return {
        "id": project_id,
        "_type": "Project",
        "name": name,
        "identifier": identifier,
        "active": True,
        "public": False,
        "description": {"raw": "Some description"},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "status": {"title": "on track"},
            "parent": {"href": "/api/v3/projects/1", "title": "Parent"},
            "update": {"href": "/api/v3/projects/6"},
            "delete": {"href": "/api/v3/projects/6"},
            "ancestors": [
                {"href": "/api/v3/projects/1", "title": "Root", "displayId": None},
            ],
        },
    }


@pytest.mark.asyncio
async def test_list_hits_projects_endpoint_with_filters() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        assert dict(request.url.params)["offset"] == "1"
        assert dict(request.url.params)["pageSize"] == "10"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_project_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list(server_offset=1, server_page_size=10, search=None)

    assert page.server_total == 1
    assert page.exhausted is True
    record = page.records[0]
    assert record.summary.id == 6
    assert record.payload == _project_payload()


@pytest.mark.asyncio
async def test_get_fetches_by_ref_and_builds_detail_with_ancestors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/demo"
        return httpx.Response(200, json=_project_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("demo")

    assert record.summary.identifier == "demo"
    detail = record.to_detail()
    assert detail.ancestors == [{"href": "/api/v3/projects/1", "title": "Root", "display_id": None}]
    assert detail.ancestors_truncated is False


@pytest.mark.asyncio
async def test_get_url_escapes_the_project_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/projects/demo%2Fslash" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_project_payload(identifier="demo/slash"), request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("demo/slash")

    assert record.summary.identifier == "demo/slash"


@pytest.mark.asyncio
async def test_list_applies_the_requested_text_limit_to_records() -> None:
    long_description = {"raw": "x" * 50}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _project_payload()
        payload["description"] = long_description
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [payload]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list(server_offset=1, server_page_size=10, search=None, text_limit=10)

    record = page.records[0]
    assert record.summary.description_truncated is True
    assert record.summary.description_length == 50


@pytest.mark.asyncio
async def test_get_applies_the_requested_text_limit() -> None:
    long_description = {"raw": "x" * 50}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _project_payload()
        payload["description"] = long_description
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("demo", text_limit=10)

    assert record.summary.description_truncated is True
    assert record.to_detail().description_truncated is True


@pytest.mark.asyncio
async def test_create_form_posts_to_form_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/form"
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        form = await api.create_form({"name": "Demo"})

    assert form.payload == {"name": "Demo"}
    assert form.validation_errors == {}


@pytest.mark.asyncio
async def test_commit_create_posts_and_returns_normalized_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        assert request.method == "POST"
        return httpx.Response(201, json=_project_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_create({"name": "Demo"})

    assert detail.id == 6


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_normalized_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_project_payload(name="Renamed"), request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(6, {"name": "Renamed"})

    assert detail.name == "Renamed"


@pytest.mark.asyncio
async def test_delete_issues_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete(6)  # must not raise


@pytest.mark.asyncio
async def test_set_favorite_uses_request_raw_for_empty_204_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/workspaces/6/favorite"
        assert request.method == "POST"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.set_favorite(6, favorite=True)  # must not raise


@pytest.mark.asyncio
async def test_set_favorite_removal_issues_delete() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/workspaces/6/favorite"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.set_favorite(6, favorite=False)  # must not raise


@pytest.mark.asyncio
async def test_list_available_parent_projects_accepts_relative_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/available_parent_projects"
        return httpx.Response(200, json={"_embedded": {"elements": [_project_payload(project_id=1)]}}, request=request)

    schema = {"parent": {"_links": {}}}
    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        refs = await api.list_available_parent_projects(6, schema=schema)

    assert refs[0].id == 1


@pytest.mark.asyncio
async def test_list_available_parent_projects_accepts_absolute_same_origin_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/available_parent_projects"
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    schema = {
        "parent": {"_links": {"allowedValues": {"href": f"{BASE_URL}/api/v3/projects/available_parent_projects"}}}
    }
    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        refs = await api.list_available_parent_projects(6, schema=schema)

    assert refs == []


@pytest.mark.asyncio
async def test_list_available_parent_projects_rejects_foreign_origin_link_before_any_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request to foreign origin: {request.url}")

    schema = {"parent": {"_links": {"allowedValues": {"href": "https://evil.example.com/api/v3/projects/foo"}}}}
    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(OpenProjectServerError, match="unexpected link host"):
            await api.list_available_parent_projects(6, schema=schema)


@pytest.mark.asyncio
async def test_commit_copy_relative_location_becomes_absolute_web_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/6/copy":
            return httpx.Response(302, headers={"Location": "/api/v3/projects/6/copy/status/42"}, request=request)
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        job_status_url = await api.commit_copy(6, {"name": "Copy"})

    assert job_status_url == f"{BASE_URL}/api/v3/projects/6/copy/status/42"


@pytest.mark.asyncio
async def test_commit_copy_foreign_origin_location_returns_none() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/6/copy":
            return httpx.Response(302, headers={"Location": "https://evil.example.com/status/42"}, request=request)
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        job_status_url = await api.commit_copy(6, {"name": "Copy"})

    assert job_status_url is None


@pytest.mark.asyncio
async def test_copy_form_posts_to_copy_form_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6/copy/form"
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.copy_form(6, {"name": "Copy"})

    assert result.payload == {"name": "Copy"}
    assert result.validation_errors == {}


@pytest.mark.asyncio
async def test_get_configuration_fetches_project_configuration_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6/configuration"
        return httpx.Response(200, json={"hostName": "op.example.com"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        config = await api.get_configuration(6)

    assert config["hostName"] == "op.example.com"


@pytest.mark.asyncio
async def test_list_phase_definitions_filters_by_type() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/project_phase_definitions"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "elements": [
                        {"id": 1, "_type": "ProjectPhaseDefinition", "name": "Initiation"},
                        {"id": 2, "_type": "Other", "name": "Ignored"},
                    ]
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        results = await api.list_phase_definitions()

    assert len(results) == 1
    assert results[0].id == 1


@pytest.mark.asyncio
async def test_get_phase_fetches_by_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/project_phases/3"
        return httpx.Response(
            200,
            json={
                "id": 3,
                "name": "Build",
                "startDate": "2026-01-01",
                "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxProjectApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get_phase(3)

    assert record.phase.id == 3
    assert record.phase.name == "Build"
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo"}
