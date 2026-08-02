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


class Transport(Protocol):
    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]: ...

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def post_raw_json(self, path: str, *, content: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """POST a raw, non-JSON body (e.g. Content-Type: text/plain) and parse a
        JSON response -- added for render_text (Extended Metadata domain, 19th
        migration), the first endpoint to POST raw text rather than a JSON body."""
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
        part) and parse a JSON response -- added for Attachments (29th
        migration), the first endpoint to POST a file upload rather than a
        JSON or raw-text body. Verbatim of client.py's `_post_multipart`: the
        metadata part must be a plain form field with no filename in its
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
