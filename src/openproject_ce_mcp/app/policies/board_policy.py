"""Boards read/write allowlist policy. Pure, no I/O.

A thin delegation to `scope.py`'s shared primitives, mirroring News'/
Documents'/Versions' `<domain>_payload_allowed` pattern -- Boards has no
Grids-style bespoke carve-out (no `/my/page`-equivalent special case).

A Board is an OpenProject Query under the hood, and `QueryRepresenter`
explicitly supports a global (project-less) query, rendering an empty
project link for it -- so a Board's project link is OPTIONAL, not required.
Uses `scope.ensure_project_link_allowed_if_present`/
`ensure_project_write_link_allowed_if_present`: a missing/explicitly-empty
link is allowed under a wide-open scope and denied under a restrictive one
(a real, documented server state, not a defect), while a structurally
malformed link is always rejected regardless of scope.

The "global board" business rule (an unscoped/no-project board write requires
BOTH read_projects and write_projects fully open) is NOT a per-link allowlist
check at all -- it has no link to check against -- so it stays in
BoardService.create(), verbatim-ported from client.py's `create_board`, not
here.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from . import scope


def board_read_allowed(project_link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]) -> bool:
    return scope.payload_allowed(
        lambda: scope.ensure_project_link_allowed_if_present(
            project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
        )
    )


def ensure_board_read_allowed(
    project_link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    scope.ensure_project_link_allowed_if_present(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )


def ensure_board_write_allowed(
    project_link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    scope.ensure_project_write_link_allowed_if_present(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
