from __future__ import annotations

from typing import Any

import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.errors import TransportError
from openproject_ce_mcp.app.services.project_directory_service import ProjectDirectoryService
from openproject_ce_mcp.app.transport.learning_transport import LearningTransport
from openproject_ce_mcp.app.transport.protocol import BinaryContent, TransportResponse


class _Inner:
    """Answers every call with its own fresh body, so identity shows the body
    is passed through untouched."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def _body(self) -> dict[str, Any]:
        body = {"_type": "WorkPackage", "_links": {"project": {"href": "/api/v3/projects/7"}}}
        self.bodies.append(body)
        return body

    async def get_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def post_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def post_raw_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def post_multipart(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def patch_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def delete_json(self, path: str, **_: Any) -> dict[str, Any]:
        return self._body()

    async def get_binary(self, path: str, **_: Any) -> BinaryContent:
        return BinaryContent(data=b"x", content_type=None, truncated=False)

    async def delete(self, path: str, **_: Any) -> None:
        return None

    async def request_raw(self, method: str, path: str, **_: Any) -> TransportResponse:
        return TransportResponse(status_code=204, headers={}, redirect_headers=())


JSON_CALLS = {
    "get_json": lambda t: t.get_json("x"),
    "post_json": lambda t: t.post_json("x", json_body={}),
    "post_raw_json": lambda t: t.post_raw_json("x", content=b"{}", headers={}),
    "post_multipart": lambda t: t.post_multipart(
        "x", metadata={}, file_name="a.txt", file_bytes=b"a", content_type="text/plain"
    ),
    "patch_json": lambda t: t.patch_json("x", json_body={}),
    "delete_json": lambda t: t.delete_json("x"),
}

OTHER_CALLS = {
    "get_binary": lambda t: t.get_binary("x", max_bytes=1),
    "delete": lambda t: t.delete("x"),
    "request_raw": lambda t: t.request_raw("GET", "x"),
}


@pytest.mark.parametrize("call", JSON_CALLS.values(), ids=JSON_CALLS.keys())
@pytest.mark.asyncio
async def test_every_json_body_is_learned_before_it_is_returned_unchanged(call) -> None:
    inner = _Inner()
    learned: list[Any] = []

    async def learn(payload: Any) -> None:
        learned.append(payload)

    body = await call(LearningTransport(inner, learn=learn))

    assert body is inner.bodies[0]
    assert learned == [body]
    assert learned[0] is body


@pytest.mark.parametrize("call", OTHER_CALLS.values(), ids=OTHER_CALLS.keys())
@pytest.mark.asyncio
async def test_responses_without_a_json_body_are_not_learned(call) -> None:
    learned: list[Any] = []

    async def learn(payload: Any) -> None:
        learned.append(payload)

    await call(LearningTransport(_Inner(), learn=learn))

    assert learned == []


@pytest.mark.asyncio
async def test_a_failed_project_lookup_does_not_lose_a_confirmed_write() -> None:
    class _UnreachableProjects:
        async def get(self, project_ref: str, **_: Any):
            raise TransportError("Could not reach OpenProject")

    directory = ProjectDirectoryService(
        api=_UnreachableProjects(),  # type: ignore[arg-type]
        settings=_base_settings(read_projects=("demo",), write_projects=("demo",)),
        origin="https://op.example.com",
        api_prefix="/api/v3/",
    )
    inner = _Inner()

    body = await LearningTransport(inner, learn=directory.learn).patch_json("work_packages/1", json_body={})

    assert body is inner.bodies[0]
    assert directory.positives == {}
