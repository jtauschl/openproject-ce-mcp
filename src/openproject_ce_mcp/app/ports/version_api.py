"""Versions Domain API port -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import VersionDetail, VersionSummary
from ..form_result import FormResult

# Duplicated from httpx_version_api.py's constant of the same name (a deliberate
# duplication) -- needed here only as the Protocol's default text_limit.
FORMATTABLE_LIMIT = 1_200


def summary_to_detail(s: VersionSummary) -> VersionDetail:
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
        description_truncated=s.description_truncated,
        description_length=s.description_length,
    )


@dataclass(frozen=True)
class VersionRecord:
    """One version as read from the API: the normalized summary plus the raw
    definingProject HAL link. The link must be carried separately because
    VersionSummary.defining_project is title-only -- OpenProject's version payload
    never carries the defining project's identifier, only its display title. The
    allowlist Policy check needs the raw link (href/id), so it cannot be done from
    the normalized model alone.

    `lookup_name` carries the raw payload's `name` field, independent of
    `summary.name`. `normalize_version` falls back to a synthetic display name
    (`f"Version {id}"`) when the raw name is blank/missing -- correct DISPLAY
    behavior, but wrong for exact-name RESOLUTION (`VersionResolver` must not
    let a caller's literal search for "Version 7" accidentally match a version
    whose real name was blank). `lookup_name` is never synthesized, so
    `VersionResolver` compares against it instead of `summary.name`.
    """

    summary: VersionSummary
    defining_project_link: dict[str, Any] | None
    lookup_name: str

    def to_detail(self) -> VersionDetail:
        return summary_to_detail(self.summary)


@dataclass(frozen=True)
class VersionPage:
    records: list[VersionRecord]
    server_total: int | None  # set only by the exact-server-pagination path; None elsewhere


VersionFormResult = FormResult


class VersionApi(Protocol):
    """Narrow, Versions-only Domain API port. VersionService/VersionResolver depend
    on this Protocol, never on HttpxVersionApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionPage: ...
    async def list_global(
        self, *, offset: int, page_size: int, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionPage: ...
    async def get(self, version_id: int, *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionRecord: ...
    async def create_form(self, payload: dict[str, Any]) -> VersionFormResult: ...
    async def update_form(self, version_id: int, payload: dict[str, Any]) -> VersionFormResult: ...
    async def commit_create(self, payload: dict[str, Any]) -> VersionDetail: ...
    async def commit_update(self, version_id: int, payload: dict[str, Any]) -> VersionDetail: ...
    async def delete(self, version_id: int) -> None: ...
