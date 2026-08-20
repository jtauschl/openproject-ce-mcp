"""HTTP-backed ExtendedMetadataApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `FORMATTABLE_LIMIT`
(value 1_200) is a local constant, not shared via `_text.py`, matching
Documents/News/Versions/Projects' own local duplication of the same constant.

render_text is the only method that POSTs a raw (non-JSON) body -- it uses
`Transport.post_raw_json` to POST raw content with custom headers and parse
a JSON response.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import (
    CustomOptionSummary,
    HelpTextSummary,
    NonWorkingDay,
    RenderedText,
    WorkingDay,
)
from ..ports.extended_metadata_api import (
    CustomOptionRecord,
    HelpTextRecord,
    NonWorkingDayRecord,
    RenderedTextRecord,
    WorkingDayRecord,
)
from ..transport.protocol import Transport
from ._text import trim_text as _trim_text

FORMATTABLE_LIMIT = 1_200


def normalize_help_text(payload: dict[str, Any]) -> HelpTextSummary:
    """Pure HAL->model translation. Excludes hidden-field masking: this
    entity has no hidden-field masking at the adapter level (masking, if
    any, is a Service-layer concern).

    attribute_caption reads `caption` -- `HelpTextRepresenter` (verified
    against op-sources 16.1/17.7) declares `property :caption` with no
    `as:` rename, not `attributeCaption`.
    """
    help_text_value = payload.get("helpText")
    return HelpTextSummary(
        id=int(payload["id"]),
        attribute_name=payload.get("attribute") or payload.get("attributeName"),
        attribute_caption=payload.get("caption"),
        help_text=_trim_text(
            help_text_value.get("raw") if isinstance(help_text_value, dict) else help_text_value,
            limit=FORMATTABLE_LIMIT,
        ),
    )


def normalize_working_day(payload: dict[str, Any]) -> WorkingDay:
    # day_of_week reads `day` -- WeekDayRepresenter (verified against
    # op-sources 16.1/17.7) declares `property :day`, not `dayOfWeek`.
    return WorkingDay(
        name=payload.get("name", ""),
        day_of_week=int(payload.get("day", 0)),
        working=bool(payload.get("working", True)),
    )


def normalize_non_working_day(payload: dict[str, Any]) -> NonWorkingDay:
    return NonWorkingDay(
        date=payload.get("date", ""),
        name=payload.get("name"),
    )


class HttpxExtendedMetadataApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def render_text(self, *, text: str, format: str) -> RenderedTextRecord:
        endpoint = "render/markdown" if format == "markdown" else "render/plain"
        data = await self._transport.post_raw_json(
            endpoint, content=text.encode("utf-8"), headers={"Content-Type": "text/plain"}
        )
        return RenderedTextRecord(summary=RenderedText(format=format, raw=text, html=data.get("html", "")))

    async def list_help_texts(self) -> list[HelpTextRecord]:
        payload = await self._transport.get_json("help_texts")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [HelpTextRecord(summary=normalize_help_text(item)) for item in elements if isinstance(item, dict)]

    async def get_help_text(self, help_text_id: int) -> HelpTextRecord:
        payload = await self._transport.get_json(f"help_texts/{help_text_id}")
        return HelpTextRecord(summary=normalize_help_text(payload))

    async def list_working_days(self) -> list[WorkingDayRecord]:
        payload = await self._transport.get_json("days/week")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [WorkingDayRecord(summary=normalize_working_day(item)) for item in elements if isinstance(item, dict)]

    async def list_non_working_days(self, *, year: int | None) -> list[NonWorkingDayRecord]:
        params: dict[str, str] | None = None
        if year is not None:
            params = {
                "filters": json.dumps([{"date": {"operator": "<>d", "values": [f"{year}-01-01", f"{year}-12-31"]}}])
            }
        payload = await self._transport.get_json("days/non_working", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            NonWorkingDayRecord(summary=normalize_non_working_day(item)) for item in elements if isinstance(item, dict)
        ]

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionRecord:
        payload = await self._transport.get_json(f"custom_options/{custom_option_id}")
        return CustomOptionRecord(summary=CustomOptionSummary(id=int(payload["id"]), value=payload.get("value")))
