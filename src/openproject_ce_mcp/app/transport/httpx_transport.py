"""httpx-backed Transport port implementation.

The only module under app/ allowed to `import httpx` (enforced by the
architecture-boundary test, Slice 6).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ...hal import normalize_links
from ..errors import OpenProjectServerError, TransportError
from .errors import raise_for_status
from .protocol import BinaryContent, TransportResponse

# Redirect statuses get_binary follows itself (see Transport.get_binary's
# docstring for why this path does not lean on httpx's client-level
# follow_redirects). 303 is included because OpenProject's own
# `/attachments/{id}/content` answers with a redirect to the storage backend,
# and 307/308 because an object-storage host may answer with either.
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
# Enough for OpenProject -> storage backend (one hop) with room for a bucket
# that redirects once more; low enough that a redirect loop fails fast.
_MAX_REDIRECTS = 5


def _origin_of(url: httpx.URL) -> tuple[str, str, int | None]:
    """Scheme/host/port triple. `url.port` is None for a scheme's default port,
    so http://host and http://host:80 compare equal here only if httpx
    normalized them identically -- which it does, since it drops the default
    port when parsing."""
    return (url.scheme, url.host, url.port)


def _redirect_request(request: httpx.Request, location: str) -> httpx.Request:
    """Build the next hop, carrying the previous request's headers minus the
    ones that must not survive it.

    Authorization is dropped when the hop crosses origins: on an S3-backed
    instance the target is a pre-signed bucket URL, and sending the
    instance's Basic credentials to a third-party host would leak them for no
    benefit (the pre-signed URL authenticates itself). It is kept on a
    same-origin hop, which is what local-filesystem storage produces.

    Host is dropped unconditionally: it belongs to the previous hop's origin
    and httpx recomputes it for the new URL.

    Constructed via `httpx.Request(...)` rather than `client.build_request`
    on purpose -- build_request would merge the client's default headers back
    in, putting the Authorization header we just removed straight back on a
    cross-origin request.
    """
    target = httpx.URL(location)
    if not target.is_absolute_url:
        target = request.url.join(location)
    drop = {"host"}
    if _origin_of(target) != _origin_of(request.url):
        drop.add("authorization")
    headers = [(name, value) for name, value in request.headers.multi_items() if name.lower() not in drop]
    return httpx.Request("GET", target, headers=headers)


async def _read_bounded(response: httpx.Response, max_bytes: int) -> BinaryContent:
    """Accumulate the streamed body, stopping as soon as it exceeds `max_bytes`.

    Reading stops at the first chunk that crosses the limit, so an oversized
    attachment costs one chunk of memory and one chunk of transfer past the
    cap -- not the whole file. The returned data is trimmed to exactly
    `max_bytes` in that case, and `truncated` says so; a body that ends
    exactly at the limit is NOT truncated.
    """
    content_type = response.headers.get("content-type")
    buffer = bytearray()
    async for chunk in response.aiter_bytes():
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            return BinaryContent(data=bytes(buffer[:max_bytes]), content_type=content_type, truncated=True)
    return BinaryContent(data=bytes(buffer), content_type=content_type, truncated=False)


class HttpxTransport:
    """Wraps the SAME httpx.AsyncClient instance OpenProjectClient.__init__ already
    constructs ("httpx confinement") -- one connection pool, not two.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", path, params=params)

    async def get_binary(self, path: str, *, max_bytes: int) -> BinaryContent:
        request = self._client.build_request("GET", path)
        for _ in range(_MAX_REDIRECTS + 1):
            response = await self._send_stream(request)
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUS_CODES and location:
                await response.aclose()
                request = _redirect_request(request, location)
                continue
            try:
                if response.status_code >= 400:
                    await self._raise_for_stream_status(response)
                return await _read_bounded(response, max_bytes)
            finally:
                await response.aclose()
        raise OpenProjectServerError("OpenProject redirected the attachment download too many times.")

    async def post_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request_json("POST", path, params=params, json_body=json_body)

    async def post_raw_json(self, path: str, *, content: bytes, headers: dict[str, str]) -> dict[str, Any]:
        response = await self._request("POST", path, content=content, headers=headers)
        return self._parse_json(response)

    async def post_multipart(
        self,
        path: str,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            path,
            files={
                "metadata": (None, json.dumps(metadata), "application/json"),
                "file": (file_name, file_bytes, content_type),
            },
        )
        return self._parse_json(response)

    async def patch_json(
        self, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request_json("PATCH", path, params=params, json_body=json_body)

    async def delete(self, path: str, *, params: dict[str, str] | None = None) -> None:
        response = await self._request("DELETE", path, params=params)
        if response.status_code not in {200, 202, 204}:
            raise OpenProjectServerError(f"OpenProject delete request failed with status {response.status_code}.")

    async def delete_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request_json("DELETE", path, params=params)

    async def request_raw(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> TransportResponse:
        response = await self._request(method, path, params=params, json_body=json_body)
        return TransportResponse(
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            redirect_headers=tuple(
                {k.lower(): v for k, v in redirect.headers.items()} for redirect in response.history
            ),
        )

    async def _send_stream(self, request: httpx.Request) -> httpx.Response:
        """Send one hop with the body left unread, mapping transport failures the
        same way `_request` does. `follow_redirects=False`: get_binary walks the
        redirect chain itself so the Authorization header's fate at a
        cross-origin hop is explicit rather than inherited from the client."""
        try:
            return await self._client.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise TransportError("OpenProject request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TransportError("Could not reach OpenProject.") from exc

    async def _raise_for_stream_status(self, response: httpx.Response) -> None:
        """Read an error response's (small, JSON) body and raise the mapped
        error. Safe to read in full here, unlike the success path: this only
        runs for a >=400 status, whose body is an API error document."""
        try:
            await response.aread()
            payload = response.json()
        except (ValueError, httpx.HTTPError):
            payload = {}
        raise_for_status(response.status_code, payload)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, params=params, json_body=json_body)
        return self._parse_json(response)

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
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
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, path, params=params, json=json_body, content=content, headers=headers, files=files
            )
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
