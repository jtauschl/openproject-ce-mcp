"""Projects-only policy. Pure, no I/O.

Verbatim port of client.py's _ensure_project_allowed/_ensure_project_write_allowed/
_ensure_project_write_candidate_allowed (client.py:7384-7420), built on the
already-shared scope.py primitives rather than duplicating candidate-matching
logic here.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ..errors import PermissionDeniedError
from .scope import project_candidates, scope_allows_all, scope_matches_candidates


def ensure_project_read_allowed(
    payload: dict[str, Any],
    *,
    project_ref: str | None = None,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
) -> None:
    """Read-allowlist check on an already-resolved project payload.

    project_ref (the ref the caller originally resolved by, e.g. an identifier
    or numeric-id string) is included as its own candidate alongside the
    payload's own fields -- verbatim parity with client.py's
    _ensure_project_allowed(project_ref, payload=...), which always passes
    both.
    """
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_candidates(
        project_id_to_identifier=project_id_to_identifier, project_ref=project_ref, payload=payload
    )
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_allowed(
    payload: dict[str, Any],
    *,
    project_ref: str | None = None,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
) -> None:
    """Read- AND write-allowlist check (write implies read), for update/delete/favorite."""
    candidates = project_candidates(
        project_id_to_identifier=project_id_to_identifier, project_ref=project_ref, payload=payload
    )
    ensure_project_read_allowed(
        payload, project_ref=project_ref, settings=settings, project_id_to_identifier=project_id_to_identifier
    )
    if scope_allows_all(settings.write_projects):
        return
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")


def ensure_project_create_target_allowed(
    *,
    identifier: str | None,
    name: str | None,
    settings: Settings,
    project_id_to_identifier: dict[int, str],
) -> None:
    """Read- then write-allowlist check on an intended create/copy target.

    No resolved payload with an `id` exists yet at create time, so this checks
    the intended identifier/name directly -- read first, then write, matching
    _ensure_project_write_candidate_allowed's order: a writable target must
    also be readable.
    """
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, identifier=identifier, name=name)
    if not scope_allows_all(settings.read_projects) and not scope_matches_candidates(
        settings.read_projects, candidates
    ):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if not scope_allows_all(settings.write_projects) and not scope_matches_candidates(
        settings.write_projects, candidates
    ):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
