"""Application Service for the Storages domain.

Depends on the StorageApi Protocol, never HttpxStorageApi concretely
(enforced by the architecture-boundary test). No ProjectRefResolver:
storages are a global/instance-wide resource with no project concept of
their own (a storage is later LINKED to projects via project_storages, but
the storage record itself isn't project-scoped) -- same zero-Resolver
template as RoleService/UserService/GroupService.

`list_storages` paginates client-side via `paginate_client`, not
server-side (verified directly against source): `/api/v3/storages`'
StorageCollectionRepresenter subclasses UnpaginatedCollection, not
OffsetPaginatedCollection -- the server ignores offset/pageSize entirely
and always returns the full collection. `_api.list_all` is always called
with `offset=1, page_size=settings.max_results` (fetch everything), and the
resulting full list is sliced locally via `paginate_client` -- same pattern
as RoleService.

Read/write scope is "admin" throughout (list/get/create/update/delete): this
mirrors OpenProject's own admin-gating for writes exactly
(Storages::Storages::BaseContract's ManageStoragesGuarded +
DeleteContract's separate `delete_permission :admin` both require
user.admin? && user.active?), but is a deliberate simplification for reads
-- OpenProject's own `Storage.visible` scope also allows a non-admin user
with `manage_files_in_project` in any project (or `view_file_links` in a
project already linked to the storage) to read storages. This MCP does not
attempt to mirror that finer-grained read permission; "admin" scope gating
list_storages/get_storage is consistent with this codebase's existing
precedent for Users/Groups (also read-gated under "admin" even though
OpenProject's own API might allow a narrower non-admin read in some cases).

create()/update()/delete() have NO form endpoint (storages_api.rb mounts
Endpoints::Create/Update directly, never Endpoints::CreateForm/UpdateForm)
-- modeled on GroupService's no-form write shape (build the payload dict
directly, no validation-errors preview branch) rather than VersionService's
`_finalize_write`/form-based flow. A caller therefore only discovers a
contract validation failure (including the Enterprise-gate rejection on
create for OneDrive/Sharepoint, and the SYNCHRONOUS live Nextcloud-host
probe OpenProject itself runs on a Nextcloud create/update whose `host`
attribute changed -- verified against
NextcloudCompatibleHostValidator#validate_each, which fires a real HTTP GET
against `{host}/ocs/v2.php/cloud/capabilities` and
`{host}/index.php/apps/integration_openproject/check-config`) at
confirm=true commit time, not at the confirm=false preview step -- there is
no OpenProject-side endpoint that would let this Service validate cheaply
before committing.

Provider payload shape is genuinely different per provider_type (verified
against each provider's own contract, not assumed uniform):
- Nextcloud: `host` required (goes through the live-reachability probe
  above) and `authentication_method` required (one of "two_way_oauth2" /
  "oauth2_sso", GeneralInformationContract#AUTHENTICATION_METHODS).
- OneDrive: `host` must be ABSENT (OneDriveContract validates :host,
  absence: true) -- `tenant_id` required (GUID format, or the literal
  string "consumers"). `drive_id` optional.
- Sharepoint: `host` required, matching `https://.../sites/...`
  (SharepointContract's format validator) -- `tenant_id` required (same
  format as OneDrive).
This Service does not attempt to pre-validate these provider-specific rules
beyond routing `provider_type` to a known URN (a nonsense provider_type
string is rejected client-side as basic input hygiene) -- the rest is left
to OpenProject's own contract validation, propagated via the existing
403/422 transport mapping (see raise_for_status), consistent with every
other Enterprise-gated capability in this codebase ("let the server
decide", never "assume no Enterprise token" client-side).

create()/update()/delete() all check access.ensure_write_enabled("admin",
...) UNCONDITIONALLY (not gated inside the confirm branch) for create (no
prior GET to piggyback on); update()/delete() perform a prior GET (to show
a real current-state preview) but still check write-enablement
unconditionally, matching GroupService's documented tradeoff (a caller
without OPENPROJECT_ENABLE_ADMIN_WRITE cannot see a full preview via
update()/delete(), only the identity confirmation) -- actually stronger
here, since delete()'s prior GET means even the identity confirmation is
withheld from a read-disabled-but-somehow-write-enabled caller (an
unreachable combination given Settings.from_env's write-implies-read
validation, but the ordering still matters for a directly-constructed
Settings in a test).

delete()'s prior GET and preview message deliberately surface a warning
about OpenProject's own cascade behavior: Storages::Storages::DeleteService
destroys every linked ProjectStorage (`has_many :project_storages,
dependent: :destroy`), and for a storage with `automatically_managed`
project folders, this can trigger a REMOTE folder-deletion call against the
external storage itself -- a real-world side effect well beyond deleting a
database row, worth surfacing before a caller confirms.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import StorageDetail, StorageListResult, StorageWriteResult, WriteResultState
from ..errors import InvalidInputError
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..ports.storage_api import StorageApi

_PROVIDER_TYPE_URN = {
    "Nextcloud": "urn:openproject-org:api:v3:storages:Nextcloud",
    "OneDrive": "urn:openproject-org:api:v3:storages:OneDrive",
    "Sharepoint": "urn:openproject-org:api:v3:storages:Sharepoint",
}

# authenticationMethod is a `link_without_resource` on StorageRepresenter
# (op-sources/full-17.6/.../storage_representer.rb), not a plain top-level
# JSON property -- its setter reads ONLY `_links.authenticationMethod.href`
# (a full URN) via `AUTHENTICATION_METHOD_MAP.fetch(href)`, breaking on
# (silently ignoring) any other shape, including a bare top-level string.
# Reverse of the adapter's own _AUTHENTICATION_METHOD_MAP
# (httpx_storage_api.py), which decodes the URN suffix on read.
_AUTHENTICATION_METHOD_URN = {
    "two_way_oauth2": "urn:openproject-org:api:v3:storages:authenticationMethod:TwoWayOAuth2",
    "oauth2_sso": "urn:openproject-org:api:v3:storages:authenticationMethod:OAuth2SSO",
}


class StorageService:
    def __init__(self, *, api: StorageApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("storage", value, settings=self._settings)

    async def list_storages(self, *, offset: int = 1, limit: int | None = None) -> StorageListResult:
        access.ensure_read_enabled("admin", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
        # NB: the server ignores offset/pageSize for /api/v3/storages and
        # always returns the full collection -- fetch everything once
        # (bounded by max_results, not effective_limit) and slice locally
        # instead of trusting a server-side page that never actually happens.
        records, _server_total = await self._api.list_all(offset=1, page_size=self._settings.max_results)
        all_results = [self._stamp(record.summary) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=all_results)
        return StorageListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get_storage(self, storage_id: int) -> StorageDetail:
        access.ensure_read_enabled("admin", settings=self._settings)
        record = await self._api.get(storage_id)
        return self._stamp(record.to_detail())

    async def create(
        self,
        *,
        name: str,
        provider_type: str,
        host: str | None = None,
        authentication_method: str | None = None,
        tenant_id: str | None = None,
        drive_id: str | None = None,
        confirm: bool = False,
    ) -> StorageWriteResult:
        # Checked unconditionally -- no prior GET to gate an unauthorized
        # preview request on (matches GroupService.create()).
        access.ensure_write_enabled("admin", settings=self._settings)
        urn = _PROVIDER_TYPE_URN.get(provider_type)
        if urn is None:
            raise InvalidInputError(
                f"OpenProject storage provider_type must be one of {sorted(_PROVIDER_TYPE_URN)}, got {provider_type!r}."
            )
        hidden_fields.ensure_field_writable("storage", "name", settings=self._settings)
        hidden_fields.ensure_field_writable("storage", "provider_type", settings=self._settings)
        links: dict[str, Any] = {"type": {"href": urn}}
        payload_preview: dict[str, Any] = {"name": name, "provider_type": provider_type}
        if host is not None:
            hidden_fields.ensure_field_writable("storage", "host", settings=self._settings)
            links["origin"] = {"href": host}
            payload_preview["host"] = host
        if authentication_method is not None:
            hidden_fields.ensure_field_writable("storage", "authentication_method", settings=self._settings)
            auth_urn = _AUTHENTICATION_METHOD_URN.get(authentication_method)
            if auth_urn is None:
                raise InvalidInputError(
                    "OpenProject storage authentication_method must be one of "
                    f"{sorted(_AUTHENTICATION_METHOD_URN)}, got {authentication_method!r}."
                )
            links["authenticationMethod"] = {"href": auth_urn}
            payload_preview["authentication_method"] = authentication_method
        body: dict[str, Any] = {"name": name, "_links": links}
        if tenant_id is not None:
            hidden_fields.ensure_field_writable("storage", "tenant_id", settings=self._settings)
            body["tenant_id"] = tenant_id
            payload_preview["tenant_id"] = tenant_id
        if drive_id is not None:
            hidden_fields.ensure_field_writable("storage", "drive_id", settings=self._settings)
            body["drive_id"] = drive_id
            payload_preview["drive_id"] = drive_id

        if not confirm:
            return self._write_result(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to attempt creating the storage. There is no pre-validation "
                    "endpoint for storages, so provider-specific rejections (an OneDrive/Sharepoint "
                    "provider_type on a Community Edition instance without an Enterprise token; a "
                    "Nextcloud host that fails OpenProject's live reachability/setup-completeness probe) "
                    "only surface at confirm=true commit time, not at this preview step. Ask for "
                    "confirmation, then call again with confirm=true to create it."
                ),
                storage_id=None,
                payload=payload_preview,
                validation_errors={},
                result=None,
            )
        result = self._stamp(await self._api.commit_create(body))
        return self._write_result(
            action="create",
            state="confirmed",
            ready=True,
            message="Storage created successfully.",
            storage_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        *,
        storage_id: int,
        name: str | None = None,
        host: str | None = None,
        confirm: bool = False,
    ) -> StorageWriteResult:
        access.ensure_write_enabled("admin", settings=self._settings)
        body: dict[str, Any] = {}
        links: dict[str, Any] = {}
        if name is not None:
            hidden_fields.ensure_field_writable("storage", "name", settings=self._settings)
            body["name"] = name
        if host is not None:
            hidden_fields.ensure_field_writable("storage", "host", settings=self._settings)
            links["origin"] = {"href": host}
        if links:
            body["_links"] = links
        payload_preview: dict[str, Any] = {}
        if name is not None:
            payload_preview["name"] = name
        if host is not None:
            payload_preview["host"] = host

        if not confirm:
            # Fetched only on the preview branch -- the confirmed branch never
            # references it (its own PATCH result comes from commit_update).
            current = await self._api.get(storage_id)
            return self._write_result(
                action="update",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to attempt updating the storage. Changing `host` on a Nextcloud "
                    "storage re-runs OpenProject's live host-reachability/setup-completeness probe at "
                    "confirm=true (no pre-validation endpoint exists to check this earlier). Ask for "
                    "confirmation, then call again with confirm=true."
                ),
                storage_id=storage_id,
                payload=payload_preview,
                validation_errors={},
                result=self._stamp(current.to_detail()),
            )
        result = self._stamp(await self._api.commit_update(storage_id, body))
        return self._write_result(
            action="update",
            state="confirmed",
            ready=True,
            message="Storage updated successfully.",
            storage_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def delete(self, storage_id: int, *, confirm: bool = False) -> StorageWriteResult:
        access.ensure_write_enabled("admin", settings=self._settings)
        payload = {"id": storage_id}
        if not confirm:
            # Fetched only on the preview branch -- the confirmed branch never
            # references it (commit_delete needs only the id).
            current = await self._api.get(storage_id)
            return self._write_result(
                action="delete",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to delete the storage. This cascades: every project's link to "
                    "this storage (project_storages) is deleted along with it, and if the storage has "
                    "automatically-managed project folders, OpenProject may also issue a REMOTE "
                    "folder-deletion call against the external storage itself. Ask for confirmation, then "
                    "call again with confirm=true to delete it."
                ),
                storage_id=storage_id,
                payload=payload,
                validation_errors={},
                result=self._stamp(current.to_detail()),
            )
        await self._api.commit_delete(storage_id)
        return self._write_result(
            action="delete",
            state="confirmed",
            ready=True,
            message="Storage deleted successfully.",
            storage_id=storage_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    def _write_result(
        self,
        *,
        action: str,
        state: WriteResultState,
        ready: bool,
        message: str,
        storage_id: int | None,
        payload: dict[str, Any],
        validation_errors: dict[str, str],
        result: StorageDetail | None,
    ) -> StorageWriteResult:
        return StorageWriteResult(
            action=action,
            state=state,
            ready=ready,
            message=message,
            storage_id=storage_id,
            payload=payload,
            validation_errors=validation_errors,
            result=result,
        )
