"""Application Service for the User Preferences domain (18th migrated domain).

Depends on the UserPreferencesApi Protocol, never HttpxUserPreferencesApi
concretely (enforced by the architecture-boundary test). No Resolver, no
Policy file: this is the first self-scoped (not project-scoped, not
purely-global-admin-scoped) domain to migrate -- `my_preferences` has no
project link and no allowlist concept at all, so neither
app/policies/scope.py's helpers nor a dedicated <domain>_policy.py module
apply. Constructor shape follows RoleService's purely-global template
(`api`, `settings` only, no `project_id_to_identifier`), not WikiPageService's
(which, despite having no list endpoint either, still carries
`project_id_to_identifier` and a project-link allowlist check).

Exactly one write action (`update`), no list endpoint at all: no shared
`_WriteOutcome`/`_finalize_write` state machine, matching DocumentService's
single-call-site shape. Note the shared machine's own threshold is "2+ write
actions sharing the same preview/commit/reject shape" (per
_write_outcome.py's docstring), not "no other domain has ever skipped it" --
UserService (5 write actions) and GroupService (3) also skip the shared
machine for their own reasons, so Documents is not cited here as the sole
precedent, only as the nearest single-call-site sibling.

update()'s write-scope gate (access.ensure_write_enabled("personal", ...))
runs at the TOP of the method, before the preview/confirm branch -- this is
the OPPOSITE of DocumentService's ordering (gate after the preview return).
Verbatim port of client.py:3542's placement (self._ensure_write_enabled
("personal") precedes the `if not confirm:` check there too) -- preserved
exactly, not normalized to the Document-style ordering, since changing it
would silently loosen preview-time behavior (today, a caller without
personal-write can't even preview a change).

update() performs no prerequisite GET (unlike Document.update(), which
fetches the current resource for its project_link): there is no project link
to derive, so the payload is built and PATCHed directly on confirm, exactly
matching client.py's original.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import UserPreferences, UserPreferencesWriteResult
from ..policies import access, hidden_fields
from ..ports.user_preferences_api import UserPreferencesApi


class UserPreferencesService:
    def __init__(self, *, api: UserPreferencesApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("user_preferences", value, settings=self._settings)

    async def get(self) -> UserPreferences:
        access.ensure_read_enabled("personal", settings=self._settings)
        record = await self._api.get()
        return self._stamp(record.detail)

    async def update(
        self,
        *,
        lang: str | None = None,
        time_zone: str | None = None,
        comment_sort_descending: bool | None = None,
        warn_on_leaving_unsaved: bool | None = None,
        auto_hide_popups: bool | None = None,
        confirm: bool = False,
    ) -> UserPreferencesWriteResult:
        access.ensure_write_enabled("personal", settings=self._settings)

        payload: dict[str, Any] = {}
        if lang is not None:
            hidden_fields.ensure_field_writable("user_preferences", "lang", settings=self._settings)
            payload["lang"] = lang
        if time_zone is not None:
            hidden_fields.ensure_field_writable("user_preferences", "time_zone", settings=self._settings)
            payload["timeZone"] = time_zone
        if comment_sort_descending is not None:
            hidden_fields.ensure_field_writable("user_preferences", "comment_sort_descending", settings=self._settings)
            payload["commentSortDescending"] = comment_sort_descending
        if warn_on_leaving_unsaved is not None:
            hidden_fields.ensure_field_writable("user_preferences", "warn_on_leaving_unsaved", settings=self._settings)
            payload["warnOnLeavingUnsaved"] = warn_on_leaving_unsaved
        if auto_hide_popups is not None:
            hidden_fields.ensure_field_writable("user_preferences", "auto_hide_popups", settings=self._settings)
            payload["autoHidePopups"] = auto_hide_popups

        if not confirm:
            return UserPreferencesWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update your preferences. Call again with confirm=true to write.",
                payload=payload,
                result=None,
            )

        result = self._stamp(await self._api.commit_update(payload))
        return UserPreferencesWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Preferences updated successfully.",
            payload=payload,
            result=result,
        )
