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
`app/` to reuse for `delete()` either -- `FileLinkService.delete()` is
itself a fully inline preview/confirm method, the real precedent this
Service's `delete()` follows.

Filesystem-access security logic (`_attachment_root`/`_is_sensitive_attachment`/
`_prepare_attachment_file`/`_validate_attachment_size`) lives HERE as private
Service methods, not in the Adapter: this is authorization/security logic
(bounding which local files a caller can upload), not HAL<->model
translation, so it belongs at the same layer every other authorization check
in this codebase lives at. This is the first Service under `app/` to touch
the local filesystem at all.

`get_max_attachment_size_bytes()` on `AttachmentApi` reaches into the otherwise
entirely unmigrated, global Instance Configuration domain for exactly the
one field `_validate_attachment_size` needs -- a deliberate, narrow
cross-domain dependency (not the "raw sibling-domain resource" pattern
`EmojiReactionApi.get_activity`/`ReminderApi.get_remindable_link` follow, see
`attachment_api.py`'s own docstring), chosen specifically to avoid migrating
the complete Instance Configuration domain as a side effect of this one.

Read/write scope reuses `"work_package"` (not a dedicated `"attachment"`
scope).
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import Settings
from ...models import (
    AttachmentContentOutcome,
    AttachmentContentResult,
    AttachmentListResult,
    AttachmentListWithImages,
    AttachmentSummary,
    AttachmentWriteResult,
)
from ..errors import InvalidInputError, OpenProjectServerError, PermissionDeniedError
from ..pagination import clamp_limit, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.scope import id_from_href
from ..ports.attachment_api import AttachmentApi, AttachmentContent
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

# The only image types inlined as an ImageContent block. Deliberately an
# explicit allowlist, not `image/*`: SVG is a scripted document rather than a
# bitmap, and the long tail (TIFF, BMP, HEIC, ICO) is what a client is most
# likely to fail to render -- either would cost the full base64 payload for
# something the model never sees.
_INLINE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
# Text-like types returned as a TextContent block. Decoded text is directly
# readable and usually SMALLER than the same bytes base64-encoded.
_TEXT_TYPE_PREFIXES = ("text/",)
_TEXT_TYPES = frozenset({"application/json", "application/xml"})
_TEXT_TYPE_SUFFIXES = ("+json", "+xml")
# Content types that carry no information: OpenProject serves anything it will
# not inline as application/octet-stream -- JSON very much included -- and an
# external-storage redirect can drop the header altogether. Seeing one of
# these means "ask the stored metadata whether this is text", not "this is a
# binary blob"; it never promotes anything to an image.
_GENERIC_CONTENT_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})

_OUTCOME_IMAGE = "image"
_OUTCOME_TEXT = "text"
_OUTCOME_TOO_LARGE = "too_large"
_OUTCOME_NOT_SUPPORTED = "not_inline_supported"


def _normalize_content_type(value: str | None) -> str | None:
    """Bare lowercase type, parameters dropped: `image/PNG; charset=binary` ->
    `image/png`. None for a missing or empty header."""
    if not value:
        return None
    bare = value.split(";", 1)[0].strip().lower()
    return bare or None


def _is_inline_image_type(content_type: str | None) -> bool:
    return content_type in _INLINE_IMAGE_TYPES


def _is_text_type(content_type: str | None) -> bool:
    if content_type is None:
        return False
    if content_type in _TEXT_TYPES or content_type.startswith(_TEXT_TYPE_PREFIXES):
        return True
    return content_type.endswith(_TEXT_TYPE_SUFFIXES)


def _text_type_from_metadata_fallback(served: str | None, stored: str | None) -> str | None:
    """The stored metadata's type, if -- and only if -- the served header said
    nothing usable and the stored type is on the text allowlist.

    This is the one place the stored type changes a DECISION (`_classify` also
    reports it as the content type of an unusable blob, which decides
    nothing). The served response header is otherwise the sole authority,
    because it describes the bytes that actually arrived; the fallback exists
    because OpenProject normalizes a served attachment's Content-Type to
    application/octet-stream for anything it will not inline -- JSON very much
    included, and especially on an external-storage redirect -- so without it
    every JSON attachment would silently classify as an unusable binary blob.
    It is deliberately narrow: no image is ever inlined on the strength of the
    stored type, since a bitmap the server refused to label is not worth a
    broken image block.
    """
    if served is not None and served not in _GENERIC_CONTENT_TYPES:
        return None
    return stored if _is_text_type(stored) else None


@dataclass(frozen=True)
class _PreparedFile:
    file_name: str
    file_size_bytes: int
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

    async def list_for_work_package(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None, include_total_size: bool = False
    ) -> AttachmentListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        # Resolving the id already confirms the anchor work package itself is
        # allowed against OPENPROJECT_READ_PROJECTS before its attachments
        # are fetched.
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)

        def _record_allowed(record: Any) -> bool:
            return record.summary.container_type == "WorkPackage" and record.summary.container_id == resolved_id

        # Scan server pages rather than a single fetch capped at
        # settings.max_results, which would silently hide any attachment
        # beyond that cap -- same early-stopping pattern as
        # Documents/Views/News.
        raw_items, truncated = await scan_records_and_paginate(
            lambda o, ps: self._api.list_for_work_package(resolved_id, offset=o, page_size=ps),
            item_allowed=_record_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective_limit,
            key=lambda r: r.summary.id,
        )
        results = [self._stamp(record.summary) for record in raw_items]
        total = len(results)
        total_size_bytes = (
            await self._sum_attachment_sizes(resolved_id, results, truncated) if include_total_size else None
        )
        return AttachmentListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=offset + 1 if truncated else None,
            truncated=truncated,
            results=results,
            total_size_bytes=total_size_bytes,
        )

    async def _sum_attachment_sizes(
        self, work_package_id: int, page_results: list[AttachmentSummary], truncated: bool
    ) -> int | None:
        """OpenProject's own attachments endpoint is unpaginated
        (AttachmentCollectionRepresenter < UnpaginatedCollection) -- any
        single fetch already returns every attachment, so `page_results` is
        already the complete set unless the SCAN stopped early at `limit`
        (truncated=True), in which case a second, unbounded fetch gets the
        rest. Returns None (not a silently partial sum) if any attachment's
        file_size_bytes is hidden or unknown, matching how a hidden field
        must not leak indirectly through an aggregate.
        """
        if hidden_fields.field_hidden("attachment", "file_size_bytes", settings=self._settings):
            return None
        if not truncated:
            summaries = page_results
        else:
            raw_items, _ = await scan_records_and_paginate(
                lambda o, ps: self._api.list_for_work_package(work_package_id, offset=o, page_size=ps),
                item_allowed=lambda record: (
                    record.summary.container_type == "WorkPackage" and record.summary.container_id == work_package_id
                ),
                server_page_size=self._settings.max_page_size,
                offset=1,
                limit=self._settings.max_results,
                key=lambda r: r.summary.id,
            )
            summaries = [record.summary for record in raw_items]
        sizes = [s.file_size_bytes for s in summaries]
        known_sizes = [size for size in sizes if size is not None]
        if len(known_sizes) != len(sizes):
            return None
        return sum(known_sizes)

    async def get(self, attachment_id: int) -> AttachmentSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(attachment_id)
        attachment = self._stamp(record.summary)
        await self._ensure_container_allowed(record.container_link, write=False)
        return attachment

    async def get_content(self, attachment_id: int, *, max_bytes: int | None = None) -> AttachmentContentOutcome:
        """Fetch an attachment's bytes and decide how (or whether) they can be inlined.

        Authorization runs to completion BEFORE any content is requested: the
        metadata fetch resolves the container work package and its project is
        checked against the read allowlist, so an attachment outside the
        caller's scope never causes a download at all.
        """
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(attachment_id)
        summary = self._stamp(record.summary)
        await self._ensure_container_allowed(record.container_link, write=False)
        limit = self._content_byte_limit(max_bytes)
        content = await self._api.get_content(attachment_id, max_bytes=limit)
        return self._classify(summary, content, limit=limit)

    async def list_for_work_package_with_images(
        self,
        work_package_id: int | str,
        *,
        offset: int = 1,
        limit: int | None = None,
        include_total_size: bool = False,
    ) -> AttachmentListWithImages:
        """`list_for_work_package` plus the inlineable images of the attachments
        it returned.

        One aggregate byte budget for the whole call (the configured
        `attachment_content_max_bytes`, not that much per image): the point of
        the cap is the agent's context window, which a work package with
        twenty screenshots would otherwise blow through twenty times over.
        Images are taken in listing order until the budget runs out; whatever
        is left over is reported as a skip with its reason, never silently
        dropped.
        """
        listing = await self.list_for_work_package(
            work_package_id, offset=offset, limit=limit, include_total_size=include_total_size
        )
        remaining = self._settings.attachment_content_max_bytes
        entries: list[AttachmentContentResult] = []
        included: list[AttachmentContentOutcome] = []
        for summary in listing.results:
            if not _is_inline_image_type(_normalize_content_type(summary.content_type)):
                entries.append(
                    self._content_metadata(
                        summary,
                        outcome=_OUTCOME_NOT_SUPPORTED,
                        content_type=_normalize_content_type(summary.content_type),
                        size_bytes=None,
                        truncated=False,
                        reason=(
                            "include_images inlines images only. Call get_attachment_content for this "
                            "attachment to read it as text, if its type allows."
                        ),
                    )
                )
                continue
            if remaining <= 0:
                entries.append(
                    self._content_metadata(
                        summary,
                        outcome=_OUTCOME_TOO_LARGE,
                        content_type=_normalize_content_type(summary.content_type),
                        size_bytes=None,
                        truncated=False,
                        reason=(
                            f"The {self._settings.attachment_content_max_bytes}-byte budget for this call was "
                            "already used by the images above. Call get_attachment_content for this attachment "
                            "on its own."
                        ),
                    )
                )
                continue
            content = await self._api.get_content(summary.id, max_bytes=remaining)
            outcome = self._classify(summary, content, limit=remaining, aggregate=True)
            entries.append(outcome.metadata)
            if outcome.image_bytes is not None:
                remaining -= len(outcome.image_bytes)
                included.append(outcome)
        listing.images = entries
        return AttachmentListWithImages(list_result=listing, included=tuple(included))

    def _content_byte_limit(self, max_bytes: int | None) -> int:
        """The configured cap, which a per-call `max_bytes` may only lower.

        Raising it per call is deliberately impossible: the cap is the
        operator's setting (`OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES`), and a
        tool argument is caller-controlled -- letting an argument raise it
        would make the setting advisory.
        """
        configured = self._settings.attachment_content_max_bytes
        if max_bytes is None:
            return configured
        if max_bytes < 1:
            raise InvalidInputError("max_bytes must be at least 1 byte.")
        return min(max_bytes, configured)

    def _content_metadata(
        self,
        summary: AttachmentSummary,
        *,
        outcome: str,
        content_type: str | None,
        size_bytes: int | None,
        truncated: bool,
        reason: str | None,
    ) -> AttachmentContentResult:
        # `size_bytes` carries a different field name than the stored
        # `file_size_bytes`, so `apply_hidden_fields` below would never mask
        # it -- yet for content returned whole it is exactly the number the
        # operator hid. Nulled for the same reason `total_size_bytes` is (see
        # _sum_attachment_sizes): a hidden field must not come back
        # indirectly under another name.
        if size_bytes is not None and hidden_fields.field_hidden(
            "attachment", "file_size_bytes", settings=self._settings
        ):
            size_bytes = None
        return hidden_fields.apply_hidden_fields(
            "attachment",
            AttachmentContentResult(
                attachment_id=summary.id,
                file_name=summary.file_name,
                outcome=outcome,
                content_type=content_type,
                size_bytes=size_bytes,
                truncated=truncated,
                reason=reason,
            ),
            settings=self._settings,
        )

    def _classify(
        self, summary: AttachmentSummary, content: AttachmentContent, *, limit: int, aggregate: bool = False
    ) -> AttachmentContentOutcome:
        """Decide what an attachment's downloaded bytes can be returned as.

        An image is all-or-nothing: half a PNG is not a smaller PNG, it is a
        broken one, so an image over the limit comes back as `too_large` with
        no bytes at all. Text is the opposite -- its first N bytes are still
        worth reading -- so an oversized text attachment comes back truncated
        rather than refused, and never as base64 just because it hit the cap.
        """
        served = _normalize_content_type(content.served_content_type)
        stored = _normalize_content_type(summary.content_type)
        # Images: the served header alone decides. Text: the served header,
        # or the stored type when the header is generic octet-stream (the
        # only fallback there is -- see _text_type_from_metadata_fallback).
        text_type = served if _is_text_type(served) else _text_type_from_metadata_fallback(served, stored)
        # What the metadata block reports the decision was made on: the served
        # type when it was specific, the stored type when the text fallback
        # was what actually matched.
        effective = text_type if text_type is not None else (served or stored)
        budget_note = f"the {limit}-byte budget left for this call" if aggregate else f"the {limit}-byte inline limit"

        if _is_inline_image_type(served):
            if content.truncated:
                return AttachmentContentOutcome(
                    metadata=self._content_metadata(
                        summary,
                        outcome=_OUTCOME_TOO_LARGE,
                        content_type=effective,
                        size_bytes=None,
                        truncated=False,
                        reason=(
                            f"The image is larger than {budget_note} and is not returned partially. "
                            "Raise OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES, or open download_url in a browser."
                        ),
                    )
                )
            return AttachmentContentOutcome(
                metadata=self._content_metadata(
                    summary,
                    outcome=_OUTCOME_IMAGE,
                    content_type=effective,
                    size_bytes=len(content.data),
                    truncated=False,
                    reason=None,
                ),
                image_bytes=content.data,
            )

        if text_type is not None:
            # errors="replace" rather than a decode failure: a text/* file with
            # a few bytes of mojibake is still readable, and refusing the whole
            # attachment over them would be worse than showing U+FFFD.
            text = content.data.decode("utf-8", errors="replace")
            return AttachmentContentOutcome(
                metadata=self._content_metadata(
                    summary,
                    outcome=_OUTCOME_TEXT,
                    content_type=effective,
                    size_bytes=len(content.data),
                    truncated=content.truncated,
                    reason=(f"Cut at {budget_note}." if content.truncated else None),
                ),
                text=text,
            )

        # An unusable blob reports the STORED metadata type, not the served
        # one: OpenProject serves everything it will not inline as
        # application/octet-stream, so the served header here only repeats
        # "not inlineable" while the stored type still names what the file
        # actually is -- and naming it is the whole value of this outcome.
        # Classification above is untouched: it stays served-header-based
        # (see _text_type_from_metadata_fallback), only the reported value
        # differs. Same type the include_images pre-filter already reports
        # for a non-image, which never downloads anything at all.
        reported = (
            stored if not hidden_fields.field_hidden("attachment", "content_type", settings=self._settings) else None
        )
        return AttachmentContentOutcome(
            metadata=self._content_metadata(
                summary,
                outcome=_OUTCOME_NOT_SUPPORTED,
                content_type=reported,
                size_bytes=None,
                truncated=False,
                reason=(
                    f"Content type {reported or 'unknown'} is not something an MCP client can display. "
                    "The bytes are not returned; open download_url in a browser instead."
                ),
            )
        )

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
        # Stat and validate the size BEFORE reading file bytes into memory:
        # reading bytes unconditionally would let an oversized upload be
        # fully buffered in memory before being rejected. File bytes are
        # only read after the size check passes.
        file_info = self._prepare_attachment_file(file_path, include_bytes=False)
        await self._validate_attachment_size(file_info.file_size_bytes)
        if not confirm:
            return AttachmentWriteResult(
                action="create",
                state="preview",
                ready=True,
                message="OpenProject is ready to upload this attachment. Ask for confirmation, then call again with confirm=true.",
                attachment_id=None,
                work_package_id=resolved_id,
                payload={
                    "fileName": file_info.file_name,
                    "fileSize": file_info.file_size_bytes,
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
            state="confirmed",
            ready=True,
            message="Attachment uploaded successfully.",
            attachment_id=result.id,
            work_package_id=resolved_id,
            payload={
                "fileName": file_info.file_name,
                "fileSize": file_info.file_size_bytes,
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
            "fileSize": attachment.file_size_bytes,
        }
        if not confirm:
            return AttachmentWriteResult(
                action="delete",
                state="preview",
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
            state="confirmed",
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
        second-to-last segment), not a raw substring: a plain `"work_packages/"
        in href` check would also match an unrelated path merely containing
        that substring, e.g. `/api/v3/not_work_packages/9`, wrongly treating
        it as a work package container and authorizing against an unrelated
        resource."""
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
        file_size_bytes = path.stat().st_size
        file_bytes = path.read_bytes() if include_bytes else None
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return _PreparedFile(
            file_name=path.name, file_size_bytes=file_size_bytes, file_bytes=file_bytes, content_type=content_type
        )

    async def _validate_attachment_size(self, file_size_bytes: int) -> None:
        maximum = await self._api.get_max_attachment_size_bytes()
        if maximum is not None and file_size_bytes > maximum:
            raise InvalidInputError(
                f"Attachment exceeds the configured OpenProject maximum attachment size of {maximum} bytes."
            )
