"""Reminders Domain API port.

Full CRUD: list (global, not work-package-scoped -- filtered client-side by
project allowlist in the Service) + get (used only when the full normalized
record is needed) + get_remindable_link (a narrower, raw-payload-only fetch
used by update()/delete()'s allowlist check) + create + update + delete.

`get_remindable_link` exists as its own method, not folded into `get()`,
because client.py's original `_ensure_reminder_project_write_allowed` reads
`_links.remindable` directly off the raw `GET reminders/{id}` payload
WITHOUT normalizing it into a `ReminderSummary` first -- a payload missing
other required fields (e.g. `id`) still lets the allowlist check run.
Routing this through `get()`/`normalize_reminder` would raise a spurious
KeyError on any payload shape the original never needed to fully parse.

This is not a first-of-its-kind pattern: `app/ports/emoji_reaction_api.py`'s
`get_activity` already does the identical thing for the same reason
(`EmojiReactionService.toggle()` reads an activity's `workPackage` link
without normalizing the whole activity). A Port offering a raw-`dict`
method alongside its normalized Record methods, specifically to avoid
forcing full normalization the original code never needed, is a sanctioned,
recurring shape (see `docs/architecture.md`) -- reuse it in future
migrations (Time Entries/Attachments/Relations/Notifications) rather than
treating it as novel each time.

`ReminderRecord.summary` is a LAZY callable, not an eager field -- found and
fixed during this migration's step-6.5 Codex review. client.py's original
`list_reminders` filters the RAW elements by project allowlist first and
normalizes only the survivors (`elements = filtered` happens before
`self.normalize_reminder(item)` is ever called); an eager `summary` field
would normalize every record up front, including ones the Service is about
to discard, and would raise a spurious `KeyError` on a filtered-out record
missing an unrelated field (e.g. `id`) -- exactly the bug class
`get_remindable_link` already exists to avoid, recurring in `list_all()`
instead of `update()`/`delete()`. Deferring `summary` until the Service has
finished filtering restores the original's "filter raw, normalize
survivors" order exactly.

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
    at all" from "link present but unparsable" -- both collapse to a
    fail-closed denial, matching client.py's original
    `_ensure_reminder_project_write_allowed`.
    """

    summary: Callable[[], ReminderSummary]
    remindable_link: dict[str, Any] | None


class ReminderApi(Protocol):
    """Narrow, Reminders-only Domain API port. ReminderService depends on
    this Protocol, never on HttpxReminderApi concretely (enforced by the
    architecture-boundary test).

    `list_all(offset, page_size)` takes real pagination parameters -- found
    via an independent Codex review (verified against
    op-sources/17.2/lib/api/v3/reminders/reminder_collection_representer.rb:
    `ReminderCollectionRepresenter < OffsetPaginatedCollection`, the same
    real server-side pagination Roles/Memberships already page-walk) that
    an earlier version of this method issued a single unparameterized GET,
    silently returning only the server's default page instead of every
    reminder.
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ReminderRecord], int]: ...
    async def get(self, reminder_id: int) -> ReminderRecord: ...
    async def get_remindable_link(self, reminder_id: int) -> dict[str, Any] | None: ...
    async def create(self, work_package_id: int, payload: dict[str, Any]) -> ReminderRecord: ...
    async def update(self, reminder_id: int, payload: dict[str, Any]) -> ReminderRecord: ...
    async def delete(self, reminder_id: int) -> None: ...
