"""Statuses/Priorities/Types Domain API port.

Three unrelated-but-bundled read-only lookups (client.py places them
adjacently, grouped as one migration -- same
bundling rationale as Actions & Capabilities). Each has its
own Record; none carries a project link -- Status/Priority have no project
concept at all, and Type's project-optional `list()` branch shapes the
*request* (which endpoint to call), not a per-record link to allowlist-check
after the fact (verified: client.py's original `list_types` resolves the
project purely to pick `projects/{id}/types` vs `types`, with no per-record
scope filtering of the response).

No `to_detail` split on any of the three Records: `get_status`/`get_priority`/
`get_type` are plain single-item fetches through the same normalizer as list
rows, with no separate detail-only fields to compute lazily (unlike Users/
Documents/Versions).

Each Record also carries `lookup_name`: the raw payload's `name` field
(`str(payload.get("name", ""))`), independent of `summary.name`. The two
differ deliberately: `summary.name` falls back to a synthetic display name
(`f"Status {id}"`) when the raw name is blank/missing, so list/get MCP tool
output never shows an empty display name -- correct DISPLAY behavior, but
wrong for exact-name RESOLUTION (a caller searching for the literal string
"Status 7" should not accidentally match a status whose real name was blank,
the way matching against `summary.name` would allow). `lookup_name` is
never synthesized, so resolvers compare against it, not `summary.name`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import PrioritySummary, StatusSummary, TypeSummary


@dataclass(frozen=True)
class StatusRecord:
    summary: StatusSummary
    lookup_name: str


@dataclass(frozen=True)
class PriorityRecord:
    summary: PrioritySummary
    lookup_name: str


@dataclass(frozen=True)
class TypeRecord:
    summary: TypeSummary
    lookup_name: str


class StatusPriorityTypeApi(Protocol):
    """Narrow, Statuses/Priorities/Types-only Domain API port.
    StatusPriorityTypeService depends on this Protocol, never on
    HttpxStatusPriorityTypeApi concretely (enforced by the
    architecture-boundary test).

    Read-only, unpaginated (plain `CollectionResult` fetch-all, matching
    Categories' shape, not Roles'/Actions' offset/pageSize `PageResult`
    shape) -- verified against `StatusListResult`/`PriorityListResult`/
    `TypeListResult` in models.py, all plain `CollectionResult` subclasses.
    No create/update/delete for any of the three -- OpenProject's API
    exposes none (admin-UI-only resources, same category as Roles).
    """

    async def list_statuses(self) -> list[StatusRecord]: ...

    async def get_status(self, status_id: int) -> StatusRecord: ...

    async def list_priorities(self) -> list[PriorityRecord]: ...

    async def get_priority(self, priority_id: int) -> PriorityRecord: ...

    async def list_types(self, *, project_id: int | None) -> list[TypeRecord]: ...

    async def get_type(self, type_id: int) -> TypeRecord: ...
