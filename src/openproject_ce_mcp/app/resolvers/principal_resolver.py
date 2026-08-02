"""Principal-reference resolver (ADR 0001).

Resolves a principal reference ("me", numeric id, or exact case-insensitive
name) to a concrete numeric-id string. Verbatim behavioral port of the
pre-existing `_resolve_principal_id`. Depends on `PrincipalApi` (never
`PrincipalService`) and the pre-existing `CurrentUserLookup` seam -- same
"depend on Ports, not sibling Services" shape as `VersionResolver`.

Deliberately does NOT call `access.ensure_read_enabled` before searching via
`PrincipalApi` -- existing quirk, preserved exactly. This resolver is used
internally by write paths (membership/work-package writes resolving a
name-based principal reference) that have already been authorized through
their own operation's scope check; it never surfaces the full principal list
to the agent, only a single resolved id, so gating it a second time behind
`OPENPROJECT_ENABLE_ADMIN_READ` would needlessly break every write path that
accepts a principal name instead of a numeric id.

Name comparison uses `PrincipalRecord.lookup_name` (the raw, never-synthesized
name), not `summary.name`: `normalize_principal` falls back to a synthetic
display name (`f"Principal {id}"`) when the raw name is blank/missing, which
could otherwise make a caller's literal search for "Principal 7" accidentally
match a principal whose real name was blank. See `app/ports/principal_api.py`'s
module docstring for the full rationale.
"""

from __future__ import annotations

from ...config import Settings
from ..errors import InvalidInputError
from ..pagination import effective_limit as _effective_limit
from ..ports.current_user import CurrentUserLookup
from ..ports.principal_api import PrincipalApi


class PrincipalResolver:
    def __init__(self, *, api: PrincipalApi, current_user: CurrentUserLookup, settings: Settings) -> None:
        self._api = api
        self._current_user = current_user
        self._settings = settings

    async def resolve_id(self, principal_ref: str) -> str:
        if principal_ref.casefold() == "me":
            current_user = await self._current_user()
            return str(current_user.id)
        if principal_ref.isdigit():
            return principal_ref

        # Capped by both max_page_size and max_results (min of the two, via
        # effective_limit), not max_results alone -- the original
        # _resolve_principal_id passed max_results into _list_principals_
        # unchecked, which then ran it through _resolve_limit's identical
        # min(...) clamp. Passing max_results directly here would silently
        # request a larger page than the server-side/config page-size cap
        # allows.
        records, _total = await self._api.list_principals(
            search=principal_ref,
            offset=1,
            page_size=_effective_limit(self._settings.max_results, settings=self._settings),
        )
        matches = [
            str(record.summary.id) for record in records if record.lookup_name.casefold() == principal_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject principal '{principal_ref}' was not found.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject principal '{principal_ref}' is ambiguous. Pass a numeric user or group id."
            )
        return matches[0]
