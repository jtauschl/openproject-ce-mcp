"""Project Storages Domain API port -- narrow, read-only.

No commit_create/commit_update/commit_delete: OpenProject's v3 API mounts
only `get` (Index) and `get` under route_param :id (Show) for
project_storages -- confirmed against modules/storages/lib/api/v3/
project_storages/project_storages_api.rb, no post/patch/delete verb exists
in the REST v3 surface at all (app/contracts/storages/project_storages/
create_contract.rb and delete_contract.rb exist on disk, but back the
internal Rails/UI CreateService/DeleteService, not the API -- they are
unreachable from ProjectStoragesAPI). The `open`/`openWithConnectionEnsured`
sub-endpoint (a 303 redirect to the external storage's folder URL) is out of
scope -- not a data-returning endpoint and not naturally tool-shaped.

`project_storages`' collection representer (ProjectStorageCollectionRepresenter)
subclasses `::API::Decorators::UnpaginatedCollection`, not
`OffsetPaginatedCollection` -- verified directly against source, same as
Storages. The server ignores `offset`/`pageSize` entirely and always returns
the full (server-side-filtered, if `filters=` was sent) collection. This
port does not thread a raw `filters=` parameter through at all -- list_all
always fetches everything and ProjectStorageService applies its own
allowlist/candidate filtering client-side, the same shape RoleService uses
for its own unpaginated collection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ProjectStorageDetail, ProjectStorageSummary


@dataclass(frozen=True)
class ProjectStorageRecord:
    """Carries the raw `project` link alongside the normalized summary/detail
    thunk, same rationale as DocumentRecord: the allowlist Policy check needs
    the raw href/title, which neither normalized model carries.
    """

    summary: ProjectStorageSummary
    to_detail: Callable[[], ProjectStorageDetail]
    project_link: dict[str, Any] | None


class ProjectStorageApi(Protocol):
    """Narrow, ProjectStorages-only Domain API port. ProjectStorageService
    depends on this Protocol, never on HttpxProjectStorageApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ProjectStorageRecord], int]: ...
    async def get(self, project_storage_id: int) -> ProjectStorageRecord: ...
