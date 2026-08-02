"""Documents Domain API port -- narrow, no universal gateway."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import DocumentDetail, DocumentSummary


@dataclass(frozen=True)
class DocumentRecord:
    """One document as read from the API: the list-row-truncated `summary`,
    a LAZY `to_detail` thunk for the larger single-item shape, plus the raw
    `project` HAL link (carried separately because the allowlist Policy
    check needs the raw link (href/id), which neither normalized model
    carries).

    `to_detail` is a callable, not a precomputed `DocumentDetail` field,
    because normalize_document/normalize_document_detail apply DIFFERENT
    truncation limits to the same raw description (SUBJECT_LIMIT vs the
    uncapped FORMATTABLE_LIMIT default) -- detail cannot be derived from
    summary by a simple copy. Same rationale as NewsRecord.to_detail.
    """

    summary: DocumentSummary
    to_detail: Callable[[], DocumentDetail]
    project_link: dict[str, Any] | None


class DocumentApi(Protocol):
    """Narrow, Documents-only Domain API port. DocumentService depends on
    this Protocol, never on HttpxDocumentApi concretely (enforced by the
    architecture-boundary test).

    PATCH-only: the OpenProject v3 API exposes no POST create / DELETE for
    documents -- no commit_create/delete methods exist on this Protocol.
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[DocumentRecord], int]: ...
    async def get(self, document_id: int) -> DocumentRecord: ...
    async def commit_update(self, document_id: int, payload: dict[str, Any]) -> DocumentDetail: ...
