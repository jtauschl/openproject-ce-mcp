"""File Links Domain API port (ADR 0001, OPM-318 first consumer).

Narrow: list (scoped to one work package) + get (single file link, used only
by delete()'s preview/allowlist step) + delete. No create/update endpoint --
the OpenProject v3 API exposes no POST/PATCH for file links (client.py's flat
implementation never had one either; this is a Nextcloud-storage-integration
read+delete resource by design, not an oversight).

No `to_detail`: `FileLinkSummary` IS the only normalized shape this domain
has (no separate Detail model exists in models.py), so `FileLinkRecord`
carries no lazy-detail thunk, unlike `DocumentRecord`/`NewsRecord`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import FileLinkSummary


@dataclass(frozen=True)
class FileLinkRecord:
    """One file link as read from the API: the normalized `summary`, plus the
    raw `_links.container` link dict. Carried as the RAW link dict, not a
    pre-extracted href/int, because the Service needs to distinguish "no
    container link at all" from "container link present but unparsable" --
    both collapse to `work_package_id=None` in client.py's original, a
    behavior preserved here without change.
    """

    summary: FileLinkSummary
    container_link: dict[str, Any] | None


class FileLinkApi(Protocol):
    """Narrow, File-Links-only Domain API port. FileLinkService depends on
    this Protocol, never on HttpxFileLinkApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[FileLinkRecord]: ...
    async def get(self, file_link_id: int) -> FileLinkRecord: ...
    async def delete(self, file_link_id: int) -> None: ...
