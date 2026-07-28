"""Emoji Reactions Domain API port (ADR 0001, OPM-318 third consumer).

Narrow: list (scoped to one work package) + get_activity (used only by
toggle()'s activity->work_package link resolution) + toggle (PATCH, returns
the full reaction collection for that activity afterwards).

No `to_detail`: `EmojiReactionSummary` IS the only normalized shape this
domain has (no separate Detail model exists in models.py), matching File
Links'/Watchers' precedent.
"""

from __future__ import annotations

from typing import Any, Protocol

from ...models import EmojiReactionSummary


class EmojiReactionApi(Protocol):
    """Narrow, Emoji-Reactions-only Domain API port. EmojiReactionService
    depends on this Protocol, never on HttpxEmojiReactionApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[EmojiReactionSummary]: ...
    async def get_activity(self, activity_id: int) -> dict[str, Any]: ...
    async def toggle(self, activity_id: int, reaction: str) -> list[EmojiReactionSummary]: ...
