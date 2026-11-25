"""`execute_query` refuses a saved query whose stored selection uses a hidden field, and returns no row of it.

The check sits inside the page fetch: the server has run the stored selection when its answer arrives, so the claim
is that no row of a refused page is read, not that no request is made. Stated boundary: the fakes here are the
service's ports; the shape of a real response is pinned by `test_stored_query_definition_adapter.py`.
"""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings
from test_app_query_execution_service import (
    PLAIN_DEFINITION,
    _FakeQueryExecutionApi,
    _FakeWorkPackageApi,
    _raw_wp,
    _service,
)

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.query_execution_api import QueryResultPage
from openproject_ce_mcp.app.ports.work_package_api import WorkPackageRecord
from openproject_ce_mcp.app.stored_query import StoredFilter, StoredQuery

BY_STATUS = dataclasses.replace(PLAIN_DEFINITION, filters=(StoredFilter("status", "="),))
STATUS_MESSAGE = (
    "OpenProject work package field 'status' is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS "
    "and cannot be used by the saved query (filter 'status')."
)


class _DefinitionPerPageApi(_FakeQueryExecutionApi):
    def __init__(self, pages: list[list[dict]], definitions: list[StoredQuery | None]) -> None:
        super().__init__(pages)
        self._definitions = definitions

    async def execute(self, query_id: int, *, offset: int, page_size: int) -> QueryResultPage:
        page = await super().execute(query_id, offset=offset, page_size=page_size)
        return dataclasses.replace(page, definition=self._definitions[offset - 1])


class _CountingWorkPackageApi(_FakeWorkPackageApi):
    def __init__(self) -> None:
        self.normalised: list[int] = []

    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        self.normalised.append(payload["id"])
        return super().to_record(payload, text_limit=text_limit)


def _settings(**changes):
    return dataclasses.replace(make_settings(), read_projects=("demo",), max_page_size=3, **changes)


@pytest.mark.asyncio
async def test_a_stored_selection_by_a_hidden_field_is_refused_and_no_row_is_read() -> None:
    api = _DefinitionPerPageApi([[_raw_wp(1), _raw_wp(2)], [_raw_wp(3)]], [BY_STATUS, BY_STATUS])
    counting = _CountingWorkPackageApi()
    service = _service(
        api=api, settings=_settings(hidden_fields={"work_package": ("status",)}), work_package_api=counting
    )

    with pytest.raises(InvalidInputError) as refusal:
        await service.execute(7, offset=1, limit=20)

    assert str(refusal.value) == STATUS_MESSAGE
    assert len(api.execute_calls) == 1
    assert counting.normalised == []


@pytest.mark.asyncio
async def test_the_definition_is_judged_on_every_page() -> None:
    api = _DefinitionPerPageApi([[_raw_wp(1), _raw_wp(2)], [_raw_wp(3)]], [PLAIN_DEFINITION, BY_STATUS])
    counting = _CountingWorkPackageApi()
    service = _service(
        api=api, settings=_settings(hidden_fields={"work_package": ("status",)}), work_package_api=counting
    )

    with pytest.raises(InvalidInputError) as refusal:
        await service.execute(7, offset=1, limit=20)

    assert str(refusal.value) == STATUS_MESSAGE
    assert len(api.execute_calls) == 2
    assert counting.normalised == [1, 2]


@pytest.mark.asyncio
async def test_the_same_query_returns_its_rows_while_the_field_is_visible() -> None:
    api = _DefinitionPerPageApi([[_raw_wp(1), _raw_wp(2)], [_raw_wp(3)]], [BY_STATUS, BY_STATUS])
    service = _service(api=api, settings=_settings(hidden_fields={"work_package": ("description",)}))

    result = await service.execute(7, offset=1, limit=20)

    assert [r.id for r in result.results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_definition_that_could_not_be_read_is_refused_while_a_field_is_hidden() -> None:
    api = _DefinitionPerPageApi([[_raw_wp(1)]], [None])
    hiding = _service(api=api, settings=_settings(hidden_fields={"work_package": ("description",)}))
    plain = _service(api=_DefinitionPerPageApi([[_raw_wp(1)]], [None]), settings=_settings())

    with pytest.raises(InvalidInputError, match="could not be read"):
        await hiding.execute(7, offset=1, limit=20)
    assert [r.id for r in (await plain.execute(7, offset=1, limit=20)).results] == [1]


@pytest.mark.asyncio
async def test_an_empty_read_allowlist_still_returns_before_any_request() -> None:
    api = _DefinitionPerPageApi([[_raw_wp(1)]], [BY_STATUS])
    settings = dataclasses.replace(make_settings(), read_projects=(), hidden_fields={"work_package": ("status",)})
    service = _service(api=api, settings=settings)

    result = await service.execute(7, offset=1, limit=20)

    assert result.results == [] and api.execute_calls == []
