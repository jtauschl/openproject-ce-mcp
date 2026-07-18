from __future__ import annotations

import json
import re

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
    make_settings,
)

from openproject_ce_mcp.client import (
    OpenProjectClient,
)
from openproject_ce_mcp.config import Settings


@pytest.mark.asyncio
async def test_create_relation_and_delete_relation_work_when_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/55" and request.method == "GET":
            # The relation target's own project must be allowlist-checked too.
            return httpx.Response(
                200,
                json={"id": 55, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/relations" and request.method == "POST":
            body = json.loads(request.content)
            assert body["type"] == "blocks"
            assert body["_links"]["to"]["href"] == "/api/v3/work_packages/55"
            return httpx.Response(
                201,
                json={
                    "id": 650,
                    "type": "blocks",
                    "description": "Blocked until API rollout finishes",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42", "title": "Backend API"},
                        "to": {"href": "/api/v3/work_packages/55", "title": "App integration"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/650" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 650,
                    "type": "blocks",
                    "description": "Blocked until API rollout finishes",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42", "title": "Backend API"},
                        "to": {"href": "/api/v3/work_packages/55", "title": "App integration"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/650" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    created = await client.create_work_package_relation(
        work_package_id=42,
        related_to_work_package_id=55,
        relation_type="blocks",
        description="Blocked until API rollout finishes",
        confirm=True,
    )
    assert created.confirmed is True
    assert created.result is not None
    assert created.result.to_id == 55

    deleted = await client.delete_relation(relation_id=650, confirm=True)
    assert deleted.confirmed is True
    assert deleted.result is None

    await client.aclose()


@pytest.mark.asyncio
async def test_list_relations_returns_empty_under_empty_read_projects() -> None:
    # Regression guard: `allowlisted` must not be gated on
    # `self.settings.allowed_projects` truthiness — an empty (deny-all)
    # scope must still run the per-item check, not skip it and leak every
    # relation unfiltered.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "type": "relates",
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/1", "title": "A"},
                                    "to": {"href": "/api/v3/work_packages/2", "title": "B"},
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path in ("/api/v3/work_packages/1", "/api/v3/work_packages/2"):
            return httpx.Response(
                200,
                json={"id": 1, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_relations()

    assert result.count == 0
    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_list_relations_and_update_relation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 7,
                                "type": "blocks",
                                "description": None,
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                                    "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "type": "blocks",
                    "description": None,
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                        "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/1" and request.method == "GET":
            # update_relation resolves the relation's source work package to apply
            # the project write allowlist before patching.
            return httpx.Response(
                200,
                json={"id": 1, "subject": "Task A", "_links": {"project": {"title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/relations/7" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["description"] == "updated"
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "type": "blocks",
                    "description": "updated",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                        "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    relations = await client.list_relations()
    assert relations.count == 1
    assert relations.results[0].type == "blocks"

    preview = await client.update_relation(relation_id=7, description="updated", confirm=False)
    assert preview.requires_confirmation is True

    updated = await client.update_relation(relation_id=7, description="updated", confirm=True)
    assert updated.result is not None
    assert updated.result.type == "blocks"

    await client.aclose()


async def test_list_relations_filters_by_read_allowlist_both_sides() -> None:
    """list_relations drops a relation if EITHER linked WP is outside the allowlist.

    - rel 1: from allowed, to allowed          -> kept
    - rel 2: from secret                        -> dropped (source outside)
    - rel 3: from allowed, to secret            -> dropped (proves the to-side leak is closed)
    """
    # project of each work package
    wp_project = {10: "allowed", 11: "allowed", 20: "secret", 30: "allowed", 31: "secret"}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "type": "blocks",
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/10"},
                                    "to": {"href": "/api/v3/work_packages/11"},
                                },
                            },
                            {
                                "id": 2,
                                "type": "blocks",
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/20"},
                                    "to": {"href": "/api/v3/work_packages/10"},
                                },
                            },
                            {
                                "id": 3,
                                "type": "blocks",
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/30"},
                                    "to": {"href": "/api/v3/work_packages/31"},
                                },
                            },
                        ]
                    }
                },
                request=request,
            )
        m = re.match(r"^/api/v3/work_packages/(\d+)$", request.url.path)
        if m:
            wp = int(m.group(1))
            return httpx.Response(
                200,
                json={"id": wp, "_links": {"project": {"title": wp_project[wp]}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.list_relations()
    ids = {r.id for r in result.results}
    assert ids == {1}, f"expected only rel 1, got {ids}"
    await client.aclose()


async def test_relation_hides_wp_subject_when_wp_subject_hidden() -> None:
    """from_subject/to_subject honor the work_package subject hide list."""
    settings = _base_settings(hidden_fields={"work_package": ("subject",)})
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    rel = client.normalize_relation(
        {
            "id": 5,
            "type": "blocks",
            "_links": {
                "from": {"href": "/api/v3/work_packages/1", "title": "Secret A"},
                "to": {"href": "/api/v3/work_packages/2", "title": "Secret B"},
            },
        }
    )
    assert rel.from_subject is None
    assert rel.to_subject is None
    await client.aclose()


async def test_create_relation_resolves_semantic_target_to_numeric() -> None:
    """A semantic target ref is resolved to a numeric id before the HAL 'to' link."""
    posted = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/PROJ-20" and request.method == "GET":
            return httpx.Response(200, json={"id": 20, "_links": {"project": {"title": "Demo"}}}, request=request)
        if request.url.path == "/api/v3/work_packages/PROJ-10" and request.method == "GET":
            return httpx.Response(200, json={"id": 10, "_links": {"project": {"title": "Demo"}}}, request=request)
        if request.url.path == "/api/v3/work_packages/PROJ-10/relations" and request.method == "POST":
            posted.update(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "id": 99,
                    "type": "blocks",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/10"},
                        "to": {"href": "/api/v3/work_packages/20"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    await client.create_work_package_relation(
        work_package_id="PROJ-10",
        related_to_work_package_id="PROJ-20",
        relation_type="blocks",
        confirm=True,
    )
    # The 'to' link must carry the numeric id (20), not the semantic ref.
    assert posted["_links"]["to"]["href"].endswith("/work_packages/20")
    await client.aclose()
