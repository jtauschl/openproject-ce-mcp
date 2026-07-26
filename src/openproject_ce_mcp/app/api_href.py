"""Shared API-href construction helper (ADR 0001).

Package-root shared kernel: pure, dependency-free string formatting used by any
Service/Adapter that needs to build a relative API href for an outgoing HAL
`_links` payload (e.g. `{"href": api_href(f"projects/{id}", api_prefix=...)}`).

Extracted after a byte-identical `_api_href`/`api_href` helper was found
independently duplicated in MembershipService, VersionService, ProjectService,
and httpx_grid_api.py (found during the Sprints migration's step-6
reuse/simplification audit) -- past this project's own "3+ identical copies"
unification threshold.
"""

from __future__ import annotations


def api_href(relative_path: str, *, api_prefix: str) -> str:
    return f"/{api_prefix.lstrip('/')}{relative_path.lstrip('/')}"
