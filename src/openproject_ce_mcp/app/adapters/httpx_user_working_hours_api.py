"""HTTP-backed UserWorkingHoursApi adapter. No `httpx` import.

`list_for_user`: GET users/{user_ref}/working_hours -- UNPAGINATED (see port
docstring), server-ordered `valid_from desc`.

`get`: GET users/{user_ref}/working_hours/{id} -- real single-resource GET,
unlike UserNonWorkingTimeApi.

`create`: POST users/{user_ref}/working_hours, flat payload (`validFrom` plus
whichever of the 7 weekday-hours fields/`availabilityFactor` were actually
supplied -- only the non-None ones are included, matching every other
create() that omits absent optional fields rather than sending explicit
nulls).

`update`/`delete`: PATCH/DELETE users/{user_ref}/working_hours/{id}. `update`'s
`payload` is passed straight through, already camelCase-keyed by the Service
(same convention as `httpx_reminder_api.py`'s `update`/`board_service.py`'s
payload construction -- the Service builds wire-ready keys directly, the
Adapter never re-maps them).

Field casing: `UserWorkingHoursRepresenter` declares plain Roar
`date_property :valid_from` and `property :monday_hours` etc. (verified
against source) -- Representable's default camelCase JSON-key inference
applies, hence `validFrom`/`mondayHours`/.../`availabilityFactor` here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import UserWorkingHoursSummary
from ..ports.user_working_hours_api import UserWorkingHoursRecord
from ..transport.protocol import Transport
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments


def normalize_user_working_hours(payload: dict[str, Any]) -> UserWorkingHoursSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    links = payload.get("_links", {})
    user_link = links.get("user")
    user_href = user_link.get("href") if isinstance(user_link, dict) else None
    return UserWorkingHoursSummary(
        id=int(payload["id"]),
        user_id=int(user_href.rsplit("/", 1)[-1]) if user_href else None,
        user_name=user_link.get("title") if isinstance(user_link, dict) else None,
        valid_from=payload.get("validFrom"),
        monday_hours=payload.get("mondayHours"),
        tuesday_hours=payload.get("tuesdayHours"),
        wednesday_hours=payload.get("wednesdayHours"),
        thursday_hours=payload.get("thursdayHours"),
        friday_hours=payload.get("fridayHours"),
        saturday_hours=payload.get("saturdayHours"),
        sunday_hours=payload.get("sundayHours"),
        availability_factor=payload.get("availabilityFactor"),
    )


class HttpxUserWorkingHoursApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> UserWorkingHoursRecord:
        return UserWorkingHoursRecord(summary=normalize_user_working_hours(payload))

    def _path(self, user_ref: str, *segments: str) -> str:
        safe_ref = _reject_path_traversal_segments(user_ref, field_name="user_ref")
        parts = [f"users/{quote(safe_ref, safe='')}/working_hours", *segments]
        return "/".join(parts)

    async def list_for_user(
        self, user_ref: str, *, offset: int, page_size: int
    ) -> tuple[list[UserWorkingHoursRecord], int]:
        # NB: OpenProject's UserWorkingHoursCollectionRepresenter subclasses
        # UnpaginatedCollection (not OffsetPaginatedCollection) -- verified
        # against source. The server ignores offset/pageSize entirely and
        # always returns every record. Sent here for interface symmetry /
        # forward-compat only; do not assume this call has already sliced
        # the result. See UserWorkingHoursService.list_for_user for the
        # client-side slicing this requires.
        payload = await self._transport.get_json(
            self._path(user_ref), params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        records = [self._record(item) for item in elements]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, user_ref: str, working_hours_id: int) -> UserWorkingHoursRecord:
        response = await self._transport.get_json(self._path(user_ref, str(working_hours_id)))
        return self._record(response)

    async def create(
        self,
        user_ref: str,
        *,
        valid_from: str,
        monday_hours: float | None,
        tuesday_hours: float | None,
        wednesday_hours: float | None,
        thursday_hours: float | None,
        friday_hours: float | None,
        saturday_hours: float | None,
        sunday_hours: float | None,
        availability_factor: float | None,
    ) -> UserWorkingHoursRecord:
        body: dict[str, Any] = {"validFrom": valid_from}
        field_map = {
            "mondayHours": monday_hours,
            "tuesdayHours": tuesday_hours,
            "wednesdayHours": wednesday_hours,
            "thursdayHours": thursday_hours,
            "fridayHours": friday_hours,
            "saturdayHours": saturday_hours,
            "sundayHours": sunday_hours,
            "availabilityFactor": availability_factor,
        }
        for key, value in field_map.items():
            if value is not None:
                body[key] = value
        response = await self._transport.post_json(self._path(user_ref), json_body=body)
        return self._record(response)

    async def update(self, user_ref: str, working_hours_id: int, *, payload: dict[str, Any]) -> UserWorkingHoursRecord:
        response = await self._transport.patch_json(self._path(user_ref, str(working_hours_id)), json_body=payload)
        return self._record(response)

    async def delete(self, user_ref: str, working_hours_id: int) -> None:
        await self._transport.delete(self._path(user_ref, str(working_hours_id)))
