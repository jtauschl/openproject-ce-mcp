"""Revisions Domain API port.

Read-only: a work package's linked repository revisions, and one revision by
id. Records carry the raw `_links.project` link beside the normalized
summary, because the Service authorizes every revision against
OPENPROJECT_READ_PROJECTS by the project it belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import RevisionSummary


@dataclass(frozen=True)
class RevisionRecord:
    summary: RevisionSummary
    project_link: dict[str, Any] | None


class RevisionApi(Protocol):
    """Narrow, Revisions-only Domain API port. RevisionService depends on this
    Protocol, never on HttpxRevisionApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[RevisionRecord]: ...
    async def get(self, revision_id: int) -> RevisionRecord: ...
