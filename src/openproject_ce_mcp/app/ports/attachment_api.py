"""Attachments Domain API port.

Full CRUD minus update (OpenProject's v3 API has no `PATCH /attachments/{id}`
endpoint -- verbatim of client.py's original shape, which never exposed an
`update_attachment` method either). No `to_detail`: `AttachmentSummary` is
the only normalized shape this domain has (no separate Detail model exists in
models.py, verified against client.py's `normalize_attachment`, which returns
`AttachmentSummary` for both the list and get paths), so `AttachmentRecord`
carries no lazy-detail thunk, matching `FileLinkRecord`'s shape.

`AttachmentRecord` carries the raw `container_link` dict (not a pre-extracted
href/int), the same reason `FileLinkRecord` does: the Service needs to
distinguish "no container link at all" from "container link present but
unparsable," both of which collapse to a fail-closed denial without losing
that distinction at the Port boundary.

`list_for_work_package` is a hand-rolled page-walk (`offset`/`page_size`
params on the Adapter side, not `paginate_all`) because the Attachments
collection endpoint's response was never confirmed to carry a `total` field
in the original client.py code (only `_embedded.elements` was ever read) --
using `paginate_all`'s `(items, total)` contract here would be an unverified,
speculative behavior change. See `HttpxAttachmentApi.list_for_work_package`'s
own docstring for the guard-loop detail.

`get_max_attachment_size` is a narrow, single-field lookup against the
otherwise entirely unmigrated, global Instance Configuration domain -- not
the same "raw sibling-domain resource" pattern as `EmojiReactionApi.
get_activity`/`ReminderApi.get_remindable_link` (those fetch a raw payload
from WITHIN their own domain); this one deliberately reaches into a
different, unrelated domain for exactly the one field
(`maximumAttachmentFileSize`) `_validate_attachment_size` needs, so a future
Instance Configuration migration does not have to happen first. Migrating
the complete Instance Configuration domain here would be out-of-scope creep
for an Attachments migration.
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

    async def list_for_work_package(self, work_package_id: int, *, page_size: int) -> list[AttachmentRecord]: ...
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
