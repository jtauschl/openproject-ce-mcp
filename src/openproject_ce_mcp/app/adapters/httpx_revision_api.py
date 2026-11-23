"""HTTP-backed RevisionApi adapter."""

from __future__ import annotations

from typing import Any

from ...models import RevisionSummary
from ..ports.revision_api import RevisionRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_revision(payload: dict[str, Any], *, text_limit: int | None) -> RevisionRecord:
    """Pure HAL->model translation; hidden-field masking is a Service decision.

    The author name and the commit message come from the repository, not from OpenProject, so both are
    delimited as user content.
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    message, truncated, length = _extract_formattable_text_with_meta(payload.get("message"), limit=text_limit)
    revision_id = int(payload["id"])
    summary = RevisionSummary(
        id=revision_id,
        identifier=_trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT),
        formatted_identifier=_trim_text(payload.get("formattedIdentifier"), limit=SUBJECT_LIMIT),
        author_name=_delimit_user_content(_trim_text(payload.get("authorName"), limit=SUBJECT_LIMIT)),
        message=_delimit_user_content(message),
        message_truncated=truncated,
        message_length=length,
        created_at=payload.get("createdAt"),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
    )
    return RevisionRecord(summary=summary, project_link=project_link)


class HttpxRevisionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_work_package(self, work_package_id: int, *, text_limit: int | None) -> list[RevisionRecord]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/revisions")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [normalize_revision(item, text_limit=text_limit) for item in elements if isinstance(item, dict)]
