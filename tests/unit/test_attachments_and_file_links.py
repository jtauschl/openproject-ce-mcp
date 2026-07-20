from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
)

from openproject_ce_mcp.client import (
    InvalidInputError,
    OpenProjectClient,
    PermissionDeniedError,
)


async def test_attachment_rejects_file_outside_root(tmp_path, monkeypatch) -> None:
    """A file outside the attachment root is refused (no token/host exfiltration)."""
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("api-token-here")

    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    with pytest.raises(InvalidInputError, match="outside the allowed attachment directory"):
        client._prepare_attachment_file(str(outside), include_bytes=True)
    await client.aclose()


async def test_attachment_allows_file_inside_root(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    inside = root / "note.txt"
    inside.write_text("hello")
    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    info = client._prepare_attachment_file(str(inside), include_bytes=True)
    assert info["file_bytes"] == b"hello"
    await client.aclose()


@pytest.mark.parametrize("secret_name", [".mcp.json", ".mcp.json.bak.20260101", ".env", "server.pem", "id_rsa"])
async def test_attachment_rejects_sensitive_file_inside_root(tmp_path, secret_name) -> None:
    """A credential/config file inside the root is refused (closes the token-exfil gap)."""
    root = tmp_path / "project"
    root.mkdir()
    secret = root / secret_name
    secret.write_text("OPENPROJECT_API_TOKEN=opapi-secret")
    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    with pytest.raises(InvalidInputError, match="credential/config file"):
        client._prepare_attachment_file(str(secret), include_bytes=True)
    await client.aclose()


async def test_attachment_rejects_symlink_escape(tmp_path) -> None:
    """A symlink inside the root pointing outside is refused (resolve() containment)."""
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = root / "innocent.txt"
    link.symlink_to(outside)
    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    with pytest.raises(InvalidInputError, match="outside the allowed attachment directory"):
        client._prepare_attachment_file(str(link), include_bytes=True)
    await client.aclose()


async def test_attachment_root_empty_refuses_upload(tmp_path) -> None:
    """No OPENPROJECT_ATTACHMENT_ROOT means uploads are disabled, not cwd."""
    settings = _base_settings(enable_work_package_write=True)  # attachment_root defaults to ""
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    some_file = tmp_path / "note.txt"
    some_file.write_text("hello")
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ATTACHMENT_ROOT"):
        client._prepare_attachment_file(str(some_file), include_bytes=True)
    await client.aclose()


async def test_create_work_package_attachment_refuses_when_root_unset(tmp_path) -> None:
    """The refusal surfaces through the full create_work_package_attachment call path."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True)  # attachment_root defaults to ""
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    some_file = tmp_path / "note.txt"
    some_file.write_text("hello")
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ATTACHMENT_ROOT"):
        await client.create_work_package_attachment(work_package_id=42, file_path=str(some_file), confirm=True)
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_file_link_allows_write_project() -> None:
    """A container WP in an allowed project passes the allowlist and deletes."""
    deleted: dict[str, bool] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/file_links/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "_links": {
                        "self": {"href": "/api/v3/file_links/5"},
                        "container": {"href": "/api/v3/work_packages/9"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/file_links/5" and request.method == "DELETE":
            deleted["done"] = True
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, write_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.delete_file_link(5, confirm=True)

    assert deleted.get("done") is True
    assert result.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_file_link_reports_none_work_package_id_when_container_unresolvable() -> None:
    # OPM-1453: a file link with no resolvable container used to fake a work_package_id
    # of 0 (a real-looking id) instead of reporting "unknown/none" as None.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/file_links/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 5, "_links": {"self": {"href": "/api/v3/file_links/5"}}},  # no "container" link
                request=request,
            )
        if request.url.path == "/api/v3/file_links/5" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, write_projects=("*",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.delete_file_link(5, confirm=True)

    assert result.work_package_id is None
    assert result.confirmed is True

    await client.aclose()
