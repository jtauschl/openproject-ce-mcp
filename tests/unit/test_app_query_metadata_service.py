from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.query_metadata_api import (
    QueryColumnRecord,
    QueryFilterInstanceSchemaRecord,
    QueryFilterRecord,
    QueryOperatorRecord,
    QuerySortByRecord,
)
from openproject_ce_mcp.app.services.query_metadata_service import QueryMetadataService
from openproject_ce_mcp.models import (
    QueryColumnSummary,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
)
from openproject_ce_mcp.tools import _to_payload


def _filter_summary(filter_id: str = "assignee") -> QueryFilterSummary:
    return QueryFilterSummary(id=filter_id, name="Assignee", url=f"https://op.example.com/queries/filters/{filter_id}")


def _column_summary(column_id: str = "subject") -> QueryColumnSummary:
    return QueryColumnSummary(
        id=column_id,
        name="Subject",
        type="Query::Column::Property",
        relation_type=None,
        url=f"https://op.example.com/queries/columns/{column_id}",
    )


def _operator_summary(operator_id: str = "=") -> QueryOperatorSummary:
    return QueryOperatorSummary(
        id=operator_id, name="is (OR)", url=f"https://op.example.com/queries/operators/{operator_id}"
    )


def _sort_by_summary(sort_by_id: str = "subject:asc") -> QuerySortBySummary:
    return QuerySortBySummary(
        id=sort_by_id,
        name="Subject asc",
        column="Subject",
        direction="ascending",
        url=f"https://op.example.com/queries/sort_bys/{sort_by_id}",
    )


def _schema_summary(schema_id: str = "assignee") -> QueryFilterInstanceSchemaSummary:
    return QueryFilterInstanceSchemaSummary(
        id=schema_id,
        name="Assignee schema",
        filter="Assignee",
        operator_count=2,
        url=f"https://op.example.com/queries/filter_instance_schemas/{schema_id}",
    )


class _FakeQueryMetadataApi:
    def __init__(
        self,
        *,
        filters: dict[str, QueryFilterRecord] | None = None,
        columns: dict[str, QueryColumnRecord] | None = None,
        operators: dict[str, QueryOperatorRecord] | None = None,
        sort_bys: dict[str, QuerySortByRecord] | None = None,
        schemas: list[QueryFilterInstanceSchemaRecord] | None = None,
    ) -> None:
        self._filters = filters or {"assignee": QueryFilterRecord(summary=_filter_summary())}
        self._columns = columns or {"subject": QueryColumnRecord(summary=_column_summary())}
        self._operators = operators or {"=": QueryOperatorRecord(summary=_operator_summary())}
        self._sort_bys = sort_bys or {"subject:asc": QuerySortByRecord(summary=_sort_by_summary())}
        self._schemas = schemas if schemas is not None else [QueryFilterInstanceSchemaRecord(summary=_schema_summary())]
        self._schemas_by_id = {s.summary.id: s for s in self._schemas}
        self.list_filter_instance_schemas_calls: list[int | None] = []

    async def get_filter(self, filter_id: str) -> QueryFilterRecord:
        return self._filters[filter_id]

    async def get_column(self, column_id: str) -> QueryColumnRecord:
        return self._columns[column_id]

    async def get_operator(self, operator_id: str) -> QueryOperatorRecord:
        return self._operators[operator_id]

    async def get_sort_by(self, sort_by_id: str) -> QuerySortByRecord:
        return self._sort_bys[sort_by_id]

    async def list_filter_instance_schemas(self, *, project_id: int | None) -> list[QueryFilterInstanceSchemaRecord]:
        self.list_filter_instance_schemas_calls.append(project_id)
        return list(self._schemas)

    async def get_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaRecord:
        return self._schemas_by_id[schema_id]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _denying_resolve_project_ref(message: str):
    async def _resolve(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError(message)

    return _resolve


def _service(
    api: _FakeQueryMetadataApi | None = None,
    *,
    settings=None,
    resolve_project_ref=_resolve_project_ref,
) -> QueryMetadataService:
    api = api or _FakeQueryMetadataApi()
    return QueryMetadataService(api=api, settings=settings or make_settings(), resolve_project_ref=resolve_project_ref)


@pytest.mark.asyncio
async def test_get_filter_returns_summary() -> None:
    service = _service()

    filter_ = await service.get_filter("assignee")

    assert filter_.id == "assignee"


@pytest.mark.asyncio
async def test_get_filter_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"query_filter": ("name",)})
    service = _service(settings=settings)

    filter_ = await service.get_filter("assignee")

    assert filter_._hidden_keys == frozenset({"name"})
    serialized = _to_payload(filter_)
    assert "name" not in serialized


@pytest.mark.asyncio
async def test_get_filter_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_board_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_filter("assignee")


@pytest.mark.asyncio
async def test_get_column_returns_summary_with_type_fields() -> None:
    service = _service()

    column = await service.get_column("subject")

    assert column.id == "subject"
    assert column.type == "Query::Column::Property"


@pytest.mark.asyncio
async def test_get_operator_returns_summary() -> None:
    service = _service()

    operator = await service.get_operator("=")

    assert operator.id == "="


@pytest.mark.asyncio
async def test_get_sort_by_returns_summary() -> None:
    service = _service()

    sort_by = await service.get_sort_by("subject:asc")

    assert sort_by.direction == "ascending"


@pytest.mark.asyncio
async def test_query_filter_hidden_by_query_filter_scope_not_query_column_scope() -> None:
    """Regression test for the entity="query_filter" vs a same-named-neighbor
    hide-field bug class: masking must be keyed to "query_filter", not
    silently reuse "query_column"'s configured patterns."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"query_column": ("name",)})
    service = _service(settings=settings)

    filter_ = await service.get_filter("assignee")

    assert not hasattr(filter_, "_hidden_keys")


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_without_project_does_not_resolve_a_project_ref() -> None:
    api = _FakeQueryMetadataApi()
    service = _service(api)

    result = await service.list_filter_instance_schemas()

    assert result.count == 1
    assert api.list_filter_instance_schemas_calls == [None]


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_with_project_resolves_project_ref_for_read() -> None:
    calls: list[tuple[str, bool]] = []

    async def resolve_project_ref_tracking(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append((project_ref, write))
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeQueryMetadataApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking)

    result = await service.list_filter_instance_schemas(project="demo")

    assert result.count == 1
    assert calls == [("demo", False)]
    assert api.list_filter_instance_schemas_calls == [6]


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_denies_when_project_ref_resolution_denies() -> None:
    service = _service(resolve_project_ref=_denying_resolve_project_ref("OPENPROJECT_READ_PROJECTS"))

    with pytest.raises(PermissionDeniedError):
        await service.list_filter_instance_schemas(project="demo")


@pytest.mark.asyncio
async def test_list_filter_instance_schemas_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"query_filter_instance_schema": ("filter",)})
    service = _service(settings=settings)

    result = await service.list_filter_instance_schemas()
    schema = result.results[0]

    assert schema._hidden_keys == frozenset({"filter"})
    serialized = _to_payload(schema)
    assert "filter" not in serialized


@pytest.mark.asyncio
async def test_get_filter_instance_schema_returns_summary() -> None:
    service = _service()

    schema = await service.get_filter_instance_schema("assignee")

    assert schema.operator_count == 2


@pytest.mark.asyncio
async def test_get_filter_instance_schema_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_board_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_filter_instance_schema("assignee")
