"""Versions Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import VersionDetail, VersionSummary


@dataclass(frozen=True)
class VersionRecord:
    """One version as read from the API: the normalized summary plus the raw
    definingProject HAL link. The link must be carried separately because
    VersionSummary.defining_project is title-only -- OpenProject's version payload
    never carries the defining project's identifier, only its display title. The
    allowlist Policy check needs the raw link (href/id), so it cannot be done from
    the normalized model alone.
    """

    summary: VersionSummary
    defining_project_link: dict[str, Any] | None

    def to_detail(self) -> VersionDetail:
        s = self.summary
        return VersionDetail(
            id=s.id,
            name=s.name,
            status=s.status,
            sharing=s.sharing,
            start_date=s.start_date,
            end_date=s.end_date,
            defining_project=s.defining_project,
            description=s.description,
            url=s.url,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


@dataclass(frozen=True)
class VersionPage:
    records: list[VersionRecord]
    server_total: int | None  # set only by the exact-server-pagination path; None elsewhere


@dataclass(frozen=True)
class VersionFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]


class VersionApi(Protocol):
    """Narrow, Versions-only Domain API port. VersionService/VersionResolver depend
    on this Protocol, never on HttpxVersionApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_project(self, project_id: int, *, offset: int, page_size: int) -> VersionPage: ...
    async def list_global(self, *, offset: int, page_size: int) -> VersionPage: ...
    async def get(self, version_id: int) -> VersionRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> VersionFormResult: ...
    async def update_form(self, version_id: int, payload: dict[str, Any]) -> VersionFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> VersionDetail: ...
    async def commit_update(self, version_id: int, payload: dict[str, Any]) -> VersionDetail: ...
    async def delete(self, version_id: int) -> None: ...
