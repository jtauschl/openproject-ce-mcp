"""Principals Domain API port (ADR 0001).

Read-only list only -- OpenProject exposes no single-item GET for a
principal (users/groups have their own domain single-item GETs; `principals`
is a read-only, combined-search collection over both).

Named `principal_api.py`, NOT `principal_ref.py` -- that filename is already
taken by the pre-existing `PrincipalRefResolver` seam Protocol
(app/ports/principal_ref.py), a bare-callable seam three already-migrated
Services depend on (satisfied structurally by the bound method
`self._resolve_principal_id`, unrelated to this migration and left
untouched).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import PrincipalSummary


@dataclass(frozen=True)
class PrincipalRecord:
    summary: PrincipalSummary


class PrincipalApi(Protocol):
    """Narrow, Principals-only Domain API port. PrincipalService and
    PrincipalResolver both depend on this Protocol, never on
    HttpxPrincipalApi concretely (enforced by the architecture-boundary
    test). Deliberately ungated -- I/O and normalization only, no read-scope
    check -- so PrincipalResolver can search principals without requiring
    OPENPROJECT_ENABLE_ADMIN_READ (see PrincipalResolver's own docstring).
    """

    async def list_principals(
        self, *, search: str | None, offset: int, page_size: int
    ) -> tuple[list[PrincipalRecord], int]: ...
