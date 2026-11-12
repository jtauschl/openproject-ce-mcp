"""HTTP-backed WorkPackageLookupApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter's convention). Two endpoints, raw HAL payload returned
unnormalized -- see `app/ports/work_package_lookup_api.py`'s module docstring
for why this stays minimal rather than growing into a full `WorkPackageApi`,
and for why two methods (not one) are needed.

Needs `base_url`/`api_prefix` constructor params (matching `HttpxProjectApi`)
for `get_by_href`'s `link_to_api_path` origin check -- unlike
`HttpxProjectApi`, `get()` itself never needs them (it already receives a bare
reference, not a link), but `get_by_href()` does.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..ports.work_package_ref import work_package_ref as _valid_work_package_ref
from ..transport.protocol import Transport
from ._text import link_to_api_path


class HttpxWorkPackageLookupApi:
    """`WorkPackageLookupApi` Protocol implementation. `WorkPackageResolver`
    depends on the `WorkPackageLookupApi` Protocol, never on this concrete
    class (enforced by the architecture-boundary test).
    """

    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._link_to_api_path = partial(link_to_api_path, base_url=base_url, api_prefix=api_prefix)

    async def get(self, work_package_ref: str) -> dict[str, Any]:
        return await self._transport.get_json(f"work_packages/{_valid_work_package_ref(work_package_ref)}")

    async def get_by_href(self, href: str) -> dict[str, Any]:
        return await self._transport.get_json(self._link_to_api_path(href))
