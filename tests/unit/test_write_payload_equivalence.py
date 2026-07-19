"""OPM-209 (Phase D): preview-vs-confirmed payload semantic equivalence.

Generic at the mechanism level, representative at the edges -- not one test per
tool. `client.py:_finalize_write` (the shared preview/confirm state machine
behind 7 form-based write finalizers: project, work_package, board, grid,
membership, user) and `app/services/version_service.py`'s separate,
deliberately duplicated copy of the same shape both read the *same* `payload`
local for both the preview return and the confirmed HTTP call -- so proving the
property once per mechanism proves it for every one of their callers by
construction. The two hand-rolled outliers below (`create_work_package_relation`,
`delete_work_package`) don't route through either shared helper and are proven
individually.

Allowed deviations named in the OPM-209 ticket: lockVersion, form-validation
results, server-determined hrefs, unavoidable time-dependent values. This file
also documents a fifth, found while writing these tests: preview-only
echo/context fields a hand-rolled write adds for caller readability but never
sends over the wire (`create_work_package_relation`'s `to_work_package_id`).
"""

from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.client import OpenProjectClient


@pytest.mark.asyncio
async def test_finalize_write_sends_the_same_payload_it_previewed() -> None:
    """Proof at the client.py `_finalize_write` mechanism level, exercised via
    one real caller (create_project) -- all 7 of that helper's current callers
    inherit this guarantee by construction, since preview and the confirmed
    POST/PATCH both read the identical `payload` local (client.py:6707-6785).
    """
    sent_body: dict | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {"name": "Demo", "identifier": "demo", "active": True},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects" and request.method == "POST":
            nonlocal sent_body
            sent_body = json.loads(request.content)
            return httpx.Response(
                201,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_project_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    preview = await client.create_project(name="Demo", identifier="demo", active=True, confirm=False)
    assert preview.payload == {"name": "Demo", "identifier": "demo", "active": True}

    committed = await client.create_project(name="Demo", identifier="demo", active=True, confirm=True)
    assert committed.confirmed is True
    assert sent_body == preview.payload

    await client.aclose()


@pytest.mark.asyncio
async def test_version_service_finalize_write_sends_the_same_payload_it_previewed() -> None:
    """Same proof for app/services/version_service.py's separate _finalize_write
    copy (duplicated, not shared, because an Application Service calls a port
    rather than doing I/O itself -- see that module's own docstring)."""
    sent_body: dict | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/myproject":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 5, "name": "My Project", "identifier": "myproject"},
                request=request,
            )
        if request.url.path == "/api/v3/versions/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {"name": "v2.0", "_links": {"definingProject": {"href": "/api/v3/projects/5"}}},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions" and request.method == "POST":
            nonlocal sent_body
            sent_body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "_type": "Version",
                    "id": 9,
                    "name": "v2.0",
                    "_links": {"definingProject": {"href": "/api/v3/projects/5"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_version_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    preview = await client.create_version(project="myproject", name="v2.0", confirm=False)
    assert preview.payload == {"name": "v2.0", "_links": {"definingProject": {"href": "/api/v3/projects/5"}}}

    committed = await client.create_version(project="myproject", name="v2.0", confirm=True)
    assert committed.confirmed is True
    assert sent_body == preview.payload

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_relation_preview_payload_matches_sent_body_modulo_echo_fields() -> None:
    """The hand-rolled outlier (client.py:2989-3046, not routed through
    _finalize_write): its preview payload is `payload | {"to_work_package_id":
    related_numeric_id}` -- a caller-readability echo key that is never part of
    the actual POST body. Equivalence holds once that one documented key is
    excluded -- the fifth allowed-deviation category this file's module
    docstring names.
    """
    sent_body: dict | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 10, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/20" and request.method == "GET":
            return httpx.Response(200, json={"id": 20}, request=request)
        if request.url.path == "/api/v3/work_packages/10/relations" and request.method == "POST":
            nonlocal sent_body
            sent_body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 3,
                    "type": "follows",
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

    preview = await client.create_work_package_relation(
        work_package_id=10, related_to_work_package_id=20, relation_type="follows", confirm=False
    )
    assert preview.payload["to_work_package_id"] == 20

    committed = await client.create_work_package_relation(
        work_package_id=10, related_to_work_package_id=20, relation_type="follows", confirm=True
    )
    assert committed.confirmed is True
    assert sent_body is not None
    assert "to_work_package_id" not in sent_body, "the echo key must never be sent over the wire"

    trimmed_preview = {k: v for k, v in preview.payload.items() if k != "to_work_package_id"}
    assert trimmed_preview == sent_body

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_work_package_preview_and_confirmed_target_the_same_resource() -> None:
    """Delete-category degenerate case: DELETE sends no request body at all, so
    "payload equivalence" doesn't apply at the body level -- the meaningful
    check instead is that preview and confirm target the identical resource
    (same id), which is what actually matters for a delete. This is
    deliberately NOT forced into an artificial body comparison.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Delete me",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "DELETE":
            assert request.content == b""
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    preview = await client.delete_work_package(work_package_id=42, confirm=False)
    committed = await client.delete_work_package(work_package_id=42, confirm=True)

    assert preview.work_package_id == committed.work_package_id == 42
    assert preview.payload["id"] == 42

    await client.aclose()
