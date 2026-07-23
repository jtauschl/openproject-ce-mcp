"""Memberships Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import MembershipSummary


@dataclass(frozen=True)
class MembershipRecord:
    """One membership as read from the API: the normalized summary plus the raw
    `project` HAL link. The link must be carried separately (mirrors
    VersionRecord.defining_project_link) because the allowlist Policy check
    needs the raw link (href/id), which MembershipSummary itself (a
    display-only, already-normalized model) does not carry.
    """

    summary: MembershipSummary
    project_link: dict[str, Any] | None


@dataclass(frozen=True)
class MembershipPage:
    records: list[MembershipRecord]
    server_total: int | None


@dataclass(frozen=True)
class MembershipFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]


class MembershipApi(Protocol):
    """Narrow, Memberships-only Domain API port. MembershipService depends on
    this Protocol, never on HttpxMembershipApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_project(
        self, project_memberships_href: str, *, offset: int, page_size: int
    ) -> MembershipPage: ...
    async def get(self, membership_id: int) -> MembershipRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> MembershipFormResult: ...
    async def update_form(self, membership_id: int, payload: dict[str, Any]) -> MembershipFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> MembershipSummary: ...
    async def commit_update(self, membership_id: int, payload: dict[str, Any]) -> MembershipSummary: ...
    async def delete(self, membership_id: int) -> None: ...
