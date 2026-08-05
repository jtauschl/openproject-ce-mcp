"""Users Domain API port.

`UserRecord` carries no link: Users have no project concept at all, the
same shape as `RoleRecord`/`ActionRecord`. `to_detail` is a LAZY
`Callable[[], UserDetail]` thunk, not an eager field -- `list_users()`
builds a `UserRecord` per row but `UserService.list_users()` never reads
`.to_detail` on that path (only `get_user()` does), and
`normalize_user_detail` parses several detail-only fields (`groups`,
`authSource`, `identityUrl`, `language`) beyond a cheap summary field-copy --
same rationale as `DocumentRecord`/`NewsRecord`'s lazy thunk. Note this is
NOT the same shape as `SprintRecord`'s/`BoardRecord`'s eager
`summary_to_detail`: eager computation is only correct when detail reduces
to a cheap field-copy off summary (matching truncation limits, no extra
parsing); here detail requires real extra parsing work, so it must stay lazy.

`commit_lock`/`commit_unlock` are non-CRUD write actions (see
`ProjectApi.set_favorite` for the closest precedent, a boolean-toggle write
with the same no-form shape).

`UserService.list_users()`'s search branch scans `list_users` directly via
`scan_records_and_paginate`, folding the search predicate into
`item_allowed` rather than over-fetching the entire collection first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import UserDetail, UserSummary
from ..form_result import FormResult


@dataclass(frozen=True)
class UserRecord:
    summary: UserSummary
    to_detail: Callable[[], UserDetail]


UserFormResult = FormResult


class UserApi(Protocol):
    """Narrow, Users-only Domain API port. UserService depends on this
    Protocol, never on HttpxUserApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_users(self, *, offset: int, page_size: int) -> tuple[list[UserRecord], int]: ...
    async def get_user(self, user_ref: str) -> UserRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> UserFormResult: ...
    async def update_form(self, user_id: int, payload: dict[str, Any]) -> UserFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> UserDetail: ...
    async def commit_update(self, user_id: int, payload: dict[str, Any]) -> UserDetail: ...
    async def commit_delete(self, user_id: int) -> None: ...
    async def commit_lock(self, user_id: int) -> UserDetail: ...
    async def commit_unlock(self, user_id: int) -> UserDetail: ...
