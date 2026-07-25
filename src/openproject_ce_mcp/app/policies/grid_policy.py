"""Grids-only policy (ADR 0001). Pure, no I/O.

Unlike Categories/Views/Wiki Pages, Grids needs a dedicated policy file: the
"/my/page" personal-grid carve-out (a grid scoped to the current user's own
dashboard is always allowed, read or write, regardless of
OPENPROJECT_READ_PROJECTS/OPENPROJECT_WRITE_PROJECTS) is domain-specific
branching logic, not a generic scope.py primitive.

Read and write functions intentionally have different parameter shapes,
matching client.py's original asymmetry: the read functions take the raw
scope HAL link dict (`_ensure_grid_payload_allowed` passes the whole link to
`_ensure_project_link_allowed`, which also reads `link.get("title")`, not
just `href`), while the write function takes a bare href string (its two
flat call sites -- create_grid, _authorize_grid_write -- already have one in
hand, per client.py:3995-4002).
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ..errors import PermissionDeniedError
from .scope import (
    ensure_project_link_allowed,
    ensure_project_write_link_allowed,
    payload_allowed,
    scope_allows_all,
)


def grid_scope_href(scope_link: dict[str, Any] | None) -> str | None:
    """Extract the raw `href` from a grid's `_links.scope` HAL link dict.

    Shared with GridService, which needs the same extraction for an
    already-fetched grid's own scope_link before calling
    ensure_grid_write_allowed (whose parameter is a bare href string, not a
    link dict -- see the module docstring for why the two shapes differ).
    """
    return scope_link.get("href") if isinstance(scope_link, dict) else None


def ensure_grid_read_allowed(
    scope_link: dict[str, Any] | None, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    if grid_scope_href(scope_link) == "/my/page":
        return
    ensure_project_link_allowed(scope_link, settings=settings, project_id_to_identifier=project_id_to_identifier)


def grid_read_allowed(
    scope_link: dict[str, Any] | None, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> bool:
    return payload_allowed(
        lambda: ensure_grid_read_allowed(
            scope_link, settings=settings, project_id_to_identifier=project_id_to_identifier
        )
    )


def ensure_grid_write_allowed(
    scope_href: str | None, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    if scope_href == "/my/page":
        return
    if scope_allows_all(settings.read_projects) and scope_allows_all(settings.write_projects):
        return
    if not scope_href:
        raise PermissionDeniedError("OpenProject writes to this grid are disabled by OPENPROJECT_WRITE_PROJECTS.")
    ensure_project_write_link_allowed(
        {"href": scope_href}, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
