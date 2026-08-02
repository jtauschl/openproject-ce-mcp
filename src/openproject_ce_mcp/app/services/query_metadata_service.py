"""Application Service for the Query Metadata domain.

Depends on the QueryMetadataApi Protocol, never HttpxQueryMetadataApi
concretely (enforced by the architecture-boundary test). No dedicated
Resolver for any of the five: filter/column/operator/sort-by/schema ids are
opaque strings, not semantic references needing lookup.

All five share `access.ensure_read_enabled("board", ...)` as their gate
(verbatim port of client.py's `_ensure_read_enabled("board")` for all six
methods -- these describe the query/board schema, not a dedicated
OPENPROJECT_ENABLE_QUERY_METADATA_* flag), so one Service bundling all five,
rather than five separate Services, avoids depending on the exact same seam
five times for no behavioral difference -- same rationale as Actions &
Capabilities and Statuses/Priorities/Types.

`list_filter_instance_schemas(project=...)` takes a `ProjectRefResolver`
dependency to resolve the optional `project` ref to an id -- this shapes
which endpoint the Adapter calls (`projects/{id}/queries/filter_instance_schemas`
vs `queries/filter_instance_schemas`), it is not a per-record allowlist
filter, same pattern as `StatusPriorityTypeService.list_types`: read-scope
enforcement for the given `project` ref already happens inside
`ProjectRefResolver` itself.
"""

from __future__ import annotations

from ...config import Settings
from ...models import (
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
)
from ..policies import access, hidden_fields
from ..ports.project_ref import ProjectRefResolver
from ..ports.query_metadata_api import QueryMetadataApi


class QueryMetadataService:
    def __init__(
        self,
        *,
        api: QueryMetadataApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    async def get_filter(self, filter_id: str) -> QueryFilterSummary:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get_filter(filter_id)
        return hidden_fields.apply_hidden_fields("query_filter", record.summary, settings=self._settings)

    async def get_column(self, column_id: str) -> QueryColumnSummary:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get_column(column_id)
        return hidden_fields.apply_hidden_fields("query_column", record.summary, settings=self._settings)

    async def get_operator(self, operator_id: str) -> QueryOperatorSummary:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get_operator(operator_id)
        return hidden_fields.apply_hidden_fields("query_operator", record.summary, settings=self._settings)

    async def get_sort_by(self, sort_by_id: str) -> QuerySortBySummary:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get_sort_by(sort_by_id)
        return hidden_fields.apply_hidden_fields("query_sort_by", record.summary, settings=self._settings)

    async def list_filter_instance_schemas(self, *, project: str | None = None) -> QueryFilterInstanceSchemaListResult:
        access.ensure_read_enabled("board", settings=self._settings)
        project_id: int | None = None
        if project is not None:
            project_payload = await self._resolve_project_ref(project, write=False)
            project_id = int(project_payload["id"])
        records = await self._api.list_filter_instance_schemas(project_id=project_id)
        results = [
            hidden_fields.apply_hidden_fields("query_filter_instance_schema", record.summary, settings=self._settings)
            for record in records
        ]
        return QueryFilterInstanceSchemaListResult(count=len(results), results=results)

    async def get_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaSummary:
        access.ensure_read_enabled("board", settings=self._settings)
        record = await self._api.get_filter_instance_schema(schema_id)
        return hidden_fields.apply_hidden_fields(
            "query_filter_instance_schema", record.summary, settings=self._settings
        )
