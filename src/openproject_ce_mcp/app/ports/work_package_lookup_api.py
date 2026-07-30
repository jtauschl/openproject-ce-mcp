"""Work-package lookup port (ADR 0001) -- deliberately minimal.

Unlike `ProjectApi`/`VersionApi` (full Domain API ports covering list/get/create/
update/delete for their domain), this Protocol exposes only the two GETs the
extracted work-package-reference-resolution infrastructure needs
(`WorkPackageResolver`, see `app/resolvers/work_package_resolver.py`). A full
`WorkPackageApi` Port with Summary/Detail normalization is out of scope here --
that belongs to the eventual full Work Packages CRUD migration (currently
blocked on ~1170 lines in client.py). Both methods return the raw HAL payload
unnormalized, not a model, for the same reason: normalization is that future
migration's job, not this preparatory extraction's.

Two methods, not one, because the two call sites this Port serves need
different inputs: `resolve_id()` (client.py's former `_resolve_work_package_id`)
starts from a bare reference (numeric id or `PROJ-123`-style identifier), while
`project_link_allowed()` (former `_work_package_project_allowed`) starts from an
already-known `_links.*` href (e.g. a relation's `_links.from`) that must be
origin-checked before being contacted -- a manipulated/foreign href must never
be dereferenced. `get()` covers the former; `get_by_href()` the latter,
verbatim porting client.py's `_link_to_api_path` safety check (see
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
