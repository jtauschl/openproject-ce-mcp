"""HTTP-backed EmojiReactionApi adapter (ADR 0001, OPM-318 third consumer).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`SUBJECT_LIMIT` come from `app/adapters/_text.py`
-- verified against client.py's real `normalize_emoji_reaction`
(client.py:2910-2924): this normalizer needs only `trim_text` (per-user
title truncation) -- no id-from-href, no web-URL builder, since
EmojiReactionSummary carries no id/url field at all.
"""

from __future__ import annotations

from typing import Any

from ...models import EmojiReactionSummary
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_emoji_reaction(payload: dict[str, Any]) -> EmojiReactionSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_emoji_reaction, minus the
    _apply_hidden_fields call -- masking is a Service-layer concern applied
    after this returns (same pattern as every other migrated normalize_*).
    """
    users = [
        _trim_text(u.get("title"), limit=SUBJECT_LIMIT) or ""
        for u in payload.get("_links", {}).get("reactingUsers", [])
        if isinstance(u, dict)
    ]
    return EmojiReactionSummary(
        reaction=payload.get("reaction", ""),
        emoji=payload.get("emoji"),
        count=int(payload.get("reactionsCount", 0)),
        users=[u for u in users if u],
    )


def normalize_emoji_reactions(payload: dict[str, Any]) -> list[EmojiReactionSummary]:
    """Verbatim port of client.py's `_emoji_reactions_result`'s element-mapping
    half (the Result-wrapper construction itself is a Service-layer concern,
    since count/results belong to EmojiReactionListResult, not this Port)."""
    elements = payload.get("_embedded", {}).get("elements", [])
    return [normalize_emoji_reaction(item) for item in elements if isinstance(item, dict)]


class HttpxEmojiReactionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_work_package(self, work_package_id: int) -> list[EmojiReactionSummary]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/activities_emoji_reactions")
        return normalize_emoji_reactions(payload)

    async def get_activity(self, activity_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"activities/{activity_id}")

    async def toggle(self, activity_id: int, reaction: str) -> list[EmojiReactionSummary]:
        payload = await self._transport.patch_json(
            f"activities/{activity_id}/emoji_reactions",
            json_body={"reaction": reaction},
        )
        return normalize_emoji_reactions(payload)
