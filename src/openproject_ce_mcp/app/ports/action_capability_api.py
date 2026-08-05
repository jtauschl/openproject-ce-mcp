"""Actions & Capabilities Domain API port -- narrow, no universal gateway.

Two unrelated-but-bundled read-only lookups, each with its own Record.
`ActionRecord` carries no link: Actions has no project concept at all.
`CapabilityRecord` DOES carry the raw `context` HAL link (per the OpenProject
API docs, `context.href` is a genuine `/api/v3/projects/{id}` or
`/api/v3/workspaces/{id}` link, not merely a title): a `capability_id`-only
call (no `project` given) has no `project` parameter to allowlist-check, so
each individual returned record's own `context` link must be checked instead
-- otherwise a restrictive `OPENPROJECT_READ_PROJECTS` scope would leak
capability records, including their project-identifying `context`
title/href, for projects outside the caller's read scope. `CapabilityService`
checks each record's `context` link the same way Views checks its
(also-nullable) `project_link` -- see `view_service.py`'s `_allowed` for the
shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ActionSummary, CapabilitySummary


@dataclass(frozen=True)
class ActionRecord:
    summary: ActionSummary


@dataclass(frozen=True)
class CapabilityRecord:
    summary: CapabilitySummary
    context_link: dict[str, Any] | None


class ActionCapabilityApi(Protocol):
    """Narrow, Actions/Capabilities-only Domain API port. ActionCapabilityService
    depends on this Protocol, never on HttpxActionCapabilityApi concretely
    (enforced by the architecture-boundary test).

    Actions: read-only, server-paginated (offset/pageSize) list only, no
    single-item GET, no create/update/delete -- OpenProject's API exposes
    none of those for actions. Capabilities: read-only, server-paginated
    list PLUS a single-item `get` (a `capability_id`-only lookup uses this
    `get`, not a collection `id` filter, which the API does not support;
    see `action_capability_service.py`'s module docstring).
    """

    async def list_actions(self, *, offset: int, page_size: int) -> tuple[list[ActionRecord], int]: ...

    async def list_capabilities(
        self, *, filters: list[dict[str, object]], offset: int, page_size: int
    ) -> tuple[list[CapabilityRecord], int]: ...

    async def get_capability(self, capability_id: str) -> CapabilityRecord: ...
