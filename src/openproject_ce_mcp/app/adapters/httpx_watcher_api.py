"""HTTP-backed WatcherApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`SUBJECT_LIMIT`/`web_url` come from
`app/adapters/_text.py` -- verified against client.py's real
`normalize_watcher` (client.py:4375-4385): this normalizer needs only
`trim_text` (name truncation, with a "User {id}" fallback) and `web_url`
(the `url` field builder). `web_url` lives in `_text.py`, shared across
adapters, rather than as a local copy here.
"""

from __future__ import annotations

from typing import Any

from ...models import WatcherSummary
from ..api_href import api_href as _api_href
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text
from ._text import web_url as _web_url


def normalize_watcher(payload: dict[str, Any], *, base_url: str) -> WatcherSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_watcher, minus the
    _apply_hidden_fields call -- masking is a Service-layer concern applied
    after this returns (same pattern as every other migrated normalize_*).
    """
    watcher_id = int(payload["id"])
    return WatcherSummary(
        id=watcher_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"User {watcher_id}",
        login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
        url=_web_url(f"users/{watcher_id}", base_url=base_url),
    )


class HttpxWatcherApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._base_url = base_url
        self._api_prefix = api_prefix

    def _record(self, payload: dict[str, Any]) -> WatcherSummary:
        return normalize_watcher(payload, base_url=self._base_url)

    async def list_for_work_package(self, work_package_id: int) -> list[WatcherSummary]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/watchers")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def get_user(self, user_id: int) -> WatcherSummary:
        return self._record(await self._transport.get_json(f"users/{user_id}"))

    async def add(self, work_package_id: int, user_id: int) -> WatcherSummary:
        response = await self._transport.post_json(
            f"work_packages/{work_package_id}/watchers",
            json_body={"_links": {"user": {"href": _api_href(f"users/{user_id}", api_prefix=self._api_prefix)}}},
        )
        return self._record(response)

    async def remove(self, work_package_id: int, user_id: int) -> None:
        await self._transport.delete(f"work_packages/{work_package_id}/watchers/{user_id}")
