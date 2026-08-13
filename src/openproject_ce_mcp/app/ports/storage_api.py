"""Storages Domain API port.

Full CRUD (unlike FileLinks/Documents/ProjectStorages): OpenProject's v3 API
genuinely exposes POST/GET/PATCH/DELETE on storages
(modules/storages/lib/api/v3/storages/storages_api.rb mounts all four verbs
directly), all four admin-gated (Storages::Storages::BaseContract includes
ManageStoragesGuarded, covering Create+Update; DeleteContract separately
declares `delete_permission :admin` -- a different mechanism, same effective
gate). GET (list_all/get) is additionally reachable by a non-admin user with
`manage_files_in_project` in any project or `view_file_links` in a project
already linked to the storage (`Storages::Storage.visible`) -- this MCP does
not attempt to mirror that finer read permission and gates both read and
write under this MCP's own "admin" scope, matching the existing Users/Groups
precedent.

No `create_form`/`update_form`: storages_api.rb mounts Endpoints::Create/
Update directly (no Endpoints::CreateForm/UpdateForm), so there is no
`.../form` two-phase validation endpoint to call, unlike Versions/Users/
Documents. Contract validation errors -- including the Enterprise-gate
rejection on create for OneDrive/Sharepoint, and the synchronous
Nextcloud-compatible-host probe for Nextcloud -- surface as a normal HTTP
error on the commit call itself, not as an embedded `validationErrors`
object in a 200 response. StorageService therefore follows GroupService's
form-less write shape, not VersionService's `_finalize_write`/form-based
shape.

`storages`' collection representer (StorageCollectionRepresenter) subclasses
`::API::Decorators::UnpaginatedCollection`, not `OffsetPaginatedCollection`
-- verified directly against source. The server ignores `offset`/`pageSize`
entirely and always returns the full collection; `list_all` is sent here for
interface symmetry / forward-compat only, matching RoleApi's documented
contract. See StorageService.list_storages for the required client-side
`paginate_client` slicing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import StorageDetail, StorageSummary


@dataclass(frozen=True)
class StorageRecord:
    summary: StorageSummary
    to_detail: Callable[[], StorageDetail]


class StorageApi(Protocol):
    """Narrow, Storages-only Domain API port. StorageService depends on this
    Protocol, never on HttpxStorageApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[StorageRecord], int]: ...
    async def get(self, storage_id: int) -> StorageRecord: ...
    async def commit_create(self, payload: dict[str, Any]) -> StorageDetail: ...
    async def commit_update(self, storage_id: int, payload: dict[str, Any]) -> StorageDetail: ...
    async def commit_delete(self, storage_id: int) -> None: ...
