"""Shared "list all, then filter by resolved project ref" logic.

Documents, News, Views, Boards and Project Storages share the shape "fetch
the collection, then filter rows by the resolved project's id" (as opposed to Memberships/Projects/
Versions, which filter server-side or via a project-scoped href). A future
domain with the same shape (e.g. a project-scoped, non-server-filterable
list) should depend on this module rather than duplicating it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ..policies.scope import project_id_from_href
from ..ports.project_ref import ProjectRefResolver

SUBJECT_LIMIT = 255


def trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def resolve_project_filter_id(project: str | None, *, resolve_project_ref: ProjectRefResolver) -> int | None:
    if project is None:
        return None
    project_payload = await resolve_project_ref(project, write=False)
    return int(project_payload["id"])


def record_in_project(project_link: Any, project_id: int, *, settings: Settings) -> bool:
    # Project names are not unique; the id of the project the item links to,
    # read by the same strict parser as the allowlist check, is.
    href = project_link.get("href") if isinstance(project_link, dict) else None
    return project_id_from_href(href, settings=settings) == project_id
