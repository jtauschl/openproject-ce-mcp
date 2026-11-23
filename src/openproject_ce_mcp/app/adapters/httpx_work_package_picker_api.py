"""HTTP-backed WorkPackagePickerApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). Principals reuse the Principals domain's normalizer, since the assignee
endpoints return the same representation.
"""

from __future__ import annotations

from typing import Any

from ...models import PrincipalSummary, RelationCandidateSummary, WatcherSummary
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT, unnamed
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text
from .httpx_principal_api import normalize_principal
from .httpx_watcher_api import normalize_watcher


def normalize_relation_candidate(payload: dict[str, Any]) -> RelationCandidateSummary:
    """Pure HAL->model translation. Excludes hidden-field masking."""
    links = payload.get("_links", {})
    return RelationCandidateSummary(
        id=int(payload["id"]),
        display_id=payload.get("displayId"),
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or unnamed("work package"),
        type=_link_title(links.get("type")),
        status=_link_title(links.get("status")),
        project=_link_title(links.get("project")),
    )


def _elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]


class HttpxWorkPackagePickerApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def available_assignees(
        self, *, work_package_id: int | None, project_id: int | None
    ) -> list[PrincipalSummary]:
        if work_package_id is not None:
            path = f"work_packages/{work_package_id}/available_assignees"
        else:
            path = f"projects/{project_id}/available_assignees"
        return [normalize_principal(item) for item in _elements(await self._transport.get_json(path))]

    async def relation_candidates(
        self, work_package_id: int, *, query: str | None, relation_type: str | None, page_size: int
    ) -> list[tuple[RelationCandidateSummary, dict[str, Any]]]:
        params: dict[str, str] = {"pageSize": str(page_size)}
        if query is not None:
            params["query"] = query
        if relation_type is not None:
            params["type"] = relation_type
        payload = await self._transport.get_json(
            f"work_packages/{work_package_id}/available_relation_candidates", params=params
        )
        return [(normalize_relation_candidate(item), item) for item in _elements(payload)]

    async def available_watchers(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[WatcherSummary], int]:
        payload = await self._transport.get_json(
            f"work_packages/{work_package_id}/available_watchers",
            params={"offset": str(offset), "pageSize": str(page_size)},
        )
        elements = _elements(payload)
        return [normalize_watcher(item) for item in elements], int(payload.get("total", len(elements)))
