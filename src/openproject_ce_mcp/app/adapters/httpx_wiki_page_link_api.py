"""HTTP-backed WikiPageLinkApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).

`list_for_work_package` uses `GET work_packages/{id}/wiki_page_links`, whose
response IS paginated (`PageLinkCollectionRepresenter` inherits OpenProject's
`OffsetPaginatedCollection`, unlike the Attachments endpoint) -- `total` is
read directly from the response, no `len(records)` fallback needed.

KNOWN SERVER LIMITATION (not fixed client-side): the
work-package-scoped endpoint's own handler (`work_package_wiki_page_links_
api.rb`) never forwards the request's `offset` param into `page:` when
constructing `PageLinkCollectionRepresenter` -- only `per_page: params[:
pageSize]` is passed. `OffsetPaginatedCollection#initialize` defaults `page`
to 1 whenever it's not explicitly given, so every call to this endpoint
returns the SAME first page regardless of the `offset` this client sends.
The Service's `scan_records_and_paginate`/`paginate_all` repeated-page guard
prevents an infinite loop from this (a second identical page is detected and
treated as exhaustion), but it also means any links beyond the first server
page are silently unreachable through this endpoint until fixed upstream --
not currently independently verifiable since OP-19928 (see
tests/integration/test_wiki_page_links.py) already 500s the same endpoint
whenever any link exists at all.

`create` POSTs to the same work-package-scoped path, not the global
`POST /wiki_page_links`: the scoped endpoint sets `linkable` from the URL
server-side. The request body is always the bulk `_embedded/elements` shape
(`ParsePageLinkParamsService` requires it even for a single element) --
`elements: [{"identifier": ..., "_links": {"provider": {...}, "author": {...}}}]`.
Every link created through this API becomes a `Wikis::RelationPageLink`
(`wikiPageLinkType` "Relation") -- inline links are extracted from body text
server-side and are never created via this endpoint.

`_links.author` must be sent explicitly, pointing at `users/{author_id}` --
verified live against a real instance: `relation_page_link_representer.rb`'s
author setter only runs when the request body contains an `author` link key
at all; omitting the key entirely leaves `author` unset (NOT defaulted to
the current user), which the server-side create contract then rejects with
"Author is invalid" (`author == user` fails against nil).
"""

from __future__ import annotations

from typing import Any

from ...models import WikiPageLinkSummary
from ..errors import OpenProjectServerError
from ..ports.wiki_page_link_api import WikiPageLinkRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text

_LINK_TYPE_URN_SUFFIX = {
    "wikiPageLinks:Inline": "inline",
    "wikiPageLinks:Relation": "relation",
}


def normalize_wiki_page_link(payload: dict[str, Any]) -> WikiPageLinkSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    provider_link = links.get("provider")
    linkable_link = links.get("linkable")
    author_link = links.get("author")
    urn = payload.get("wikiPageLinkType") or ""
    link_type = next((v for k, v in _LINK_TYPE_URN_SUFFIX.items() if urn.endswith(k)), None)
    return WikiPageLinkSummary(
        id=int(payload["id"]),
        identifier=_trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT),
        link_type=link_type,
        provider=_link_title(provider_link) if isinstance(provider_link, dict) else None,
        work_package_id=_id_from_href(linkable_link.get("href")) if isinstance(linkable_link, dict) else None,
        author=_link_title(author_link) if isinstance(author_link, dict) else None,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxWikiPageLinkApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> WikiPageLinkRecord:
        return WikiPageLinkRecord(summary=normalize_wiki_page_link(payload))

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WikiPageLinkRecord], int]:
        payload = await self._transport.get_json(
            f"work_packages/{work_package_id}/wiki_page_links",
            params={"offset": str(offset), "pageSize": str(page_size)},
        )
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        records = [self._record(item) for item in elements]
        total = int(payload.get("total", len(records)))
        return records, total

    async def create(
        self, work_package_id: int, *, identifier: str, provider: str, author_id: int
    ) -> WikiPageLinkRecord:
        response = await self._transport.post_json(
            f"work_packages/{work_package_id}/wiki_page_links",
            json_body={
                "_embedded": {
                    "elements": [
                        {
                            "identifier": identifier,
                            "_links": {
                                "provider": {"href": f"/api/v3/wiki_providers/{provider}"},
                                "author": {"href": f"/api/v3/users/{author_id}"},
                            },
                        }
                    ]
                }
            },
        )
        elements = response.get("_embedded", {}).get("elements", [])
        if not elements or not isinstance(elements[0], dict):
            raise OpenProjectServerError("OpenProject returned no created wiki page link element.")
        return self._record(elements[0])

    async def delete(self, link_id: int) -> None:
        await self._transport.delete(f"wiki_page_links/{link_id}")
