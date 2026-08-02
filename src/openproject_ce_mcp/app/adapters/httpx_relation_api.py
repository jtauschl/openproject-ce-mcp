"""HTTP-backed RelationApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`link_title`/`id_from_href`/`delimit_user_content`/
`SUBJECT_LIMIT` come from `app/adapters/_text.py` -- verified against the
pre-migration flat client.py's original `normalize_relation`: this normalizer
needs `trim_text` (description truncation), `delimit_user_content` (description
wrapped as untrusted user content), `link_title` (from/to subject titles), and
`id_from_href` (from/to numeric ids from their hrefs).

Unlike most other adapters, this one takes no `api_prefix` -- `RelationSummary`
has no `url` field of its own (nothing here builds an `_api_href(...)` link),
and the outgoing paths (`relations`, `relations/{id}`, `work_packages/{ref}/
relations`) are always passed relative to the transport, never prefix-joined
locally.

`normalize_relation` here always computes `from_subject`/`to_subject`
unconditionally -- the work_package-subject-hide check (from_subject/
to_subject nulled when work_package.subject is hidden) is a Service-layer
concern applied via `dataclasses.replace` after normalization (see
RelationService._stamp), keeping this adapter's normalize function structurally
identical to every other domain's Settings-free normalize_*.

`create()` encodes the source work-package reference itself via the shared
`work_package_ref()` encoder before building the POST path -- unlike
`WorkPackageLookupApi.get()`, which encodes internally for its own lookup GET,
nothing else in the call chain encodes the reference used in the outgoing
POST path. Passing an already-encoded string here would double-encode it.
"""

from __future__ import annotations

from typing import Any

from ...models import RelationSummary
from ..ports.relation_api import RelationRecord
from ..ports.work_package_ref import work_package_ref as _encode_work_package_ref
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_relation(payload: dict[str, Any]) -> RelationSummary:
    links = payload.get("_links", {})
    return RelationSummary(
        id=int(payload["id"]),
        type=payload.get("type"),
        description=_delimit_user_content(_trim_text(payload.get("description"), limit=SUBJECT_LIMIT)),
        from_id=_id_from_href(links.get("from", {}).get("href")),
        from_subject=_link_title(links.get("from")),
        to_id=_id_from_href(links.get("to", {}).get("href")),
        to_subject=_link_title(links.get("to")),
    )


class HttpxRelationApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def to_record(self, payload: dict[str, Any]) -> RelationRecord:
        links = payload.get("_links", {})
        # `summary` is lazy (see RelationRecord's docstring): the Service
        # filters records by from_link/to_link BEFORE ever reading .summary,
        # matching client.py's original "filter raw, normalize survivors"
        # order -- an eager field here would normalize (and potentially
        # KeyError on) records the Service is about to discard.
        return RelationRecord(
            summary=lambda: normalize_relation(payload),
            from_link=links.get("from"),
            to_link=links.get("to"),
        )

    async def fetch_page(self, *, offset: int, page_size: int, filters: str | None) -> dict[str, Any]:
        params = {"offset": str(offset), "pageSize": str(page_size)}
        if filters is not None:
            params["filters"] = filters
        return await self._transport.get_json("relations", params=params)

    async def get(self, relation_id: int) -> RelationRecord:
        payload = await self._transport.get_json(f"relations/{relation_id}")
        return self.to_record(payload)

    async def create(self, work_package_ref: str, payload: dict[str, Any]) -> RelationRecord:
        encoded = _encode_work_package_ref(work_package_ref)
        response = await self._transport.post_json(f"work_packages/{encoded}/relations", json_body=payload)
        return self.to_record(response)

    async def update(self, relation_id: int, payload: dict[str, Any]) -> RelationRecord:
        response = await self._transport.patch_json(f"relations/{relation_id}", json_body=payload)
        return self.to_record(response)

    async def delete(self, relation_id: int) -> None:
        await self._transport.delete(f"relations/{relation_id}")
