"""Actions & Capabilities Domain API port (ADR 0001) -- narrow, no universal gateway.

Two unrelated-but-bundled read-only lookups (OPM-276 groups them as one
migration ticket, matching client.py's own adjacent placement), each with its
own Record: neither payload carries a `project` HAL link of its own (Actions
has no project concept at all; Capabilities' project scope comes from the
caller-supplied `context` filter, already allowlist-checked by
ProjectRefResolver before the fetch, same as Categories) -- so neither Record
carries a link field for a Policy check to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import ActionSummary, CapabilitySummary


@dataclass(frozen=True)
class ActionRecord:
    summary: ActionSummary


@dataclass(frozen=True)
class CapabilityRecord:
    summary: CapabilitySummary


class ActionCapabilityApi(Protocol):
    """Narrow, Actions/Capabilities-only Domain API port. ActionCapabilityService
    depends on this Protocol, never on HttpxActionCapabilityApi concretely
    (enforced by the architecture-boundary test).

    Both read-only, server-paginated (offset/pageSize) list endpoints with no
    single-item GET, no create/update/delete -- OpenProject's API exposes
    neither for actions nor for capabilities.
    """

    async def list_actions(self, *, offset: int, page_size: int) -> tuple[list[ActionRecord], int]: ...

    async def list_capabilities(
        self, *, filters: list[dict[str, object]], offset: int, page_size: int
    ) -> tuple[list[CapabilityRecord], int]: ...
