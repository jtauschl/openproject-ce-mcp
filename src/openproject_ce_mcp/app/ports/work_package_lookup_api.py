"""Work-package lookup port -- deliberately minimal.

Unlike `ProjectApi`/`VersionApi` (full Domain API ports covering list/get/create/
update/delete for their domain), this Protocol exposes only the two GETs that
work-package-reference-resolution infrastructure needs (`WorkPackageResolver`,
see `app/resolvers/work_package_resolver.py`). A full `WorkPackageApi` Port
with Summary/Detail normalization is a separate, full Work Packages CRUD port
(`app/ports/work_package_api.py`); both methods here return the raw HAL
payload unnormalized, not a model -- normalization is that port's job, not
this narrow lookup port's.

Two methods, not one, because the two call sites this Port serves need
different inputs: `resolve_id()` starts from a bare reference (numeric id or
`PROJ-123`-style identifier), while `project_link_allowed()` starts from an
already-known `_links.*` href (e.g. a relation's `_links.from`) that must be
origin-checked before being contacted -- a manipulated/foreign href must never
be dereferenced. `get()` covers the former; `get_by_href()` the latter, which
applies a safety check on the href's origin before dereferencing it (see
`HttpxWorkPackageLookupApi`).
"""

from __future__ import annotations

from typing import Any, Protocol


class WorkPackageLookupApi(Protocol):
    """Narrow, two-method port. `WorkPackageResolver` depends on this Protocol,
    never on `HttpxWorkPackageLookupApi` concretely (enforced by the
    architecture-boundary test).
    """

    async def get(self, work_package_ref: str) -> dict[str, Any]: ...
    async def get_by_href(self, href: str) -> dict[str, Any]: ...
