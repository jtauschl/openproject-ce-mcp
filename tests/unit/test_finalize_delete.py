"""Direct unit tests for OpenProjectClient._finalize_delete (OPM-46).

Covers the two behaviors most easily flattened by a future edit: preview_result
and commit_result threaded independently (not assumed equal), and result_kwargs
working for a Result dataclass with no `payload` field at all (mirroring
FileLinkWriteResult's shape).
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.client import OpenProjectClient


@dataclasses.dataclass
class _FakeDeleteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    validation_errors: dict
    result: object
    entity_id: int
    payload: dict


@dataclasses.dataclass
class _FakeDeleteResultNoPayload:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    validation_errors: dict
    result: object
    entity_id: int


def _no_request_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request must be issued for a preview call: {request.method} {request.url}")


@pytest.mark.asyncio
async def test_finalize_delete_preview_and_commit_results_are_independent() -> None:
    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(_no_request_handler))

    preview = await client._finalize_delete(
        result_cls=_FakeDeleteResult,
        confirm=False,
        result_kwargs={"entity_id": 7, "payload": {"id": 7}},
        preview_result="preview-marker",
        commit_result="commit-marker",
        write_scope="project",
        delete_path="widgets/7",
        preview_message="preview message",
        success_message="success message",
    )
    assert preview.confirmed is False
    assert preview.requires_confirmation is True
    assert preview.result == "preview-marker"
    assert preview.message == "preview message"
    assert preview.entity_id == 7
    assert preview.payload == {"id": 7}

    await client.aclose()


@pytest.mark.asyncio
async def test_finalize_delete_commit_calls_delete_and_uses_commit_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/widgets/7" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = dataclasses.replace(make_settings(), enable_project_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    committed = await client._finalize_delete(
        result_cls=_FakeDeleteResult,
        confirm=True,
        result_kwargs={"entity_id": 7, "payload": {"id": 7}},
        preview_result="preview-marker",
        commit_result="commit-marker",
        write_scope="project",
        delete_path="widgets/7",
        preview_message="preview message",
        success_message="success message",
    )
    assert committed.confirmed is True
    assert committed.requires_confirmation is False
    assert committed.result == "commit-marker"
    assert committed.message == "success message"

    await client.aclose()


@pytest.mark.asyncio
async def test_finalize_delete_supports_result_class_without_payload_field() -> None:
    """Mirrors FileLinkWriteResult, which has no `payload` field at all -- an
    earlier draft of this helper always passed payload=..., which would have
    raised TypeError for this exact shape.
    """
    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(_no_request_handler))

    preview = await client._finalize_delete(
        result_cls=_FakeDeleteResultNoPayload,
        confirm=False,
        result_kwargs={"entity_id": 9},
        preview_result=None,
        commit_result=None,
        write_scope="project",
        delete_path="widgets/9",
        preview_message="preview message",
        success_message="success message",
    )
    assert preview.confirmed is False
    assert preview.entity_id == 9
    assert not hasattr(preview, "payload")

    await client.aclose()
