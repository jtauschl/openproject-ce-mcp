"""HTTP-backed RevisionApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). The commit message is repository-authored free text, so it is
delimited like every other user-content field.
"""

from __future__ import annotations

from typing import Any

from ...models import RevisionSummary
from ..ports.revision_api import RevisionRecord
from ..transport.protocol import Transport
from ._text import FORMATTABLE_LIMIT, SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_revision(payload: dict[str, Any]) -> RevisionSummary:
    """Pure HAL->model translation. Excludes hidden-field masking."""
    links = payload.get("_links", {})
    message, truncated, _length = _extract_formattable_text_with_meta(
        payload.get("message"), limit=FORMATTABLE_LIMIT, preserve_newlines=True
    )
    return RevisionSummary(
        id=int(payload["id"]),
        identifier=_trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT),
        formatted_identifier=_trim_text(payload.get("formattedIdentifier"), limit=SUBJECT_LIMIT),
        author_name=_trim_text(payload.get("authorName"), limit=SUBJECT_LIMIT),
        author=_link_title(links.get("author")),
        message=_delimit_user_content(message),
        project=_link_title(links.get("project")),
        created_at=payload.get("createdAt"),
        message_truncated=truncated,
    )


def _record(payload: dict[str, Any]) -> RevisionRecord:
    return RevisionRecord(summary=normalize_revision(payload), project_link=payload.get("_links", {}).get("project"))


class HttpxRevisionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_work_package(self, work_package_id: int) -> list[RevisionRecord]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/revisions")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [_record(item) for item in elements if isinstance(item, dict)]

    async def get(self, revision_id: int) -> RevisionRecord:
        return _record(await self._transport.get_json(f"revisions/{revision_id}"))
