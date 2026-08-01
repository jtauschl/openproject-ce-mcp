"""Status/priority-reference resolver (ADR 0001, OPM-371).

Bundles `resolve_status_id`/`resolve_priority_id` in one Resolver, matching
how client.py placed `_resolve_status_id`/`_resolve_priority_id` adjacently
and their identical shape: both need only the `StatusPriorityTypeApi`
dependency, neither takes a project/context parameter.

Behavioral note preserved verbatim from the flat originals (OPM-371 Finding
1a): on a duplicate name match, both methods silently return the FIRST
match -- there is no ambiguity check here, unlike `TypeResolver`/
`SprintResolver`, which both raise on an ambiguous match. This asymmetry is
pre-existing, not a bug introduced by this migration; do not "fix" it by
adding an ambiguity check that changes existing behavior.

Genuine bug fix folded into this move (OPM-371 Finding 1b): the flat
originals made a raw, unnormalized `_get("statuses")`/`_get("priorities")`
HTTP call and hand-parsed `_embedded.elements` directly, duplicating parsing
logic `StatusPriorityTypeApi.list_statuses`/`list_priorities` already do
correctly. This resolver goes through the Port instead, reusing
`normalize_status`/`normalize_priority`. The Port's normalizer trims/
collapses whitespace and truncates at 255 chars (`app/adapters/_text.py`'s
`trim_text`) before this resolver ever sees a name -- a narrow, acknowledged
behavior change from the flat code's raw, untrimmed `str(name).casefold()`
comparison. In practice this only affects a status/priority name containing
irregular whitespace or exceeding 255 characters (OpenProject status/priority
names are admin-controlled and realistically short/single-line), but it is a
real, deliberate difference, not an accidental one -- see
`test_app_status_priority_type_resolver.py`'s dedicated regression test.
Depends on `StatusPriorityTypeApi` (the Port), never
`StatusPriorityTypeService` -- reusing the Service's own gated
`list_statuses`/`list_priorities` would reintroduce exactly the
read-enablement-gate regression `WorkPackageService`'s own module docstring
already documents fixing elsewhere: an instance can have work-package writes
enabled with reads entirely disabled, and this resolver's callers (write-path
name resolution) must keep working in that configuration.
"""

from __future__ import annotations

from ..errors import InvalidInputError
from ..ports.status_priority_type_api import StatusPriorityTypeApi


class StatusPriorityTypeResolver:
    def __init__(self, *, api: StatusPriorityTypeApi) -> None:
        self._api = api

    async def resolve_status_id(self, status_ref: str) -> str:
        if status_ref.isdigit():
            return status_ref
        records = await self._api.list_statuses()
        matches = [
            str(record.summary.id) for record in records if record.summary.name.casefold() == status_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject status '{status_ref}' was not found.")
        return matches[0]

    async def resolve_priority_id(self, priority_ref: str) -> str:
        if priority_ref.isdigit():
            return priority_ref
        records = await self._api.list_priorities()
        matches = [
            str(record.summary.id) for record in records if record.summary.name.casefold() == priority_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject priority '{priority_ref}' was not found.")
        return matches[0]
