"""HTTP-backed MembershipApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_link_title`/`_id_from_href`/`link_to_api_path`/`SUBJECT_LIMIT` are shared
via `app/adapters/_text.py`; `link_to_api_path` rejects an href that leaves the
instance BEFORE any authenticated request is made.
"""

from __future__ import annotations

from functools import partial
from typing import Any
from urllib.parse import parse_qsl

from ...models import MembershipSummary
from ..ports.membership_api import MembershipFormResult, MembershipPage, MembershipRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT, link_to_api_path
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import normalize_form_validation_errors as _normalize_validation_errors
from ._text import trim_text as _trim_text


def normalize_membership(payload: dict[str, Any]) -> MembershipSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Policy decision the Service
    applies after this returns, not something the adapter does. No web `url`
    field: OpenProject has no bare `/memberships/:id` show route at all
    (only nested user-scoped create/update/destroy).
    """
    links = payload.get("_links", {})
    roles = links.get("roles", [])
    return MembershipSummary(
        id=int(payload["id"]),
        principal_id=_id_from_href(links.get("principal", {}).get("href")),
        principal_name=_link_title(links.get("principal")),
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project_name=_link_title(links.get("project")),
        role_ids=[
            role_id
            for role in roles
            if isinstance(role, dict)
            if (role_id := _id_from_href(role.get("href"))) is not None
        ],
        role_names=[
            title
            for role in roles
            if isinstance(role, dict)
            if (title := _trim_text(role.get("title"), limit=SUBJECT_LIMIT)) is not None
        ],
        can_update="update" in links,
        can_update_immediately="updateImmediately" in links,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxMembershipApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._link_to_api_path = partial(link_to_api_path, base_url=base_url, api_prefix=api_prefix)

    def _record(self, payload: dict[str, Any]) -> MembershipRecord:
        return MembershipRecord(
            summary=normalize_membership(payload),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_for_project(self, project_memberships_href: str, *, offset: int, page_size: int) -> MembershipPage:
        # httpx's params= REPLACES a URL's existing query string rather than
        # merging with it, so offset/pageSize must be merged into the href's
        # own query (e.g. its "filters=...") ourselves, not passed as separate
        # params. The quirk is fully contained inside this adapter method;
        # callers (MembershipService) pass a bare href and never see
        # parse_qsl at all.
        path = self._link_to_api_path(project_memberships_href)
        base_path, _, query = path.partition("?")
        merged_params = dict(parse_qsl(query))
        merged_params.update({"offset": str(offset), "pageSize": str(page_size)})
        payload = await self._transport.get_json(base_path, params=merged_params)
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements]
        return MembershipPage(records=records, server_total=int(payload.get("total", len(records))))

    async def get(self, membership_id: int) -> MembershipRecord:
        return self._record(await self._transport.get_json(f"memberships/{membership_id}"))

    async def create_form(self, payload: dict[str, Any]) -> MembershipFormResult:
        return self._form_result(await self._transport.post_json("memberships/form", json_body=payload))

    async def update_form(self, membership_id: int, payload: dict[str, Any]) -> MembershipFormResult:
        return self._form_result(
            await self._transport.post_json(f"memberships/{membership_id}/form", json_body=payload)
        )

    async def commit_create(self, payload: dict[str, Any]) -> MembershipSummary:
        response = await self._transport.post_json("memberships", json_body=payload)
        return normalize_membership(response)

    async def commit_update(self, membership_id: int, payload: dict[str, Any]) -> MembershipSummary:
        response = await self._transport.patch_json(f"memberships/{membership_id}", json_body=payload)
        return normalize_membership(response)

    async def delete(self, membership_id: int) -> None:
        await self._transport.delete(f"memberships/{membership_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> MembershipFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return MembershipFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
