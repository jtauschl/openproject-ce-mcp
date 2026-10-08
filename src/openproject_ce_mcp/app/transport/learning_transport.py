"""A Transport that shows every JSON response body to a learner first.

Scope policies are synchronous and read state that must already know every
project a response refers to; awaiting the learner here, before the body
reaches any adapter, is what makes that true for every caller at once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .protocol import BinaryContent, Transport, TransportResponse


class LearningTransport:
    def __init__(self, inner: Transport, *, learn: Callable[[Any], Awaitable[None]]) -> None:
        self._inner = inner
        self._learn = learn

    async def _learned(self, body: dict[str, Any]) -> dict[str, Any]:
        await self._learn(body)
        return body

    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._learned(await self._inner.get_json(path, params=params))

    async def get_binary(self, path: str, *, max_bytes: int) -> BinaryContent:
        return await self._inner.get_binary(path, max_bytes=max_bytes)

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._learned(await self._inner.post_json(path, params=params, json_body=json_body))

    async def post_raw_json(self, path: str, *, content: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return await self._learned(await self._inner.post_raw_json(path, content=content, headers=headers))

    async def post_multipart(
        self,
        path: str,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        return await self._learned(
            await self._inner.post_multipart(
                path, metadata=metadata, file_name=file_name, file_bytes=file_bytes, content_type=content_type
            )
        )

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._learned(await self._inner.patch_json(path, params=params, json_body=json_body))

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None:
        await self._inner.delete(path, params=params)

    async def delete_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._learned(await self._inner.delete_json(path, params=params))

    async def request_raw(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> TransportResponse:
        return await self._inner.request_raw(method, path, params=params, json_body=json_body)
