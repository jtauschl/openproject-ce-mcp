"""Shared "list all, then filter by resolved project ref" logic (ADR 0001).

Extracted after `DocumentService` (the fifth migrated domain) was found to
have verbatim-copied `_trim_text`/`_resolve_project_filter_candidates`/
`_summary_matches_project_candidates` from `NewsService` byte-for-byte
(differing only in the `NewsSummary`/`DocumentSummary` type annotation) --
new-domain-copies-newest-sibling duplication, found during the Documents
migration's post-implementation review, not the documented/sanctioned
client.py-transition duplication every adapter's module docstring already
covers. Both domains share the exact "fetch the full collection client-side,
then filter rows against a resolved project id/identifier/name candidate
set" shape (as opposed to Memberships/Projects/Versions, which filter
server-side or via a project-scoped href). A future domain with the same
shape (e.g. a project-scoped, non-server-filterable list) should depend on
this module rather than re-copying it a third time.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..ports.project_ref import ProjectRefResolver

SUBJECT_LIMIT = 255


class _ProjectScopedSummary(Protocol):
    project_id: int | None
    project: str | None


def trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def resolve_project_filter_candidates(
    project: str | None, *, resolve_project_ref: ProjectRefResolver
) -> set[str] | None:
    if project is None:
        return None
    project_payload = await resolve_project_ref(project, write=False)
    return {
        str(project_payload["id"]).casefold(),
        (trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
        (trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
    }


def summary_matches_project_candidates(item: _ProjectScopedSummary, project_candidates: set[str]) -> bool:
    return not project_candidates.isdisjoint(
        {
            str(item.project_id).casefold() if item.project_id is not None else "",
            (item.project or "").casefold(),
        }
    )
