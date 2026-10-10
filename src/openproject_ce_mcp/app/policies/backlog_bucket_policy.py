"""Backlog Bucket (Backlogs) allowlist policy. Pure, no I/O.

Verbatim structural port of sprint_policy.py: the workspace-allowlist check
has the same TWO branches, not one.
- If the raw payload has a full `_embedded.definingWorkspace` object, that
  payload's own id/identifier/name is checked directly, not via a `_links`
  lookup.
- Otherwise it falls back to the raw `_links.definingWorkspace` link (or one
  synthesized from the embedded object's own `_links.self`, if only the
  embedded form exists without a top-level link -- see
  `httpx_backlog_bucket_api.py`'s `_defining_workspace_link`).

The link branch maps 1:1 onto `scope.ensure_project_link_allowed`. The
embedded-object branch first requires the object's own self link to name
its id (`scope.ensure_embedded_project_consistent`), then is composed from
`scope.project_candidates(payload=...)` + `scope.scope_matches_candidates(...)`.

Takes `BacklogBucketRecord.defining_workspace_payload`/`.defining_workspace_link`
directly (not a raw HAL payload) -- the Service only ever has the normalized
Record, never the raw API response, so both branches' inputs are threaded
through the Port rather than re-extracted here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ... import policy_observation
from ...config import Settings
from ..errors import ProjectScopeDeniedError
from . import scope


def _payload_display_value(payload: dict[str, Any]) -> str | None:
    """Mirrors scope.py's `_project_scope_display`/project_policy.py's
    `_display_value` for this module's embedded-payload branch -- prefers a
    known identifier over a bare numeric id."""
    identifier_value = payload.get("identifier")
    if identifier_value:
        return str(identifier_value)
    project_id = payload.get("id")
    return str(project_id) if project_id is not None else None


def ensure_backlog_bucket_workspace_allowed(
    *,
    defining_workspace_payload: dict[str, Any] | None,
    defining_workspace_link: Any,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    if defining_workspace_payload is not None:
        policy_observation.record_project_scope(_payload_display_value(defining_workspace_payload))
        try:
            scope.ensure_embedded_project_consistent(
                defining_workspace_payload, link=defining_workspace_link, settings=settings
            )
        except ProjectScopeDeniedError:
            policy_observation.record_policy_decision("project_scope_read_denied")
            raise
        if scope.scope_allows_all(settings.read_projects):
            policy_observation.record_policy_decision("project_scope_read_allowed")
            return
        candidates = scope.project_candidates(
            project_id_to_identifier=project_id_to_identifier, settings=settings, payload=defining_workspace_payload
        )
        if not scope.scope_matches_candidates(settings.read_projects, candidates):
            policy_observation.record_policy_decision("project_scope_read_denied")
            raise ProjectScopeDeniedError(
                "OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS."
            )
        policy_observation.record_policy_decision("project_scope_read_allowed")
        return
    # The link branch delegates to the already-instrumented
    # scope.ensure_project_link_allowed (its own @_observe_project_scope_check
    # decorator records project_scope/policy_decision) -- no separate
    # recording needed here.
    scope.ensure_project_link_allowed(
        defining_workspace_link, settings=settings, project_id_to_identifier=project_id_to_identifier
    )


def backlog_bucket_payload_allowed(
    *,
    defining_workspace_payload: dict[str, Any] | None,
    defining_workspace_link: Any,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> bool:
    return scope.payload_allowed(
        lambda: ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload=defining_workspace_payload,
            defining_workspace_link=defining_workspace_link,
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    )
