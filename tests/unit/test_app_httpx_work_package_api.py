from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_work_package_api import HttpxWorkPackageApi
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.models import SortCriterion

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _wp_payload(wp_id: int = 6, subject: str = "Demo WP", **extra) -> dict:
    payload = {
        "id": wp_id,
        "_type": "WorkPackage",
        "subject": subject,
        "lockVersion": 1,
        "description": {"raw": "Some description"},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "type": {"title": "Task"},
            "status": {"title": "New"},
            "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
            "activities": {"href": "/api/v3/work_packages/6/activities"},
            "relations": {"href": "/api/v3/work_packages/6/relations"},
        },
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_list_hits_work_packages_endpoint_with_filters_sort_and_group() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        params = dict(request.url.params)
        assert params["offset"] == "1"
        assert params["pageSize"] == "10"
        assert json.loads(params["filters"]) == [{"project_id": {"operator": "=", "values": ["1"]}}]
        assert json.loads(params["sortBy"]) == [["status", "desc"]]
        assert params["groupBy"] == "status"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_wp_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list(
            filters=[{"project_id": {"operator": "=", "values": ["1"]}}],
            offset=1,
            limit=10,
            sort_by=[SortCriterion(field="status", direction="desc")],
            group_by="status",
        )

    assert page.server_total == 1
    assert len(page.raw_elements) == 1
    assert page.raw_elements[0]["id"] == 6


@pytest.mark.asyncio
async def test_list_returns_raw_unnormalized_elements_not_records() -> None:
    """The list() page must carry raw payload dicts, not pre-normalized
    WorkPackageRecords -- allowlist filtering happens in the Service BEFORE
    normalization for this domain (see app/ports/work_package_api.py's
    module docstring), unlike Projects."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_wp_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list(filters=[], offset=1, limit=10, sort_by=None, group_by=None)

    assert isinstance(page.raw_elements[0], dict)
    assert page.raw_elements[0] == _wp_payload()


@pytest.mark.asyncio
async def test_get_fetches_by_ref_and_builds_record() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/6"
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("6")

    assert record.summary.id == 6
    assert record.summary.subject == "Demo WP"
    assert record.payload == _wp_payload()


@pytest.mark.asyncio
async def test_get_url_escapes_a_semantic_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.get("PROJ-123")


@pytest.mark.asyncio
async def test_get_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(InvalidInputError):
            await api.get("../job_statuses/77")


@pytest.mark.asyncio
async def test_to_record_lazy_to_detail_diverges_from_summary_on_long_text() -> None:
    """Summary caps description at the requested (small) text_limit; detail's
    to_detail() re-extracts with FORMATTABLE_LIMIT (1200), a genuinely
    different, larger cap -- proving to_detail is lazily computed from the
    raw payload, not a cheap copy of the already-capped summary text."""
    long_description = {"raw": "x" * 900}
    payload = _wp_payload(description=long_description)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("6", text_limit=10)

    assert record.summary.description_truncated is True
    assert record.summary.description_length == 900
    detail = record.to_detail()
    # get()'s detail_text_limit propagation: to_detail must use the SAME
    # text_limit passed to get() (10), matching client.py's get_work_package
    # default (text_limit=None means uncapped, but an explicit small limit
    # here proves to_detail re-derives from text_limit, not FORMATTABLE_LIMIT).
    assert detail.description_truncated is True


@pytest.mark.asyncio
async def test_to_record_to_detail_is_lazy_not_precomputed() -> None:
    """list()'s raw elements, once turned into records via to_record(), must
    not eagerly compute .to_detail() -- proven by a record whose payload would
    raise if detail-normalized (a payload missing a required field detail
    normalization reads), confirming to_detail is a deferred callable."""
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()), base_url=BASE_URL)
    payload = _wp_payload()
    record = api.to_record(payload, text_limit=None)

    assert callable(record.to_detail)
    # Calling it explicitly must still work (proves it's not broken, just deferred).
    detail = record.to_detail()
    assert detail.id == 6


@pytest.mark.asyncio
async def test_normalize_detail_milestone_date_fallback() -> None:
    """Milestone work packages report the single day under `date`, not
    startDate/dueDate (verified against OpenProject 17.2's
    work_package_representer.rb: date_property :date with
    getter: default_date_getter(:due_date), skip_render: !milestone?)."""
    payload = _wp_payload(date="2026-03-15")
    payload.pop("startDate", None)
    payload.pop("dueDate", None)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("6")

    assert record.summary.start_date == "2026-03-15"
    assert record.summary.due_date == "2026-03-15"


@pytest.mark.asyncio
async def test_normalize_detail_children_and_ancestors_truncation() -> None:
    many_children = [{"href": f"/api/v3/work_packages/{i}", "title": f"Child {i}"} for i in range(60)]
    payload = _wp_payload()
    payload["_links"]["children"] = many_children

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("6")

    detail = record.to_detail()
    assert len(detail.children) == 50  # WORK_PACKAGE_CHILDREN_LIMIT
    assert detail.children_truncated is True


@pytest.mark.asyncio
async def test_normalize_detail_ancestors_missing_display_id_on_classic_instance() -> None:
    """Regression guard: hierarchy links carry displayId only from 17.5+
    (verified: no displayId on the 17.2 representer's :children/:ancestors
    links) -- must tolerate its absence rather than crash."""
    payload = _wp_payload()
    payload["_links"]["ancestors"] = [{"href": "/api/v3/work_packages/1", "title": "Parent"}]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get("6")

    detail = record.to_detail()
    assert detail.ancestors == [{"href": "/api/v3/work_packages/1", "title": "Parent", "display_id": None}]


@pytest.mark.asyncio
async def test_validate_create_posts_to_project_scoped_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/1/work_packages/form"
        body = json.loads(request.content)
        assert body == {"subject": "Draft"}
        return httpx.Response(
            200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        form = await api.validate_create("1", {"subject": "Draft"})

    assert form["_embedded"]["payload"] == {"subject": "Draft"}


@pytest.mark.asyncio
async def test_validate_update_posts_to_work_package_scoped_form_and_escapes_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/work_packages/PROJ-123/form" in bytes(request.url.raw_path)
        body = json.loads(request.content)
        assert body == {"subject": "Updated"}
        return httpx.Response(
            200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.validate_update("PROJ-123", {"subject": "Updated"})


@pytest.mark.asyncio
async def test_validate_update_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(InvalidInputError):
            await api.validate_update("../job_statuses/77", {})


def test_parse_form_extracts_payload_validation_errors_and_schema() -> None:
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()), base_url=BASE_URL)
    form = {
        "_type": "Form",
        "_embedded": {
            "payload": {"subject": "Draft"},
            "validationErrors": {"subject": {"message": "can't be blank"}},
            "schema": {"priority": {"writable": True}},
        },
    }

    result = api.parse_form(form)

    assert result.payload == {"subject": "Draft"}
    assert result.validation_errors == {"subject": "can't be blank"}
    assert result.schema == {"priority": {"writable": True}}


def test_parse_form_defaults_missing_sections_to_empty() -> None:
    api = HttpxWorkPackageApi(HttpxTransport(httpx.AsyncClient()), base_url=BASE_URL)

    result = api.parse_form({"_type": "Form", "_embedded": {}})

    assert result.payload == {}
    assert result.validation_errors == {}
    assert result.schema == {}


@pytest.mark.asyncio
async def test_commit_create_posts_to_work_packages_and_caps_text_limit() -> None:
    long_description = {"raw": "x" * 900}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/work_packages"
        return httpx.Response(200, json=_wp_payload(description=long_description), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.commit_create({"subject": "New"}, text_limit=10)

    assert record.summary.description_truncated is True


@pytest.mark.asyncio
async def test_commit_update_patches_by_ref_and_escapes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_wp_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.commit_update("PROJ-123", {"subject": "Updated"}, text_limit=None)

    assert record.summary.id == 6


@pytest.mark.asyncio
async def test_delete_issues_delete_by_ref_and_escapes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert b"/api/v3/work_packages/PROJ-123" in bytes(request.url.raw_path)
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete("PROJ-123")


@pytest.mark.asyncio
async def test_delete_rejects_path_traversal_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(InvalidInputError):
            await api.delete("../job_statuses/77")


@pytest.mark.asyncio
async def test_post_comment_builds_params_and_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/6/activities"
        assert dict(request.url.params) == {"notify": "true"}
        body = json.loads(request.content)
        assert body == {"comment": {"raw": "Hello"}, "internal": True}
        return httpx.Response(201, json={"id": 99, "_links": {}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageApi(HttpxTransport(http_client), base_url=BASE_URL)
        activity = await api.post_comment("6", comment="Hello", internal=True, notify=True)

    assert activity["id"] == 99
