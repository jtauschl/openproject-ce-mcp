"""HTTP-backed GroupApi adapter (15th migrated domain).

No `httpx` import (depends on the `Transport` Protocol only). No
`create_form`/`update_form`: verified against `client.py`'s `create_group`/
`update_group`, neither calls a `groups/form` endpoint -- writes go
directly to `POST groups`/`PATCH groups/{id}`.

`normalize_group`/`normalize_group_detail` are verbatim ports of
`client.py`'s originals, minus the `_apply_hidden_fields` call (the Service
is the sole masking point). `member_count` tolerates both the real API
shape (`_embedded.members` as a flat array) and a `{count, ...}`/
`{total, ...}` collection-object shape defensively, matching the original's
own tolerance.

`web_url` (imported from `_text.py`) replaces a local copy here, promoted
once it crossed the "3+ identical copies" threshold across adapters.
"""

from __future__ import annotations

from typing import Any

from ...models import GroupDetail, GroupSummary
from ..pagination import paginate_all
from ..ports.group_api import GroupRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import can_update_from_links as _can_update_from_links
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _link_to_web_url
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text
from ._text import web_url as _web_url


def _member_count(payload: dict[str, Any]) -> int:
    # OpenProject's group representer emits members differently depending on
    # the endpoint: a single-item GET (get) embeds a flat array under
    # _embedded.members, but the list endpoint (list_all) only ever carries
    # _links.members (a bare array of HAL links, no _embedded.members at
    # all) -- verified live against both endpoints. A {count,...}/
    # {total,...} collection object is tolerated defensively too,
    # in case a future version reintroduces it, but neither of the two real
    # shapes above use it.
    embedded_members = payload.get("_embedded", {}).get("members", [])
    if isinstance(embedded_members, dict):
        return int(embedded_members.get("count") or embedded_members.get("total") or 0)
    if isinstance(embedded_members, list) and embedded_members:
        return len(embedded_members)
    link_members = payload.get("_links", {}).get("members", [])
    return len(link_members) if isinstance(link_members, list) else 0


def normalize_group(payload: dict[str, Any], *, base_url: str) -> GroupSummary:
    """Pure HAL->model translation. Verbatim port of client.py's
    normalize_group, minus the _apply_hidden_fields call.
    """
    links = payload.get("_links", {})
    return GroupSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
        member_count=_member_count(payload),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        can_update=_can_update_from_links(links),
        can_delete=bool(links.get("delete")),
        url=_web_url(f"groups/{payload['id']}", base_url=base_url),
    )


def normalize_group_detail(
    payload: dict[str, Any], *, base_url: str, origin: str, summary: GroupSummary | None = None
) -> GroupDetail:
    """Verbatim port of client.py's normalize_group_detail: field-copies
    from the already-computed summary rather than re-deriving it.

    `summary` lets a caller that already built a `GroupSummary` for the same
    payload (see `_record()`) pass it in directly instead of paying for a
    second `normalize_group()` call.
    """
    if summary is None:
        summary = normalize_group(payload, base_url=base_url)
    members = payload.get("_embedded", {}).get("members", [])
    if isinstance(members, dict):
        members = members.get("elements", [])
    member_names: list[str] = []
    if isinstance(members, list):
        for item in members:
            if isinstance(item, dict):
                label = _trim_text(item.get("name"), limit=SUBJECT_LIMIT) or _link_title(
                    item.get("_links", {}).get("self")
                )
                if label:
                    member_names.append(label)
    memberships_url = _link_to_web_url(
        payload.get("_links", {}).get("memberships", {}).get("href"), base_url=base_url, origin=origin
    )
    return GroupDetail(
        id=summary.id,
        name=summary.name,
        member_count=summary.member_count,
        members=member_names,
        memberships_url=memberships_url,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        url=summary.url,
    )


class HttpxGroupApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)

    def _record(self, payload: dict[str, Any]) -> GroupRecord:
        # to_detail is a lazy thunk: list_groups()/list_groups_search() build
        # a GroupRecord per row, but GroupService.list_groups() never reads
        # .to_detail on that path (only get_group() does) -- deferring the
        # detail-only parsing (members, memberships_url) avoids paying for it
        # on every list row. The thunk still passes the already-computed
        # summary through, so calling it never re-derives a second
        # GroupSummary either.
        summary = normalize_group(payload, base_url=self._base_url)
        return GroupRecord(
            summary=summary,
            to_detail=lambda: normalize_group_detail(
                payload, base_url=self._base_url, origin=self._origin, summary=summary
            ),
        )

    async def list_groups(self, *, offset: int, page_size: int) -> tuple[list[GroupRecord], int]:
        payload = await self._transport.get_json("groups", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def list_groups_search(self, *, page_size: int) -> list[GroupRecord]:
        # Walk every server page for the caller to filter in-memory -- no
        # server-side name filter exists to delegate to. Groups is genuinely
        # OffsetPaginatedCollection server-side (verified against op-sources),
        # so a single bounded fetch capped at page_size (this method's prior
        # behavior) would silently hide any match beyond that cap once the
        # real group count exceeded it (found via a full-diff Codex review on
        # release/0.3.4, ported here).
        return await paginate_all(
            lambda offset, size: self.list_groups(offset=offset, page_size=size),
            page_size=page_size,
            key=lambda r: r.summary.id,
        )

    async def get_group(self, group_id: int) -> GroupRecord:
        return self._record(await self._transport.get_json(f"groups/{group_id}"))

    async def get_member_ids(self, group_id: int) -> set[int]:
        # Raw _links.members href->id extraction -- verbatim port of
        # client.py's update_group member-diff step. GroupDetail.members
        # only carries display names, so this reads the raw payload
        # directly rather than going through normalize_group_detail.
        payload = await self._transport.get_json(f"groups/{group_id}")
        member_links = payload.get("_links", {}).get("members", [])
        if not isinstance(member_links, list):
            return set()
        ids: set[int] = set()
        for link in member_links:
            if isinstance(link, dict):
                uid = _id_from_href(link.get("href"))
                if uid is not None:
                    ids.add(int(uid))
        return ids

    async def commit_create(self, payload: dict[str, Any]) -> GroupSummary:
        response = await self._transport.post_json("groups", json_body=payload)
        return normalize_group(response, base_url=self._base_url)

    async def commit_update(self, group_id: int, payload: dict[str, Any]) -> GroupSummary:
        response = await self._transport.patch_json(f"groups/{group_id}", json_body=payload)
        return normalize_group(response, base_url=self._base_url)

    async def commit_delete(self, group_id: int) -> None:
        await self._transport.delete(f"groups/{group_id}")


__all__ = ["HttpxGroupApi", "normalize_group", "normalize_group_detail"]
