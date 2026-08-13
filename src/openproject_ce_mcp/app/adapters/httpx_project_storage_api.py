"""HTTP-backed ProjectStorageApi adapter.

No `httpx` import (Transport Protocol only). `storage_id`/`storage_name` use
the same id_from_href/link_title extraction as FileLinkSummary's storage_id/
storage_name (httpx_file_link_api.py) -- deliberate consistency, not
incidental duplication (both read the *same* `_links.storage` shape).

No pagination handling here: ProjectStorageCollectionRepresenter subclasses
UnpaginatedCollection (verified against source) -- offset/pageSize are sent
for interface symmetry only and the server ignores them, always returning
every project_storage. See ProjectStorageService.list_project_storages for
the client-side `paginate_client` slicing this requires.
"""

from __future__ import annotations

from typing import Any

from ...models import ProjectStorageDetail, ProjectStorageSummary
from ..ports.project_storage_api import ProjectStorageRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_project_storage(payload: dict[str, Any]) -> ProjectStorageSummary:
    links = payload.get("_links", {})
    storage_link = links.get("storage")
    project_link = links.get("project")
    return ProjectStorageSummary(
        id=int(payload["id"]),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        storage_id=_id_from_href(storage_link.get("href")) if isinstance(storage_link, dict) else None,
        storage_name=_link_title(storage_link),
        project_folder_mode=payload.get("projectFolderMode"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_project_storage_detail(
    payload: dict[str, Any], *, summary: ProjectStorageSummary | None = None
) -> ProjectStorageDetail:
    if summary is None:
        summary = normalize_project_storage(payload)
    links = payload.get("_links", {})
    creator_link = links.get("creator")
    return ProjectStorageDetail(
        id=summary.id,
        project_id=summary.project_id,
        project=summary.project,
        storage_id=summary.storage_id,
        storage_name=summary.storage_name,
        project_folder_mode=summary.project_folder_mode,
        creator_id=_id_from_href(creator_link.get("href")) if isinstance(creator_link, dict) else None,
        creator=_trim_text(creator_link.get("title") if isinstance(creator_link, dict) else None, limit=SUBJECT_LIMIT),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


class HttpxProjectStorageApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> ProjectStorageRecord:
        summary = normalize_project_storage(payload)
        return ProjectStorageRecord(
            summary=summary,
            to_detail=lambda: normalize_project_storage_detail(payload, summary=summary),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ProjectStorageRecord], int]:
        # NB: OpenProject's ProjectStoragesAPI mounts a hand-rolled Index (via
        # ParamsToQueryService) with ProjectStorageCollectionRepresenter,
        # which subclasses UnpaginatedCollection (not
        # OffsetPaginatedCollection) -- verified against OpenProject's own API
        # implementation. The server ignores offset/pageSize entirely and
        # always returns every project_storage, `total` included. Sent here
        # for interface symmetry / forward-compat only; do not assume this
        # call has already sliced the result. See
        # ProjectStorageService.list_project_storages for the client-side
        # slicing this requires.
        payload = await self._transport.get_json(
            "project_storages", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, project_storage_id: int) -> ProjectStorageRecord:
        return self._record(await self._transport.get_json(f"project_storages/{project_storage_id}"))


__all__ = ["HttpxProjectStorageApi", "normalize_project_storage", "normalize_project_storage_detail"]
