"""Attachments Domain API port.

Full CRUD minus update: OpenProject's v3 API has no `PATCH /attachments/{id}`
endpoint. No `to_detail`: `AttachmentSummary` is the only normalized shape
this domain has (no separate Detail model exists in models.py), so
`AttachmentRecord` carries no lazy-detail thunk, matching `FileLinkRecord`'s
shape.

`AttachmentRecord` carries the raw `container_link` dict (not a pre-extracted
href/int), the same reason `FileLinkRecord` does: the Service needs to
distinguish "no container link at all" from "container link present but
unparsable," both of which collapse to a fail-closed denial without losing
that distinction at the Port boundary.

`list_for_work_package` returns one page at a time (`offset`/`page_size` ->
`(records, total)`), scanned by the Service via `scan_records_and_paginate`,
matching every other list domain's shape. The Attachments collection
endpoint's response is not guaranteed to carry a real `total` field, so the
Adapter falls back to `total = len(records)` (this page's own count) when
the server omits it, the same fallback `httpx_sprint_api.py` uses.

`get_max_attachment_size` is a narrow, single-field lookup against the
global Instance Configuration domain -- not the same "raw sibling-domain
resource" pattern as `EmojiReactionApi.get_activity`/`ReminderApi.
get_remindable_link` (those fetch a raw payload from WITHIN their own
domain); this one deliberately reaches into a different, unrelated domain
for exactly the one field (`maximumAttachmentFileSize`)
`_validate_attachment_size` needs, rather than depending on the full
Instance Configuration domain for a single value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import AttachmentSummary


@dataclass(frozen=True)
class AttachmentRecord:
    """One attachment as read from the API: the normalized `summary`, plus
    the raw `_links.container` link dict -- see module docstring for why the
    raw dict, not a pre-extracted id, is carried across the Port boundary.
    """

    summary: AttachmentSummary
    container_link: dict[str, Any] | None


class AttachmentApi(Protocol):
    """Narrow, Attachments-only Domain API port. AttachmentService depends on
    this Protocol, never on HttpxAttachmentApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[AttachmentRecord], int]: ...
    async def get(self, attachment_id: int) -> AttachmentRecord: ...
    async def create(
        self,
        work_package_id: int,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> AttachmentRecord: ...
    async def delete(self, attachment_id: int) -> None: ...
    async def get_max_attachment_size(self) -> int | None: ...
