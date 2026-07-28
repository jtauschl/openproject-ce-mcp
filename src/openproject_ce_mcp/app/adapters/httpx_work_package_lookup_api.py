"""HTTP-backed WorkPackageLookupApi adapter (ADR 0001, OPM-318).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter's convention). Two endpoints, raw HAL payload returned
unnormalized -- see `app/ports/work_package_lookup_api.py`'s module docstring
for why this stays minimal rather than growing into a full `WorkPackageApi`,
and for why two methods (not one) are needed.

Needs `base_url`/`api_prefix` constructor params (matching `HttpxProjectApi`)
for `get_by_href`'s `_link_to_api_path`-equivalent origin check -- unlike
`HttpxProjectApi`, `get()` itself never needs them (it already receives a bare
reference, not a link), but `get_by_href()` does.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..errors import OpenProjectServerError
from ..origin import origin_from_url as _origin_from_url
from ..ports.work_package_ref import work_package_ref as _encode_work_package_ref
from ..transport.protocol import Transport


class HttpxWorkPackageLookupApi:
    """`WorkPackageLookupApi` Protocol implementation. `WorkPackageResolver`
    depends on the `WorkPackageLookupApi` Protocol, never on this concrete
    class (enforced by the architecture-boundary test).
    """

    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._origin = _origin_from_url(base_url)
        self._api_prefix = api_prefix

    async def get(self, work_package_ref: str) -> dict[str, Any]:
        # Same URL-encoding as the shared pure helper in
        # app/ports/work_package_ref.py -- reused here directly rather than
        # re-deriving the encoding rule a second time.
        encoded = _encode_work_package_ref(work_package_ref)
        return await self._transport.get_json(f"work_packages/{encoded}")

    async def get_by_href(self, href: str) -> dict[str, Any]:
        return await self._transport.get_json(self._link_to_api_path(href))

    def _link_to_api_path(self, href: str) -> str:
        """Same-origin-checked href -> API-relative path (with the API prefix
        stripped, since the Transport's own base URL already includes it).

        Verbatim port of client.py's `_link_to_api_path` (also mirrored by
        `HttpxProjectApi._link_to_api_path`): an absolute href whose origin
        differs from this instance's configured origin is rejected BEFORE any
        authenticated request is made -- a manipulated/foreign link href must
        never be contacted.
        """
        parsed = urlparse(href)
        if not parsed.scheme:
            path = parsed.path or href
        else:
            if _origin_from_url(href) != self._origin:
                raise OpenProjectServerError("OpenProject returned an unexpected link host.")
            path = parsed.path
        if path.startswith(self._api_prefix):
            relative_path = path[len(self._api_prefix) :]
        else:
            relative_path = path.lstrip("/")
        if parsed.query:
            return f"{relative_path}?{parsed.query}"
        return relative_path
