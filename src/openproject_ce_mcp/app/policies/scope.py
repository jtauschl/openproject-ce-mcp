"""Project-scope / allowlist policy (ADR 0001). Pure, no I/O.

Contains small, deliberately duplicated private copies of `_trim_text`/
`_id_from_href`/`_slug_from_href` (+ `SUBJECT_LIMIT`) -- duplicated rather than
imported from client.py to avoid `app/` importing from `client.py` (these are still
used ~136/43/15 times respectively by every other domain's normalize_* methods).
Unify only once every domain has migrated and client.py's copies become truly dead.
"""

from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatch
from typing import Any
from urllib.parse import unquote

from ...config import Settings
from ..errors import PermissionDeniedError

SUBJECT_LIMIT = 255


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def scope_allows_all(values: tuple[str, ...]) -> bool:
    return any(item.strip() == "*" for item in values)


def scope_matches_candidates(scope: tuple[str, ...], candidates: set[str]) -> bool:
    normalized_candidates = {candidate.casefold() for candidate in candidates if candidate}
    if not normalized_candidates:
        return False
    if scope_allows_all(scope):
        return True
    for raw_pattern in scope:
        pattern = raw_pattern.strip().casefold()
        if not pattern:
            continue
        for candidate in normalized_candidates:
            # fnmatch is case-insensitive (not fnmatchcase) since both are casefolded
            if fnmatch(candidate, pattern):
                return True
    return False


def project_candidates(
    *,
    project_id_to_identifier: dict[int, str],
    project_ref: str | None = None,
    payload: dict[str, Any] | None = None,
    link: Any = None,
    identifier: str | None = None,
    name: str | None = None,
) -> set[str]:
    candidates: set[str] = set()
    for value in (project_ref, identifier, name):
        if value:
            candidates.add(str(value).casefold())
    if payload is not None:
        identifier_value = _trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT)
        name_value = _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
        if identifier_value:
            candidates.add(identifier_value.casefold())
        if name_value:
            candidates.add(name_value.casefold())
        project_id = payload.get("id")
        if project_id is not None:
            candidates.add(str(project_id).casefold())
    if isinstance(link, dict):
        href = link.get("href")
        title = link.get("title")
        if href:
            slug = _slug_from_href(href)
            if slug:
                candidates.add(slug.casefold())
            project_id = _id_from_href(href)
            if project_id is not None:
                candidates.add(str(project_id).casefold())
                known_identifier = project_id_to_identifier.get(project_id)
                if known_identifier:
                    candidates.add(known_identifier.casefold())
        if title:
            title_cf = str(title).casefold()
            candidates.add(title_cf)
            # Also add an identifier-style variant (spaces → hyphens) so that a project
            # named "My Project" matches the pattern "my-project" (its likely identifier).
            candidates.add(title_cf.replace(" ", "-"))
    return {candidate for candidate in candidates if candidate}


def payload_allowed(ensure: Callable[[], None]) -> bool:
    """Run an `ensure_*_allowed` check, turning PermissionDeniedError into False.

    Shared by every bool-returning `_X_payload_allowed` wrapper.
    """
    try:
        ensure()
        return True
    except PermissionDeniedError:
        return False


def ensure_project_link_allowed(link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]) -> None:
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    ensure_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if scope_allows_all(settings.write_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
