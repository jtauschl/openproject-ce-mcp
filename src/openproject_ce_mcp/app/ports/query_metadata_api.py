"""Query Metadata Domain API port (17th migrated domain, OPM-1611).

Five unrelated-but-bundled read-only lookups (client.py places them
adjacently, and OPM-1611 groups them as one migration ticket -- same
bundling rationale as Actions & Capabilities under OPM-276 and
Statuses/Priorities/Types under OPM-1627). Each has its own Record; none
carries a project link -- these describe OpenProject's *query* schema
(available filters/columns/operators/sort-bys and per-filter-type instance
schemas), not project-scoped resources. `list_filter_instance_schemas`'
optional `project` filter shapes the *request* (which endpoint to call),
not a per-record allowlist check -- same shape as Type's project-optional
list branch in the Statuses/Priorities/Types migration.

No `to_detail` split on any of the five Records: every method here is
either a single-item GET or (for filter instance schemas) a list whose rows
are never separately "detailed" -- get_*/list_* all go through the same
normalizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import (
    QueryColumnSummary,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
)


@dataclass(frozen=True)
class QueryFilterRecord:
    summary: QueryFilterSummary


@dataclass(frozen=True)
class QueryColumnRecord:
    summary: QueryColumnSummary


@dataclass(frozen=True)
class QueryOperatorRecord:
    summary: QueryOperatorSummary


@dataclass(frozen=True)
class QuerySortByRecord:
    summary: QuerySortBySummary


@dataclass(frozen=True)
class QueryFilterInstanceSchemaRecord:
    summary: QueryFilterInstanceSchemaSummary


class QueryMetadataApi(Protocol):
    """Narrow, Query-Metadata-only Domain API port. QueryMetadataService
    depends on this Protocol, never on HttpxQueryMetadataApi concretely
    (enforced by the architecture-boundary test).

    Read-only, no create/update/delete for any of the five -- OpenProject's
    API exposes none (these describe the query schema itself, not a
    resource). `list_filter_instance_schemas` is unpaginated (plain
    `CollectionResult` fetch-all, matching Categories'/
    Statuses-Priorities-Types' shape, not Roles'/Actions' offset/pageSize
    `PageResult` shape) -- verified against `QueryFilterInstanceSchemaListResult`
    in models.py, a plain `CollectionResult` subclass.
    """

    async def get_filter(self, filter_id: str) -> QueryFilterRecord: ...

    async def get_column(self, column_id: str) -> QueryColumnRecord: ...

    async def get_operator(self, operator_id: str) -> QueryOperatorRecord: ...

    async def get_sort_by(self, sort_by_id: str) -> QuerySortByRecord: ...

    async def list_filter_instance_schemas(
        self, *, project_id: int | None
    ) -> list[QueryFilterInstanceSchemaRecord]: ...

    async def get_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaRecord: ...
