"""HTTP-backed MembershipApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). Contains small,
deliberately duplicated private copies of `_trim_text`/`_link_title`/
`_id_from_href`/`_normalize_validation_errors`/`_origin_from_url` (+
`SUBJECT_LIMIT`) and of `_link_to_api_path` (see HttpxProjectApi's copy of the
same name for the full rationale: an absolute href whose origin differs from
this instance's configured origin is rejected BEFORE any authenticated
request is made) -- duplicated rather than imported from client.py to avoid
`app/` importing from `client.py`. Unify only once every domain has migrated.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse

from ...models import MembershipSummary
from ..errors import OpenProjectServerError
from ..ports.membership_api import MembershipFormResult, MembershipPage, MembershipRecord
from ..transport.protocol import Transport

SUBJECT_LIMIT = 255


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = None
        if isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_membership(payload: dict[str, Any], *, base_url: str) -> MembershipSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_membership, minus the
    _apply_hidden_fields call -- hidden-field masking is a Policy decision the
    Service applies after this returns, not something the adapter does.
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
        url=urljoin(f"{base_url.rstrip('/')}/", f"memberships/{payload['id']}"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxMembershipApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)
        self._api_prefix = api_prefix

    def _link_to_api_path(self, href: str) -> str:
        """Same-origin-checked href -> API-relative path (with the API prefix
        stripped, since the Transport's own base URL already includes it).

        Verbatim port of client.py's _link_to_api_path: an absolute href whose
        origin differs from this instance's configured origin is rejected
        BEFORE any authenticated request is made -- a manipulated/foreign
        `memberships` href must never be contacted.
        """
        parsed = urlparse(href)
        if not parsed.scheme:
            path = parsed.path or href
        else:
            if _origin_from_url(href) != self._origin:
                raise OpenProjectServerError("OpenProject returned an unexpected link host.")
            path = parsed.path
        relative_path = path[len(self._api_prefix) :] if path.startswith(self._api_prefix) else path.lstrip("/")
        if parsed.query:
            return f"{relative_path}?{parsed.query}"
        return relative_path

    def _record(self, payload: dict[str, Any]) -> MembershipRecord:
        return MembershipRecord(
            summary=normalize_membership(payload, base_url=self._base_url),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_for_project(self, project_memberships_href: str, *, offset: int, page_size: int) -> MembershipPage:
        # httpx's params= REPLACES a URL's existing query string rather than
        # merging with it, so offset/pageSize must be merged into the href's
        # own query (e.g. its "filters=...") ourselves, not passed as separate
        # params -- verbatim port of client.py's former inline merge. The
        # quirk is fully contained inside this adapter method; callers
        # (MembershipService) pass a bare href and never see parse_qsl at all.
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
        return normalize_membership(response, base_url=self._base_url)

    async def commit_update(self, membership_id: int, payload: dict[str, Any]) -> MembershipSummary:
        response = await self._transport.patch_json(f"memberships/{membership_id}", json_body=payload)
        return normalize_membership(response, base_url=self._base_url)

    async def delete(self, membership_id: int) -> None:
        await self._transport.delete(f"memberships/{membership_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> MembershipFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return MembershipFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
