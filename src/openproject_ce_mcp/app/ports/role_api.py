"""Roles Domain API port (13th migrated domain).

Read-only, server-paginated (offset/pageSize) list only -- OpenProject's API
exposes no single-item GET, no create/update/delete for roles (admin-UI-only
resource). `RoleRecord` carries no link: roles have no project concept at all,
same shape as `ActionRecord`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import RoleSummary


@dataclass(frozen=True)
class RoleRecord:
    summary: RoleSummary


class RoleApi(Protocol):
    """Narrow, Roles-only Domain API port. RoleService depends on this
    Protocol, never on HttpxRoleApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_roles(self, *, offset: int, page_size: int) -> tuple[list[RoleRecord], int]: ...
