"""Users Domain API port.

`UserRecord` carries no link: Users have no project concept at all, the
same shape as `RoleRecord`/`ActionRecord`. `to_detail` is a LAZY
`Callable[[], UserDetail]` thunk, not an eager field -- `list_users()`
builds a `UserRecord` per row but `UserService.list_users()` never reads
`.to_detail` on that path (only `get_user()` does), and
`normalize_user_detail` parses several detail-only fields (`groups`,
`authSource`, `identityUrl`, `language`) beyond a cheap summary field-copy --
same rationale as `DocumentRecord`/`NewsRecord`'s lazy thunk, not
`SprintRecord`'s/`BoardRecord`'s eager `summary_to_detail` (an earlier
version of this file wrongly reasoned eager was correct here since the
summary/detail truncation limits match; that only justifies a cheap
field-copy, not unconditional computation.

`commit_lock`/`commit_unlock` are the first Domain API methods for a
non-CRUD write action (see `ProjectApi.set_favorite` for the closest
existing precedent, a boolean-toggle write with the same no-form shape).

`list_users_search` was removed (OPM-373 Phase 5): it was a `paginate_all`
wrapper around this same `list_users(offset, page_size)` method, walking
the entire collection before `UserService.list_users()`'s search branch
ever sliced out the requested `offset`/`limit` window. That branch now
scans `list_users` directly via `scan_records_and_paginate`, folding the
search predicate into `item_allowed` instead of a separate over-fetch step.
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
