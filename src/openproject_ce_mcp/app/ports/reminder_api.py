"""Reminders Domain API port.

Full CRUD: list (global, not work-package-scoped -- filtered client-side by
project allowlist in the Service) + get (used only when the full normalized
record is needed) + get_remindable_link (a narrower, raw-payload-only fetch
used by update()/delete()'s allowlist check) + create + update + delete.

`get_remindable_link` exists as its own method, not folded into `get()`,
because the allowlist check on update()/delete() reads `_links.remindable`
directly off the raw `GET reminders/{id}` payload WITHOUT normalizing it
into a `ReminderSummary` first -- a payload missing other required fields
(e.g. `id`) still lets the allowlist check run. Routing this through
`get()`/`normalize_reminder` would raise a spurious KeyError on any payload
shape that doesn't need to be fully parsed for this check.

This is not a first-of-its-kind pattern: `app/ports/emoji_reaction_api.py`'s
`get_activity` does the identical thing for the same reason
(`EmojiReactionService.toggle()` reads an activity's `workPackage` link
without normalizing the whole activity). A Port offering a raw-`dict`
method alongside its normalized Record methods, specifically to avoid
forcing full normalization when it isn't needed, is a sanctioned, recurring
shape (see `docs/architecture.md`).

`ReminderRecord.summary` is a LAZY callable, not an eager field: `list_all()`
filters the RAW elements by project allowlist first and normalizes only the
survivors; an eager `summary` field would normalize every record up front,
including ones the Service is about to discard, and would raise a spurious
`KeyError` on a filtered-out record missing an unrelated field (e.g. `id`)
-- the same bug class `get_remindable_link` exists to avoid. Deferring
`summary` until the Service has finished filtering preserves a strict
filter-then-normalize order.

No `to_detail`: `ReminderSummary` IS the only normalized shape this domain
has (no separate Detail model exists in models.py), matching every other
similarly-shaped domain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ReminderSummary


@dataclass(frozen=True)
class ReminderRecord:
    """One reminder as read from the API: a LAZY `summary` callable (see the
    module docstring for why), plus the raw `_links.remindable` link dict.
    `remindable_link` is carried as the RAW link dict, not a pre-extracted
    href/int, because the Service needs to distinguish "no remindable link
    at all" from "link present but unparsable" -- both cases resolve to a
    fail-closed denial.
    """

    summary: Callable[[], ReminderSummary]
    remindable_link: dict[str, Any] | None


class ReminderApi(Protocol):
    """Narrow, Reminders-only Domain API port. ReminderService depends on
    this Protocol, never on HttpxReminderApi concretely (enforced by the
    architecture-boundary test).

    `fetch_page(offset, page_size)` returns the raw HAL page dict (not a
    list of records), because the Service's per-item allowlist check needs
    an HTTP call per candidate work package (`WorkPackageProjectAllowedCheck`)
    -- genuine async I/O per item, not a pure-function predicate over already-
    normalized fields. `fetch_bounded_and_paginate` (app/pagination.py)
    accepts exactly this raw-page-plus-async-`item_allowed` shape, the same
    one `RelationApi.fetch_page`/`to_record` already use for the identical
    reason (Relations' own per-endpoint allowlist check). `to_record`
    converts one raw element into a `ReminderRecord` -- kept synchronous and
    separate from `fetch_page` so the Service can filter raw elements BEFORE
    normalizing (see `ReminderRecord`'s own docstring for why `summary` stays
    lazy). The collection is genuinely `OffsetPaginatedCollection`
    server-side (the same real server-side pagination Roles/Memberships
    already page-walk), so a fixed page size must always be sent -- omitting
    it silently returns only the server's default page instead of every
    reminder.
    """

    async def fetch_page(self, *, offset: int, page_size: int) -> dict[str, Any]: ...
    def to_record(self, payload: dict[str, Any]) -> ReminderRecord: ...
    async def get(self, reminder_id: int) -> ReminderRecord: ...
    async def get_remindable_link(self, reminder_id: int) -> dict[str, Any] | None: ...
    async def create(self, work_package_id: int, payload: dict[str, Any]) -> ReminderRecord: ...
    async def update(self, reminder_id: int, payload: dict[str, Any]) -> ReminderRecord: ...
    async def delete(self, reminder_id: int) -> None: ...
