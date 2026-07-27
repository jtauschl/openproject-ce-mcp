"""Narrow transport port (ADR 0001).

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
    """Raw response envelope for request_raw (ADR 0001).

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

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None: ...

    async def delete_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]: ...

    async def request_raw(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> TransportResponse: ...
