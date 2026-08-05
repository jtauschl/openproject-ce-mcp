"""Principal-reference resolution port.

Narrow, single-callable seam for resolving a principal reference (name or
id) to a principal id, used by `MembershipService`/`WorkPackageService`/
`TimeEntryService`. Distinct from `PrincipalApi` (`principal_api.py`), which
is a read-only list/search Domain API port for principal records -- this
seam is purely a reference-resolution function, not a general lookup API,
and the two are not interchangeable.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class PrincipalRefResolver(Protocol):
    def __call__(self, principal_ref: str) -> Awaitable[str]: ...
