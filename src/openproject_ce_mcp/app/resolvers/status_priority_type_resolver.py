"""Status/priority-reference resolver.

Bundles `resolve_status_id`/`resolve_priority_id` in one Resolver: both need
only the `StatusPriorityTypeApi` dependency, neither takes a
project/context parameter.

On a duplicate name match, both methods silently return the FIRST match --
there is no ambiguity check here, unlike `TypeResolver`/`SprintResolver`,
which both raise on an ambiguous match. This asymmetry is intentional; do
not "fix" it by adding an ambiguity check that changes existing behavior.

Name comparison uses each Record's `lookup_name` field, NOT `summary.name`:
`summary.name` falls back to a synthetic display name (`f"Status {id}"`)
when the raw name is blank/missing, so matching against it could make a
caller's literal search for "Status 7" accidentally match a status whose
real name was blank. `lookup_name` is the raw name, never synthesized --
see `app/ports/status_priority_type_api.py`'s module docstring for the
full `lookup_name`-vs-`summary.name` rationale, and
`test_app_status_priority_type_resolver.py`'s dedicated regression test.
Depends on `StatusPriorityTypeApi` (the Port), never
`StatusPriorityTypeService`: reusing the Service's own gated
`list_statuses`/`list_priorities` would reintroduce a read-enablement-gate
regression -- an instance can have work-package writes enabled with reads
entirely disabled, and this resolver's callers (write-path name resolution)
must keep working in that configuration.

`statuses_cache`/`priorities_cache` are the same `CachedValue` instances
`client.py` also gives `StatusPriorityTypeService` -- see `app/caches.py`.
Consulting the cache here does NOT add a read-gate check: the cache holds no
gate logic of its own, so this resolver's no-gate contract is unchanged.
"""

from __future__ import annotations

from ...work_package_reference import is_numeric_ref
from ..caches import CachedValue
from ..errors import InvalidInputError
from ..offered_values import offered_clause
from ..ports.status_priority_type_api import PriorityRecord, StatusPriorityTypeApi, StatusRecord


class StatusPriorityTypeResolver:
    def __init__(
        self,
        *,
        api: StatusPriorityTypeApi,
        statuses_cache: CachedValue[list[StatusRecord]],
        priorities_cache: CachedValue[list[PriorityRecord]],
    ) -> None:
        self._api = api
        self._statuses_cache = statuses_cache
        self._priorities_cache = priorities_cache

    async def resolve_status_id(self, status_ref: str) -> str:
        if is_numeric_ref(status_ref):
            return status_ref
        statuses = await self._statuses_cache.get(self._api.list_statuses)
        matches = [
            str(record.summary.id) for record in statuses if record.lookup_name.casefold() == status_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(
                f"OpenProject status '{status_ref}' was not found."
                + offered_clause((record.lookup_name for record in statuses), plural="statuses")
            )
        return matches[0]

    async def resolve_priority_id(self, priority_ref: str) -> str:
        if is_numeric_ref(priority_ref):
            return priority_ref
        priorities = await self._priorities_cache.get(self._api.list_priorities)
        matches = [
            str(record.summary.id) for record in priorities if record.lookup_name.casefold() == priority_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(
                f"OpenProject priority '{priority_ref}' was not found."
                + offered_clause((record.lookup_name for record in priorities), plural="priorities")
            )
        return matches[0]
