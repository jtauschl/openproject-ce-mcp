"""Boards read/write allowlist policy (ADR 0001). Pure, no I/O.

A thin delegation to `scope.py`'s shared primitives, mirroring News'/
Documents'/Versions' `<domain>_payload_allowed` pattern -- Boards has no
Grids-style bespoke carve-out (no `/my/page`-equivalent special case), so no
dedicated fail-closed logic is written here: `scope.ensure_project_link_allowed`/
`ensure_project_write_link_allowed` already produce the exact same outcome as
client.py's original `_ensure_board_payload_allowed`/
`_ensure_board_write_payload_allowed` for a per-board project link (read-scope
short-circuit on "*", fail-closed on a missing/malformed link, else an
allowlist match against the link's project candidates).

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
        lambda: scope.ensure_project_link_allowed(
            project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
        )
    )


def ensure_board_read_allowed(
    project_link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    scope.ensure_project_link_allowed(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )


def ensure_board_write_allowed(
    project_link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    scope.ensure_project_write_link_allowed(
        project_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
