"""Sprint (Backlogs) allowlist policy (ADR 0001). Pure, no I/O.

Unlike Views/Documents/News, Sprints genuinely needs a dedicated policy file:
`_ensure_sprint_workspace_allowed` (client.py) has TWO branches, not one.
- If the raw payload has a full `_embedded.definingWorkspace` object, the old
  code checked that payload's own id/identifier/name directly
  (`_ensure_project_allowed(str(embedded["id"]), payload=embedded)`), not via
  a `_links` lookup.
- Otherwise it fell back to the raw `_links.definingWorkspace` link (or one
  synthesized from the embedded object's own `_links.self`, if only the
  embedded form exists without a top-level link -- see
  `httpx_sprint_api.py`'s `_defining_workspace_link`).

The link branch maps 1:1 onto `scope.ensure_project_link_allowed` (client.py's
`_ensure_project_link_allowed` is already a thin pass-through to that exact
function). The embedded-object branch has no equivalent in any migrated
domain and is composed here from `scope.project_candidates(payload=...)` +
`scope.scope_matches_candidates(...)` -- verified against client.py's real
`_ensure_project_allowed` body: it calls `_project_candidates(project_ref=...,
payload=embedded)`, but the `project_ref` argument (`str(embedded["id"])`) is
redundant with `payload=embedded`, since `project_candidates(payload=...)`
independently re-derives the same id from the payload. Dropping it here
produces an identical candidate set.

Takes `SprintRecord.defining_workspace_payload`/`.defining_workspace_link`
directly (not a raw HAL payload) -- the Service only ever has the normalized
Record, never the raw API response, so both branches' inputs are threaded
through the Port rather than re-extracted here.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ..errors import PermissionDeniedError
from . import scope


def ensure_sprint_workspace_allowed(
    *,
    defining_workspace_payload: dict[str, Any] | None,
    defining_workspace_link: Any,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
) -> None:
    """Verbatim-behavior port of client.py's `_ensure_sprint_workspace_allowed`."""
    if defining_workspace_payload is not None:
        if scope.scope_allows_all(settings.read_projects):
            return
        candidates = scope.project_candidates(
            project_id_to_identifier=project_id_to_identifier, payload=defining_workspace_payload
        )
        if not scope.scope_matches_candidates(settings.read_projects, candidates):
            raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
        return
    scope.ensure_project_link_allowed(
        defining_workspace_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )


def sprint_payload_allowed(
    *,
    defining_workspace_payload: dict[str, Any] | None,
    defining_workspace_link: Any,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
) -> bool:
    return scope.payload_allowed(
        lambda: ensure_sprint_workspace_allowed(
            defining_workspace_payload=defining_workspace_payload,
            defining_workspace_link=defining_workspace_link,
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    )
