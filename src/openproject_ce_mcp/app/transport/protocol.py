"""Narrow transport port.

HttpxTransport is the only implementation for 0.4.0; the point is that VersionApi
adapters depend on this Protocol, not on HttpxTransport concretely, mirroring the
VersionService/VersionApi rule one layer down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TransportResponse:
    """Raw response envelope for request_raw.

    Used only where a JSON-parsed body isn't the right contract: a 204 response
    with no body (post_json would fail parsing it), or a redirect whose
    Location header -- not the final response's own headers -- carries the
    result (project copy). header/redirect_headers keys are always lowercase
    (httpx.Headers is case-insensitive; a naive dict(response.headers) is not,
    so this normalization must happen once here rather than at every call site).
    """

    status_code: int
    headers: Mapping[str, str]
    redirect_headers: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class BinaryContent:
    """Bounded binary body read by get_binary.

    `content_type` is the SERVED response's own Content-Type header (the
    final response after any redirect), not the stored metadata's -- the two
    disagree often enough that the caller must be able to tell them apart:
    OpenProject normalizes a served attachment to `application/octet-stream`
    for anything it will not inline, including JSON. None when the response
    carried no Content-Type at all.

    `truncated` is True when the body was longer than the caller's `max_bytes`
    and reading stopped there; `data` then holds exactly the first `max_bytes`
    bytes. The caller -- not the transport -- decides whether a truncated body
    is usable (text) or must be discarded (an image is never partially
    returned).
    """

    data: bytes
    content_type: str | None
    truncated: bool


class Transport(Protocol):
    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]: ...

    async def get_binary(self, path: str, *, max_bytes: int) -> BinaryContent:
        """GET a binary body, streamed and stopped at `max_bytes`.

        Streaming, not a buffered read: the size limit must bound memory and
        network transfer, not just what is handed back -- a buffered GET would
        pull a multi-gigabyte attachment into memory before the caller could
        reject it.

        Redirects are followed explicitly here rather than left to httpx's
        client-level `follow_redirects=True`, because this is the one path
        whose redirect target is routinely a foreign origin (a pre-signed
        object-storage URL on an S3-backed instance): the `Authorization`
        header is kept on a same-origin hop and dropped on a cross-origin one,
        so instance credentials never reach a third-party bucket. httpx's own
        default happens to behave the same way, but this path states it
        outright and tests it, matching how `_link_to_api_path` refuses to
        follow an unexpected link host rather than trusting a default.
        """
        ...

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def post_raw_json(self, path: str, *, content: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """POST a raw, non-JSON body (e.g. Content-Type: text/plain) and parse a
        JSON response -- used by render_text, the only endpoint that POSTs raw
        text rather than a JSON body."""
        ...

    async def post_multipart(
        self,
        path: str,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """POST a multipart/form-data body (a JSON metadata part plus a file
        part) and parse a JSON response -- used by Attachments, the only
        endpoint that POSTs a file upload rather than a JSON or raw-text body.
        The metadata part must be a plain form field with no filename in its
        Content-Disposition (a filename makes Rails' multipart parser treat
        it as an uploaded file, not a JSON string, and OpenProject 500s)."""
        ...

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None: ...

    async def delete_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]: ...

    async def request_raw(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> TransportResponse: ...
