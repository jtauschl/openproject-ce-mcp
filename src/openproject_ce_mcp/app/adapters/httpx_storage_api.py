"""HTTP-backed StorageApi adapter.

No `httpx` import (Transport Protocol only). Provider-polymorphic
normalization: `provider_type` is derived from the `type` link's href (a
URN, e.g. "urn:openproject-org:api:v3:storages:Nextcloud") by taking the
final ":"-delimited segment -- verified directly against
StorageRepresenter's `link_without_resource :type` getter
(`type.split(":").last` on the Ruby side), so this is not an inference, it
is the literal algorithm OpenProject itself uses to derive the same link's
`title`.

`authorizationState`'s href is ALSO a URN (e.g.
"urn:...:storages:authorization:FailedAuthorization"), but unlike `type`,
its human string is carried in the link's separate `title` key (an I18n
string), not encoded in the href suffix in a way meant for direct display.
This adapter normalizes from the href suffix (not the title, which is
locale-dependent free text) into a small fixed snake_case vocabulary via an
explicit map, rather than a naive `.rsplit(":", 1)[-1].casefold()` --
verified against StorageRepresenter's four literal URN constants
(Connected/NotConnected/FailedAuthorization/Error), which are PascalCase,
not directly snake-case-able by a mechanical transform for the two-word
values.

No pagination handling here: StorageCollectionRepresenter subclasses
UnpaginatedCollection (verified against source) -- offset/pageSize are sent
for interface symmetry only and the server ignores them, always returning
every storage. See StorageService.list_storages for the client-side
`paginate_client` slicing this requires.
"""

from __future__ import annotations

from typing import Any

from ...models import StorageDetail, StorageSummary
from ..ports.storage_api import StorageRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text

_AUTHORIZATION_STATE_MAP = {
    "Connected": "connected",
    "NotConnected": "not_connected",
    "FailedAuthorization": "failed_authorization",
    "Error": "error",
}

_AUTHENTICATION_METHOD_MAP = {
    "TwoWayOAuth2": "two_way_oauth2",
    "OAuth2SSO": "oauth2_sso",
    "OAuth2SSOFallbackToTwoWayOAuth2": "oauth2_sso_fallback_to_two_way_oauth2",
}


def _urn_suffix(link: Any) -> str | None:
    href = link.get("href") if isinstance(link, dict) else None
    if isinstance(href, str) and ":" in href:
        return href.rsplit(":", 1)[-1]
    return None


def _provider_type(links: dict[str, Any]) -> str:
    return _urn_suffix(links.get("type")) or "Unknown"


def _authentication_method(links: dict[str, Any]) -> str | None:
    suffix = _urn_suffix(links.get("authenticationMethod"))
    if suffix is None:
        return None
    return _AUTHENTICATION_METHOD_MAP.get(suffix, suffix)


def _authorization_state(links: dict[str, Any]) -> str | None:
    suffix = _urn_suffix(links.get("authorizationState"))
    if suffix is None:
        return None
    return _AUTHORIZATION_STATE_MAP.get(suffix, suffix)


def normalize_storage(payload: dict[str, Any]) -> StorageSummary:
    links = payload.get("_links", {})
    provider_type = _provider_type(links)
    is_nextcloud = provider_type == "Nextcloud"
    is_one_drive = provider_type == "OneDrive"
    origin_link = links.get("origin")
    host = origin_link.get("href") if isinstance(origin_link, dict) else None
    return StorageSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Storage {payload.get('id')}",
        provider_type=provider_type,
        host=host,
        configured=bool(payload.get("configured", False)),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        has_application_password=payload.get("hasApplicationPassword") if is_nextcloud else None,
        forbidden_file_name_characters=payload.get("forbiddenFileNameCharacters") if is_nextcloud else None,
        tenant_id=payload.get("tenant_id") if is_one_drive else None,
        drive_id=payload.get("drive_id") if is_one_drive else None,
    )


def normalize_storage_detail(payload: dict[str, Any], *, summary: StorageSummary | None = None) -> StorageDetail:
    if summary is None:
        summary = normalize_storage(payload)
    links = payload.get("_links", {})
    return StorageDetail(
        id=summary.id,
        name=summary.name,
        provider_type=summary.provider_type,
        host=summary.host,
        configured=summary.configured,
        authorization_state=_authorization_state(links),
        authentication_method=_authentication_method(links),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        has_application_password=summary.has_application_password,
        forbidden_file_name_characters=summary.forbidden_file_name_characters,
        tenant_id=summary.tenant_id,
        drive_id=summary.drive_id,
    )


class HttpxStorageApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> StorageRecord:
        summary = normalize_storage(payload)
        return StorageRecord(summary=summary, to_detail=lambda: normalize_storage_detail(payload, summary=summary))

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[StorageRecord], int]:
        # NB: OpenProject's StoragesAPI mounts Endpoints::Index with
        # StorageCollectionRepresenter, which subclasses UnpaginatedCollection
        # (not OffsetPaginatedCollection) -- verified against OpenProject's
        # own API implementation. The server ignores offset/pageSize entirely
        # and always returns every storage, `total` included. Sent here for
        # interface symmetry / forward-compat only; do not assume this call
        # has already sliced the result. See StorageService.list_storages for
        # the client-side slicing this requires.
        payload = await self._transport.get_json("storages", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, storage_id: int) -> StorageRecord:
        return self._record(await self._transport.get_json(f"storages/{storage_id}"))

    async def commit_create(self, payload: dict[str, Any]) -> StorageDetail:
        return normalize_storage_detail(await self._transport.post_json("storages", json_body=payload))

    async def commit_update(self, storage_id: int, payload: dict[str, Any]) -> StorageDetail:
        return normalize_storage_detail(await self._transport.patch_json(f"storages/{storage_id}", json_body=payload))

    async def commit_delete(self, storage_id: int) -> None:
        await self._transport.delete(f"storages/{storage_id}")


__all__ = ["HttpxStorageApi", "normalize_storage", "normalize_storage_detail"]
