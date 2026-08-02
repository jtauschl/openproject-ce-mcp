"""File Links Domain API port.

Narrow: list (scoped to one work package) + get (single file link, used only
by delete()'s preview/allowlist step) + delete. No create/update TOOL is
exposed here, but this is a deliberate product scoping decision, not an
absence-of-endpoint fact: OpenProject's v3 API DOES have a real
`POST /api/v3/work_packages/{id}/file_links` (verified against OpenProject's
own API implementation: `post &WorkPackagesFileLinksCreateEndpoint`), and
`PATCH` genuinely does not exist. Create is left unimplemented because it
requires storage-specific origin/location data this server has no mechanism
to source (Nextcloud/OneDrive file identifiers), not because no endpoint
exists to call.

`list_for_work_package` takes real pagination parameters -- the collection is
genuinely `OffsetPaginatedCollection` server-side, so an earlier version of
this method that issued a single unparameterized GET was silently returning
only the server's default page instead of every file link.

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

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[FileLinkRecord], int]: ...
    async def get(self, file_link_id: int) -> FileLinkRecord: ...
    async def delete(self, file_link_id: int) -> None: ...
