"""HTTP-backed InstanceConfigurationApi adapter.

No `httpx` import (depends on the `Transport` Protocol only).
"""

from __future__ import annotations

from typing import Any

from ...models import InstanceConfiguration
from ..ports.instance_configuration_api import InstanceConfigurationRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_instance_configuration(payload: dict[str, Any]) -> InstanceConfiguration:
    """Pure HAL->model translation. Verbatim port of client.py's
    normalize_instance_configuration, minus the _apply_hidden_fields call.

    Two deliberately asymmetric list-building idioms, preserved exactly:
    `per_page_options` keeps only genuine `int` entries (no coercion of
    non-ints; note `bool` is an `int` subclass, so a stray `True`/`False`
    entry would still pass through as `1`/`0`, matching the original), while
    the three feature-flag lists coerce every entry via `str()`, drop
    blank/whitespace-only results, and sort alphabetically (not payload
    order) -- these are NOT the same normalization strategy and must not be
    unified.
    """
    return InstanceConfiguration(
        host_name=_trim_text(payload.get("hostName"), limit=SUBJECT_LIMIT),
        maximum_attachment_file_size=payload.get("maximumAttachmentFileSize"),
        maximum_api_v3_page_size=payload.get("maximumAPIV3PageSize"),
        per_page_options=[int(item) for item in payload.get("perPageOptions", []) if isinstance(item, int)],
        duration_format=_trim_text(payload.get("durationFormat"), limit=SUBJECT_LIMIT),
        hours_per_day=payload.get("hoursPerDay"),
        days_per_month=payload.get("daysPerMonth"),
        active_feature_flags=sorted(str(item) for item in payload.get("activeFeatureFlags", []) if str(item).strip()),
        available_features=sorted(str(item) for item in payload.get("availableFeatures", []) if str(item).strip()),
        trialling_features=sorted(str(item) for item in payload.get("triallingFeatures", []) if str(item).strip()),
    )


class HttpxInstanceConfigurationApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get_configuration(self) -> InstanceConfigurationRecord:
        payload = await self._transport.get_json("configuration")
        return InstanceConfigurationRecord(summary=normalize_instance_configuration(payload))
