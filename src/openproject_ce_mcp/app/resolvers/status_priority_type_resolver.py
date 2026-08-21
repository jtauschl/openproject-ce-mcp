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

`statuses_cache`/`priorities_cache` are the same `SingletonCache` instances
`client.py` also gives `StatusPriorityTypeService` -- see `app/caches.py`.
Consulting the cache here does NOT add a read-gate check: the cache holds no
gate logic of its own, so this resolver's no-gate contract is unchanged.
"""

from __future__ import annotations

from ..caches import SingletonCache
from ..errors import InvalidInputError
from ..ports.status_priority_type_api import PriorityRecord, StatusPriorityTypeApi, StatusRecord


class StatusPriorityTypeResolver:
    def __init__(
        self,
        *,
        api: StatusPriorityTypeApi,
        statuses_cache: SingletonCache[list[StatusRecord]],
        priorities_cache: SingletonCache[list[PriorityRecord]],
    ) -> None:
        self._api = api
        self._statuses_cache = statuses_cache
        self._priorities_cache = priorities_cache

    async def resolve_status_id(self, status_ref: str) -> str:
        if status_ref.isdigit():
            return status_ref
        if self._statuses_cache.value is None:
            self._statuses_cache.value = await self._api.list_statuses()
        matches = [
            str(record.summary.id)
            for record in self._statuses_cache.value
            if record.lookup_name.casefold() == status_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject status '{status_ref}' was not found.")
        return matches[0]

    async def resolve_priority_id(self, priority_ref: str) -> str:
        if priority_ref.isdigit():
            return priority_ref
        if self._priorities_cache.value is None:
            self._priorities_cache.value = await self._api.list_priorities()
        matches = [
            str(record.summary.id)
            for record in self._priorities_cache.value
            if record.lookup_name.casefold() == priority_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject priority '{priority_ref}' was not found.")
        return matches[0]
