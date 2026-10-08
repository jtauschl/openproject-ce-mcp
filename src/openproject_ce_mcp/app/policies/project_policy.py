"""Projects-only policy. Pure, no I/O.

Read/write allowlist checks for projects, built on the shared scope.py
primitives rather than duplicating candidate-matching logic here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ... import policy_observation
from ...config import Settings
from ..errors import ProjectScopeDeniedError
from .scope import project_candidates, scope_allows_all, scope_matches_candidates


def _display_value(
    *, payload: dict[str, Any] | None, project_ref: str | None, identifier: str | None, name: str | None
) -> str | None:
    """A single, unambiguous display value for the `project_scope` log
    field -- mirrors scope.py's `_project_scope_display`, but for this
    module's payload/ref/identifier-based signatures rather than a HAL link.
    Prefers a known identifier over a numeric id or a bare ref/name, since an
    identifier is what an operator actually recognizes in an allowlist."""
    if payload is not None:
        identifier_value = payload.get("identifier")
        if identifier_value:
            return str(identifier_value)
        project_id = payload.get("id")
        if project_id is not None:
            return str(project_id)
    return identifier or project_ref or name


def ensure_project_read_allowed(
    payload: dict[str, Any],
    *,
    project_ref: str | None = None,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    """Read-allowlist check on an already-resolved project payload.

    project_ref (the ref the caller originally resolved by, e.g. an identifier
    or numeric-id string) is included as its own candidate alongside the
    payload's own fields.
    """
    policy_observation.record_project_scope(
        _display_value(payload=payload, project_ref=project_ref, identifier=None, name=None)
    )
    if scope_allows_all(settings.read_projects):
        policy_observation.record_policy_decision("project_read_allowed")
        return
    candidates = project_candidates(
        project_id_to_identifier=project_id_to_identifier, project_ref=project_ref, payload=payload
    )
    if not scope_matches_candidates(settings.read_projects, candidates):
        policy_observation.record_policy_decision("project_read_denied")
        raise ProjectScopeDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    policy_observation.record_policy_decision("project_read_allowed")


def ensure_project_write_allowed(
    payload: dict[str, Any],
    *,
    project_ref: str | None = None,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    """Read- AND write-allowlist check (write implies read), for update/delete/favorite."""
    candidates = project_candidates(
        project_id_to_identifier=project_id_to_identifier, project_ref=project_ref, payload=payload
    )
    ensure_project_read_allowed(
        payload, project_ref=project_ref, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
    # The read check above already recorded project_scope/a read-flavored
    # decision; this write-flavored decision, recorded last, is what a human
    # debugging a denial actually sees -- same reasoning as scope.py's
    # ensure_project_write_link_allowed's own nested-call comment.
    if scope_allows_all(settings.write_projects):
        policy_observation.record_policy_decision("project_write_allowed")
        return
    if not scope_matches_candidates(settings.write_projects, candidates):
        policy_observation.record_policy_decision("project_write_denied")
        raise ProjectScopeDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    policy_observation.record_policy_decision("project_write_allowed")


def ensure_project_create_target_allowed(
    *,
    identifier: str | None,
    name: str | None,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    """Read- then write-allowlist check on an intended create/copy target.

    No resolved payload with an `id` exists yet at create time, so this checks
    the intended identifier/name directly -- read is checked first, then
    write, since a writable target must also be readable.
    """
    policy_observation.record_project_scope(
        _display_value(payload=None, project_ref=None, identifier=identifier, name=name)
    )
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, identifier=identifier, name=name)
    if not scope_allows_all(settings.read_projects) and not scope_matches_candidates(
        settings.read_projects, candidates
    ):
        policy_observation.record_policy_decision("project_read_denied")
        raise ProjectScopeDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if not scope_allows_all(settings.write_projects) and not scope_matches_candidates(
        settings.write_projects, candidates
    ):
        policy_observation.record_policy_decision("project_write_denied")
        raise ProjectScopeDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    policy_observation.record_policy_decision("project_write_allowed")
