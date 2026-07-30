"""Boards read/write allowlist policy (ADR 0001). Pure, no I/O.

A thin delegation to `scope.py`'s shared primitives, mirroring News'/
Documents'/Versions' `<domain>_payload_allowed` pattern -- Boards has no
Grids-style bespoke carve-out (no `/my/page`-equivalent special case).

A Board is an OpenProject Query under the hood, and `QueryRepresenter`
explicitly supports a global (project-less) query, rendering an empty
project link for it (verified against the vendored OpenProject source,
OPM-359 research) -- so a Board's project link is OPTIONAL, not required.
Uses `scope.ensure_project_link_allowed_if_present`/
`ensure_project_write_link_allowed_if_present`: a missing/explicitly-empty
link keeps the pre-existing "* allows, restrictive scope denies" behavior
(a real, documented server state, not a defect), while a genuinely MALFORMED
link is now always rejected -- correcting this module's own former docstring,
which incorrectly claimed to already be fail-closed on a missing link (it
wasn't; the underlying `scope.py` bug affected this module exactly like
every other caller until OPM-359).

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
