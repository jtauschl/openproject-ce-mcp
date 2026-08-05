"""Work-package-type-reference resolver.

Raises `InvalidInputError` on more than one case-insensitive name match --
unlike `StatusPriorityTypeResolver`'s status/priority methods, which
silently return the first match; see that resolver's module docstring for
the asymmetry. Depends on `StatusPriorityTypeApi` (the Port, not the gated
Service -- same read-gate-bypass reasoning as `StatusPriorityTypeResolver`)
plus the `ProjectRefResolver` seam for resolving `project` to a numeric id
first. Name comparison uses `TypeRecord.lookup_name` (the raw,
never-synthesized name), not `summary.name` -- see
`app/ports/status_priority_type_api.py`'s module docstring for why.
"""

from __future__ import annotations

from ..errors import InvalidInputError
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.status_priority_type_api import StatusPriorityTypeApi


class TypeResolver:
    def __init__(self, *, api: StatusPriorityTypeApi, resolve_project_ref: ProjectRefResolver) -> None:
        self._api = api
        self._resolve_project_ref = resolve_project_ref

    async def resolve_id(
        self, type_ref: str, *, project: str | None, context: ProjectResolutionContext | None = None
    ) -> str:
        if type_ref.isdigit():
            return type_ref
        if not project:
            raise InvalidInputError("type names require a project filter. Pass a numeric type id or set project.")

        project_payload = await self._resolve_project_ref(project, context=context)
        project_id = int(project_payload["id"])
        records = await self._api.list_types(project_id=project_id)
        matches = [str(record.summary.id) for record in records if record.lookup_name.casefold() == type_ref.casefold()]
        if not matches:
            raise InvalidInputError(f"OpenProject type '{type_ref}' was not found in project '{project}'.")
        if len(matches) > 1:
            raise InvalidInputError(f"OpenProject type '{type_ref}' is ambiguous. Pass a numeric type id.")
        return matches[0]
