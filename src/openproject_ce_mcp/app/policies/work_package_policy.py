"""Work-Packages-only policy. Pure, no I/O.

Direct replacement for client.py's `_work_package_payload_allowed`. A work
package's `_links.project` is a REQUIRED link (OpenProject's representer
always emits one, or the URN_UNDISCLOSED placeholder for an
invisible-but-existing project) -- never optional -- so this uses
`project_link_payload_allowed` (the `ensure_project_link_allowed`-backed,
fail-closed-on-missing-link contract), matching Documents/News/Versions'
same-shaped wrapper, not the `_if_present` variant Memberships/Views/Boards
use.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from .scope import project_link_payload_allowed


def work_package_payload_allowed(
    payload: dict[str, Any], *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> bool:
    return project_link_payload_allowed(
        payload, link_key="project", settings=settings, project_id_to_identifier=project_id_to_identifier
    )
