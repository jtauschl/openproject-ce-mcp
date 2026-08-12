"""HTTP-backed UserNonWorkingTimeApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).

`list_for_user`: GET users/{user_ref}/non_working_times?year=... -- response
is UNPAGINATED (see port docstring); `total` read directly from the response
payload same as every other adapter (falls back to len(records) if absent),
but the Service must not trust it as a pagination signal (RoleService's
documented caveat applies identically here).

`create`: POST users/{user_ref}/non_working_times with a flat (non-bulk)
body -- unlike WikiPageLink's bulk `_embedded/elements` shape,
UserNonWorkingTime uses OpenProject's generic `API::V3::Utilities::Endpoints
::Create` (verified against source: `non_working_times_by_user_api.rb`
mounts it directly, with no `ParsePageLinkParamsService`-style bulk-body
requirement), which accepts a flat payload matching
`UserNonWorkingTimePayloadRepresenter` directly (`{"startDate": ...,
"endDate": ...}`).

`update`/`delete`: PATCH/DELETE users/{user_ref}/non_working_times/{id}.

Field casing: `UserNonWorkingTimeRepresenter` declares plain Roar
`date_property :start_date`/`:end_date` (verified against source) --
Representable's default camelCase JSON-key inference applies, matching every
other adapter in this codebase (e.g. `httpx_time_entry_api.py`'s
`spentOn`/`startTime`), hence `startDate`/`endDate` here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import UserNonWorkingTimeSummary
from ..ports.user_non_working_time_api import UserNonWorkingTimeRecord
from ..transport.protocol import Transport
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments


def normalize_user_non_working_time(payload: dict[str, Any]) -> UserNonWorkingTimeSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    user_link = links.get("user")
    user_href = user_link.get("href") if isinstance(user_link, dict) else None
    return UserNonWorkingTimeSummary(
        id=int(payload["id"]),
        user_id=int(user_href.rsplit("/", 1)[-1]) if user_href else None,
        user_name=user_link.get("title") if isinstance(user_link, dict) else None,
        start_date=payload.get("startDate"),
        end_date=payload.get("endDate"),
    )


class HttpxUserNonWorkingTimeApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> UserNonWorkingTimeRecord:
        return UserNonWorkingTimeRecord(summary=normalize_user_non_working_time(payload))

    def _path(self, user_ref: str, *segments: str) -> str:
        safe_ref = _reject_path_traversal_segments(user_ref, field_name="user_ref")
        parts = [f"users/{quote(safe_ref, safe='')}/non_working_times", *segments]
        return "/".join(parts)

    async def list_for_user(
        self, user_ref: str, *, year: int | None, offset: int, page_size: int
    ) -> tuple[list[UserNonWorkingTimeRecord], int]:
        # NB: OpenProject's UserNonWorkingTimeCollectionRepresenter subclasses
        # UnpaginatedCollection (not OffsetPaginatedCollection) -- verified
        # against source. The server ignores offset/pageSize entirely and
        # always returns every record for the (defaulted-to-current) year.
        # Sent here for interface symmetry / forward-compat only; do not
        # assume this call has already sliced the result. See
        # UserNonWorkingTimeService.list_for_user for the client-side
        # slicing this requires.
        params = {"offset": str(offset), "pageSize": str(page_size)}
        if year is not None:
            params["year"] = str(year)
        payload = await self._transport.get_json(self._path(user_ref), params=params)
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        records = [self._record(item) for item in elements]
        total = int(payload.get("total", len(records)))
        return records, total

    async def create(self, user_ref: str, *, start_date: str, end_date: str) -> UserNonWorkingTimeRecord:
        response = await self._transport.post_json(
            self._path(user_ref), json_body={"startDate": start_date, "endDate": end_date}
        )
        return self._record(response)

    async def update(
        self, user_ref: str, non_working_time_id: int, *, payload: dict[str, Any]
    ) -> UserNonWorkingTimeRecord:
        response = await self._transport.patch_json(self._path(user_ref, str(non_working_time_id)), json_body=payload)
        return self._record(response)

    async def delete(self, user_ref: str, non_working_time_id: int) -> None:
        await self._transport.delete(self._path(user_ref, str(non_working_time_id)))
