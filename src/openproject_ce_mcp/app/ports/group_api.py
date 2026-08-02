"""Groups Domain API port.

`GroupRecord` carries no link: Groups have no project concept at all, the
same shape as `RoleRecord`/`UserRecord`. `to_detail` is a LAZY
`Callable[[], GroupDetail]` thunk, not an eager field -- `list_groups()`/
`list_groups_search()` build a `GroupRecord` per row but `GroupService.
list_groups()` never reads `.to_detail` on that path (only `get_group()`
does), and `normalize_group_detail` parses extra fields (`members`,
`memberships_url`) beyond a cheap summary field-copy -- same rationale as
`UserRecord`/`DocumentRecord`/`NewsRecord`'s lazy thunk.

No `create_form`/`update_form`: verified against `client.py`'s
`create_group`/`update_group`, neither calls a `groups/form` endpoint --
Groups has no `/form` endpoint at all, unlike Users/Memberships/Versions.
`commit_create`/`commit_update` return `GroupSummary`, not `GroupDetail`
(verified: `client.py`'s originals normalize the write response with
`normalize_group`, summary only).

`get_member_ids` exposes the raw `_links.members` href->id extraction
(client.py's `_id_from_href` over `current_payload["_links"]["members"]`)
as its own Port method: `GroupDetail.members` only carries display names,
not ids, so the Service's member-diff arithmetic (`current | add - remove`)
needs a dedicated raw-id accessor rather than reconstructing ids from the
normalized detail model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import GroupDetail, GroupSummary


@dataclass(frozen=True)
class GroupRecord:
    summary: GroupSummary
    to_detail: Callable[[], GroupDetail]


class GroupApi(Protocol):
    """Narrow, Groups-only Domain API port. GroupService depends on this
    Protocol, never on HttpxGroupApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_groups(self, *, offset: int, page_size: int) -> tuple[list[GroupRecord], int]: ...
    async def list_groups_search(self, *, page_size: int) -> list[GroupRecord]: ...
    async def get_group(self, group_id: int) -> GroupRecord: ...
    async def get_member_ids(self, group_id: int) -> set[int]: ...
    async def commit_create(self, payload: dict[str, Any]) -> GroupSummary: ...
    async def commit_update(self, group_id: int, payload: dict[str, Any]) -> GroupSummary: ...
    async def commit_delete(self, group_id: int) -> None: ...
