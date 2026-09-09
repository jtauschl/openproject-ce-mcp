from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
)

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.services.attachment_service import AttachmentService
from openproject_ce_mcp.client import (
    OpenProjectClient,
    PermissionDeniedError,
)


def _prepare(client: OpenProjectClient, file_path: str, *, include_bytes: bool):
    # Re-anchored (2029 migration: Attachments) at the new AttachmentService
    # layer -- `client._prepare_attachment_file` no longer exists, the
    # method moved to `AttachmentService._prepare_attachment_file`.
    service: AttachmentService = client._attachment_service
    return service._prepare_attachment_file(file_path, include_bytes=include_bytes)


async def test_attachment_rejects_file_outside_root(tmp_path, monkeypatch) -> None:
    """A file outside the attachment root is refused (no token/host exfiltration)."""
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("api-token-here")

    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    with pytest.raises(InvalidInputError, match="outside the allowed attachment directory"):
        _prepare(client, str(outside), include_bytes=True)
    await client.aclose()


async def test_attachment_allows_file_inside_root(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    inside = root / "note.txt"
    inside.write_text("hello")
    settings = _base_settings(enable_work_package_write=True, attachment_root=str(root))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    info = _prepare(client, str(inside), include_bytes=True)
    assert info.file_bytes == b"hello"
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
        _prepare(client, str(secret), include_bytes=True)
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
        _prepare(client, str(link), include_bytes=True)
    await client.aclose()


async def test_attachment_root_empty_refuses_upload(tmp_path) -> None:
    """No OPENPROJECT_ATTACHMENT_ROOT means uploads are disabled, not cwd."""
    settings = _base_settings(enable_work_package_write=True)  # attachment_root defaults to ""
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    some_file = tmp_path / "note.txt"
    some_file.write_text("hello")
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ATTACHMENT_ROOT"):
        _prepare(client, str(some_file), include_bytes=True)
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
        await client.attachment.create(work_package_id=42, file_path=str(some_file), confirm=True)
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

    result = await client.file_link.delete(5, confirm=True)

    assert deleted.get("done") is True
    assert result.state == "confirmed"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_package_file_links_denies_anchor_outside_read_allowlist() -> None:
    """list_work_package_file_links must check the anchor WP's own project.

    Previously it fetched work_packages/{id}/file_links directly with no
    allowlist check at all, leaking file link filenames/URLs for any WP id.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/2", "title": "secret"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError):
        await client.file_link.list_for_work_package(9)

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_package_file_links_allows_anchor_inside_read_allowlist() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/1", "title": "allowed"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9/file_links" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 5, "originData": {"name": "spec.pdf"}}]}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.file_link.list_for_work_package(9)

    assert result.count == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_file_link_denies_when_container_unresolvable_even_under_wide_open_write_scope() -> None:
    """A file link with no resolvable container has no verifiable project
    association -- deleting it must be denied even under
    write_projects=("*",), not silently allowed with work_package_id=None."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/file_links/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 5, "_links": {"self": {"href": "/api/v3/file_links/5"}}},  # no "container" link
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, write_projects=("*",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError):
        await client.file_link.delete(5, confirm=True)

    await client.aclose()


# --- get_attachment_content / include_images (tool layer, through the real wrapper) ---
#
# These go through `create_app()` and call the REGISTERED tool function (the
# one `tools_runtime`'s trimming wrapper produced), not the bare tool body:
# the point is the ContentBundle seam -- the body must come back as one
# leading JSON text block, trimmed like any other result, with the native
# content blocks after it.


def _registered_tool(name: str):
    from _tools_test_helpers import FakeContext  # noqa: F401  (re-exported for callers below)

    from openproject_ce_mcp.server import create_app

    mcp = create_app(_base_settings())
    return {t.name: t for t in mcp._tool_manager.list_tools()}[name].fn


def _fake_ctx(**attachment_methods):
    from types import SimpleNamespace

    from _tools_test_helpers import FakeContext

    client = SimpleNamespace(attachment=SimpleNamespace(**attachment_methods))
    return FakeContext(client)  # type: ignore[arg-type]


def _content_result(**overrides):
    from openproject_ce_mcp.models import AttachmentContentResult

    base = {
        "attachment_id": 5,
        "file_name": "shot.png",
        "outcome": "image",
        "content_type": "image/png",
        "size_bytes": 3,
        "truncated": False,
        "reason": None,
    }
    base.update(overrides)
    return AttachmentContentResult(**base)


async def test_get_attachment_content_returns_json_block_then_image_block() -> None:
    import base64
    import json

    from mcp.types import ImageContent, TextContent

    from openproject_ce_mcp.models import AttachmentContentOutcome

    calls: list[tuple[int, int | None]] = []

    async def get_content(attachment_id: int, *, max_bytes: int | None = None):
        calls.append((attachment_id, max_bytes))
        return AttachmentContentOutcome(metadata=_content_result(), image_bytes=b"PNG")

    tool = _registered_tool("get_attachment_content")
    result = await tool(_fake_ctx(get_content=get_content), attachment_id=5, max_bytes=100)

    assert calls == [(5, 100)]
    assert [type(block) for block in result] == [TextContent, ImageContent]
    metadata = json.loads(result[0].text)
    assert metadata == {
        "attachment_id": 5,
        "file_name": "shot.png",
        "outcome": "image",
        "content_type": "image/png",
        "size_bytes": 3,
        "truncated": False,
        # No `select` on this tool, so a None field stays an explicit null
        # (the same elide_none rule every select-less tool follows).
        "reason": None,
    }
    assert result[1].mime_type == "image/png"
    assert base64.b64decode(result[1].data) == b"PNG"


async def test_get_attachment_content_text_outcome_returns_text_block() -> None:
    from mcp.types import TextContent

    from openproject_ce_mcp.models import AttachmentContentOutcome

    async def get_content(attachment_id: int, *, max_bytes: int | None = None):
        return AttachmentContentOutcome(
            metadata=_content_result(outcome="text", content_type="text/plain", size_bytes=5, truncated=True),
            text="hello",
        )

    result = await _registered_tool("get_attachment_content")(_fake_ctx(get_content=get_content), attachment_id=5)

    assert [type(block) for block in result] == [TextContent, TextContent]
    # Attachment text is user-authored: delimited like descriptions/comments.
    assert result[1].text == "<user-content>hello</user-content>"


async def test_get_attachment_content_without_inlineable_content_returns_only_metadata() -> None:
    import json

    from openproject_ce_mcp.models import AttachmentContentOutcome

    async def get_content(attachment_id: int, *, max_bytes: int | None = None):
        return AttachmentContentOutcome(
            metadata=_content_result(
                outcome="not_inline_supported", content_type="application/pdf", size_bytes=None, reason="nope"
            )
        )

    result = await _registered_tool("get_attachment_content")(_fake_ctx(get_content=get_content), attachment_id=5)

    assert len(result) == 1
    assert json.loads(result[0].text)["outcome"] == "not_inline_supported"


async def test_get_attachment_content_rejects_non_positive_max_bytes_before_calling_the_client() -> None:
    async def get_content(attachment_id: int, *, max_bytes: int | None = None):
        raise AssertionError("must not be reached")

    with pytest.raises(ValueError, match=r"\[validation_error\].*max_bytes"):
        await _registered_tool("get_attachment_content")(
            _fake_ctx(get_content=get_content), attachment_id=5, max_bytes=0
        )


def _listing(*summaries):
    from openproject_ce_mcp.models import AttachmentListResult

    return AttachmentListResult(
        offset=1,
        limit=20,
        total=len(summaries),
        count=len(summaries),
        next_offset=None,
        truncated=False,
        results=list(summaries),
    )


def _summary(attachment_id: int, content_type: str):
    from openproject_ce_mcp.models import AttachmentSummary

    return AttachmentSummary(
        id=attachment_id,
        title=f"a{attachment_id}",
        file_name=f"a{attachment_id}",
        file_size_bytes=3,
        description=None,
        content_type=content_type,
        status="uploaded",
        author="Alice",
        container_type="WorkPackage",
        container_id=9,
        created_at=None,
        download_url=None,
    )


async def test_list_work_package_attachments_without_include_images_is_unchanged() -> None:
    async def list_for_work_package(work_package_id, *, offset, limit, include_total_size):
        return _listing(_summary(1, "image/png"))

    async def list_for_work_package_with_images(*args, **kwargs):
        raise AssertionError("include_images=False must not take the images path")

    result = await _registered_tool("list_work_package_attachments")(
        _fake_ctx(
            list_for_work_package=list_for_work_package,
            list_for_work_package_with_images=list_for_work_package_with_images,
        ),
        work_package_id=9,
    )

    assert isinstance(result, dict)
    assert [row["id"] for row in result["results"]] == [1]
    assert "count" not in result and "truncated" not in result
    assert "images" not in result  # None -> elided, exactly as before


async def test_list_work_package_attachments_include_images_returns_bundle_and_trims_body() -> None:
    import json

    from mcp.types import ImageContent, TextContent

    from openproject_ce_mcp.models import AttachmentContentOutcome, AttachmentListWithImages

    listing = _listing(_summary(1, "image/png"), _summary(2, "application/pdf"))
    listing.images = [
        _content_result(attachment_id=1, file_name="a1"),
        _content_result(
            attachment_id=2,
            file_name="a2",
            outcome="not_inline_supported",
            content_type="application/pdf",
            size_bytes=None,
            reason="images only",
        ),
    ]

    async def list_for_work_package_with_images(work_package_id, *, offset, limit, include_total_size):
        return AttachmentListWithImages(
            list_result=listing,
            included=(AttachmentContentOutcome(metadata=listing.images[0], image_bytes=b"PNG"),),
        )

    result = await _registered_tool("list_work_package_attachments")(
        _fake_ctx(list_for_work_package_with_images=list_for_work_package_with_images),
        work_package_id=9,
        select=["id"],
        include_images=True,
    )

    assert [type(block) for block in result] == [TextContent, ImageContent]
    body = json.loads(result[0].text)
    # `select` still trims the rows -- the body went through the normal seam.
    assert body["results"] == [{"id": 1}, {"id": 2}]
    assert "count" not in body
    assert [(e["attachment_id"], e["outcome"]) for e in body["images"]] == [
        (1, "image"),
        (2, "not_inline_supported"),
    ]
    assert body["images"][1]["reason"] == "images only"
    assert result[1].mime_type == "image/png"
