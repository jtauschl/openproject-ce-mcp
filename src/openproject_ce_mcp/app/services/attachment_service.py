"""Application Service for the Attachments domain.

Depends on the `AttachmentApi` Protocol (never `HttpxAttachmentApi`
concretely -- enforced by the architecture-boundary test), on
`WorkPackageLookupApi` directly, and on `WorkPackageIdResolver`. Three
Protocol dependencies, matching File Links' shape: `list_for_work_package`'s
anchor-resolution and `create()`'s caller-supplied-reference resolution both
go through `WorkPackageIdResolver`, while `get()`'s and `delete()`'s
container-derived id go through `WorkPackageLookupApi.get()` directly --
both already hold a concrete href from the fetched attachment's own
`_links.container`, not a caller-supplied reference to resolve.

No `attachment_policy.py`: `list()`'s scoping is entirely delegated to
`WorkPackageIdResolver` (read-check on the anchor work package happens
THERE, before the attachments sub-fetch, matching File Links/Emoji
Reactions); `get()`/`delete()`'s scoping is a direct
`scope_policy.ensure_project_link_allowed`/`ensure_project_write_link_allowed`
call against the container work package's own project link, fetched via
`WorkPackageLookupApi.get()`.

`create()` and `delete()` are each independent, inline preview/confirm
methods -- NOT the shared `app/services/_write_outcome.py` state machine.
That machine's threshold ("2+ write actions sharing the same shape") looks
satisfied on paper (both write actions return `AttachmentWriteResult`), but
`_finalize_write` specifically expects a `<domain>/form`-validated payload
(a `form` dict with `_embedded.payload`/`validationErrors`) -- Attachments'
`create()` has no such form endpoint at all (a direct multipart POST with a
hand-built preview), so the shapes are genuinely heterogeneous, not merely
differently-named. There is also no shared "delete finalizer" anywhere in
`app/` to reuse for `delete()` either -- verified against
`FileLinkService.delete()`, which is itself a fully inline preview/confirm
method, the real precedent this Service's `delete()` follows.
`client.py`'s own `_finalize_delete` (a client.py-local helper for the
still-flat GET-then-delete domains) is not reachable from `app/`.

Filesystem-access security logic (`_attachment_root`/`_is_sensitive_attachment`/
`_prepare_attachment_file`/`_validate_attachment_size`) lives HERE as private
Service methods, not in the Adapter: this is authorization/security logic
(bounding which local files a caller can upload), not HAL<->model
translation, so it belongs at the same layer every other authorization check
in this codebase lives at. This is the first Service under `app/` to touch
the local filesystem at all.

`get_max_attachment_size()` on `AttachmentApi` reaches into the otherwise
entirely unmigrated, global Instance Configuration domain for exactly the
one field `_validate_attachment_size` needs -- a deliberate, narrow
cross-domain dependency (not the "raw sibling-domain resource" pattern
`EmojiReactionApi.get_activity`/`ReminderApi.get_remindable_link` follow, see
`attachment_api.py`'s own docstring), chosen specifically to avoid migrating
the complete Instance Configuration domain as a side effect of this one.

Read/write scope reuses `"work_package"` (not a dedicated `"attachment"`
scope) -- verbatim behavior of client.py's original
`_ensure_read_enabled("work_package")`/`write_scope="work_package"`.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import Settings
from ...models import AttachmentListResult, AttachmentSummary, AttachmentWriteResult
from ..errors import InvalidInputError, OpenProjectServerError, PermissionDeniedError
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.scope import id_from_href
from ..ports.attachment_api import AttachmentApi
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver

# Files that must never be uploaded even from inside the attachment root: the
# config often lives in the server's working directory, so directory
# containment alone would still expose the API token and other secrets.
_ATTACHMENT_DENY_NAMES = frozenset(
    {
        ".mcp.json",
        ".env",
        "credentials",
        "id_rsa",
        "id_ed25519",
    }
)
_ATTACHMENT_DENY_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


@dataclass(frozen=True)
class _PreparedFile:
    file_name: str
    file_size: int
    file_bytes: bytes | None
    content_type: str


class AttachmentService:
    def __init__(
        self,
        *,
        api: AttachmentApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: AttachmentSummary) -> AttachmentSummary:
        return hidden_fields.apply_hidden_fields("attachment", summary, settings=self._settings)

    async def list_for_work_package(self, work_package_id: int | str) -> AttachmentListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        # Resolving the id already confirms the anchor work package itself is
        # allowed against OPENPROJECT_READ_PROJECTS before its attachments
        # are fetched (verbatim behavior of client.py's original order).
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        records = await self._api.list_for_work_package(resolved_id, page_size=self._settings.max_page_size)
        results = [
            self._stamp(record.summary)
            for record in records
            if record.summary.container_type == "WorkPackage" and record.summary.container_id == resolved_id
        ]
        return AttachmentListResult(count=len(results), results=results)

    async def get(self, attachment_id: int) -> AttachmentSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(attachment_id)
        attachment = self._stamp(record.summary)
        await self._ensure_container_allowed(record.container_link, write=False)
        return attachment

    async def create(
        self,
        *,
        work_package_id: int | str,
        file_path: str,
        description: str | None = None,
        confirm: bool = False,
    ) -> AttachmentWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        hidden_fields.ensure_field_writable("attachment", "file_name", settings=self._settings)
        if description is not None:
            hidden_fields.ensure_field_writable("attachment", "description", settings=self._settings)
        # Stat and validate the size BEFORE reading file bytes into memory --
        # the original client.py code read the full file first, then
        # validated (`include_bytes=confirm` reads unconditionally on a
        # confirmed call), letting an oversized upload be fully buffered in
        # memory before being rejected. Fixed here: only read bytes after the
        # size check passes.
        file_info = self._prepare_attachment_file(file_path, include_bytes=False)
        await self._validate_attachment_size(file_info.file_size)
        if not confirm:
            return AttachmentWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to upload this attachment. Ask for confirmation, then call again with confirm=true.",
                attachment_id=None,
                work_package_id=resolved_id,
                payload={
                    "fileName": file_info.file_name,
                    "fileSize": file_info.file_size,
                    "description": description,
                },
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        file_info = self._prepare_attachment_file(file_path, include_bytes=True)
        assert file_info.file_bytes is not None
        # Re-validate against the bytes actually read, not just the earlier
        # stat: the file on disk could have grown between the size check
        # above and this second read (a TOCTOU window, however small) --
        # closes it rather than trusting the stale stat.
        await self._validate_attachment_size(len(file_info.file_bytes))
        record = await self._api.create(
            resolved_id,
            metadata={
                "fileName": file_info.file_name,
                **({"description": {"format": "markdown", "raw": description}} if description is not None else {}),
            },
            file_name=file_info.file_name,
            file_bytes=file_info.file_bytes,
            content_type=file_info.content_type,
        )
        result = self._stamp(record.summary)
        return AttachmentWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Attachment uploaded successfully.",
            attachment_id=result.id,
            work_package_id=resolved_id,
            payload={
                "fileName": file_info.file_name,
                "fileSize": file_info.file_size,
                "description": description,
            },
            validation_errors={},
            result=result,
        )

    async def delete(self, attachment_id: int, *, confirm: bool = False) -> AttachmentWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(attachment_id)
        attachment = self._stamp(record.summary)
        work_package_id = await self._ensure_container_allowed(record.container_link, write=True)
        preview_payload = {
            "id": attachment.id,
            "title": attachment.title,
            "fileName": attachment.file_name,
            "fileSize": attachment.file_size,
        }
        if not confirm:
            return AttachmentWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the attachment. Ask for confirmation, then call again with confirm=true to delete it.",
                attachment_id=attachment.id,
                work_package_id=work_package_id,
                payload=preview_payload,
                validation_errors={},
                result=attachment,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(attachment_id)
        return AttachmentWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Attachment deleted successfully.",
            attachment_id=attachment.id,
            work_package_id=work_package_id,
            payload=preview_payload,
            validation_errors={},
            result=None,
        )

    async def _ensure_container_allowed(self, container_link: dict[str, Any] | None, *, write: bool) -> int | None:
        """The container link must point at a work package; that work package
        is then fetched and its project link checked against the read/write
        allowlist. Returns the container work package's numeric id.

        The container-type check matches on the `work_packages/<id>` PATH
        SEGMENT pair (via `_id_from_href`'s own parsing, applied to the
        second-to-last segment), not a raw substring -- client.py's original
        `"work_packages/" not in href` check (verbatim ported here at first)
        would also match an unrelated path merely containing that substring,
        e.g. `/api/v3/not_work_packages/9`, wrongly treating it as a work
        package container and authorizing against an unrelated resource.
        Found via a Codex review of this migration; fixed here since the
        pre-migration flat code has already been deleted from client.py --
        see 90-lessons-log.md for whether release/0.3.x still needs the same
        fix ported to its own still-flat copy."""
        href = container_link.get("href") if isinstance(container_link, dict) else None
        if not isinstance(href, str):
            raise InvalidInputError("Only work package attachments are supported.")
        segments = href.rstrip("/").split("/")
        if len(segments) < 2 or segments[-2] != "work_packages":
            raise InvalidInputError("Only work package attachments are supported.")
        work_package_id = id_from_href(href)
        if work_package_id is None:
            raise OpenProjectServerError("OpenProject returned an attachment without a valid container id.")
        work_package = await self._work_package_lookup_api.get(str(work_package_id))
        project_link = work_package.get("_links", {}).get("project")
        if write:
            scope_policy.ensure_project_write_link_allowed(
                project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        else:
            scope_policy.ensure_project_link_allowed(
                project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        return work_package_id

    def _attachment_root(self) -> Path:
        """The directory attachment uploads are confined to.

        OPENPROJECT_ATTACHMENT_ROOT must be set to an absolute directory;
        there is no current-working-directory fallback (a globally installed
        MCP server's cwd is unpredictable, so silently falling back to it
        would let an upload land in, or escape from, whatever directory
        happened to launch the server). This bounds which local files a
        caller can upload, so a malicious/confused agent cannot exfiltrate
        arbitrary host files (e.g. the API token in .mcp.json, SSH keys,
        /etc/passwd). `tools.py` also only registers
        `create_work_package_attachment` when this is set; this check is
        defense-in-depth for a caller that constructs `OpenProjectClient`
        directly, bypassing that registration gate.
        """
        configured = self._settings.attachment_root
        if not configured:
            raise PermissionDeniedError(
                "Attachment uploads are disabled: OPENPROJECT_ATTACHMENT_ROOT is not set. "
                "There is no current-working-directory fallback — set it to an absolute, "
                "existing directory to allow local file uploads."
            )
        return Path(configured).expanduser().resolve()

    def _is_sensitive_attachment(self, path: Path) -> bool:
        name = path.name
        lower = name.lower()
        if lower in _ATTACHMENT_DENY_NAMES:
            return True
        if lower.startswith(".mcp.json"):  # e.g. .mcp.json.bak.<ts>
            return True
        return any(lower.endswith(suffix) for suffix in _ATTACHMENT_DENY_SUFFIXES)

    def _prepare_attachment_file(self, file_path: str, *, include_bytes: bool) -> _PreparedFile:
        root = self._attachment_root()
        # Resolve symlinks and .. so the containment check cannot be defeated.
        path = Path(file_path).expanduser().resolve()
        if root not in path.parents and path != root:
            raise InvalidInputError(
                f"Attachment file '{file_path}' is outside the allowed attachment directory "
                f"({root}). Set OPENPROJECT_ATTACHMENT_ROOT to permit another location."
            )
        if self._is_sensitive_attachment(path):
            raise InvalidInputError(
                f"Attachment file '{file_path}' looks like a credential/config file and cannot be "
                "uploaded. This protects the API token and other local secrets."
            )
        if not path.is_file():
            raise InvalidInputError(f"Attachment file '{file_path}' does not exist or is not a file.")
        file_size = path.stat().st_size
        file_bytes = path.read_bytes() if include_bytes else None
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return _PreparedFile(file_name=path.name, file_size=file_size, file_bytes=file_bytes, content_type=content_type)

    async def _validate_attachment_size(self, file_size: int) -> None:
        maximum = await self._api.get_max_attachment_size()
        if maximum is not None and file_size > maximum:
            raise InvalidInputError(
                f"Attachment exceeds the configured OpenProject maximum attachment size of {maximum} bytes."
            )
