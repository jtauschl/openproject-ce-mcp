"""Principal-reference resolution port (ADR 0001).

Narrow seam onto the still-flat Admin/Principal domain's existing resolution
machinery (_resolve_principal_id -- explicitly out of scope for the
Memberships migration, reused as-is, mirroring how app/ports/project_ref.py
seams onto _get_project_payload for the still-unmigrated Project-resolution
machinery during the Versions pilot). The concrete value OpenProjectClient
hands in is literally the bound method self._resolve_principal_id
(structural typing, no wrapper class needed). Replace with a real
PrincipalApi port once a Principal/Admin domain migrates.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class PrincipalRefResolver(Protocol):
    def __call__(self, principal_ref: str) -> Awaitable[str]: ...
