"""httpx-backed Transport port implementation (ADR 0001).

The only module under app/ allowed to `import httpx` (enforced by the
architecture-boundary test, Slice 6).
"""

from __future__ import annotations

from typing import Any

import httpx

from ...hal import normalize_links
from ..errors import OpenProjectServerError, TransportError
from .errors import raise_for_status


class HttpxTransport:
    """Wraps the SAME httpx.AsyncClient instance OpenProjectClient.__init__ already
    constructs (ADR 0001, "httpx confinement") -- one connection pool, not two.
    Verbatim behavioral port of client.py's
    _request/_request_json/_get/_post/_patch/_delete/_raise_for_status.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", path, params=params)

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request_json("POST", path, params=params, json_body=json_body)

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request_json("PATCH", path, params=params, json_body=json_body)

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None:
        response = await self._request("DELETE", path, params=params)
        if response.status_code not in {200, 202, 204}:
            raise OpenProjectServerError(f"OpenProject delete request failed with status {response.status_code}.")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, params=params, json_body=json_body)
        try:
            return normalize_links(response.json())
        except ValueError as exc:
            raise OpenProjectServerError("OpenProject returned invalid JSON.") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, params=params, json=json_body)
        except httpx.TimeoutException as exc:
            raise TransportError("OpenProject request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TransportError("Could not reach OpenProject.") from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            raise_for_status(response.status_code, payload)
        return response
