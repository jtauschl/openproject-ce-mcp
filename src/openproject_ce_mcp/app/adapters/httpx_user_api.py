"""HTTP-backed UserApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`SUBJECT_LIMIT`/`link_to_web_url` are shared via `app/adapters/_text.py`.
User has no formattable-text field at all (every field is a plain scalar or
a link-derived title), so the `hidden_fields.apply_hidden_fields`
Service-side stamp is the only masking layer this domain has;
`normalize_user`/`normalize_user_detail` exclude that call.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import UserDetail, UserSummary
from ..ports.user_api import UserFormResult, UserRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import link_title as _link_title
from ._text import origin_from_url as _origin_from_url
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments
from ._text import trim_text as _trim_text


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = None
        if isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


def normalize_user(payload: dict[str, Any], *, base_url: str, origin: str) -> UserSummary:
    """Pure HAL->model translation. Excludes hidden-field masking.

    avatar is a top-level string property (already a full absolute URL,
    e.g. "https://host/users/5/avatar"), not a `_links.avatar` link --
    verified against `user_representer.rb` (`property :avatar, getter:
    ->(*) { avatar_url(represented) }`) and live against a real instance.
    A prior version of this function read `_links.avatar`, which
    UserRepresenter never sends -- avatar_url was always None.
    """
    return UserSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
        login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
        email=_trim_text(payload.get("email"), limit=SUBJECT_LIMIT),
        status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
        admin=payload.get("admin"),
        locked=payload.get("locked"),
        avatar_url=_trim_text(payload.get("avatar"), limit=SUBJECT_LIMIT),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        firstname=_trim_text(payload.get("firstName"), limit=SUBJECT_LIMIT),
        lastname=_trim_text(payload.get("lastName"), limit=SUBJECT_LIMIT),
    )


def normalize_user_detail(
    payload: dict[str, Any], *, base_url: str, origin: str, summary: UserSummary | None = None
) -> UserDetail:
    """Field-copies from the already-computed summary rather than
    re-extracting from the raw payload with a different truncation limit
    (both use SUBJECT_LIMIT uniformly) -- the eager `UserRecord.to_detail`
    shape depends on this.

    `summary` lets a caller that already built a `UserSummary` for the same
    payload (see `_record()`) pass it in directly instead of paying for a
    second `normalize_user()` call -- callers with only the raw payload
    (commit_create/commit_update/commit_lock/commit_unlock) omit it and get
    the summary computed here, same as before.

    No `groups` field: `user_representer.rb` declares no `_links.groups` (or
    any other group-membership exposure) at all -- a prior version of this
    function read `_links.groups`, which was always empty. There is no route
    that lists a user's groups from the user side; `get_group`'s own
    `members` field is the only way to see this relationship, from the
    group's side.
    """
    if summary is None:
        summary = normalize_user(payload, base_url=base_url, origin=origin)
    links = payload.get("_links", {})
    auth_source = _link_title(links.get("authSource"))
    identity_url = payload.get("identityUrl")
    return UserDetail(
        id=summary.id,
        name=summary.name,
        login=summary.login,
        email=summary.email,
        status=summary.status,
        admin=summary.admin,
        locked=summary.locked,
        avatar_url=summary.avatar_url,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        language=_trim_text(payload.get("language"), limit=SUBJECT_LIMIT),
        identity_url=identity_url,
        auth_source=auth_source,
        firstname=summary.firstname,
        lastname=summary.lastname,
    )


class HttpxUserApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)

    def _record(self, payload: dict[str, Any]) -> UserRecord:
        # to_detail is a lazy thunk: list_users()/list_users_search() build a
        # UserRecord per row, but UserService.list_users() never reads
        # .to_detail on that path (only get_user() does) -- deferring the
        # detail-only parsing (groups/authSource/identityUrl/language) avoids
        # paying for it on every list row. The thunk still passes the
        # already-computed summary through, so calling it never re-derives a
        # second UserSummary either.
        summary = normalize_user(payload, base_url=self._base_url, origin=self._origin)
        return UserRecord(
            summary=summary,
            to_detail=lambda: normalize_user_detail(
                payload, base_url=self._base_url, origin=self._origin, summary=summary
            ),
        )

    async def list_users(self, *, offset: int, page_size: int) -> tuple[list[UserRecord], int]:
        payload = await self._transport.get_json("users", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get_user(self, user_ref: str) -> UserRecord:
        # user_ref can be a login (e.g. containing "@"/".") or the literal
        # "me", not just a numeric id. A literal "."/".." path segment is
        # still rejected by the generalized path-traversal guard -- a real
        # login containing a dot never forms a bare "." segment on its own.
        safe_ref = _reject_path_traversal_segments(user_ref, field_name="user_ref")
        return self._record(await self._transport.get_json(f"users/{quote(safe_ref, safe='')}"))

    async def create_form(self, payload: dict[str, Any]) -> UserFormResult:
        return self._form_result(await self._transport.post_json("users/form", json_body=payload))

    async def update_form(self, user_id: int, payload: dict[str, Any]) -> UserFormResult:
        return self._form_result(await self._transport.post_json(f"users/{user_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> UserDetail:
        response = await self._transport.post_json("users", json_body=payload)
        return normalize_user_detail(response, base_url=self._base_url, origin=self._origin)

    async def commit_update(self, user_id: int, payload: dict[str, Any]) -> UserDetail:
        response = await self._transport.patch_json(f"users/{user_id}", json_body=payload)
        return normalize_user_detail(response, base_url=self._base_url, origin=self._origin)

    async def commit_delete(self, user_id: int) -> None:
        await self._transport.delete(f"users/{user_id}")

    async def commit_lock(self, user_id: int) -> UserDetail:
        # An empty dict, not None -- a bodyless POST here sends no Content-Type
        # header at all (httpx only sets one when `json` is non-None), and
        # OpenProject's Grape endpoint rejects that with 406 "Missing
        # content-type header" even though the POST itself carries no data.
        response = await self._transport.post_json(f"users/{user_id}/lock", json_body={})
        return normalize_user_detail(response, base_url=self._base_url, origin=self._origin)

    async def commit_unlock(self, user_id: int) -> UserDetail:
        # DELETE .../lock already returns the full updated user representation
        # (OpenProject's user_transition helper responds with UserRepresenter
        # for both the POST and DELETE lock transitions) -- no follow-up GET
        # needed, mirroring commit_lock.
        response = await self._transport.delete_json(f"users/{user_id}/lock")
        return normalize_user_detail(response, base_url=self._base_url, origin=self._origin)

    @staticmethod
    def _form_result(form: dict[str, Any]) -> UserFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return UserFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
