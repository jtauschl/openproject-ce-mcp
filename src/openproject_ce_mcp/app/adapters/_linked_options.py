"""Every element of an `allowedValues` collection a schema field links instead of embedding."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..errors import OpenProjectServerError
from ..pagination import paginate_all
from ..transport.protocol import Transport

# An unpaged request returns only the server's default page (20 entries), so an option past it would be
# refused as not allowed. The server caps the size it honours; the walk counts elements against `total`, so a
# smaller page than asked for is fine.
_OPTION_PAGE_SIZE = 100


def _page_path(path: str, offset: int, page_size: int) -> str:
    parts = urlsplit(path)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("offset", "pageSize")]
    query += [("offset", str(offset)), ("pageSize", str(page_size))]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def read_linked_options(transport: Transport, path: str) -> list[dict[str, Any]]:
    async def fetch_page(offset: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        payload = await transport.get_json(_page_path(path, offset, page_size))
        elements = (payload.get("_embedded") or {}).get("elements", [])
        if "total" not in payload:
            raise OpenProjectServerError(f"OpenProject returned a collection without a total for {path}.")
        return elements, int(payload["total"])

    return await paginate_all(
        fetch_page,
        page_size=_OPTION_PAGE_SIZE,
        key=lambda element: str(((element.get("_links") or {}).get("self") or {}).get("href")),
    )
