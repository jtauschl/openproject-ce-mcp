"""Narrow transport port (ADR 0001).

HttpxTransport is the only implementation for 0.4.0; the point is that VersionApi
adapters depend on this Protocol, not on HttpxTransport concretely, mirroring the
VersionService/VersionApi rule one layer down.
"""

from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]: ...

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None: ...
