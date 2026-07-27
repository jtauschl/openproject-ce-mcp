"""Application Service for the Users domain (14th migrated domain).

Depends on the UserApi Protocol, never HttpxUserApi concretely (enforced by
the architecture-boundary test). No `ProjectRefResolver`: Users have no
project concept at all, following `RoleService`'s/`ActionCapabilityService`'s
zero-Resolver template. No dedicated policy file: nothing here needs
client-side project-link filtering.

`list()` needs BOTH `pagination.paginate_server` (no-search branch) and
`pagination.paginate_client` (search branch, over-fetch-then-filter) --
unlike Roles, which only ever needed the former since it has no search
parameter. Verbatim port of client.py's `list_users` dual-branch shape;
`list_groups` (still flat) shares the identical structure.

`lock()`/`unlock()` are the first Service methods for a non-CRUD write
action. Modeled on `ProjectService.set_favorite` (the closest existing
precedent: a no-form, no-prior-GET, preview/confirm/commit toggle) via a
small shared `_finalize_action` helper local to this Service -- lock/unlock
share an identical shape with EACH OTHER (not with create/update/delete),
so a dedicated 2-call-site helper here follows the same "2+ write actions
sharing the same shape" threshold `_write_outcome.py`'s module docstring
already applies project-wide, without forcing lock/unlock onto the
form-based `_finalize_write` shape they don't fit.

`delete()`/`lock()`/`unlock()` all check `access.ensure_write_enabled("admin", ...)`
UNCONDITIONALLY (not gated inside the confirm branch) -- a deliberate,
verified port of client.py's own asymmetry: `delete_user`/`lock_user`/
`unlock_user` have no prior GET to piggyback the check on (unlike e.g.
`MembershipService.delete()`, which checks only inside `if confirm:` because
it already does a prior GET for the allowlist check). Kept as-is rather than
silently normalized to the `_write_outcome.py` convention, since the
underlying reason (nothing else to gate an unauthorized preview request on)
applies here exactly as it did in the original.

`create()`/`update()`/lock/unlock's `_finalize_action` all call
`hidden_fields.ensure_field_writable("user", <field>, ...)` for every field
they write, matching every other full-CRUD Service (News/Board/Document/
Membership/Project/Version). This is a DELIBERATE HARDENING beyond
client.py's original `create_user`/`update_user`/`lock_user`/`unlock_user`,
which never called the equivalent `_ensure_field_writable` at all -- a
genuine pre-existing gap (verified: `OPENPROJECT_HIDE_USER_FIELDS` masked
reads but never blocked writes) found by a step-6.5 Codex review of this
migration, fixed here rather than faithfully ported, since every sibling
domain already has this protection and there is no reason to preserve an
inconsistency once found.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import UserDetail, UserListResult, UserWriteResult
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client, paginate_server
from ..policies import access, hidden_fields
from ..ports.user_api import UserApi


class UserService:
    def __init__(self, *, api: UserApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("user", value, settings=self._settings)

    async def list_users(
        self, *, search: str | None = None, offset: int = 1, limit: int | None = None
    ) -> UserListResult:
        access.ensure_read_enabled("admin", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)

        if search is not None:
            records = await self._api.list_users_search(page_size=self._settings.max_results)
            search_key = search.casefold()
            matches = [
                record
                for record in records
                if search_key in (record.summary.name or "").casefold()
                or search_key in (record.summary.login or "").casefold()
                or search_key in (record.summary.email or "").casefold()
            ]
            summaries = [self._stamp(record.summary) for record in matches]
            page, total, next_offset, truncated = paginate_client(
                offset=offset, limit=effective_limit, results=summaries
            )
            return UserListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(page),
                next_offset=next_offset,
                truncated=truncated,
                results=page,
            )

        records, total = await self._api.list_users(offset=offset, page_size=effective_limit)
        results = [self._stamp(record.summary) for record in records]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return UserListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get_user(self, user_ref: str) -> UserDetail:
        access.ensure_read_enabled("admin", settings=self._settings)
        record = await self._api.get_user(user_ref)
        return self._stamp(record.to_detail())

    async def create(
        self,
        *,
        login: str,
        email: str,
        firstname: str,
        lastname: str,
        password: str | None = None,
        admin: bool = False,
        status: str = "active",
        language: str | None = None,
        confirm: bool = False,
    ) -> UserWriteResult:
        hidden_fields.ensure_field_writable("user", "login", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "email", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "firstname", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "lastname", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "admin", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "status", settings=self._settings)
        payload: dict[str, Any] = {
            "login": login,
            "email": email,
            "firstName": firstname,
            "lastName": lastname,
            "admin": admin,
            "status": status,
        }
        if password is not None:
            payload["password"] = password
        if language is not None:
            hidden_fields.ensure_field_writable("user", "language", settings=self._settings)
            payload["language"] = language
        form = await self._api.create_form(payload)
        if form.validation_errors:
            return self._write_result(
                action="create",
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed user changes. Fix the validation errors before confirming.",
                user_id=None,
                payload=form.payload,
                validation_errors=form.validation_errors,
                result=None,
            )
        if not confirm:
            return self._write_result(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject validated the user. Ask for confirmation, then call again with confirm=true to create it.",
                user_id=None,
                payload=form.payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("admin", settings=self._settings)
        detail = await self._api.commit_create(form.payload)
        return self._write_result(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User created successfully.",
            user_id=detail.id,
            payload=form.payload,
            validation_errors={},
            result=detail,
        )

    async def update(
        self,
        *,
        user_id: int,
        login: str | None = None,
        email: str | None = None,
        firstname: str | None = None,
        lastname: str | None = None,
        admin: bool | None = None,
        language: str | None = None,
        confirm: bool = False,
    ) -> UserWriteResult:
        payload: dict[str, Any] = {}
        if login is not None:
            hidden_fields.ensure_field_writable("user", "login", settings=self._settings)
            payload["login"] = login
        if email is not None:
            hidden_fields.ensure_field_writable("user", "email", settings=self._settings)
            payload["email"] = email
        if firstname is not None:
            hidden_fields.ensure_field_writable("user", "firstname", settings=self._settings)
            payload["firstName"] = firstname
        if lastname is not None:
            hidden_fields.ensure_field_writable("user", "lastname", settings=self._settings)
            payload["lastName"] = lastname
        if admin is not None:
            hidden_fields.ensure_field_writable("user", "admin", settings=self._settings)
            payload["admin"] = admin
        if language is not None:
            hidden_fields.ensure_field_writable("user", "language", settings=self._settings)
            payload["language"] = language
        form = await self._api.update_form(user_id, payload)
        if form.validation_errors:
            return self._write_result(
                action="update",
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed user changes. Fix the validation errors before confirming.",
                user_id=user_id,
                payload=form.payload,
                validation_errors=form.validation_errors,
                result=None,
            )
        if not confirm:
            return self._write_result(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject validated the user change. Ask for confirmation, then call again with confirm=true to write it.",
                user_id=user_id,
                payload=form.payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("admin", settings=self._settings)
        detail = await self._api.commit_update(user_id, form.payload)
        return self._write_result(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User updated successfully.",
            user_id=detail.id,
            payload=form.payload,
            validation_errors={},
            result=detail,
        )

    async def delete(self, user_id: int, *, confirm: bool = False) -> UserWriteResult:
        # Checked unconditionally (not just on confirm) -- there is no prior
        # GET to gate an unauthorized preview request on, verbatim port of
        # client.py's delete_user.
        access.ensure_write_enabled("admin", settings=self._settings)
        payload = {"id": user_id}
        if not confirm:
            return self._write_result(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete the user. Ask for confirmation, then call again with confirm=true.",
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        await self._api.commit_delete(user_id)
        return self._write_result(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User deleted successfully.",
            user_id=user_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    async def lock(self, user_id: int, *, confirm: bool = False) -> UserWriteResult:
        return await self._finalize_action(
            action="lock",
            user_id=user_id,
            confirm=confirm,
            preview_message="OpenProject is ready to lock the user. Ask for confirmation, then call again with confirm=true.",
            success_message="User locked successfully.",
            commit=self._api.commit_lock,
        )

    async def unlock(self, user_id: int, *, confirm: bool = False) -> UserWriteResult:
        return await self._finalize_action(
            action="unlock",
            user_id=user_id,
            confirm=confirm,
            preview_message="OpenProject is ready to unlock the user. Ask for confirmation, then call again with confirm=true.",
            success_message="User unlocked successfully.",
            commit=self._api.commit_unlock,
        )

    async def _finalize_action(
        self,
        *,
        action: str,
        user_id: int,
        confirm: bool,
        preview_message: str,
        success_message: str,
        commit: Any,
    ) -> UserWriteResult:
        # Shared shape for lock/unlock only: no form, no validation-errors
        # branch, no prior GET -- checked unconditionally for the same reason
        # as delete() above. Not `_write_outcome.py`'s `_finalize_write`
        # (that shape assumes a form/validation-errors branch neither action
        # has); modeled instead on `ProjectService.set_favorite`'s no-form
        # toggle shape.
        access.ensure_write_enabled("admin", settings=self._settings)
        hidden_fields.ensure_field_writable("user", "locked", settings=self._settings)
        payload = {"id": user_id}
        if not confirm:
            return self._write_result(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message,
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        detail = await commit(user_id)
        return self._write_result(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message,
            user_id=detail.id,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    def _write_result(
        self,
        *,
        action: str,
        confirmed: bool,
        requires_confirmation: bool,
        ready: bool,
        message: str,
        user_id: int | None,
        payload: dict[str, Any],
        validation_errors: dict[str, str],
        result: UserDetail | None,
    ) -> UserWriteResult:
        return UserWriteResult(
            action=action,
            confirmed=confirmed,
            requires_confirmation=requires_confirmation,
            ready=ready,
            message=message,
            user_id=user_id,
            payload=payload,
            validation_errors=validation_errors,
            result=self._stamp(result) if result is not None else None,
        )
