from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_extended_metadata_api import (
    HttpxExtendedMetadataApi,
    normalize_help_text,
    normalize_non_working_day,
    normalize_working_day,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def test_normalize_help_text_extracts_raw_text_from_nested_dict() -> None:
    summary = normalize_help_text(
        {
            "id": 5,
            "attributeName": "description",
            "attributeCaption": "Description",
            "helpText": {"format": "markdown", "raw": "Describe the work."},
        }
    )
    assert summary.id == 5
    assert summary.attribute_name == "description"
    assert summary.help_text == "Describe the work."


def test_normalize_help_text_falls_back_to_attribute_key() -> None:
    summary = normalize_help_text({"id": 6, "attribute": "subject", "helpText": "Plain string help"})
    assert summary.attribute_name == "subject"
    assert summary.help_text == "Plain string help"


def test_normalize_working_day_maps_fields() -> None:
    day = normalize_working_day({"name": "Monday", "dayOfWeek": 1, "working": True})
    assert day.name == "Monday"
    assert day.day_of_week == 1
    assert day.working is True


def test_normalize_non_working_day_maps_fields() -> None:
    day = normalize_non_working_day({"date": "2026-12-25", "name": "Christmas Day"})
    assert day.date == "2026-12-25"
    assert day.name == "Christmas Day"


@pytest.mark.asyncio
async def test_render_text_posts_raw_text_plain_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/render/markdown"
        assert request.headers["content-type"] == "text/plain"
        assert request.content.decode("utf-8") == "**Hello**"
        return httpx.Response(200, json={"html": "<p><strong>Hello</strong></p>"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        record = await api.render_text(text="**Hello**", format="markdown")

    assert record.summary.html == "<p><strong>Hello</strong></p>"
    assert record.summary.raw == "**Hello**"
    assert record.summary.format == "markdown"


@pytest.mark.asyncio
async def test_render_text_plain_format_uses_plain_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/render/plain"
        return httpx.Response(200, json={"html": "Hello"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        await api.render_text(text="Hello", format="plain")


@pytest.mark.asyncio
async def test_list_help_texts_sends_get_and_builds_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/help_texts"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": 5, "attribute": "description", "helpText": None}]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        records = await api.list_help_texts()

    assert len(records) == 1
    assert records[0].summary.id == 5


@pytest.mark.asyncio
async def test_get_help_text_sends_get_single_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/help_texts/5"
        return httpx.Response(200, json={"id": 5, "attributeName": "description"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        record = await api.get_help_text(5)

    assert record.summary.id == 5


@pytest.mark.asyncio
async def test_list_working_days_sends_days_week_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/days/week"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"name": "Monday", "dayOfWeek": 1, "working": True}]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        records = await api.list_working_days()

    assert len(records) == 1
    assert records[0].summary.name == "Monday"


@pytest.mark.asyncio
async def test_list_non_working_days_without_year_sends_no_filter_params() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/days/non_working"
        assert "filters" not in request.url.params
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        records = await api.list_non_working_days(year=None)

    assert records == []


@pytest.mark.asyncio
async def test_list_non_working_days_with_year_builds_date_range_filter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/days/non_working"
        filters = json.loads(request.url.params["filters"])
        assert filters == [{"date": {"operator": "<>d", "values": ["2026-01-01", "2026-12-31"]}}]
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"date": "2026-12-25", "name": "Christmas Day"}]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        records = await api.list_non_working_days(year=2026)

    assert len(records) == 1
    assert records[0].summary.name == "Christmas Day"


@pytest.mark.asyncio
async def test_get_custom_option_sends_get_single_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/custom_options/42"
        return httpx.Response(200, json={"id": 42, "value": "High Priority"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxExtendedMetadataApi(HttpxTransport(http_client))
        record = await api.get_custom_option(42)

    assert record.summary.id == 42
    assert record.summary.value == "High Priority"
