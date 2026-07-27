"""Application Service for the Groups domain (15th migrated domain).

Depends on the GroupApi Protocol, never HttpxGroupApi concretely (enforced
by the architecture-boundary test). No `ProjectRefResolver`: Groups have no
project concept at all, following `RoleService`'s/`UserService`'s
zero-Resolver template. No dedicated policy file: nothing here needs
client-side project-link filtering.

`list_groups()` needs BOTH `pagination.paginate_server` (no-search branch)
and `pagination.paginate_client` (search branch, over-fetch-then-filter) --
verbatim port of client.py's `list_groups` dual-branch shape, byte-identical
to `list_users`'s structure but filtering only on `name` (Groups has no
login/email fields to search).

`create()`/`update()` have NO form endpoint (verified: client.py's
`create_group`/`update_group` never call a `groups/form` path) -- modeled
on `NewsService`'s no-form write shape (build the payload dict directly, no
validation-errors branch) rather than `UserService`'s form-based flow.
`GroupWriteResult.result` is typed `GroupSummary`, not `GroupDetail`
(verified: the original normalizes the write response with
`normalize_group`, summary only).

`update()`'s member diff (`add_user_ids`/`remove_user_ids`) is a genuine
behavioral requirement, not incidental structure: the `PATCH groups/{id}`
endpoint requires a COMPLETE `_links.members` array, not a delta -- no
add/remove operation exists. This Service fetches the current membership via
`self._api.get_member_ids()` (a raw href->id extraction the Adapter exposes
separately from `get_group()`, since `GroupDetail.members` only carries
display names, not ids), computes `current | add - remove` in Python, and
builds the full replacement list, exactly like client.py's original.

`create()`/`update()`/`delete()` all check `access.ensure_write_enabled(
"admin", ...)` UNCONDITIONALLY (not gated inside the confirm branch) --
a deliberate, verified port of client.py's own behavior: none of
`create_group`/`update_group`/`delete_group` gate the check on `confirm`,
even though `update_group` has a prior GET (for the member diff) it could
otherwise gate on the way `NewsService.update()` gates on its own prior GET.
This means a caller without `OPENPROJECT_ENABLE_ADMIN_WRITE` is rejected
immediately on `update()`, even for a pure preview, and can never see a
member-diff preview -- kept as-is to match the verified original rather than
adopting News' more-permissive-preview pattern.

`create()`/`update()` call `hidden_fields.ensure_field_writable("group",
<field>, ...)` for every field they write ("name", "members"). This is a
DELIBERATE HARDENING beyond client.py's original `create_group`/
`update_group`, which never called the equivalent `_ensure_field_writable`
at all -- a genuine pre-existing gap (verified: `OPENPROJECT_HIDE_GROUP_FIELDS`
masked reads but never blocked writes), the same class of gap the Users
migration's step-6.5 review found and fixed. Fixed here as part of the
initial implementation rather than ported faithfully, since every other
full-CRUD sibling already has this protection.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import GroupDetail, GroupListResult, GroupSummary, GroupWriteResult
from ..api_href import api_href
from ..pagination import clamp_limit, paginate_client, paginate_server
from ..policies import access, hidden_fields
from ..ports.group_api import GroupApi


class GroupService:
    def __init__(self, *, api: GroupApi, settings: Settings, api_prefix: str) -> None:
        self._api = api
        self._settings = settings
        self._api_prefix = api_prefix

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("group", value, settings=self._settings)

    def _api_href(self, relative_path: str) -> str:
        return api_href(relative_path, api_prefix=self._api_prefix)

    def _effective_limit(self, limit: int | None) -> int:
        return clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )

    async def list_groups(
        self, *, search: str | None = None, offset: int = 1, limit: int | None = None
    ) -> GroupListResult:
        access.ensure_read_enabled("admin", settings=self._settings)
        effective_limit = self._effective_limit(limit)

        if search is not None:
            records = await self._api.list_groups_search(page_size=self._settings.max_results)
            search_key = search.casefold()
            matches = [record for record in records if search_key in (record.summary.name or "").casefold()]
            summaries = [self._stamp(record.summary) for record in matches]
            page, total, next_offset, truncated = paginate_client(
                offset=offset, limit=effective_limit, results=summaries
            )
            return GroupListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(page),
                next_offset=next_offset,
                truncated=truncated,
                results=page,
            )

        records, total = await self._api.list_groups(offset=offset, page_size=effective_limit)
        results = [self._stamp(record.summary) for record in records]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return GroupListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get_group(self, group_id: int) -> GroupDetail:
        access.ensure_read_enabled("admin", settings=self._settings)
        record = await self._api.get_group(group_id)
        return self._stamp(record.to_detail())

    async def create(self, *, name: str, user_ids: list[int] | None = None, confirm: bool = False) -> GroupWriteResult:
        # Checked unconditionally -- verbatim port of client.py's
        # create_group, which has no prior GET to gate an unauthorized
        # preview request on.
        access.ensure_write_enabled("admin", settings=self._settings)
        hidden_fields.ensure_field_writable("group", "name", settings=self._settings)
        body: dict[str, Any] = {"name": name}
        if user_ids:
            hidden_fields.ensure_field_writable("group", "members", settings=self._settings)
            body["_links"] = {"members": [{"href": self._api_href(f"users/{uid}")} for uid in user_ids]}
        payload_preview: dict[str, Any] = {"name": name, "user_ids": user_ids or []}

        if not confirm:
            return self._write_result(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create the group. Ask for confirmation, then call again with confirm=true.",
                group_id=None,
                payload=payload_preview,
                validation_errors={},
                result=None,
            )
        result = self._stamp(await self._api.commit_create(body))
        return self._write_result(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group created successfully.",
            group_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        group_id: int,
        *,
        name: str | None = None,
        add_user_ids: list[int] | None = None,
        remove_user_ids: list[int] | None = None,
        confirm: bool = False,
    ) -> GroupWriteResult:
        # Checked unconditionally -- verbatim port of client.py's
        # update_group, which never gates this on `confirm` even though a
        # prior GET already happens below for the member diff. See this
        # module's docstring for the resulting preview-visibility tradeoff.
        access.ensure_write_enabled("admin", settings=self._settings)
        body: dict[str, Any] = {}
        if name is not None:
            hidden_fields.ensure_field_writable("group", "name", settings=self._settings)
            body["name"] = name
        # The groups PATCH endpoint requires a complete members list (full
        # replacement, not delta). Fetch current members and compute the new
        # complete set from the add/remove requests -- a genuine behavioral
        # requirement to preserve, not incidental structure to simplify away.
        if add_user_ids or remove_user_ids:
            hidden_fields.ensure_field_writable("group", "members", settings=self._settings)
            current_ids = await self._api.get_member_ids(group_id)
            new_ids = current_ids.copy()
            if add_user_ids:
                new_ids.update(add_user_ids)
            if remove_user_ids:
                new_ids -= set(remove_user_ids)
            body["_links"] = {"members": [{"href": self._api_href(f"users/{uid}")} for uid in sorted(new_ids)]}

        payload_preview: dict[str, Any] = {}
        if name is not None:
            payload_preview["name"] = name
        if add_user_ids:
            payload_preview["add_user_ids"] = add_user_ids
        if remove_user_ids:
            payload_preview["remove_user_ids"] = remove_user_ids

        if not confirm:
            return self._write_result(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update the group. Ask for confirmation, then call again with confirm=true.",
                group_id=group_id,
                payload=payload_preview,
                validation_errors={},
                result=None,
            )
        result = self._stamp(await self._api.commit_update(group_id, body))
        return self._write_result(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group updated successfully.",
            group_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def delete(self, group_id: int, *, confirm: bool = False) -> GroupWriteResult:
        # Checked unconditionally -- verbatim port of client.py's
        # delete_group, no prior GET to gate an unauthorized preview request
        # on. No detail fetched on either branch (matches _finalize_delete's
        # preview_result=None/commit_result=None call shape).
        access.ensure_write_enabled("admin", settings=self._settings)
        payload = {"id": group_id}
        if not confirm:
            return self._write_result(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete the group. Ask for confirmation, then call again with confirm=true.",
                group_id=group_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        await self._api.commit_delete(group_id)
        return self._write_result(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group deleted successfully.",
            group_id=group_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    def _write_result(
        self,
        *,
        action: str,
        confirmed: bool,
        requires_confirmation: bool,
        ready: bool,
        message: str,
        group_id: int | None,
        payload: dict[str, Any],
        validation_errors: dict[str, str],
        result: GroupSummary | None,
    ) -> GroupWriteResult:
        return GroupWriteResult(
            action=action,
            confirmed=confirmed,
            requires_confirmation=requires_confirmation,
            ready=ready,
            message=message,
            group_id=group_id,
            payload=payload,
            validation_errors=validation_errors,
            result=result,
        )
