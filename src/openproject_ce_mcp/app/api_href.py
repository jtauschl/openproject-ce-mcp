"""Shared API-href construction helper.

Package-root shared kernel: pure, dependency-free string formatting used by any
Service/Adapter that needs to build a relative API href for an outgoing HAL
`_links` payload (e.g. `{"href": api_href(f"projects/{id}", api_prefix=...)}`).

Shared here because the same href-formatting logic is needed independently by
MembershipService, VersionService, ProjectService, and httpx_grid_api.py --
keeping one copy avoids re-duplicating it across those call sites.
"""

from __future__ import annotations


def api_href(relative_path: str, *, api_prefix: str) -> str:
    return f"/{api_prefix.lstrip('/')}{relative_path.lstrip('/')}"
